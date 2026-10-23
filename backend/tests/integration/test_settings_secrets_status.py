"""`GET /api/settings/secrets/status`: what the Settings banner reports (D3a).

It is admin-only, like the rest of `/api/settings`, and open on
`auth_mode=none`, where the one person using the app runs the instance. Both
fields are computed live: `keyring` from the keyring itself, and
`unreadable_keys` from the rows as they are now, not from the startup sweep.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import (
    CIPHERTEXT_PREFIX,
    ENV_KEY,
    _reset_keyring_for_tests,  # pyright: ignore[reportPrivateUsage] - the suite's reset hook
    encrypt,
)
from tests.integration._secret_helpers import Keep, unreadable_ciphertext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

URL = "/api/settings/secrets/status"


async def _only_these_secret_rows(db: AsyncSession, keep: Keep, rows: dict[str, str]) -> None:
    """Leave exactly `rows` among the secret keys, stored as given."""
    await keep(*SECRET_SETTING_KEYS, *rows, "auth_mode")
    await db.execute(delete(Setting).where(Setting.key.in_([*SECRET_SETTING_KEYS, *rows])))
    for key, raw in rows.items():
        db.add(Setting(key=key, stored_value=raw))
    await db.commit()


async def _set_auth_mode(db: AsyncSession, mode: str) -> None:
    await db.execute(delete(Setting).where(Setting.key == "auth_mode"))
    db.add(Setting(key="auth_mode", value=mode))
    await db.commit()


async def test_an_admin_gets_ok_and_no_keys_when_everything_reads(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _only_these_secret_rows(
        db_session,
        keep_rows,
        {"ntfy_token": encrypt("ntfy_token", "readable"), "gotify_token": "legacy-plaintext"},
    )

    response = await client.get(URL, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"keyring": "ok", "unreadable_keys": []}


async def test_unreadable_rows_are_listed_sorted(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _only_these_secret_rows(
        db_session,
        keep_rows,
        {
            "tomtom_api_key": unreadable_ciphertext("tomtom_api_key"),
            "gotify_token": unreadable_ciphertext("gotify_token"),
            "ntfy_token": encrypt("ntfy_token", "readable"),
            "slack_webhook_url": "",
        },
    )

    response = await client.get(URL, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "keyring": "ok",
        "unreadable_keys": ["gotify_token", "tomtom_api_key"],
    }
    assert CIPHERTEXT_PREFIX not in response.text


async def test_an_unavailable_keyring_is_reported_live(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _only_these_secret_rows(
        db_session,
        keep_rows,
        {"ntfy_token": encrypt("ntfy_token", "readable"), "gotify_token": "legacy-plaintext"},
    )
    response = await client.get(URL, headers=auth_headers)
    assert response.json() == {"keyring": "ok", "unreadable_keys": []}

    # A present but broken source: unavailable, with no fallthrough.
    monkeypatch.setenv(ENV_KEY, "not-a-valid-key")
    _reset_keyring_for_tests()
    try:
        response = await client.get(URL, headers=auth_headers)
    finally:
        monkeypatch.undo()
        _reset_keyring_for_tests()

    assert response.status_code == 200, response.text
    # Nothing opens without a keyring, so the ciphertext row is unreadable too;
    # the legacy plaintext row still reads.
    assert response.json() == {"keyring": "unavailable", "unreadable_keys": ["ntfy_token"]}


async def test_a_non_admin_gets_a_403_when_sign_in_is_on(
    client: AsyncClient,
    non_admin_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
) -> None:
    await _only_these_secret_rows(
        db_session, keep_rows, {"gotify_token": unreadable_ciphertext("gotify_token")}
    )
    await _set_auth_mode(db_session, "local")

    response = await client.get(URL, headers=non_admin_headers)
    assert response.status_code == 403, response.text
    assert "gotify_token" not in response.text

    anonymous = await client.get(URL)
    assert anonymous.status_code == 401, anonymous.text


async def test_auth_mode_none_answers_without_sign_in(
    client: AsyncClient, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _only_these_secret_rows(
        db_session, keep_rows, {"gotify_token": unreadable_ciphertext("gotify_token")}
    )
    await _set_auth_mode(db_session, "none")

    response = await client.get(URL)

    assert response.status_code == 200, response.text
    assert response.json() == {"keyring": "ok", "unreadable_keys": ["gotify_token"]}
