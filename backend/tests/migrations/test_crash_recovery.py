"""Regression tests for stale temp-table crash recovery.

Each test simulates a mid-migration crash by:
  1. Creating the exact pre-migration DB state
  2. Injecting a stale *_new temp table (what gets left behind after a crash)
  3. Running the migration
  4. Asserting the migration succeeds and produces the correct post-migration state

These are regression tests for GitHub issue #35.
"""

import importlib.util
import sqlite3
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


def _load_migration(name: str) -> types.ModuleType:
    """Dynamically load a migration module by filename stem."""
    migrations_dir = Path(__file__).parent.parent.parent / "app" / "migrations"
    path = migrations_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load migration: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.mark.migrations
def test_006_retry_after_stale_service_records_new(migration_db):
    """Migration 006 cleans up stale service_records_new and updates constraint.

    Regression test for GitHub issue #35: app failed to start after a previous
    run of migration 006 left service_records_new behind.
    """
    db_file, _ = migration_db

    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE vehicles (
            vin VARCHAR(17) PRIMARY KEY
        );
        CREATE TABLE service_records (
            id INTEGER NOT NULL,
            vin VARCHAR(17) NOT NULL,
            date DATE NOT NULL,
            mileage INTEGER,
            description VARCHAR(200) NOT NULL,
            cost NUMERIC(10, 2),
            notes TEXT,
            vendor_name VARCHAR(100),
            vendor_location VARCHAR(100),
            service_type VARCHAR(30),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            insurance_claim VARCHAR(50),
            PRIMARY KEY (id),
            CONSTRAINT check_service_type CHECK (
                service_type IN ('Maintenance', 'Repair', 'Inspection')
            ),
            FOREIGN KEY(vin) REFERENCES vehicles(vin) ON DELETE CASCADE
        );
        INSERT INTO vehicles VALUES ('VIN1');
        INSERT INTO service_records
            (id, vin, date, mileage, description, service_type, created_at)
        VALUES
            (1, 'VIN1', '2024-01-01', 10000, 'Oil change', 'Maintenance', CURRENT_TIMESTAMP),
            (2, 'VIN1', '2024-06-01', 20000, 'Brake check', 'Inspection', CURRENT_TIMESTAMP);
        CREATE TABLE service_records_new (id INTEGER PRIMARY KEY);
    """)
    conn.commit()
    conn.close()

    module = _load_migration("006_update_service_type_constraint")
    getattr(module, "upgrade")()  # must not raise

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'")
    table_sql = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM service_records")
    row_count = cursor.fetchone()[0]
    conn.close()

    assert "'Collision'" in table_sql, "Updated CHECK constraint missing 'Collision'"
    assert row_count == 2, f"Expected 2 rows, got {row_count}"


@pytest.mark.migrations
def test_022_retry_after_stale_service_records_new(migration_db):
    """Migration 022 cleans up stale service_records_new and redesigns schema."""
    db_file, _ = migration_db

    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE vehicles (
            vin VARCHAR(17) PRIMARY KEY
        );
        CREATE TABLE service_records (
            id INTEGER NOT NULL,
            vin VARCHAR(17) NOT NULL,
            date DATE NOT NULL,
            mileage INTEGER,
            service_type VARCHAR(30),
            cost NUMERIC(10, 2),
            notes TEXT,
            vendor_name VARCHAR(100),
            vendor_location VARCHAR(100),
            insurance_claim VARCHAR(50),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(vin) REFERENCES vehicles(vin) ON DELETE CASCADE
        );
        INSERT INTO vehicles VALUES ('VIN1');
        INSERT INTO service_records
            (id, vin, date, mileage, service_type, created_at)
        VALUES
            (1, 'VIN1', '2024-01-01', 10000, 'Maintenance', CURRENT_TIMESTAMP),
            (2, 'VIN1', '2024-06-01', 20000, 'Inspection', CURRENT_TIMESTAMP);
        CREATE TABLE service_records_new (id INTEGER PRIMARY KEY);
    """)
    conn.commit()
    conn.close()

    module = _load_migration("022_redesign_service_type_schema")
    getattr(module, "upgrade")()  # must not raise

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'")
    table_sql = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM service_records")
    row_count = cursor.fetchone()[0]
    conn.close()

    assert "service_category" in table_sql, "Post-migration schema missing service_category column"
    assert row_count == 2, f"Expected 2 rows, got {row_count}"


