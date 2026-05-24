"""Idempotency + correctness tests for migration 054_extended_fuel_tracking.

What we cover:
- All new columns get added on a representative schema
- Re-running the migration is a no-op (no errors, no double-adds)
- vehicles.fuel_type backfill normalizes free-text → enum vocabulary
- Combined NHTSA primary strings populate fuel_type_secondary
- Already-normalized values are left untouched
- Indexes get created
- Unrecognized values fall back to 'other' and write the side-log
"""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path

import pytest

from tests.migrations.fixtures.fuel_type_locales import all_pairs


def _load_migration(name: str) -> types.ModuleType:
    migrations_dir = Path(__file__).parent.parent.parent / "app" / "migrations"
    path = migrations_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load migration: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _setup_db(db_file: Path) -> None:
    """Build a representative pre-054 schema (vehicles, fuel_records, users,
    address_book) seeded with rows that exercise every backfill branch."""
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(100) NOT NULL,
            email VARCHAR(255) NOT NULL,
            hashed_password VARCHAR(255),
            full_name VARCHAR(255),
            is_active BOOLEAN DEFAULT 1,
            is_admin BOOLEAN DEFAULT 0,
            unit_preference VARCHAR(20) DEFAULT 'imperial',
            show_both_units BOOLEAN DEFAULT 0,
            language VARCHAR(10) DEFAULT 'en',
            currency_code VARCHAR(3) DEFAULT 'USD',
            mobile_quick_entry_enabled BOOLEAN DEFAULT 1,
            auth_method VARCHAR(20) DEFAULT 'local',
            family_dashboard_order INTEGER DEFAULT 0,
            show_on_family_dashboard BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vehicles (
            vin VARCHAR(17) PRIMARY KEY,
            nickname VARCHAR(100) NOT NULL,
            vehicle_type VARCHAR(20) NOT NULL,
            year INTEGER, make VARCHAR(50), model VARCHAR(50),
            fuel_type VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS fuel_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vin VARCHAR(17) NOT NULL,
            date DATE NOT NULL,
            odometer_km NUMERIC(10,2),
            liters NUMERIC(9,3),
            fuel_type VARCHAR(50)
        );

        CREATE TABLE IF NOT EXISTS address_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name VARCHAR(150) NOT NULL,
            poi_category VARCHAR(50),
            usage_count INTEGER DEFAULT 0,
            last_used DATETIME,
            source VARCHAR(20) DEFAULT 'manual',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO users (username, email) VALUES ('alice', 'alice@example.com');

        INSERT INTO vehicles (vin, nickname, vehicle_type, fuel_type) VALUES
            ('11111111111111111', 'Already Normalized', 'Car', 'gasoline'),
            ('22222222222222222', 'Old Free-Text Premium', 'Car', 'Premium'),
            ('33333333333333333', 'Diesel Truck', 'Truck', 'Diesel'),
            ('44444444444444444', 'PHEV', 'Car', 'Gasoline, Hybrid Electric'),
            ('55555555555555555', 'Flex Fuel', 'Car', 'Gasoline, E85 (Flex Fuel)'),
            ('66666666666666666', 'Mystery', 'Car', 'Quantum Fluctuator'),
            ('77777777777777777', 'Null Fuel', 'Car', NULL);

        INSERT INTO fuel_records (vin, date, fuel_type) VALUES
            ('11111111111111111', '2025-01-01', 'gasoline'),
            ('22222222222222222', '2025-01-02', '91'),
            ('22222222222222222', '2025-01-03', 'Regular'),
            ('66666666666666666', '2025-01-04', 'Pixie Dust');
    """)
    conn.commit()
    conn.close()


@pytest.mark.migrations
def test_054_adds_columns_and_backfills(migration_db, tmp_path, monkeypatch):
    db_file, db_url = migration_db
    _setup_db(db_file)

    log_path = tmp_path / "migration-054.log"
    monkeypatch.setenv("MIGRATION_054_LOG", str(log_path))

    module = _load_migration("054_extended_fuel_tracking")
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    module.upgrade(engine=engine)

    # Verify all new columns exist
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    def _columns(table: str) -> set[str]:
        rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}

    vehicle_cols = _columns("vehicles")
    assert "fuel_type_secondary" in vehicle_cols

    user_cols = _columns("users")
    assert "default_payment_method" in user_cols
    assert "default_trip_type" in user_cols

    fuel_cols = _columns("fuel_records")
    expected = {
        "filled_at",
        "station_address_book_id",
        "station_name_freetext",
        "driver_user_id",
        "driver_name_freetext",
        "payment_method",
        "trip_type",
        "outside_temp_c",
        "obc_l_per_100km",
        "obc_avg_speed_kmh",
        "obc_trip_duration_s",
        "fuel_type_used",
    }
    assert expected.issubset(fuel_cols)

    # Backfill correctness
    rows = dict(cur.execute("SELECT vin, fuel_type FROM vehicles").fetchall())
    assert rows["11111111111111111"] == "gasoline"  # untouched
    assert rows["22222222222222222"] == "gasoline"  # Premium → gasoline
    assert rows["33333333333333333"] == "diesel"
    assert rows["44444444444444444"] == "hybrid"  # combined → primary
    assert rows["55555555555555555"] == "gasoline"  # flex → gasoline
    assert rows["66666666666666666"] == "other"  # unknown → other
    assert rows["77777777777777777"] is None

    # Combined strings populate secondary
    secondaries = dict(cur.execute("SELECT vin, fuel_type_secondary FROM vehicles").fetchall())
    assert secondaries["44444444444444444"] == "electric"
    assert secondaries["55555555555555555"] == "e85"
    assert secondaries["11111111111111111"] is None

    # fuel_records backfill
    fr = dict(cur.execute("SELECT id, fuel_type FROM fuel_records").fetchall())
    assert fr[1] == "gasoline"
    assert fr[2] == "gasoline"
    assert fr[3] == "gasoline"
    assert fr[4] == "other"

    # Indexes
    indexes = {
        r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert "idx_fuel_records_station_id" in indexes
    assert "idx_fuel_records_driver_id" in indexes
    assert "idx_fuel_records_trip_type" in indexes
    assert "idx_fuel_records_filled_at" in indexes

    # Unrecognized side-log written
    assert log_path.exists()
    log_content = log_path.read_text()
    assert "Quantum Fluctuator" in log_content
    assert "Pixie Dust" in log_content

    conn.close()


@pytest.mark.migrations
def test_054_idempotent(migration_db, tmp_path, monkeypatch):
    """Running the migration twice must be a no-op the second time."""
    db_file, db_url = migration_db
    _setup_db(db_file)

    log_path = tmp_path / "migration-054.log"
    monkeypatch.setenv("MIGRATION_054_LOG", str(log_path))

    module = _load_migration("054_extended_fuel_tracking")
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    module.upgrade(engine=engine)

    # Snapshot the relevant rows after first run
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    snapshot_v = sorted(
        cur.execute("SELECT vin, fuel_type, fuel_type_secondary FROM vehicles").fetchall()
    )
    snapshot_f = sorted(cur.execute("SELECT id, fuel_type FROM fuel_records").fetchall())
    conn.close()

    # Second run — must not error or change anything
    module.upgrade(engine=engine)

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    rerun_v = sorted(
        cur.execute("SELECT vin, fuel_type, fuel_type_secondary FROM vehicles").fetchall()
    )
    rerun_f = sorted(cur.execute("SELECT id, fuel_type FROM fuel_records").fetchall())
    conn.close()

    assert snapshot_v == rerun_v
    assert snapshot_f == rerun_f


@pytest.mark.migrations
def test_054_already_normalized_values_skipped(migration_db, tmp_path, monkeypatch):
    """If a row's value is already on the enum, no UPDATE should run for it."""
    db_file, db_url = migration_db
    _setup_db(db_file)

    log_path = tmp_path / "migration-054.log"
    monkeypatch.setenv("MIGRATION_054_LOG", str(log_path))

    module = _load_migration("054_extended_fuel_tracking")
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    module.upgrade(engine=engine)

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    # The first row was 'gasoline' — must remain 'gasoline' verbatim.
    val = cur.execute("SELECT fuel_type FROM vehicles WHERE vin = '11111111111111111'").fetchone()[
        0
    ]
    assert val == "gasoline"
    conn.close()


