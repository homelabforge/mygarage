"""Tests for migration 087 — webhook ingest settings (#138).

Non-FATAL migration: inserts webhook_ingest_token and telegram_inbound_enabled
setting rows — webhooks stay disabled until the user generates a token.
Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset).
"""

import importlib.util
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_settings_table(engine):
    """Minimal settings table to receive the new rows."""
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE settings (
                    id {pk},
                    key VARCHAR(100) UNIQUE NOT NULL,
                    value TEXT,
                    category VARCHAR(50),
                    encrypted BOOLEAN DEFAULT false,
                    description TEXT
                )
                """
            )
        )


def _get_settings(engine):
    """Return dict of key → (value, category, encrypted) from settings table."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT key, value, category, encrypted FROM settings ORDER BY key")
        ).fetchall()
    # SQLite stores booleans as integers (0/1), so normalize to bool
    return {r[0]: (r[1], r[2], bool(r[3])) for r in rows}


def test_087_inserts_webhook_settings(engine_for_migration):
    """Both webhook_ingest_token and telegram_inbound_enabled are inserted."""
    _dialect, engine, _url = engine_for_migration
    _make_settings_table(engine)

    _load("087_add_webhook_ingest_settings").upgrade(engine)

    settings = _get_settings(engine)
    assert "webhook_ingest_token" in settings
    assert "telegram_inbound_enabled" in settings

    token_val, token_cat, token_enc = settings["webhook_ingest_token"]
    assert token_val == ""
    assert token_cat == "integrations"
    assert token_enc is True

    tg_val, tg_cat, tg_enc = settings["telegram_inbound_enabled"]
    assert tg_val == "false"
    assert tg_cat == "integrations"
    assert tg_enc is False


def test_087_is_idempotent(engine_for_migration):
    """Re-running must be a no-op — settings already exist."""
    _dialect, engine, _url = engine_for_migration
    _make_settings_table(engine)

    mod = _load("087_add_webhook_ingest_settings")
    mod.upgrade(engine)
    settings_before = _get_settings(engine)

    mod.upgrade(engine)

    assert _get_settings(engine) == settings_before


def test_087_skips_cleanly_when_settings_absent(engine_for_migration):
    """Early return when settings table doesn't exist."""
    _dialect, engine, _url = engine_for_migration

    _load("087_add_webhook_ingest_settings").upgrade(engine)


def test_087_preserves_existing_telegram_setting(engine_for_migration):
    """If telegram_inbound_enabled already exists, don't re-insert."""
    _dialect, engine, _url = engine_for_migration
    _make_settings_table(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO settings (key, value, category, encrypted, description)
                VALUES ('telegram_inbound_enabled', 'true', 'integrations', false, 'Preset value')
                """
            )
        )

    _load("087_add_webhook_ingest_settings").upgrade(engine)

    settings = _get_settings(engine)
    tg_val, _, _ = settings["telegram_inbound_enabled"]
    assert tg_val == "true"
