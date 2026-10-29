"""Migration 138: a fill-up's driver naming a deleted user goes back to NULL (B3-1).

Builds the tables by hand with no FK, the way 054 left SQLite. The model has
the FK, so a create_all baseline couldn't even hold a dead id to clear.
"""

import importlib.util
import logging
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

import app.migrations as _m

pytestmark = pytest.mark.migrations

_NAME = "138_clear_dangling_fuel_drivers"


def _load(name: str = _NAME):
    """Load a migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pk(engine: Engine) -> str:
    return (
        "SERIAL PRIMARY KEY"
        if engine.dialect.name == "postgresql"
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )


def _make_pre_138_tables(engine: Engine) -> None:
    """users and fuel_records, with driver_user_id a bare INTEGER as 054 added it on SQLite."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fuel_records"))
        conn.execute(text("DROP TABLE IF EXISTS users"))
        conn.execute(text(f"CREATE TABLE users (id {_pk(engine)}, username VARCHAR(50) NOT NULL)"))
        conn.execute(
            text(
                f"""
                CREATE TABLE fuel_records (
                    id {_pk(engine)},
                    vin VARCHAR(17) NOT NULL,
                    driver_user_id INTEGER,
                    driver_name_freetext VARCHAR(100)
                )
                """
            )
        )
        conn.execute(text("INSERT INTO users (username) VALUES ('still_here')"))


def _add_fill_up(engine: Engine, driver: int | None, name: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fuel_records (vin, driver_user_id, driver_name_freetext)"
                " VALUES ('B3BMIG13800000001', :d, :n)"
            ),
            {"d": driver, "n": name},
        )


def _drivers(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, driver_user_id, driver_name_freetext FROM fuel_records ORDER BY id")
        ).all()
    return [tuple(r) for r in rows]


def _user_id(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT id FROM users")).scalar_one()


def test_the_migration_is_not_fatal():
    # A guard that passes once the file exists. It kills a 138 marked FATAL,
    # which would keep the app down over a cleanup it can live without.
    assert not getattr(_load(), "FATAL", False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_driver_naming_a_deleted_user_is_cleared(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_pre_138_tables(engine)
    kept = _user_id(engine)
    _add_fill_up(engine, kept)  # 1: a real user, kept
    _add_fill_up(engine, kept + 1000, "Sam")  # 2: gone, cleared, the name stays
    _add_fill_up(engine, None, "Guest")  # 3: no account driver, untouched
    _add_fill_up(engine, kept + 2000)  # 4: gone, cleared

    _load().upgrade(engine)

    # main: FileNotFoundError, no migration 138
    assert _drivers(engine) == [
        (1, kept, None),
        (2, None, "Sam"),
        (3, None, "Guest"),
        (4, None, None),
    ]


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_pre_138_tables(engine)
    kept = _user_id(engine)
    _add_fill_up(engine, kept)
    _add_fill_up(engine, kept + 1000)
    mod = _load()
    mod.upgrade(engine)
    before = _drivers(engine)
    mod.upgrade(engine)
    assert _drivers(engine) == before


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_missing_tables_or_column_are_skipped(engine_for_migration, caplog):
    """Skipped on purpose, not caught by the error log: without the checks the UPDATE fails."""
    _dialect, engine, _url = engine_for_migration
    caplog.set_level(logging.INFO)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fuel_records"))
        conn.execute(text("DROP TABLE IF EXISTS users"))
    _load().upgrade(engine)
    assert "138: fuel_records or users missing" in caplog.text

    _make_pre_138_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE fuel_records"))
        conn.execute(text("CREATE TABLE fuel_records (id INTEGER PRIMARY KEY, vin VARCHAR(17))"))
    _load().upgrade(engine)
    assert "138: fuel_records.driver_user_id missing" in caplog.text
    assert "not cleared" not in caplog.text


def test_a_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-FATAL failure that raises stops every migration after it, so 138 logs it instead."""
    mod = _load()

    def boom(_engine: Engine) -> None:
        raise OperationalError("UPDATE fuel_records", {}, Exception("database is locked"))

    monkeypatch.setattr(mod, "_clear_dangling_drivers", boom)
    mod.upgrade(create_engine("sqlite://"))
    assert "138: dead fill-up drivers not cleared" in caplog.text
