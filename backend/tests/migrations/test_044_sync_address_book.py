"""Idempotency and correctness tests for migration 044_sync_address_book_to_vendors."""

import importlib.util
import sqlite3
import types
from pathlib import Path

import pytest


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


def _setup_db(db_file: Path) -> None:
    """Create the vendors and address_book tables needed by migration 044."""
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            address TEXT,
            city VARCHAR(100),
            state VARCHAR(50),
            zip_code VARCHAR(20),
            phone VARCHAR(20),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS address_book (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            business_name VARCHAR(150) NOT NULL,
            name VARCHAR(100),
            address TEXT,
            city VARCHAR(100),
            state VARCHAR(50),
            zip_code VARCHAR(20),
            phone VARCHAR(20),
            email VARCHAR(100),
            website VARCHAR(200),
            category VARCHAR(50),
            notes TEXT,
            source VARCHAR(20) DEFAULT 'manual',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.close()


@pytest.mark.migrations
def test_044_syncs_address_book_entries_to_vendors(migration_db):
    """Migration 044 should create vendor rows for each distinct address book business name."""
    db_file, _ = migration_db
    _setup_db(db_file)

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO address_book (business_name, city, phone) VALUES (?, ?, ?)",
        ("B&T RV Repair", "Camptown", "555-100-2000"),
    )
    conn.execute(
        "INSERT INTO address_book (business_name, city) VALUES (?, ?)",
        ("Smith Auto Parts", "Springfield"),
    )
    conn.commit()
    conn.close()

    migration = _load_migration("044_sync_address_book_to_vendors")
    migration.upgrade()

    conn = sqlite3.connect(str(db_file))
    vendors = conn.execute("SELECT name FROM vendors ORDER BY name").fetchall()
    conn.close()

    names = [row[0] for row in vendors]
    assert "B&T RV Repair" in names
    assert "Smith Auto Parts" in names
    assert len(names) == 2


@pytest.mark.migrations
def test_044_idempotent(migration_db):
    """Running migration 044 twice must not raise and must not create duplicate vendors."""
    db_file, _ = migration_db
    _setup_db(db_file)

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO address_book (business_name, city) VALUES (?, ?)",
        ("Idempotent Shop", "Anytown"),
    )
    conn.commit()
    conn.close()

    migration = _load_migration("044_sync_address_book_to_vendors")

    # First run
    migration.upgrade()
    # Second run — must not raise, must not duplicate
    migration.upgrade()

    conn = sqlite3.connect(str(db_file))
    count = conn.execute(
        "SELECT COUNT(*) FROM vendors WHERE name = 'Idempotent Shop'"
    ).fetchone()[0]
    conn.close()

    assert count == 1, f"Expected 1 vendor row, found {count}"


@pytest.mark.migrations
def test_044_skips_blank_business_names(migration_db):
    """Address book entries with NULL or empty business_name must not create vendor rows."""
    db_file, _ = migration_db
    _setup_db(db_file)

    conn = sqlite3.connect(str(db_file))
    conn.executemany(
        "INSERT INTO address_book (business_name, name) VALUES (?, ?)",
        [
            ("Valid Shop", "Jane Doe"),
            ("   ", "John Smith"),   # whitespace-only — should be skipped
        ],
    )
    conn.commit()
    conn.close()

    migration = _load_migration("044_sync_address_book_to_vendors")
    migration.upgrade()

    conn = sqlite3.connect(str(db_file))
    vendor_names = [r[0] for r in conn.execute("SELECT name FROM vendors").fetchall()]
    conn.close()

    assert "Valid Shop" in vendor_names
    assert len(vendor_names) == 1, f"Expected only 1 vendor, got: {vendor_names}"


@pytest.mark.migrations
def test_044_case_dedup(migration_db):
    """Two address book entries with same name differing only by case produce one vendor."""
    db_file, _ = migration_db
    _setup_db(db_file)

    conn = sqlite3.connect(str(db_file))
    conn.executemany(
        "INSERT INTO address_book (business_name) VALUES (?)",
        [("Acme Repair",), ("acme repair",), ("ACME REPAIR",)],
    )
    conn.commit()
    conn.close()

    migration = _load_migration("044_sync_address_book_to_vendors")
    migration.upgrade()

    conn = sqlite3.connect(str(db_file))
    count = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    conn.close()

    assert count == 1, f"Expected 1 vendor after case-dedup, got {count}"


@pytest.mark.migrations
def test_044_does_not_overwrite_existing_vendor(migration_db):
    """An existing vendor with the same name must not be overwritten by the migration."""
    db_file, _ = migration_db
    _setup_db(db_file)

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO vendors (name, city) VALUES (?, ?)",
        ("Existing Vendor", "Original City"),
    )
    conn.execute(
        "INSERT INTO address_book (business_name, city) VALUES (?, ?)",
        ("Existing Vendor", "New City from Address Book"),
    )
    conn.commit()
    conn.close()

    migration = _load_migration("044_sync_address_book_to_vendors")
    migration.upgrade()

    conn = sqlite3.connect(str(db_file))
    vendor = conn.execute(
        "SELECT city FROM vendors WHERE name = 'Existing Vendor'"
    ).fetchone()
    conn.close()

    assert vendor is not None
    assert vendor[0] == "Original City", "Existing vendor city must not be overwritten"