@pytest.mark.migrations
def test_026_retry_after_stale_service_records_new(migration_db):
    """Migration 026 cleans up stale service_records_new and adds Detailing category."""
    db_file, _ = migration_db

    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE vehicles (
            vin VARCHAR(17) PRIMARY KEY
        );
        CREATE TABLE service_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vin TEXT NOT NULL,
            date TEXT NOT NULL,
            mileage INTEGER,
            service_type TEXT NOT NULL,
            cost REAL,
            notes TEXT,
            vendor_name TEXT,
            vendor_location TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            service_category TEXT,
            insurance_claim TEXT,
            FOREIGN KEY(vin) REFERENCES vehicles(vin) ON DELETE CASCADE
        );
        INSERT INTO vehicles VALUES ('VIN1');
        INSERT INTO service_records
            (vin, date, mileage, service_type, service_category)
        VALUES
            ('VIN1', '2024-01-01', 10000, 'General Service', 'Maintenance'),
            ('VIN1', '2024-06-01', 20000, 'General Service', 'Inspection');
        CREATE TABLE service_records_new (id INTEGER PRIMARY KEY);
    """)
    conn.commit()
    conn.close()

    module = _load_migration("026_add_detailing_category")
    getattr(module, "upgrade")()  # must not raise

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'")
    table_sql = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM service_records")
    row_count = cursor.fetchone()[0]
    conn.close()

    assert "'Detailing'" in table_sql, "Updated CHECK constraint missing 'Detailing'"
    assert row_count == 2, f"Expected 2 rows, got {row_count}"


@pytest.mark.migrations
def test_002_retry_after_stale_address_book_new(migration_db):
    """Migration 002 cleans up stale address_book_new and updates schema."""
    db_file, sync_url = migration_db

    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE address_book (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                business_name VARCHAR(150),
                address TEXT,
                city VARCHAR(100),
                state VARCHAR(50),
                zip_code VARCHAR(20),
                phone VARCHAR(20),
                email VARCHAR(100),
                website VARCHAR(200),
                category VARCHAR(50),
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        conn.execute(
            text("""
            INSERT INTO address_book (name, business_name) VALUES
                ('Alice Smith', 'Acme Auto'),
                ('Bob Jones', NULL)
        """)
        )
        # Stale temp table from a previous failed run
        conn.execute(text("CREATE TABLE address_book_new (id INTEGER PRIMARY KEY)"))
    engine.dispose()

    module = _load_migration("002_update_address_book_schema")
    getattr(module, "upgrade")()  # must not raise

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='address_book'")
    table_sql = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM address_book")
    row_count = cursor.fetchone()[0]
    conn.close()

    assert "business_name VARCHAR(150) NOT NULL" in table_sql, (
        "business_name should be NOT NULL after migration"
    )
    assert row_count == 2, f"Expected 2 rows, got {row_count}"


@pytest.mark.migrations
def test_030_retry_after_stale_attachments_new(migration_db):
    """Migration 030 cleans up stale attachments_new and updates constraint."""
    db_file, sync_url = migration_db

    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(
            text("""
            CREATE TABLE service_records (
                id INTEGER PRIMARY KEY,
                vin VARCHAR(17) NOT NULL,
                date TEXT NOT NULL
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE service_visits (
                id INTEGER PRIMARY KEY,
                vin VARCHAR(17) NOT NULL,
                date TEXT NOT NULL
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type VARCHAR(30) NOT NULL,
                record_id INTEGER NOT NULL,
                file_path VARCHAR(255) NOT NULL,
                file_type VARCHAR(10),
                file_size INTEGER,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        conn.execute(text("INSERT INTO vehicles VALUES ('VIN1')"))
        conn.execute(text("INSERT INTO service_records VALUES (1, 'VIN1', '2024-01-15')"))
        conn.execute(text("INSERT INTO service_records VALUES (2, 'VIN1', '2024-02-20')"))
        # service_visits rows must match service_records by vin+date for JOIN mapping
        conn.execute(text("INSERT INTO service_visits VALUES (10, 'VIN1', '2024-01-15')"))
        conn.execute(text("INSERT INTO service_visits VALUES (11, 'VIN1', '2024-02-20')"))
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('service', 1, '/f1.pdf')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO attachments (record_type, record_id, file_path) "
                "VALUES ('service', 2, '/f2.pdf')"
            )
        )
        # Stale temp table from a previous failed run
        conn.execute(text("CREATE TABLE attachments_new (id INTEGER PRIMARY KEY)"))
    engine.dispose()

    module = _load_migration("030_migrate_service_attachments")
    getattr(module, "upgrade")()  # must not raise

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attachments'")
    table_sql = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM attachments")
    row_count = cursor.fetchone()[0]
    cursor.execute("SELECT DISTINCT record_type FROM attachments")
    record_types = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "'service_visit'" in table_sql, "Updated CHECK constraint missing 'service_visit'"
    assert row_count == 2, f"Expected 2 rows, got {row_count}"
    assert record_types == {"service_visit"}, (
        f"Expected all rows to be service_visit, got {record_types}"
    )
