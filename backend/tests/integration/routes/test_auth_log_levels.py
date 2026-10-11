"""A 401 the client caused is not a server error.

Every signed-out page load asks /auth/me, and each one logged "No credentials
provided" at ERROR. A bad or stale token is worth a WARNING, not an ERROR.
"""

import logging

import pytest
from httpx import AsyncClient

from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.auth, pytest.mark.asyncio]


def _levels(caplog: pytest.LogCaptureFixture, text: str) -> list[int]:
    return [r.levelno for r in caplog.records if text in r.getMessage()]


async def test_signed_out_me_logs_at_debug(
    client: AsyncClient, set_auth_mode, caplog: pytest.LogCaptureFixture
) -> None:
    await set_auth_mode("local")
    caplog.set_level(logging.DEBUG, logger="app.services.auth")

    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert _levels(caplog, "No credentials provided") == [logging.DEBUG]


async def test_a_token_that_does_not_decode_logs_a_warning(
    client: AsyncClient, set_auth_mode, caplog: pytest.LogCaptureFixture
) -> None:
    await set_auth_mode("local")
    caplog.set_level(logging.DEBUG, logger="app.services.auth")

    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert _levels(caplog, "JWT decode error") == [logging.WARNING]


async def test_a_token_with_no_user_id_logs_a_warning(
    client: AsyncClient, set_auth_mode, caplog: pytest.LogCaptureFixture
) -> None:
    await set_auth_mode("local")
    caplog.set_level(logging.DEBUG, logger="app.services.auth")
    token = create_access_token({"username": "nobody"})

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert _levels(caplog, "Token missing user_id or username") == [logging.WARNING]


async def test_a_bad_user_id_logs_a_warning_on_one_line(
    client: AsyncClient, set_auth_mode, caplog: pytest.LogCaptureFixture
) -> None:
    """The id comes from the token, so a newline in it can't start a fake log line."""
    await set_auth_mode("local")
    caplog.set_level(logging.DEBUG, logger="app.services.auth")
    token = create_access_token({"sub": "abc\ninjected", "username": "nobody"})

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert _levels(caplog, "Invalid user_id format") == [logging.WARNING]
    [message] = [
        r.getMessage() for r in caplog.records if "Invalid user_id format" in r.getMessage()
    ]
    assert "\n" not in message
    assert "abc\\ninjected" in message
