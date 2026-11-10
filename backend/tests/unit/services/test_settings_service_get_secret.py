"""`SettingsService.get_secret`: None means unset, unreadable raises (R1-M1).

For a credential that is optional, None means "connect without auth", so a
secret that is configured but can't be decrypted must not read as None there.
"""

from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import settings as settings_model
from app.models.settings import Setting
from app.routes.settings import _stored_secret_mask  # pyright: ignore[reportPrivateUsage]
from app.services.settings_service import SecretUnreadableError, SettingsService, reenter_message
from app.utils.settings_crypto import DecryptResult, encrypt

KEY = "ntfy_token"


async def _store(db: AsyncSession, raw: str | None) -> None:
    await db.execute(delete(Setting).where(Setting.key == KEY))
    if raw is not None:
        db.add(Setting(key=KEY, stored_value=raw))
    await db.commit()


@pytest.mark.integration
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
    row = await SettingsService.get(db_session, KEY)
    assert row is not None
    assert row.value is None


@pytest.mark.integration
@pytest.mark.parametrize("readable", [True, False], ids=["readable", "unreadable"])
async def test_one_read_decrypts_once(
    db_session: AsyncSession, keep_rows: Callable[..., Awaitable[None]], readable: bool
) -> None:
    """Asking "unreadable?" and then for the value used to open the ciphertext twice."""
    await keep_rows(KEY)
    await _store(db_session, encrypt(KEY if readable else "gotify_token", "tk_current"))
    setting = await SettingsService.get(db_session, KEY)
    assert setting is not None
    real_decrypt = settings_model.decrypt
    calls: list[str] = []

    def counted(name: str, stored: str) -> DecryptResult:
        calls.append(name)
        return real_decrypt(name, stored)

    with patch.object(settings_model, "decrypt", counted):
        if readable:
            assert await SettingsService.get_secret(db_session, KEY) == "tk_current"
        else:
            with pytest.raises(SecretUnreadableError):
                await SettingsService.get_secret(db_session, KEY)
        assert len(calls) == 1

        calls.clear()
        _stored_secret_mask(setting)
        assert len(calls) == 1


@pytest.mark.unit
def test_the_error_carries_the_shared_re_enter_wording() -> None:
    assert str(SecretUnreadableError(KEY)) == reenter_message(KEY)
