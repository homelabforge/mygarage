"""ID tokens signed EdDSA (Rauthy's default) verify without a SecurityWarning.

RFC 9864 deprecates the alg name "EdDSA" for the fully specified "Ed25519".
joserfc warns on every EdDSA token, which filled the log on each SSO sign-in.
The signature is the same either way, so the warning is noise, and a provider
that moves to the new name has to keep working.
"""

import time
import warnings
from unittest.mock import patch

import pytest
from joserfc import jwt
from joserfc.errors import SecurityWarning
from joserfc.jwk import KeySet, OKPKey

from app.services.oidc.tokens import verify_id_token

ISSUER = "https://id.example.com/auth/v1/"
CLIENT_ID = "mygarage"
NONCE = "nonce-1"
JWKS_URI = "https://id.example.com/auth/v1/oidc/certs"


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(self._payload)


@pytest.fixture
def ed_key() -> OKPKey:
    return OKPKey.generate_key("Ed25519", parameters={"kid": "ed-1"})


def _token(key: OKPKey, alg: str) -> str:
    now = int(time.time())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SecurityWarning)
        return jwt.encode(
            {"alg": alg, "kid": key.kid},
            {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "nonce": NONCE,
                "sub": "u-1",
                "iat": now,
                "exp": now + 300,
            },
            key,
            algorithms=[alg],
        )


async def _verify(key: OKPKey, alg: str) -> tuple[dict | None, list[str]]:
    jwks = KeySet([key]).as_dict(private=False)
    with (
        patch("app.services.oidc.tokens.validate_oidc_url", return_value=None),
        patch(
            "app.services.oidc.tokens.httpx.AsyncClient", lambda *a, **kw: _FakeAsyncClient(jwks)
        ),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        claims = await verify_id_token(
            _token(key, alg),
            {"issuer_url": ISSUER.rstrip("/"), "client_id": CLIENT_ID},
            {"issuer": ISSUER, "jwks_uri": JWKS_URI},
            NONCE,
        )
    return claims, [str(w.message) for w in caught if issubclass(w.category, SecurityWarning)]


@pytest.mark.unit
async def test_an_eddsa_token_verifies_without_a_security_warning(ed_key: OKPKey) -> None:
    claims, security_warnings = await _verify(ed_key, "EdDSA")

    assert claims is not None and claims["sub"] == "u-1"
    assert security_warnings == []


@pytest.mark.unit
async def test_the_rfc_9864_name_verifies_too(ed_key: OKPKey) -> None:
    claims, _ = await _verify(ed_key, "Ed25519")

    assert claims is not None and claims["sub"] == "u-1"
