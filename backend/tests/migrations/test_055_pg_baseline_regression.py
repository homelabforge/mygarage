"""Regression tests for migration 055 (fuel→odometer cascade).

Loads the committed pre_055.sql baseline (post-054, pre-055 PG schema)
into a clean schema, then verifies migration 055:

1. Adds the ``odometer_records.fuel_record_id`` column.
2. Backfills it from the ``[AUTO-SYNC from fuel #N]`` notes marker on
   rows where ``source='fuel'``.
3. Cleans up orphan synced rows (whose source fuel record no longer
   exists — the andrzejf1994 case).
4. Installs the FK with ``ON DELETE CASCADE``.
5. After the migration, deleting a fuel record actually cascades the
   synced odometer row away (the original rc1 bug).

PG-only — baselines are inherently PG.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from tests.integration._cascade import assert_cascade_clean_sync
from tests.migrations._baseline import load_baseline


def _load_migration(name: str) -> types.ModuleType:
    migrations_dir = Path(__file__).parent.parent.parent / "app" / "migrations"
    path = migrations_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load migration: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture
def baseline_loaded(pg_engine):
    load_baseline(pg_engine, "pre_055")
    return pg_engine


def _seed_fuel_with_synced_odometer(engine, vin: str = "TESTVIN1234567890") -> int:
    """Insert a vehicle + fuel record + synced odometer row with the
    same ``[AUTO-SYNC from fuel #N]`` marker the production sync helper
    emits. Returns the fuel record's id.

    Booleans (is_full_tank/missed_fillup/is_hauling) need explicit values
    here because raw SQL bypasses the SQLAlchemy model's
    ``default=`` settings, and the schema declares them NOT NULL.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, vehicle_type) "
                "VALUES (:v, 'Cascade Test', 'Car')"
            ),
            {"v": vin},
        )
        fuel_id = conn.execute(
            text(
                "INSERT INTO fuel_records "
                "(vin, date, odometer_km, liters, is_full_tank, missed_fillup, is_hauling) "
                "VALUES (:v, '2026-01-01', 12345.0, 40.0, TRUE, FALSE, FALSE) "
                "RETURNING id"
            ),
            {"v": vin},
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO odometer_records (vin, date, odometer_km, source, notes) "
                "VALUES (:v, '2026-01-01', 12345.0, 'fuel', :note)"
            ),
            {"v": vin, "note": f"[AUTO-SYNC from fuel #{fuel_id}]"},
        )
    return fuel_id


def test_055_adds_fuel_record_id_column(baseline_loaded):
    insp = inspect(baseline_loaded)
    assert "fuel_record_id" not in {c["name"] for c in insp.get_columns("odometer_records")}, (
        "baseline should be pre-055 — fuel_record_id must not yet exist"
    )

    _load_migration("055_fuel_odometer_cascade").upgrade(engine=baseline_loaded)

    insp = inspect(baseline_loaded)
    cols = {c["name"] for c in insp.get_columns("odometer_records")}
    assert "fuel_record_id" in cols


def test_055_backfills_existing_synced_rows(baseline_loaded):
    fuel_id = _seed_fuel_with_synced_odometer(baseline_loaded)

    _load_migration("055_fuel_odometer_cascade").upgrade(engine=baseline_loaded)

    with baseline_loaded.begin() as conn:
        linked_fuel_id = conn.execute(
            text(
                "SELECT fuel_record_id FROM odometer_records WHERE source = 'fuel' AND notes = :n"
            ),
            {"n": f"[AUTO-SYNC from fuel #{fuel_id}]"},
        ).scalar()
    assert linked_fuel_id == fuel_id, (
        f"backfill should have set fuel_record_id={fuel_id}, got {linked_fuel_id}"
    )


def test_055_cleans_up_orphans(baseline_loaded, tmp_path, monkeypatch):
    """A synced odometer row whose source fuel record no longer exists
    is the andrzejf1994 case — exactly what the migration must clean up."""
    vin = "ORPHANSMOKE000001"
    with baseline_loaded.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, vehicle_type) "
                "VALUES (:v, 'Orphan Test', 'Car')"
            ),
            {"v": vin},
        )
        # Marker references fuel id 99999 which doesn't exist in the
        # baseline — that's the orphan condition.
        conn.execute(
            text(
                "INSERT INTO odometer_records (vin, date, odometer_km, source, notes) "
                "VALUES (:v, '2026-02-01', 22000.0, 'fuel', '[AUTO-SYNC from fuel #99999]')"
            ),
            {"v": vin},
        )

    log_path = tmp_path / "migration-055.log"
    monkeypatch.setenv("MIGRATION_055_LOG", str(log_path))

    _load_migration("055_fuel_odometer_cascade").upgrade(engine=baseline_loaded)

    with baseline_loaded.begin() as conn:
        survivors = conn.execute(
            text("SELECT COUNT(*) FROM odometer_records WHERE vin = :v"),
            {"v": vin},
        ).scalar()
    assert survivors == 0, "orphan synced odometer row should have been deleted"

    assert log_path.exists(), "orphan cleanup should have written a side-log"
    # The side-log captures the deleted odometer row ids; we don't pin the
    # specific number (it depends on insertion order), just that the log
    # records exactly one cleanup entry from this scenario.
    assert "deleted 1 orphan" in log_path.read_text()


def test_055_installs_cascade_fk_and_actually_cascades(baseline_loaded):
    """End-to-end proof: after the migration, deleting a fuel record
    does cascade-delete its synced odometer row at the database engine
    level (no service-layer cleanup needed)."""
    fuel_id = _seed_fuel_with_synced_odometer(baseline_loaded)

    _load_migration("055_fuel_odometer_cascade").upgrade(engine=baseline_loaded)

    # Use the Phase 0.6 sync cascade helper to assert the invariant.
    assert_cascade_clean_sync(
        engine=baseline_loaded,
        parent_table="fuel_records",
        child_table="odometer_records",
        child_fk_column="fuel_record_id",
        parent_value=fuel_id,
        delete_sql="DELETE FROM fuel_records WHERE id = :id",
        delete_params={"id": fuel_id},
        on_delete="cascade",
    )


def test_055_idempotent(baseline_loaded):
    """Re-running the migration must not error and must not re-link
    rows that have already been linked."""
    fuel_id = _seed_fuel_with_synced_odometer(baseline_loaded)

    module = _load_migration("055_fuel_odometer_cascade")
    module.upgrade(engine=baseline_loaded)
    module.upgrade(engine=baseline_loaded)

    with baseline_loaded.begin() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM odometer_records "
                "WHERE source = 'fuel' AND fuel_record_id = :fid"
            ),
            {"fid": fuel_id},
        ).scalar()
    assert count == 1
