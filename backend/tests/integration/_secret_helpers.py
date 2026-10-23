"""Shared helpers for the secret-settings tests: seeding raw rows and reading them back.

The raw column is read with plain SQL through a fresh session, so neither the
identity map nor the ``Setting.value`` hybrid stands between an assertion and
the stored bytes. "Unreadable" is seeded as a real ciphertext bound to another
key name, so it is well-formed and fails only on the associated data.
"""

from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Setting
from app.utils.settings_crypto import encrypt

#: The `keep_rows` fixture's callable: snapshot these keys, restore them at teardown.
Keep = Callable[..., Awaitable[None]]


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
