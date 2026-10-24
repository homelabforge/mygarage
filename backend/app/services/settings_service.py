"""Service helpers for working with settings."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting


class SecretUnreadableError(Exception):
    """A secret setting is configured, but its ciphertext can't be decrypted.

    Raised by ``SettingsService.get_secret`` for the readers where the credential
    is optional, so None would mean "connect without auth" and an unreadable
    secret would silently drop the auth instead of stopping (R1-M1). Carries the
    key name only, never the value.

    Attributes:
        key: The setting key that can't be read.
    """

    def __init__(self, key: str) -> None:
        """Build the error for one setting key."""
        self.key = key
        super().__init__(f"The stored {key} can't be decrypted; re-enter it")


def reenter_message(label: str) -> str:
    """The advice shown when a stored secret can't be decrypted.

    Args:
        label: What the secret is, for a person ("ntfy token", "MQTT password").

    Returns:
        "The stored <label> can't be decrypted; re-enter it".
    """
    return f"The stored {label} can't be decrypted; re-enter it"


#: What an on/off setting reads as on, after a strip and lower-casing (R5).
SWITCH_ON_VALUES: frozenset[str] = frozenset({"true", "1", "yes", "on"})

#: What an on/off setting reads as off, after a strip and lower-casing (R5).
#: ``parse_bool`` reads anything outside ``SWITCH_ON_VALUES`` as off anyway;
#: this set names the words that mean off on purpose.
SWITCH_OFF_VALUES: frozenset[str] = frozenset({"false", "0", "no", "off"})


def parse_bool(text: str | None, default: bool) -> bool:
    """Read an on/off setting's stored text with the one vocabulary (R5).

    Args:
        text: The stored value, or None when there is none.
        default: What a missing or blank value means at this reader.

    Returns:
        ``default`` for None or text that is blank after a strip; True for a
        word in ``SWITCH_ON_VALUES`` (true, 1, yes, on) in any case; False for
        anything else, so an unknown word never turns a feature on.
    """
    if text is None:
        return default
    word = text.strip().lower()
    if not word:
        return default
    return word in SWITCH_ON_VALUES


class SettingsService:
    """Utility helpers for CRUD operations on Setting rows."""

    @staticmethod
    async def get_all(db: AsyncSession) -> list[Setting]:
        """Return all settings sorted by key."""
        result = await db.execute(select(Setting).order_by(Setting.key))
        return list(result.scalars().all())

    @staticmethod
    async def get(db: AsyncSession, key: str) -> Setting | None:
        """Fetch a single setting by key."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_secret(db: AsyncSession, key: str) -> str | None:
        """Read a secret setting whose absence means "connect without auth".

        Args:
            db: The session to read through.
            key: The setting key.

        Returns:
            The plaintext, ``""`` when blank, or None when there is no row.

        Raises:
            SecretUnreadableError: The row holds ciphertext that can't be
                decrypted, so the caller must stop rather than go unauthenticated.
        """
        setting = await SettingsService.get(db, key)
        if setting is None:
            return None
        if setting.unreadable:
            raise SecretUnreadableError(key)
        return setting.value

    @staticmethod
    async def get_bool(db: AsyncSession, key: str, default: bool = False) -> bool:
        """Whether a switch setting is on, read by ``parse_bool``.

        On is "true", "1", "yes" or "on" (``SWITCH_ON_VALUES``), in any case
        and with surrounding whitespace ignored. A missing row, or a value that
        is blank after a strip, reads as ``default``; any other text is off.
        Every on/off setting in the app is read with this vocabulary, so a
        value the notification dispatcher treats as on is on everywhere.
        """
        setting = await SettingsService.get(db, key)
        return parse_bool(setting.value if setting is not None else None, default)

    @staticmethod
    async def set(
        db: AsyncSession,
        key: str,
        value: str | None,
        *,
        category: str | None = None,
        description: str | None = None,
        encrypted: bool | None = None,
    ) -> Setting:
        """
        Create or update a Setting.

        The operation is not committed automatically; callers control the transaction.
        """
        setting = await SettingsService.get(db, key)

        if setting is None:
            setting = Setting(
                key=key,
                value=value,
                category=category or "general",
                description=description,
                encrypted=encrypted if encrypted is not None else False,
            )
            db.add(setting)
        else:
            setting.value = value
            if category is not None:
                setting.category = category
            if description is not None:
                setting.description = description
            if encrypted is not None:
                setting.encrypted = encrypted

        await db.flush()
        return setting

    @staticmethod
    async def delete(db: AsyncSession, key: str) -> None:
        """Delete a setting by key."""
        await db.execute(delete(Setting).where(Setting.key == key))
        await db.flush()
