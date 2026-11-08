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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import configure_sqlite_engine
from app.models.settings import Setting
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import encrypt
from tests._keep_rows import Keep

#: The tail of the advice a secret that can't be decrypted gets, wherever it's shown.
REENTER = "can't be decrypted; re-enter it"

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


#: The plaintext secret `file_db` seeds, left in the main file and the WAL.
REMNANT = "WAL-REMNANT-plaintext-5e1d07"


async def file_db(tmp_path: Path, *, timeout: float = 30) -> tuple[AsyncEngine, Path]:
    """A file-backed WAL database holding one plaintext secret, in the main file and the WAL.

    The connections start with secure_delete OFF, whatever the build default, so
    only the sweep's own PRAGMA can scrub the freed cell.
    """
    path = tmp_path / "mygarage.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": timeout})
    configure_sqlite_engine(engine)

    @event.listens_for(engine.sync_engine, "connect")
    def _secure_delete_off(dbapi_connection: Any, _record: Any) -> None:  # pyright: ignore[reportUnusedFunction]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA secure_delete=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Setting.__table__.create)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    async with engine.connect() as conn:
        # The secret first, so later rows sit between it and the free space and
        # its freed cell isn't simply reused by the longer ciphertext.
        await conn.execute(
            text("INSERT INTO settings (key, value, encrypted) VALUES ('ntfy_token', :v, 0)"),
            {"v": REMNANT},
        )
        for n in range(8):
            await conn.execute(
                text("INSERT INTO settings (key, value, encrypted) VALUES (:k, :v, 0)"),
                {"k": f"plain_{n}", "v": f"value-{n}"},
            )
        await conn.commit()
        await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        # Touch the page again, so the plaintext is in a WAL frame as well.
        await conn.execute(text("UPDATE settings SET value = 'changed' WHERE key = 'plain_0'"))
        await conn.commit()
    return engine, path


def holding(path: Path, needle: bytes) -> list[str]:
    """Which of the database file and its WAL hold `needle`, by file name."""
    files = (path, path.with_name(path.name + "-wal"))
    return [f.name for f in files if f.exists() and needle in f.read_bytes()]


async def pooled_pragma(engine: AsyncEngine, pragma: str) -> int:
    """The PRAGMA's value on the connection the pool hands out next."""
    async with engine.connect() as conn:
        return int((await conn.execute(text(f"PRAGMA {pragma}"))).scalar_one())
