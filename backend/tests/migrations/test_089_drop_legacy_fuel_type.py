"""Tests for migration 089 — retire the legacy fuel_records.fuel_type column.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset). Both dialects
matter here: the migration issues a DROP COLUMN, which SQLite only accepts
under conditions this table happens to meet.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_table(engine, *, with_legacy: bool = True):
    """Pre-089 fuel_records: both fuel-type columns, plus the price CHECK.

    The CHECK is reproduced deliberately. SQLite refuses DROP COLUMN when a
    constraint names the column being dropped, and the real table carries a
    CHECK on `price_basis` — so this fixture proves the drop survives a table
    that HAS one, as long as it does not name `fuel_type`.
    """
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    legacy = "fuel_type VARCHAR(50)," if with_legacy else ""
    with engine.begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE fuel_records (
                id {pk},
                vin VARCHAR(17) NOT NULL,
                liters NUMERIC(9,3),
                price_basis VARCHAR(12)
                    CHECK (price_basis IS NULL OR price_basis IN
                      ('per_volume', 'per_weight', 'per_tank', 'per_kwh')),
                {legacy}
                fuel_type_used VARCHAR(20)
            )
            """)
        )


def _columns(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("fuel_records")}


def _used_by_vin(engine) -> dict[str, str | None]:
    with engine.begin() as conn:
        return {
            r[0]: r[1]
            for r in conn.execute(text("SELECT vin, fuel_type_used FROM fuel_records ORDER BY id"))
        }


def test_089_backfills_from_legacy_then_drops_the_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO fuel_records (vin, fuel_type, fuel_type_used)
            VALUES
                -- 1: canonical legacy value, nothing on the new column yet.
                ('VIN00000000000001', 'gasoline', NULL),
                -- 2: the propane form's free text — the case that made
                --    fuel_type_used NULL on every propane record.
                ('VIN00000000000002', 'Propane', NULL),
                -- 3: both already set — the canonical value must win untouched.
                ('VIN00000000000003', 'gasoline', 'diesel'),
                -- 4: nothing to backfill from.
                ('VIN00000000000004', NULL, NULL),
                -- 5: off-vocabulary free text lands on 'other', not dropped.
                ('VIN00000000000005', 'Plasma fuel', NULL)
            """)
        )

    _load("089_drop_legacy_fuel_type").upgrade(engine)

    assert "fuel_type" not in _columns(engine)
    assert "fuel_type_used" in _columns(engine)
    assert _used_by_vin(engine) == {
        "VIN00000000000001": "gasoline",
        "VIN00000000000002": "propane_lpg",
        "VIN00000000000003": "diesel",
        "VIN00000000000004": None,
        "VIN00000000000005": "other",
    }


def test_089_is_idempotent(engine_for_migration):
    """Re-running on an already-migrated table is a no-op, not an error."""
    _dialect, engine, _url = engine_for_migration
    _make_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fuel_records (vin, fuel_type, fuel_type_used) "
                "VALUES ('VIN00000000000001', 'diesel', NULL)"
            )
        )

    migration = _load("089_drop_legacy_fuel_type")
    migration.upgrade(engine)
    migration.upgrade(engine)

    assert "fuel_type" not in _columns(engine)
    assert _used_by_vin(engine) == {"VIN00000000000001": "diesel"}


def test_089_refuses_when_fuel_type_used_is_missing(engine_for_migration):
    """Running out of order must fail loudly, not drop the only fuel type."""
    _dialect, engine, _url = engine_for_migration
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(
            text(f"CREATE TABLE fuel_records (id {pk}, vin VARCHAR(17), fuel_type VARCHAR(50))")
        )

    with pytest.raises(RuntimeError, match="migration 054"):
        _load("089_drop_legacy_fuel_type").upgrade(engine)

    assert "fuel_type" in _columns(engine)


def test_089_skips_a_table_that_never_had_the_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_table(engine, with_legacy=False)

    _load("089_drop_legacy_fuel_type").upgrade(engine)

    assert _columns(engine) == {"id", "vin", "liters", "price_basis", "fuel_type_used"}