# ---------------------------------------------------------------------------
# Locale-aware backfill matrix (Phase 0.7 / Phase 1.3)
# ---------------------------------------------------------------------------
# Migration 054's _NORMALIZATION_MAP ships English-only on rc1.
# andrzejf1994's PG install with vehicle.fuel_type='Benzyna' (Polish for
# gasoline) backfilled to 'other' instead of 'gasoline'. This matrix
# parametrizes one-row-per-(locale, free_text) test cases. Phase 1.3
# adds Polish/Ukrainian/Russian entries to the migration's map; failing
# cases listed below go green.


@pytest.mark.migrations
@pytest.mark.parametrize(
    "locale,free_text,expected",
    all_pairs(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_054_backfill_locale_matrix(
    migration_db, tmp_path, monkeypatch, locale, free_text, expected
):
    """Free-text fuel_type values typed in supported locales must
    backfill to the canonical enum value, not 'other'."""
    db_file, db_url = migration_db

    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(100) NOT NULL,
            email VARCHAR(255) NOT NULL,
            hashed_password VARCHAR(255),
            full_name VARCHAR(255),
            is_active BOOLEAN DEFAULT 1,
            is_admin BOOLEAN DEFAULT 0,
            unit_preference VARCHAR(20) DEFAULT 'imperial',
            show_both_units BOOLEAN DEFAULT 0,
            language VARCHAR(10) DEFAULT 'en',
            currency_code VARCHAR(3) DEFAULT 'USD',
            mobile_quick_entry_enabled BOOLEAN DEFAULT 1,
            auth_method VARCHAR(20) DEFAULT 'local',
            family_dashboard_order INTEGER DEFAULT 0,
            show_on_family_dashboard BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS vehicles (
            vin VARCHAR(17) PRIMARY KEY,
            nickname VARCHAR(100) NOT NULL,
            vehicle_type VARCHAR(20) NOT NULL,
            year INTEGER, make VARCHAR(50), model VARCHAR(50),
            fuel_type VARCHAR(50)
        );
        CREATE TABLE IF NOT EXISTS fuel_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vin VARCHAR(17) NOT NULL,
            date DATE NOT NULL,
            odometer_km NUMERIC(10,2),
            liters NUMERIC(9,3),
            fuel_type VARCHAR(50)
        );
        CREATE TABLE IF NOT EXISTS address_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name VARCHAR(150) NOT NULL,
            poi_category VARCHAR(50),
            usage_count INTEGER DEFAULT 0,
            last_used DATETIME,
            source VARCHAR(20) DEFAULT 'manual',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO users (username, email) VALUES ('alice', 'alice@example.com');
        """
    )
    test_vin = "L" + locale[:2].upper() + "TESTVEHICLE0000"[: 17 - 1 - len(locale[:2].upper())]
    # Pad/truncate to exactly 17 chars
    test_vin = (test_vin + "X" * 17)[:17]
    conn.execute(
        "INSERT INTO vehicles (vin, nickname, vehicle_type, fuel_type) VALUES (?, ?, ?, ?)",
        (test_vin, f"{locale} test", "Car", free_text),
    )
    conn.commit()
    conn.close()

    log_path = tmp_path / f"migration-054-{locale}.log"
    monkeypatch.setenv("MIGRATION_054_LOG", str(log_path))

    module = _load_migration("054_extended_fuel_tracking")
    from sqlalchemy import create_engine

    engine = create_engine(db_url)
    module.upgrade(engine=engine)

    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    actual = cur.execute("SELECT fuel_type FROM vehicles WHERE vin = ?", (test_vin,)).fetchone()[0]
    conn.close()

    assert actual == expected, (
        f"Locale {locale!r}: free_text {free_text!r} backfilled to {actual!r}, "
        f"expected {expected!r}. Add the appropriate alias to "
        f"_NORMALIZATION_MAP in app/migrations/054_extended_fuel_tracking.py."
    )
