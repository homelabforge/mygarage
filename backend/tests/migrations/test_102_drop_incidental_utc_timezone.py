"""Tests for migration 102 — delete an incidental ``timezone=UTC`` row.

Parameterized over SQLite *and* PostgreSQL via ``engine_for_migration``.
The fallback chain is driven deterministically through ``MYGARAGE_TIMEZONE``.
"""

from sqlalchemy import text

from tests.migrations._loader import load_migration


def _make_settings(engine, timezone_value=None):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE settings (key VARCHAR(50) PRIMARY KEY, value TEXT)"))
        if timezone_value is not None:
            conn.execute(
                text("INSERT INTO settings (key, value) VALUES ('timezone', :v)"),
                {"v": timezone_value},
            )


def _row(engine):
    with engine.begin() as conn:
        return conn.execute(text("SELECT value FROM settings WHERE key = 'timezone'")).scalar()


def test_102_deletes_utc_when_fallback_is_non_utc(engine_for_migration, monkeypatch):
    _dialect, engine, _url = engine_for_migration
    _make_settings(engine, "UTC")
    monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Chicago")

    load_migration("102_drop_incidental_utc_timezone").upgrade(engine)

    assert _row(engine) is None


def test_102_keeps_utc_when_fallback_is_utc_too(engine_for_migration, monkeypatch):
    _dialect, engine, _url = engine_for_migration
    _make_settings(engine, "UTC")
    monkeypatch.setenv("MYGARAGE_TIMEZONE", "UTC")

    load_migration("102_drop_incidental_utc_timezone").upgrade(engine)

    assert _row(engine) == "UTC"


def test_102_keeps_a_non_utc_row(engine_for_migration, monkeypatch):
    _dialect, engine, _url = engine_for_migration
    _make_settings(engine, "Europe/Warsaw")
    monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Chicago")

    load_migration("102_drop_incidental_utc_timezone").upgrade(engine)

    assert _row(engine) == "Europe/Warsaw"


def test_102_is_a_noop_without_the_row_and_on_rerun(engine_for_migration, monkeypatch):
    _dialect, engine, _url = engine_for_migration
    _make_settings(engine, "UTC")
    monkeypatch.setenv("MYGARAGE_TIMEZONE", "America/Chicago")

    mig = load_migration("102_drop_incidental_utc_timezone")
    mig.upgrade(engine)
    assert _row(engine) is None
    mig.upgrade(engine)  # re-run: no error, still gone
    assert _row(engine) is None


def test_102_survives_a_missing_settings_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    load_migration("102_drop_incidental_utc_timezone").upgrade(engine)  # no table: returns
