"""The startup sweep encrypts leftover plaintext secrets and re-keys old ones (D5a).

Plan test 5, and the sweep half of test 17:
- plaintext secret rows get encrypted, a row under an older key id gets
  re-encrypted under the current one, and a current-key row is left alone;
- unreadable rows (another key name, an unknown key id, tampered or malformed
  ciphertext) are reported and left byte-identical;
- every secret row ends with `encrypted` true, and a second run is a no-op;
- with the keyring unavailable, or a database error, the sweep logs and writes
  nothing, and never raises;
- `encrypt_secret_rows` flushes and leaves the commit to its caller (Task 4's
  backup preflight builds on that);
- on a file-backed WAL database, the plaintext is gone from both `mygarage.db`
  and `mygarage.db-wal` afterwards, and a checkpoint that comes back busy is
  logged without failing the sweep.

The plaintext rows are seeded with raw SQL, not through the model: a Core
`insert()` or `update()`, or an old backup, writes the column as is, and the
sweep is the backstop for exactly those rows. Every keyring here is an isolated
test key in MYGARAGE_SETTINGS_KEY, reset before and after.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import bindparam, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import configure_sqlite_engine
from app.models.settings import Setting
from app.services.settings_secrets import SweepReport, encrypt_secret_rows, sweep_secret_settings
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS
from app.utils.settings_crypto import (
    CIPHERTEXT_PREFIX,
    encrypt,
)
from tests.integration._secret_helpers import (
    Keep,
    UseKeys,
    keyring_entry,
    only_these_secret_rows,
    raw_column,
    read_back,
    unreadable_ciphertext,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SECRETS = sorted(SECRET_SETTING_KEYS)
PLAIN_NTFY = "plain-ntfy-token-9b1e"
PLAIN_TOMTOM = "plain-tomtom-key-4c2a"
OLD_LLM = "llm-key-under-the-old-key-77d0"
CURRENT_GOTIFY = "gotify-under-the-current-key-1f3b"


KEY_A = keyring_entry(b"sweep test key A")
KEY_B = keyring_entry(b"sweep test key B")
KEY_C = keyring_entry(b"sweep test key C")


async def _encrypted_flags(
    sessionmaker: async_sessionmaker[AsyncSession], keys: list[str]
) -> dict[str, bool]:
    async with sessionmaker() as fresh:
        result = await fresh.execute(
            text("SELECT key, encrypted FROM settings WHERE key IN :keys").bindparams(
                bindparam("keys", expanding=True)
            ),
            {"keys": keys},
        )
        return {key: bool(flag) for key, flag in result.all()}


def _tampered(key: str) -> str:
    """A current-key ciphertext for `key` with one payload character changed."""
    stored = encrypt(key, "the-real-secret")
    head, _, payload = stored.rpartition(":")
    middle = len(payload) // 2
    swapped = "A" if payload[middle] != "A" else "B"
    return f"{head}:{payload[:middle]}{swapped}{payload[middle + 1 :]}"


# ------------------------------------------------------------- plan test 5


async def test_the_sweep_encrypts_rekeys_and_reports(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_keys(KEY_C)
    unknown_kid = encrypt("discord_webhook_url", "under-a-key-nobody-has")
    use_keys(KEY_A)
    old_llm = encrypt("llm_api_key", OLD_LLM)
    current = use_keys(KEY_B, KEY_A)
    assert current is not None
    current_gotify = encrypt("gotify_token", CURRENT_GOTIFY)
    foreign = unreadable_ciphertext("slack_webhook_url")
    seeded = {
        "ntfy_token": PLAIN_NTFY,
        "tomtom_api_key": PLAIN_TOMTOM,
        "llm_api_key": old_llm,
        "gotify_token": current_gotify,
        "slack_webhook_url": foreign,
        "discord_webhook_url": unknown_kid,
        "pushover_user_key": "",
        "ntfy_server": "https://ntfy.example.com",
    }
    await only_these_secret_rows(db_session, keep_rows, seeded)

    with caplog.at_level(logging.INFO, logger="app.services.settings_secrets"):
        report = await sweep_secret_settings(db_session)

    assert report == SweepReport(
        encrypted=("ntfy_token", "tomtom_api_key"),
        rekeyed=("llm_api_key",),
        unreadable=("discord_webhook_url", "slack_webhook_url"),
    )
    for key, plain in (
        ("ntfy_token", PLAIN_NTFY),
        ("tomtom_api_key", PLAIN_TOMTOM),
        ("llm_api_key", OLD_LLM),
    ):
        raw = await raw_column(test_sessionmaker, key)
        assert raw is not None
        assert raw.startswith(f"{CIPHERTEXT_PREFIX}{current}:"), key
        assert plain not in raw
        assert await read_back(test_sessionmaker, key) == plain
    assert await raw_column(test_sessionmaker, "llm_api_key") != old_llm
    for key in ("gotify_token", "slack_webhook_url", "discord_webhook_url", "pushover_user_key"):
        assert await raw_column(test_sessionmaker, key) == seeded[key], key
    assert await raw_column(test_sessionmaker, "ntfy_server") == "https://ntfy.example.com"

    secret_keys = sorted(k for k in seeded if k in SECRET_SETTING_KEYS)
    assert await _encrypted_flags(test_sessionmaker, secret_keys) == dict.fromkeys(
        secret_keys, True
    )
    assert await _encrypted_flags(test_sessionmaker, ["ntfy_server"]) == {"ntfy_server": False}

    sweep_lines = [r for r in caplog.records if r.name == "app.services.settings_secrets"]
    assert [r.getMessage() for r in sweep_lines if r.getMessage().startswith("Encrypted")] == [
        "Encrypted 2, re-keyed 1, unreadable: discord_webhook_url, slack_webhook_url. They read "
        "as unset until their key is back in the keyring or they are re-entered."
    ]
    assert max(r.levelno for r in sweep_lines) == logging.ERROR
    for secret in (PLAIN_NTFY, PLAIN_TOMTOM, OLD_LLM, CURRENT_GOTIFY, CIPHERTEXT_PREFIX):
        assert secret not in caplog.text

    # Dropping the old key now loses nothing: the re-keyed row is under the current one.
    use_keys(KEY_B)
    assert await read_back(test_sessionmaker, "llm_api_key") == OLD_LLM


async def test_a_second_sweep_changes_nothing(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_keys(KEY_A)
    old = encrypt("llm_api_key", OLD_LLM)
    use_keys(KEY_B, KEY_A)
    await only_these_secret_rows(
        db_session,
        keep_rows,
        {
            "ntfy_token": PLAIN_NTFY,
            "llm_api_key": old,
            "slack_webhook_url": unreadable_ciphertext("slack_webhook_url"),
        },
    )
    first = await sweep_secret_settings(db_session)
    assert first.encrypted == ("ntfy_token",)
    after_first = {k: await raw_column(test_sessionmaker, k) for k in SECRETS}

    with caplog.at_level(logging.INFO, logger="app.services.settings_secrets"):
        second = await sweep_secret_settings(db_session)

    assert second == SweepReport(unreadable=("slack_webhook_url",))
    assert {k: await raw_column(test_sessionmaker, k) for k in SECRETS} == after_first
    assert "Encrypted 0, re-keyed 0, unreadable: slack_webhook_url" in caplog.text


async def test_tampered_and_malformed_ciphertext_stays_byte_identical(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    kid = use_keys(KEY_A)
    seeded = {
        "gotify_token": _tampered("gotify_token"),
        "matrix_access_token": "enc:v1:not-a-kid:AAAA",
        "telegram_bot_token": f"enc:v1:{kid}:short",
        "pushover_api_token": f"enc:v1:{kid}:not*base64url",
    }
    await only_these_secret_rows(db_session, keep_rows, seeded)

    report = await sweep_secret_settings(db_session)

    assert report == SweepReport(unreadable=tuple(sorted(seeded)))
    for key, stored in seeded.items():
        assert await raw_column(test_sessionmaker, key) == stored, key


async def test_an_unavailable_keyring_writes_nothing(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})
    assert use_keys("not-a-valid-key") is None

    with caplog.at_level(logging.INFO, logger="app.services.settings_secrets"):
        report = await sweep_secret_settings(db_session)

    assert report == SweepReport()
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY
    assert await _encrypted_flags(test_sessionmaker, ["ntfy_token"]) == {"ntfy_token": False}
    errors = [
        r
        for r in caplog.records
        if r.name == "app.services.settings_secrets" and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1
    assert "unavailable" in errors[0].getMessage()
    assert PLAIN_NTFY not in caplog.text


async def test_a_database_error_is_logged_and_swallowed(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})
    failure = OperationalError(
        "UPDATE settings SET value=?", {"value": "enc:v1:bound-parameter"}, Exception("locked")
    )

    with (
        caplog.at_level(logging.INFO, logger="app.services.settings_secrets"),
        patch.object(db_session, "commit", side_effect=failure),
    ):
        report = await sweep_secret_settings(db_session)

    assert report == SweepReport()
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY
    errors = [
        r
        for r in caplog.records
        if r.name == "app.services.settings_secrets" and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1
    assert "next start" in errors[0].getMessage()
    assert "bound-parameter" not in caplog.text
    assert errors[0].exc_info is None


async def test_encrypt_secret_rows_flushes_and_leaves_the_commit(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    kid = use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})

    report = await encrypt_secret_rows(db_session)

    assert report == SweepReport(encrypted=("ntfy_token",))
    flushed = (
        await db_session.execute(text("SELECT value FROM settings WHERE key = 'ntfy_token'"))
    ).scalar_one()
    assert flushed.startswith(f"{CIPHERTEXT_PREFIX}{kid}:")
    await db_session.rollback()
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


# -------------------------------------------- plan test 17: SQLite remnants

REMNANT = "WAL-REMNANT-plaintext-5e1d07"


async def _file_db(tmp_path: Path, *, timeout: float = 30) -> tuple[AsyncEngine, Path]:
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


def _holding(path: Path, needle: bytes) -> list[str]:
    files = (path, path.with_name(path.name + "-wal"))
    return [f.name for f in files if f.exists() and needle in f.read_bytes()]


async def test_no_plaintext_remains_in_the_database_or_the_wal(
    tmp_path: Path, use_keys: UseKeys
) -> None:
    kid = use_keys(KEY_A)
    engine, path = await _file_db(tmp_path)
    try:
        assert _holding(path, REMNANT.encode()) == ["mygarage.db", "mygarage.db-wal"]
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        async with sessionmaker() as db:
            report = await sweep_secret_settings(db)

        assert report == SweepReport(encrypted=("ntfy_token",))
        # Read before the engine is disposed: closing the last connection would
        # checkpoint on its own and hide a sweep that didn't.
        assert _holding(path, REMNANT.encode()) == []
        raw = await raw_column(sessionmaker, "ntfy_token")
        assert raw is not None and raw.startswith(f"{CIPHERTEXT_PREFIX}{kid}:")
        assert await read_back(sessionmaker, "ntfy_token") == REMNANT
    finally:
        await engine.dispose()


async def test_a_busy_checkpoint_is_logged_and_the_sweep_still_commits(
    tmp_path: Path, use_keys: UseKeys, caplog: pytest.LogCaptureFixture
) -> None:
    use_keys(KEY_A)
    engine, path = await _file_db(tmp_path, timeout=0.2)
    reader = sqlite3.connect(path, isolation_level=None)
    try:
        # An open read transaction pins the WAL, so a TRUNCATE checkpoint can't finish.
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM settings").fetchall()
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        with caplog.at_level(logging.INFO, logger="app.services.settings_secrets"):
            async with sessionmaker() as db:
                report = await sweep_secret_settings(db)

        assert report == SweepReport(encrypted=("ntfy_token",))
        assert await read_back(sessionmaker, "ntfy_token") == REMNANT
        raw = await raw_column(sessionmaker, "ntfy_token")
        assert raw is not None and raw.startswith(CIPHERTEXT_PREFIX)
        warnings = [
            r
            for r in caplog.records
            if r.name == "app.services.settings_secrets" and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "checkpoint" in warnings[0].getMessage()
        assert "Encrypted 1, re-keyed 0, unreadable: none" in caplog.text
    finally:
        reader.execute("ROLLBACK")
        reader.close()
        await engine.dispose()
