"""Migration 143: the country columns behind the EU/national profiles (#211).

users.country VARCHAR(2) and users.inspection_auto_schedule BOOLEAN NOT NULL
DEFAULT TRUE; vehicles.registration_country VARCHAR(2) and
vehicles.first_registration_date DATE. FATAL, because the ORM declares every
column. Parameterised over SQLite and PostgreSQL via `engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

_NAME = "143_add_country_fields"


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL, "
                "language VARCHAR(10) NOT NULL DEFAULT 'en')"
            )
        )
        conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'seb')"))
        conn.execute(
            text(
                "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100) NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO vehicles (vin, nickname) VALUES ('1HGCM82633A004352', 'Civic')")
        )


def test_143_adds_the_four_columns(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _load().upgrade(engine)

    users = {c["name"]: c for c in inspect(engine).get_columns("users")}
    vehicles = {c["name"]: c for c in inspect(engine).get_columns("vehicles")}
    assert users["country"]["nullable"] is True
    assert users["inspection_auto_schedule"]["nullable"] is False
    assert vehicles["registration_country"]["nullable"] is True
    assert vehicles["first_registration_date"]["nullable"] is True

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT country, inspection_auto_schedule FROM users WHERE id = 1")
        ).one()
        assert row[0] is None
        # Existing users keep today's behaviour: automatic scheduling on.
        assert bool(row[1]) is True
        vrow = conn.execute(
            text(
                "SELECT registration_country, first_registration_date FROM vehicles "
                "WHERE vin = '1HGCM82633A004352'"
            )
        ).one()
        assert vrow == (None, None)


def test_143_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    assert [c["name"] for c in inspect(engine).get_columns("users")].count("country") == 1
    assert [c["name"] for c in inspect(engine).get_columns("vehicles")].count(
        "registration_country"
    ) == 1


def test_143_missing_tables_skip(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("users")
    assert not inspect(engine).has_table("vehicles")


def test_143_only_users_table_present(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
    _load().upgrade(engine)
    assert "country" in {c["name"] for c in inspect(engine).get_columns("users")}
    assert not inspect(engine).has_table("vehicles")


def test_143_is_fatal():
    assert _load().FATAL is True


def test_143_sqlite_declares_types(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m143.db"
    engine = sync_engine(f"sqlite:///{db_file}")
    _make_tables(engine)
    _load().upgrade(engine)

    conn = sqlite3.connect(str(db_file))
    users = {r[1]: r for r in conn.execute("PRAGMA table_info(users)")}
    vehicles = {r[1]: r for r in conn.execute("PRAGMA table_info(vehicles)")}
    conn.close()
    assert users["country"][2].upper() == "VARCHAR(2)"
    assert users["inspection_auto_schedule"][2].upper() == "BOOLEAN"
    assert users["inspection_auto_schedule"][3] == 1  # NOT NULL
    assert users["inspection_auto_schedule"][4] == "1"  # DEFAULT 1
    assert vehicles["registration_country"][2].upper() == "VARCHAR(2)"
    assert vehicles["first_registration_date"][2].upper() == "DATE"
