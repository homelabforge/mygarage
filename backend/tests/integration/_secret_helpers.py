"""Shared helpers for the secret-settings tests: seeding raw rows and reading them back.

The raw column is read with plain SQL through a fresh session, so neither the
identity map nor the ``Setting.value`` hybrid stands between an assertion and
the stored bytes. "Unreadable" is seeded as a real ciphertext bound to another
key name, so it is well-formed and fails only on the associated data.

The ``use_keys`` fixture that swaps the keyring for isolated test keys lives in
``tests/integration/conftest.py``; ``keyring_entry`` builds those keys.
"""

import base64
import hashlib
from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Setting
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import encrypt

#: The `keep_rows` fixture's callable: snapshot these keys, restore them at teardown.
Keep = Callable[..., Awaitable[None]]

#: The `use_keys` fixture's callable: takes keyring entries (first is current), returns its kid.
UseKeys = Callable[..., str | None]


def keyring_entry(seed: bytes) -> str:
    """A keyring entry: base64url over 32 bytes derived from `seed`."""
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest()).rstrip(b"=").decode()


def unreadable_ciphertext(key: str) -> str:
    """A well-formed ciphertext that won't open under `key` (bound to another name)."""
    return encrypt(f"not_{key}", "the-real-secret")


async def seed_rows(db: AsyncSession, keep: Keep, rows: dict[str, str]) -> None:
    """Store raw column values, keeping the originals for teardown."""
    await keep(*rows)
    await db.execute(delete(Setting).where(Setting.key.in_(list(rows))))
    for key, raw in rows.items():
        db.add(Setting(key=key, stored_value=raw))
    await db.commit()


async def raw_column(sessionmaker: async_sessionmaker[AsyncSession], key: str) -> str | None:
    """The stored column, as another connection sees it (committed only)."""
    async with sessionmaker() as fresh:
        return (
            await fresh.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key})
        ).scalar_one_or_none()


async def read_back(sessionmaker: async_sessionmaker[AsyncSession], key: str) -> str | None:
    """The value as an ORM reader sees it, through a fresh session."""
    async with sessionmaker() as fresh:
        row = (await fresh.execute(select(Setting).where(Setting.key == key))).scalar_one()
        return row.value


async def insert_raw(db: AsyncSession, rows: dict[str, str]) -> None:
    """Write rows with plain SQL, as a migration or an old restore would; `encrypted` false."""
    for key, value in rows.items():
        await db.execute(
            text("INSERT INTO settings (key, value, encrypted) VALUES (:k, :v, :e)"),
            {"k": key, "v": value, "e": False},
        )
    await db.commit()


async def only_these_secret_rows(db: AsyncSession, keep: Keep, rows: dict[str, str]) -> None:
    """Leave exactly `rows` among the secret keys, stored as given with plain SQL.

    Every secret key is kept and deleted first, so a reader that walks all of
    them (the sweep, the status endpoint, the backup preflight) sees only these.
    """
    secrets = sorted(SECRET_SETTING_KEYS)
    await keep(*secrets, *rows)
    await db.execute(delete(Setting).where(Setting.key.in_(sorted({*secrets, *rows}))))
    await db.commit()
    await insert_raw(db, rows)
