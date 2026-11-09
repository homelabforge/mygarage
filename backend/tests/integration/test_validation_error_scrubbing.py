"""A rejected secret stays out of the validation-error log and the 422 body (plan test 9, L2).

Pydantic's error carries the rejected value as `input` (on a missing field, the
whole parent object) and the constraint as `ctx`. The handler logged both, so a
too-long password, OIDC client secret or API key landed in the server log.

- The log line keeps `type`, `loc` and `msg` only, for every field.
- The 422 body drops `input` and `ctx` where the field's name (the last `loc`
  segment) contains `password`, `secret`, `token` or `key`, in any case (F-2).
- It drops `input` for any field when that is a dict or a list: on a missing
  field it is the whole parent object, which holds the secret fields (T6 m3).
- A custom validator's message lands in `msg` too ("Value error, ..."), so a
  secret-named field's `value_error` or `assertion_error` gets a generic `msg`
  in the body and the log.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, field_validator
from starlette.requests import Request

from app.utils.error_handlers import handle_validation_error

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Past LoginRequest.password's max_length (100), so pydantic rejects it and echoes it as `input`.
REJECTED_PASSWORD = "Rejected-Pa55word-" + "x" * 100
REJECTED_USERNAME = "rejected-username-" + "y" * 100
# Valid on its own: only the missing username is an error, and its `input` is the whole body.
ECHOED_PASSWORD = "Whole-body-Pa55word-7c1e"


def _validation_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("Validation error")]


async def test_a_rejected_password_is_in_no_log_record_and_not_echoed(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/api/auth/login", json={"username": "someone", "password": REJECTED_PASSWORD}
        )

    assert response.status_code == 422, response.text
    assert REJECTED_PASSWORD not in response.text
    (error,) = [e for e in response.json()["details"] if e["loc"] == ["body", "password"]]
    assert "input" not in error
    assert error["type"] == "string_too_long"

    assert _validation_records(caplog), "the handler logs a validation error"
    for record in caplog.records:
        assert REJECTED_PASSWORD not in record.getMessage()


async def test_the_log_line_drops_input_and_ctx_for_every_field(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A field that isn't a secret is still left out of the log; the body keeps its input."""
    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/api/auth/login", json={"username": REJECTED_USERNAME, "password": "short"}
        )

    assert response.status_code == 422, response.text
    (error,) = [e for e in response.json()["details"] if e["loc"] == ["body", "username"]]
    assert error["input"] == REJECTED_USERNAME
    assert "ctx" in error

    (record,) = _validation_records(caplog)
    message = record.getMessage()
    assert REJECTED_USERNAME not in message
    assert "'input'" not in message
    assert "'ctx'" not in message
    assert "string_too_long" in message
    assert "username" in message


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/probe", "headers": []})


@pytest.mark.parametrize(
    ("field", "echoed"),
    [
        ("password", False),
        ("new_password", False),
        ("client_secret", False),
        ("oidc_client_secret", False),
        ("api_key", False),
        ("Api_Key", False),
        ("ntfy_token", False),
        ("ACCESS_TOKEN", False),
        ("value", True),
        ("username", True),
    ],
)
async def test_the_body_drops_input_only_for_a_secret_named_field(
    field: str, echoed: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """F-2: a custom validator's exception lands in `ctx.error`, and can quote the value."""
    rejected = f"rejected-{field}-value"
    quoted = f"validator-quoted-{field}-value"
    exc = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", field),
                "msg": "Value error, not allowed",
                "input": rejected,
                "ctx": {"error": ValueError(quoted)},
            }
        ]
    )

    with caplog.at_level(logging.DEBUG):
        response = await handle_validation_error(_request(), exc)

    body = response.body.decode()
    assert (rejected in body) is echoed
    assert (quoted in body) is echoed
    assert rejected not in caplog.text
    assert quoted not in caplog.text


@pytest.mark.parametrize(
    "container",
    [
        pytest.param({"username": "someone", "password": "in-a-dict-3f9a"}, id="dict"),
        pytest.param(["someone", "in-a-list-3f9a"], id="list"),
    ],
)
async def test_the_body_drops_a_container_input_for_any_field(
    container: object, caplog: pytest.LogCaptureFixture
) -> None:
    """T6 m3: a dict or list `input` is a whole object, which can hold a secret field."""
    exc = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("body", "value"),
                "msg": "Field required",
                "input": container,
            }
        ]
    )

    with caplog.at_level(logging.DEBUG):
        response = await handle_validation_error(_request(), exc)

    body = response.body.decode()
    assert "3f9a" not in body
    assert "Field required" in body
    assert "3f9a" not in caplog.text


