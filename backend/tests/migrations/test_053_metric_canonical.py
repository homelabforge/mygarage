"""Tests for migration 053 (metric-canonical units).

Focuses on the SQLite preflight scan that detects unanticipated
sqlite_master references to dropped imperial columns. Frozen audit
backup tables (matching `_backup` in their name) must be skipped so
the migration doesn't fail on databases left over from older
migrations.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "migrations" / "053_metric_canonical_units.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("mig053", MIGRATION_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db_with_backup_tables() -> str:
    """Build a fresh SQLite file with the 3 legacy backup tables observed in
    production (collision_records_backup, upgrade_records_backup,
    service_records_backup_<date>) plus an unrelated user trigger that does
    NOT touch dropped columns. Returns the file path."""
    fd = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = fd.name
    fd.close()
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE collision_records_backup (
            id INT, vin TEXT, mileage INT, cost NUM
        );
        CREATE TABLE upgrade_records_backup (
            id INT, vin TEXT, mileage INT, cost NUM
        );
        CREATE TABLE service_records_backup_20251229 (
            id INT, vin TEXT, mileage INT, cost NUM
        );
        -- An unrelated table that mentions `mileage` only in a column NAMED
        -- something else; the regex word boundary should NOT flag it.
        CREATE TABLE unrelated_table (
            id INT,
            high_mileage_flag INT
        );
        """
    )
    conn.commit()
    conn.close()
    return path


def test_preflight_skips_legacy_backup_tables():
    """The preflight scan must skip *_backup tables so the migration doesn't
    refuse to run against DBs that retain frozen audit data from older
    migrations."""
    mod = _load_module()
    path = _make_db_with_backup_tables()
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        suspicious = mod._scan_raw_sqlite_master_for_imperial_refs(cur)
        conn.close()

        for entry in suspicious:
            assert "_backup" not in entry, (
                f"Backup table should be skipped, but was flagged: {entry!r}"
            )
    finally:
        Path(path).unlink(missing_ok=True)


def test_preflight_still_flags_unanticipated_real_refs():
    """Sanity: the preflight DOES still flag a non-backup table that
    references a dropped column. We don't want the backup-skip rule to be
    so broad that it hides real drift."""
    mod = _load_module()
    fd = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = fd.name
    fd.close()
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        # A table that ISN'T in _ANTICIPATED_TABLES and ISN'T a backup,
        # which references one of the dropped columns. Should be flagged.
        cur.executescript("CREATE TABLE custom_user_view (id INT, mileage INT);")
        conn.commit()
        suspicious = mod._scan_raw_sqlite_master_for_imperial_refs(cur)
        conn.close()

        flagged = [s for s in suspicious if "custom_user_view" in s]
        assert flagged, "Real unanticipated mileage reference should be flagged"
    finally:
        Path(path).unlink(missing_ok=True)


def test_is_legacy_backup_table_helper():
    """Direct unit test for the name pattern matcher."""
    mod = _load_module()
    assert mod._is_legacy_backup_table("collision_records_backup")
    assert mod._is_legacy_backup_table("upgrade_records_backup")
    assert mod._is_legacy_backup_table("service_records_backup_20251229")
    # Hypothetical other backup-style names that prior migrations might create:
    assert mod._is_legacy_backup_table("fuel_records_backup_20240101")
    # Active tables must NOT match
    assert not mod._is_legacy_backup_table("fuel_records")
    assert not mod._is_legacy_backup_table("vehicles")
    assert not mod._is_legacy_backup_table("backup_log")  # safety: no `_backup`
