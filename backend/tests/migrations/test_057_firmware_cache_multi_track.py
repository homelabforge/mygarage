"""Migration 057: track column + unique index, idempotent, both dialects."""

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import app.migrations as _m
from app.migrations import runner  # noqa: F401  (ensures package import path)


def _load_057():
    path = Path(_m.__file__).parent / "057_firmware_cache_multi_track.py"
    spec = importlib.util.spec_from_file_location("m057", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_legacy_cache(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE livelink_firmware_cache ("
                "id INTEGER PRIMARY KEY, latest_version VARCHAR(20), "
                "latest_tag VARCHAR(20), release_url TEXT, release_notes TEXT, "
                "checked_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO livelink_firmware_cache (id, latest_version, latest_tag) "
                "VALUES (1, '4.50', 'v4.50p')"
            )
        )


def test_057_adds_track_clears_rows_and_unique_index():
    engine = create_engine("sqlite://")
    _make_legacy_cache(engine)
    mod = _load_057()

    mod.upgrade(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("livelink_firmware_cache")}
    assert "track" in cols
    idx = {i["name"] for i in inspector.get_indexes("livelink_firmware_cache")}
    assert "ix_livelink_firmware_cache_track" in idx
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM livelink_firmware_cache")).scalar()
    assert count == 0  # stale singleton cleared


def test_057_is_idempotent():
    engine = create_engine("sqlite://")
    _make_legacy_cache(engine)
    mod = _load_057()
    mod.upgrade(engine)
    mod.upgrade(engine)  # second run must not raise
