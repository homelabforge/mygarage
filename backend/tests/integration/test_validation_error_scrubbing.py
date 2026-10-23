"""A rejected secret stays out of the validation-error log and the 422 body (plan test 9, L2).

Pydantic's error carries the rejected value as `input` (on a missing field, the
whole parent object) and the constraint as `ctx`. The handler logged both, so a
too-long password, OIDC client secret or API key landed in the server log.

- The log line keeps `type`, `loc` and `msg` only, for every field.
- The 422 body keeps `input` except where the field's name (the last `loc`
  segment) contains `password`, `secret`, `token` or `key`, in any case.
"""

import logging

import pytest
from fastapi.exceptions import RequestValidationError
from httpx import AsyncClient
from starlette.requests import Request

from app.utils.error_handlers import handle_validation_error

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Past LoginRequest.password's max_length (100), so pydantic rejects it and echoes it as `input`.
REJECTED_PASSWORD = "Rejected-Pa55word-" + "x" * 100
REJECTED_USERNAME = "rejected-username-" + "y" * 100


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
    rejected = f"rejected-{field}-value"
    exc = RequestValidationError(
        [
            {
                "type": "string_too_long",
                "loc": ("body", field),
                "msg": "String should have at most 4 characters",
                "input": rejected,
                "ctx": {"max_length": 4},
            }
        ]
    )

    with caplog.at_level(logging.DEBUG):
        response = await handle_validation_error(_request(), exc)

    body = response.body.decode()
    assert (rejected in body) is echoed
    assert rejected not in caplog.text
