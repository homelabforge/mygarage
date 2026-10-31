"""The OIDC provider services give back None, logged once, on an answer they can't use.

Discovery, the token exchange, the ID token's JWKS and userinfo each talk to the
IdP. A transport failure other than a timeout or a refused connection, a body
that isn't JSON, or JSON that isn't an object used to escape them as an
exception, which the callback turned into a 500. A JWKS of the wrong shape did
the same from inside joserfc. Anything else still raises, so a bug doesn't pass
for a provider failure.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from unittest.mock import patch
from urllib.parse import urlparse

import httpx
import pytest

from app.services.oidc.config import get_provider_metadata
from app.services.oidc.tokens import exchange_code_for_tokens, get_userinfo, verify_id_token

_ISSUER = "https://idp.example"
_METADATA = {
    "issuer": _ISSUER,
    "token_endpoint": f"{_ISSUER}/token",
    "jwks_uri": f"{_ISSUER}/jwks",
    "userinfo_endpoint": f"{_ISSUER}/userinfo",
}

type _Answer = Callable[[httpx.Request], httpx.Response]


@contextmanager
def _provider(answer: _Answer) -> Generator[None]:
    """Every provider request gets this answer.

    URL validation is skipped, since the example host doesn't resolve. Every
    service fetches what the validator returns, so its stand-in still parses.
    """
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(answer)
    with (
        patch("app.services.oidc.config.validate_oidc_url", side_effect=urlparse),
        patch("app.services.oidc.tokens.validate_oidc_url", side_effect=urlparse),
        patch.object(httpx, "AsyncClient", lambda *_a, **_kw: real_client(transport=transport)),
    ):
        yield


def _body(status: int, body: bytes) -> _Answer:
    return lambda _request: httpx.Response(status, content=body)


def _raises(error: Exception) -> _Answer:
    def answer(_request: httpx.Request) -> httpx.Response:
        raise error

    return answer


async def _discovery() -> object:
    return await get_provider_metadata(_ISSUER)


async def _token_exchange() -> object:
    return await exchange_code_for_tokens(
        "code", {"client_id": "mygarage"}, _METADATA, "https://app.example/cb", code_verifier="v"
    )


async def _jwks() -> object:
    return await verify_id_token("id-token", {"client_id": "mygarage"}, _METADATA, "nonce")


async def _userinfo() -> object:
    return await get_userinfo("access-token", _METADATA)


# Each provider service, called the way the callback calls it.
_SERVICES: dict[str, Callable[[], Awaitable[object]]] = {
    "discovery": _discovery,
    "token-exchange": _token_exchange,
    "jwks": _jwks,
    "userinfo": _userinfo,
}

# The token, JWKS and userinfo calls, keyed by the metadata field each one fetches.
_ENDPOINT_CALLS: dict[str, Callable[[dict[str, str]], Awaitable[object]]] = {
    "token_endpoint": lambda metadata: exchange_code_for_tokens(
        "code", {"client_id": "mygarage"}, metadata, "https://app.example/cb"
    ),
    "jwks_uri": lambda metadata: verify_id_token(
        "id-token", {"client_id": "mygarage"}, metadata, "n"
    ),
    "userinfo_endpoint": lambda metadata: get_userinfo("access-token", metadata),
}

_UNUSABLE: dict[str, _Answer] = {
    "protocol-error": _raises(httpx.RemoteProtocolError("peer closed the connection")),
    "not-json": _body(200, b"<html>Bad gateway</html>"),
    "json-list": _body(200, json.dumps(["not", "an", "object"]).encode()),
    "json-string": _body(200, json.dumps("token").encode()),
}


def _oidc_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith("app.services.oidc") and r.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize("answer", list(_UNUSABLE.values()), ids=list(_UNUSABLE))
@pytest.mark.parametrize("service", list(_SERVICES.values()), ids=list(_SERVICES))
async def test_an_unusable_answer_is_none_and_logged_once(
    service: Callable[[], Awaitable[object]],
    answer: _Answer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="app.services.oidc")

    with _provider(answer):
        result = await service()

    assert result is None
    assert len(_oidc_warnings(caplog)) == 1, _oidc_warnings(caplog)


@pytest.mark.parametrize(
    "answer",
    [_body(503, b"unavailable"), _body(200, b"{}"), _body(200, b'{"keys": 5}')],
    ids=["status-503", "no-keys", "keys-not-a-list"],
)
async def test_a_jwks_that_cant_be_used_is_none_and_logged_once(
    answer: _Answer, caplog: pytest.LogCaptureFixture
) -> None:
    """A 503 and the two wrong shapes joserfc throws KeyError and TypeError on."""
    caplog.set_level(logging.WARNING, logger="app.services.oidc")

    with _provider(answer):
        result = await _jwks()

    assert result is None
    assert len(_oidc_warnings(caplog)) == 1, _oidc_warnings(caplog)


@pytest.mark.parametrize("service", list(_SERVICES.values()), ids=list(_SERVICES))
async def test_an_error_that_isnt_the_providers_still_raises(
    service: Callable[[], Awaitable[object]],
) -> None:
    """MockTransport hands the answer's own exception straight up, like a bug would."""
    with (
        _provider(_raises(RuntimeError("not a provider failure"))),
        pytest.raises(RuntimeError, match="not a provider failure"),
    ):
        await service()


async def test_a_key_set_error_that_isnt_the_jwks_shape_still_raises() -> None:
    with (
        _provider(_body(200, b'{"keys": []}')),
        patch(
            "app.services.oidc.tokens.KeySet.import_key_set",
            side_effect=RuntimeError("not a shape problem"),
        ),
        pytest.raises(RuntimeError, match="not a shape problem"),
    ):
        await _jwks()


@pytest.mark.parametrize("endpoint", list(_ENDPOINT_CALLS), ids=["token", "jwks", "userinfo"])
async def test_each_endpoint_fetch_goes_to_the_url_the_validator_parsed(endpoint: str) -> None:
    """The request goes where validate_oidc_url said, not to the raw string it was handed."""
    parsed = "https://validated.example/elsewhere"
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(503)

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(answer)
    with (
        patch(
            "app.services.oidc.tokens.validate_oidc_url",
            side_effect=lambda _url: urlparse(parsed),
        ),
        patch.object(httpx, "AsyncClient", lambda *_a, **_kw: real_client(transport=transport)),
    ):
        assert await _ENDPOINT_CALLS[endpoint](_METADATA) is None

    assert seen == [parsed]


@pytest.mark.parametrize("endpoint", list(_ENDPOINT_CALLS), ids=["token", "jwks", "userinfo"])
async def test_a_discovered_endpoint_on_a_blocked_address_is_none_and_its_url_isnt_logged(
    endpoint: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery can point an endpoint anywhere; a private one is refused, not a 500.

    The URL can carry secrets in its query, so the block logs only why.
    """
    monkeypatch.delenv("MYGARAGE_TRUSTED_HOSTS", raising=False)
    caplog.set_level(logging.ERROR, logger="app.services.oidc")
    blocked = "http://127.0.0.1:9000/secret-path?token=hunter2"

    assert await _ENDPOINT_CALLS[endpoint]({**_METADATA, endpoint: blocked}) is None

    messages = [r.getMessage() for r in caplog.records if r.name.startswith("app.services.oidc")]
    assert len(messages) == 1, messages
    assert "SSRF protection blocked" in messages[0]
    # The validator's reason stays in.
    assert "Blocked private IP address" in messages[0]
    for piece in ("http://", "secret-path", "hunter2", ":9000"):
        assert piece not in messages[0], messages[0]
