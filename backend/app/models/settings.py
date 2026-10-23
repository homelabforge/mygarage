"""Settings database model.

The secret settings (``SECRET_SETTING_KEYS``) are encrypted at rest here, at the
model, so every ORM reader and writer gets it without a change of its own:

- The ``value`` column is mapped to the attribute ``stored_value``, which holds
  the raw stored form: ciphertext for a secret, the value itself otherwise.
- ``value`` is a hybrid property. On an instance it reads and writes plaintext,
  encrypting and decrypting secret keys. At class level it is the raw column, so
  ``select(Setting.value)`` and ``where(Setting.value == ...)`` see the stored
  form, which fails closed for a secret.

Code that moves raw stored values (a test fixture, a restore of a backup that
already holds ciphertext) reads and writes ``stored_value`` instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.sql.elements import SQLColumnExpression

from app.database import Base
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import (
    CIPHERTEXT_PREFIX,
    DecryptStatus,
    current_kid,
    decrypt,
    encrypt,
    is_ciphertext,
)

# Raised by the setter below; it lives in a utils leaf so the error handlers can
# map it without importing a model (F-3). Re-exported, so existing imports work.
from app.utils.settings_errors import SettingCiphertextValue

__all__ = ["Setting", "SettingCiphertextValue"]

_UNSET: Any = object()


class Setting(Base):
    """User settings model."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    stored_value: Mapped[str | None] = mapped_column("value", Text)
    category: Mapped[str] = mapped_column(String(50), server_default="general")
    description: Mapped[str | None] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __init__(
        self,
        *,
        key: str,
        value: str | None = _UNSET,
        stored_value: str | None = _UNSET,
        **kwargs: Any,
    ) -> None:
        """Create a row, setting ``key`` before ``value`` whatever the kwargs order.

        The setter needs the key to know whether to encrypt, and binds it in as
        the associated data.

        Args:
            key: The setting key.
            value: The plaintext value; encrypted for a secret key.
            stored_value: The raw stored form, written as is (for code restoring
                bytes that are already ciphertext). Not together with ``value``.
            **kwargs: The other columns.

        Raises:
            TypeError: Both ``value`` and ``stored_value`` were given.
            SettingCiphertextValue: ``value`` for a secret key is already ciphertext.
            SettingsKeyUnavailable: A secret value needs encrypting and there is
                no usable keyring.
        """
        if value is not _UNSET and stored_value is not _UNSET:
            raise TypeError("Setting() takes value or stored_value, not both")
        super().__init__(key=key, **kwargs)
        if stored_value is not _UNSET:
            self.stored_value = stored_value
        elif value is not _UNSET:
            self.value = value

    @hybrid_property
    def value(self) -> str | None:  # pyright: ignore[reportRedeclaration]
        """The plaintext value.

        A secret key's ciphertext is decrypted, and a legacy plaintext one is
        passed through; one that can't be decrypted reads as None (see
        ``unreadable``). Any other key reads as stored.
        """
        stored = self.stored_value
        if self.key not in SECRET_SETTING_KEYS or not stored:
            return stored
        return decrypt(self.key, stored).plaintext

    @value.inplace.setter
    def _value_setter(self, new: str | None) -> None:
        """Store a plaintext value, encrypting it for a secret key.

        ``""`` and None are stored as is, so "configured or not" stays visible.
        Re-saving the value a current-key ciphertext already holds leaves the row
        alone, so a form saved unchanged doesn't churn it. A legacy plaintext
        row, or one under an older key, is always rewritten as current
        ciphertext, even when the value is unchanged (R1-H3).

        Raises:
            SettingCiphertextValue: ``new`` for a secret key is already ciphertext.
            SettingsKeyUnavailable: There is no usable keyring; nothing changes.
        """
        if self.key not in SECRET_SETTING_KEYS or not new:
            self.stored_value = new
            return
        if new.startswith(CIPHERTEXT_PREFIX):
            raise SettingCiphertextValue(self.key)
        stored = self.stored_value
        if stored and is_ciphertext(stored):
            result = decrypt(self.key, stored)
            if (
                result.status is DecryptStatus.DECRYPTED
                and result.kid == current_kid()
                and result.plaintext == new
            ):
                return
        self.stored_value = encrypt(self.key, new)

    @value.inplace.expression
    @classmethod
    def _value_expression(cls) -> SQLColumnExpression[str | None]:
        """At class level, the raw column: queries see the stored form."""
        return cls.stored_value

    @property
    def unreadable(self) -> bool:
        """True for a secret key holding ciphertext that can't be decrypted.

        Configured but unreadable (D3a): ``value`` reads as None, and the stored
        ciphertext must not be overwritten by a placeholder save.
        """
        stored = self.stored_value
        return (
            self.key in SECRET_SETTING_KEYS
            and is_ciphertext(stored)
            and decrypt(self.key, stored or "").unreadable
        )
