"""Migration 160: tidy stored switches, drop the dead map keys, empty the token tables."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

import app.migrations as _m
from app.services.setting_switches import SWITCH_SETTING_KEYS

pytestmark = pytest.mark.migrations

_NAME = "160_settings_hygiene"

#: Switch rows as they might sit in an old database, and what 160 leaves.
_SWITCHES = {
    "nhtsa_enabled": (" Yes ", "true"),
    "ntfy_enabled": ("1", "true"),
    "gotify_enabled": ("off", "false"),
    "slack_enabled": ("enabled", "false"),
    "discord_enabled": ("", ""),
    "matrix_enabled": (None, None),
    "email_enabled": ("true", "true"),
}

#: Not switches, so left exactly as they are.
_OTHERS = {
    "auth_mode": "Yes",
    "ntfy_topic": "enabled",
}

_MAP_KEYS = ("google_maps_api_key", "geoapify_api_key", "mapbox_api_key")


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


def _seed(engine: Engine, *, csrf: bool = True, pending: bool = True) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE settings (key VARCHAR(50) PRIMARY KEY, value TEXT, category VARCHAR(50))"
            )
        )
        rows = [(k, raw) for k, (raw, _want) in _SWITCHES.items()]
        rows += list(_OTHERS.items())
        rows += [(k, "some-old-key") for k in _MAP_KEYS]
        for key, value in rows:
            conn.execute(
                text("INSERT INTO settings (key, value, category) VALUES (:k, :v, 'general')"),
                {"k": key, "v": value},
            )
        if csrf:
            conn.execute(
                text(
                    "CREATE TABLE csrf_tokens (id INTEGER PRIMARY KEY, token VARCHAR(64),"
                    " user_id INTEGER, expires_at TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO csrf_tokens (id, token, user_id, expires_at)"
                    " VALUES (1, 'plain-csrf-token', 1, '2099-01-01 00:00:00')"
                )
            )
        if pending:
            conn.execute(
                text(
                    "CREATE TABLE oidc_pending_links (token VARCHAR(128) PRIMARY KEY,"
                    " username VARCHAR(100), expires_at TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO oidc_pending_links (token, username, expires_at)"
                    " VALUES ('plain-link-token', 'jamey', '2099-01-01 00:00:00')"
                )
            )


def _settings(engine: Engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM settings")).all()
    return {r[0]: r[1] for r in rows}


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def _expected_settings() -> dict[str, str | None]:
    return {k: want for k, (_raw, want) in _SWITCHES.items()} | _OTHERS


def test_the_seeded_rows_are_the_kind_the_test_says() -> None:
    # guard: if a key here stops being a switch, the test below proves nothing.
    assert set(_SWITCHES) <= SWITCH_SETTING_KEYS
    assert not set(_OTHERS) & SWITCH_SETTING_KEYS


def test_the_migration_is_not_fatal() -> None:
    # The app reads every one of these fine without it.
    assert _load().FATAL is False


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_switches_are_tidied_and_the_rest_cleared(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _seed(engine)

    _upgrade(engine)

    assert _settings(engine) == _expected_settings()
    assert _count(engine, "csrf_tokens") == 0
    assert _count(engine, "oidc_pending_links") == 0


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _seed(engine)
    _upgrade(engine)
    first = _settings(engine)

    _upgrade(engine)

    assert _settings(engine) == first == _expected_settings()
    assert _count(engine, "csrf_tokens") == 0
    assert _count(engine, "oidc_pending_links") == 0


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
@pytest.mark.parametrize("missing", ["csrf_tokens", "oidc_pending_links"])
def test_a_missing_token_table_is_skipped(engine_for_migration, missing: str) -> None:
    _dialect, engine, _url = engine_for_migration
    _seed(engine, csrf=missing != "csrf_tokens", pending=missing != "oidc_pending_links")

    _upgrade(engine)

    assert _settings(engine) == _expected_settings()
    other = "oidc_pending_links" if missing == "csrf_tokens" else "csrf_tokens"
    assert _count(engine, other) == 0


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_work_rolls_back_with_the_runners_transaction(engine_for_migration) -> None:
    # The runner stamps on the same connection after upgrade(); if that fails,
    # nothing 160 did may stick.
    _dialect, engine, _url = engine_for_migration
    _seed(engine)

    with pytest.raises(RuntimeError, match="stamp failed"):
        with engine.begin() as conn:
            _load().upgrade(conn=conn)
            raise RuntimeError("stamp failed")

    assert _settings(engine)["nhtsa_enabled"] == " Yes "
    assert _settings(engine)["google_maps_api_key"] == "some-old-key"
    assert _count(engine, "csrf_tokens") == 1
    assert _count(engine, "oidc_pending_links") == 1


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_an_empty_database_is_fine(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration

    _upgrade(engine)

    with engine.connect() as conn:
        assert not conn.dialect.has_table(conn, "settings")