async def test_a_missing_field_does_not_echo_the_whole_body(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """T6 m3: on a missing field, `input` is the whole body, the password included."""
    with caplog.at_level(logging.DEBUG):
        response = await client.post("/api/auth/login", json={"password": ECHOED_PASSWORD})

    assert response.status_code == 422, response.text
    assert ECHOED_PASSWORD not in response.text
    (error,) = response.json()["details"]
    assert error["loc"] == ["body", "username"]
    assert error["type"] == "missing"
    assert "input" not in error
    assert ECHOED_PASSWORD not in caplog.text


QUOTED = "quoted-by-the-validator-81d4"


class _Probe(BaseModel):
    """A throwaway body whose validators quote what they were given."""

    api_token: str = "tk_fine"
    nickname: str = "fine"
    access_token: str = "tk_fine"

    @field_validator("api_token", "nickname")
    @classmethod
    def _value_error(cls, value: str) -> str:
        if value != "tk_fine" and value != "fine":
            raise ValueError(f"{value!r} is not allowed")
        return value

    @field_validator("access_token")
    @classmethod
    def _assertion(cls, value: str) -> str:
        assert value == "tk_fine", f"{value!r} is not allowed"
        return value


def _probe_app() -> FastAPI:
    probe = FastAPI()
    probe.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]

    @probe.post("/probe")
    async def _post(body: _Probe) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": body.nickname}

    return probe


@pytest.mark.parametrize(
    ("field", "error_type", "kept"),
    [
        ("api_token", "value_error", False),
        ("access_token", "assertion_error", False),
        ("nickname", "value_error", True),
    ],
)
async def test_a_validator_quoting_a_secret_gets_a_generic_msg(
    field: str, error_type: str, kept: bool, caplog: pytest.LogCaptureFixture
) -> None:
    async with AsyncClient(transport=ASGITransport(app=_probe_app()), base_url="http://t") as probe:
        with caplog.at_level(logging.DEBUG):
            response = await probe.post("/probe", json={field: QUOTED})

    assert response.status_code == 422, response.text
    (error,) = response.json()["details"]
    assert error["loc"] == ["body", field]
    assert error["type"] == error_type
    # A field that isn't a secret keeps the validator's own words.
    assert (QUOTED in error["msg"]) is kept
    assert (QUOTED in response.text) is kept
    assert _validation_records(caplog), "the handler logs a validation error"
    if not kept:
        assert error["msg"] == "Invalid value"
        assert QUOTED not in caplog.text


def _password_app() -> FastAPI:
    """The three real password bodies behind the real handler."""
    from app.schemas.user import AdminPasswordReset, UserCreate, UserPasswordUpdate

    probe = FastAPI()
    probe.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]

    @probe.post("/create")
    async def _create(body: UserCreate) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": body.username}

    @probe.post("/change")
    async def _change(body: UserPasswordUpdate) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": "changed"}

    @probe.post("/reset")
    async def _reset(body: AdminPasswordReset) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": "reset"}

    return probe


_PASSWORD_BODIES = {
    "/create": ("password", {"username": "someone", "email": "someone@example.com"}),
    "/change": ("new_password", {"current_password": "Current-Pa55word"}),
    "/reset": ("new_password", {}),
}


@pytest.mark.parametrize("path", sorted(_PASSWORD_BODIES))
@pytest.mark.parametrize(
    ("rejected", "reason"),
    [
        ("lower-only-5a7c!", "Password must contain at least one uppercase letter"),
        ("UPPER-ONLY-5A7C!", "Password must contain at least one lowercase letter"),
        ("No-Digits-Here-xq!", "Password must contain at least one digit"),
        ("NoSpecial5a7cQx", "Password must contain at least one special character"),
    ],
)
async def test_a_password_rule_names_the_rule_but_never_the_password(
    path: str, rejected: str, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The strength rules are fixed text, so they reach the client; the password doesn't."""
    field, rest = _PASSWORD_BODIES[path]
    async with AsyncClient(
        transport=ASGITransport(app=_password_app()), base_url="http://t"
    ) as probe:
        with caplog.at_level(logging.DEBUG):
            response = await probe.post(path, json={**rest, field: rejected})

    assert response.status_code == 422, response.text
    (error,) = response.json()["details"]
    assert error["loc"] == ["body", field]
    assert error["type"] == "value_error"
    assert error["msg"] == f"Value error, {reason}"
    assert "input" not in error
    assert "ctx" not in error
    assert rejected not in response.text
    assert _validation_records(caplog), "the handler logs a validation error"
    assert rejected not in caplog.text
