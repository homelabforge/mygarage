"""`SettingsService.get_secret`: None means unset, unreadable raises (R1-M1).

For a credential that is optional, None means "connect without auth", so a
secret that is configured but can't be decrypted must not read as None there.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services.settings_service import SecretUnreadableError, SettingsService
from app.utils.settings_crypto import encrypt

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

KEY = "ntfy_token"


async def _store(db: AsyncSession, raw: str | None) -> None:
    await db.execute(delete(Setting).where(Setting.key == KEY))
    if raw is not None:
        db.add(Setting(key=KEY, stored_value=raw))
    await db.commit()


async def test_get_secret(
    db_session: AsyncSession, keep_rows: Callable[..., Awaitable[None]]
) -> None:
    await keep_rows(KEY)

    await _store(db_session, None)
    assert await SettingsService.get_secret(db_session, KEY) is None

    await _store(db_session, "")
    assert await SettingsService.get_secret(db_session, KEY) == ""

    await _store(db_session, "legacy-plaintext")
    assert await SettingsService.get_secret(db_session, KEY) == "legacy-plaintext"

    await _store(db_session, encrypt(KEY, "tk_current"))
    assert await SettingsService.get_secret(db_session, KEY) == "tk_current"

    # Ciphertext bound to another key name: configured, but unreadable here.
    await _store(db_session, encrypt("gotify_token", "tk_elsewhere"))
    with pytest.raises(SecretUnreadableError) as caught:
        await SettingsService.get_secret(db_session, KEY)
    assert caught.value.key == KEY
    assert "tk_elsewhere" not in str(caught.value)
    assert "enc:v1:" not in str(caught.value)
    # The plain getter still reads it as unset.
    assert (await SettingsService.get(db_session, KEY)).value is None  # type: ignore[union-attr]
