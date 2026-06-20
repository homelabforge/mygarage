"""PG baseline regression tests for migration 057 (firmware-cache multi-track).

Loads the committed pre_055.sql baseline (post-054, pre-055 PG schema) into a
clean schema, then verifies migration 057:

1. Adds a nullable ``track VARCHAR(10)`` column to ``livelink_firmware_cache``.
2. DELETEs all rows (clears the stale singleton — the cache is a
   daily-refreshed throwaway, so this is safe).
3. Creates unique index ``ix_livelink_firmware_cache_track`` on ``track``.

The pre_055 baseline contains the ``livelink_firmware_cache`` table with an
``id INTEGER NOT NULL`` primary key and no rows. There is no serial/sequence on
the id column, so seeding rows requires explicit integer ids.

PG-only — baselines are inherently PG.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

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
    """Load pre_055.sql into a clean PG schema and yield the engine.

    The pre_055 baseline already contains ``livelink_firmware_cache``
    (added before migration 054), so migration 057 has a real table to
    operate on.
    """
    load_baseline(pg_engine, "pre_055")
    return pg_engine


def test_057_adds_track_column_on_pg(baseline_loaded):
    """Migration 057 must add the nullable ``track`` column on PG.

    The pre_055 baseline does not have ``track`` — assert it is absent before
    the migration and present after.
    """
    insp = inspect(baseline_loaded)
    pre_cols = {c["name"] for c in insp.get_columns("livelink_firmware_cache")}
    assert "track" not in pre_cols, (
        "baseline should be pre-057 — track must not yet exist on livelink_firmware_cache"
    )

    _load_migration("057_firmware_cache_multi_track").upgrade(engine=baseline_loaded)

    insp = inspect(baseline_loaded)
    post_cols = {c["name"] for c in insp.get_columns("livelink_firmware_cache")}
    assert "track" in post_cols, "migration 057 should have added livelink_firmware_cache.track"


def test_057_clears_rows_and_creates_unique_index_on_pg(baseline_loaded):
    """Migration 057 must DELETE all rows and create the unique index.

    The pre_055 baseline seeds no rows into ``livelink_firmware_cache`` (the
    table's id column is a plain integer with no sequence, so we insert with
    an explicit id). After the migration: row count must be 0 and the unique
    index must exist.
    """
    # Seed a stale singleton row using an explicit id (no serial sequence).
    with baseline_loaded.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO livelink_firmware_cache "
                "(id, latest_version, latest_tag, release_url, release_notes) "
                "VALUES (1, '4.50', 'v4.50p', NULL, NULL)"
            )
        )

    # Sanity-check the seed actually landed.
    with baseline_loaded.begin() as conn:
        pre_count = conn.execute(text("SELECT COUNT(*) FROM livelink_firmware_cache")).scalar()
    assert pre_count == 1, f"seed failed — expected 1 row, got {pre_count}"

    _load_migration("057_firmware_cache_multi_track").upgrade(engine=baseline_loaded)

    # Index must exist.
    insp = inspect(baseline_loaded)
    indexes = {i["name"] for i in insp.get_indexes("livelink_firmware_cache")}
    assert "ix_livelink_firmware_cache_track" in indexes, (
        f"migration 057 should have created ix_livelink_firmware_cache_track; "
        f"found indexes: {sorted(indexes)}"
    )

    # Stale rows must have been cleared.
    with baseline_loaded.begin() as conn:
        post_count = conn.execute(text("SELECT COUNT(*) FROM livelink_firmware_cache")).scalar()
    assert post_count == 0, (
        f"migration 057 should have cleared all firmware cache rows; "
        f"found {post_count} row(s) remaining"
    )


def test_057_idempotent_on_pg(baseline_loaded):
    """Running migration 057 twice must not raise on PG."""
    module = _load_migration("057_firmware_cache_multi_track")
    module.upgrade(engine=baseline_loaded)
    module.upgrade(engine=baseline_loaded)
