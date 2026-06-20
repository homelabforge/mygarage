"""Tests for migration 059 — param_key casing-merge to UPPERCASE canonical.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture. The PG runs (under ``docker-compose.test.yml``) are the dialect gate
that actually exercises the self-join DELETE and the daily-summary
re-aggregation against PostgreSQL — they are skipped (not failed) when
``TEST_DATABASE_URL`` is unset, i.e. in the SQLite-only flow.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- vehicle_telemetry (3-table drop+rekey) ---------------------------------


def _make_telemetry(engine):
    # INTEGER PRIMARY KEY autoincrements on both SQLite and PG (PG treats a bare
    # INTEGER PK as identity-like for our purposes; we always supply explicit ids
    # via the model elsewhere, but here ids are assigned by the INSERTs' order).
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE vehicle_telemetry (id {pk}, vin VARCHAR, "
                "device_id VARCHAR, param_key VARCHAR, value REAL, "
                "timestamp TIMESTAMP, received_at TIMESTAMP)"
            )
        )
        rows = [
            # mixed-case + its uppercase twin at the SAME (device,ts) → collision, mixed dropped
            ("v", "d", "51-FuelType", 1.0, "2026-01-01 00:00:00"),
            ("v", "d", "51-FUELTYPE", 1.0, "2026-01-01 00:00:00"),
            # mixed-case only → re-keyed up, no collision
            ("v", "d", "0C-EngineRPM", 900.0, "2026-01-01 00:00:01"),
            # uppercase only (legacy) → already canonical, untouched
            ("v", "d", "ODOMETER", 1234.0, "2026-01-01 00:00:02"),
            # non-casing pair → different canonicals, both kept
            ("v", "d", "A6-Odometer", 1234.0, "2026-01-01 00:00:03"),
        ]
        for vin, dev, k, val, ts in rows:
            conn.execute(
                text(
                    "INSERT INTO vehicle_telemetry (vin, device_id, param_key, value, timestamp, received_at) "
                    "VALUES (:v,:d,:k,:val,:ts,:ts)"
                ),
                {"v": vin, "d": dev, "k": k, "val": val, "ts": ts},
            )


def test_059_merges_casing_duplicates(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_telemetry(engine)
    _load("059_param_key_casing_merge").upgrade(engine)
    with engine.begin() as conn:
        keys = sorted(
            r[0] for r in conn.execute(text("SELECT DISTINCT param_key FROM vehicle_telemetry"))
        )
        n_fueltype = conn.execute(
            text("SELECT COUNT(*) FROM vehicle_telemetry WHERE param_key='51-FUELTYPE'")
        ).scalar()
    # 51-FuelType merged into 51-FUELTYPE (collision dropped the mixed dup → 1 row)
    assert "51-FuelType" not in keys and "51-FUELTYPE" in keys
    assert n_fueltype == 1
    # mixed-only re-keyed up; uppercase-only untouched; non-casing pair kept distinct
    assert "0C-ENGINERPM" in keys and "0C-EngineRPM" not in keys
    assert "ODOMETER" in keys
    assert "A6-ODOMETER" in keys  # A6-Odometer re-keyed up (still distinct from ODOMETER)


def test_059_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_telemetry(engine)
    mod = _load("059_param_key_casing_merge")
    mod.upgrade(engine)
    mod.upgrade(engine)  # no raise, no further change
    # Same end-state as a single run.
    with engine.begin() as conn:
        n_fueltype = conn.execute(
            text("SELECT COUNT(*) FROM vehicle_telemetry WHERE param_key='51-FUELTYPE'")
        ).scalar()
    assert n_fueltype == 1


# --- telemetry_daily_summary (re-aggregation merge) -------------------------


def _make_daily_summary(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE telemetry_daily_summary (id {pk}, vin VARCHAR, "
                "param_key VARCHAR, date TIMESTAMP, min_value REAL, max_value REAL, "
                "avg_value REAL, sample_count INTEGER NOT NULL DEFAULT 0)"
            )
        )
        rows = [
            # casing collision twins at the same (vin, date) → re-aggregate into one
            ("v", "51-FuelType", "2026-01-01", 10.0, 20.0, 15.0, 4),
            ("v", "51-FUELTYPE", "2026-01-01", 5.0, 25.0, 20.0, 6),
            # mixed-only → rekey, no collision
            ("v", "0C-EngineRPM", "2026-01-01", 800.0, 900.0, 850.0, 10),
            # canonical → untouched
            ("v", "ODOMETER", "2026-01-01", 1000.0, 1000.0, 1000.0, 1),
        ]
        for vin, k, d, mn, mx, av, cnt in rows:
            conn.execute(
                text(
                    "INSERT INTO telemetry_daily_summary "
                    "(vin, param_key, date, min_value, max_value, avg_value, sample_count) "
                    "VALUES (:v,:k,:d,:mn,:mx,:av,:cnt)"
                ),
                {"v": vin, "k": k, "d": d, "mn": mn, "mx": mx, "av": av, "cnt": cnt},
            )


def _fueltype_row(engine):
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT min_value, max_value, avg_value, sample_count "
                "FROM telemetry_daily_summary "
                "WHERE vin='v' AND param_key='51-FUELTYPE' AND date='2026-01-01'"
            )
        ).fetchall()


def test_059_daily_summary_reaggregates(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_daily_summary(engine)
    _load("059_param_key_casing_merge").upgrade(engine)

    # Exactly ONE merged row for the casing-collision pair, with re-aggregated stats.
    rows = _fueltype_row(engine)
    assert len(rows) == 1
    mn, mx, av, cnt = rows[0]
    assert mn == 5.0
    assert mx == 25.0
    assert cnt == 10
    # sample-count-weighted mean: (15*4 + 20*6) / (4+6) = 180/10 = 18.0
    assert av == 18.0

    with engine.begin() as conn:
        keys = sorted(
            r[0]
            for r in conn.execute(text("SELECT DISTINCT param_key FROM telemetry_daily_summary"))
        )
    # mixed-case twin gone, mixed-only rekeyed up, canonical untouched
    assert "51-FuelType" not in keys
    assert "0C-ENGINERPM" in keys and "0C-EngineRPM" not in keys
    assert "ODOMETER" in keys


def test_059_daily_summary_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_daily_summary(engine)
    mod = _load("059_param_key_casing_merge")
    mod.upgrade(engine)
    mod.upgrade(engine)  # second run must be a no-op (NOT re-merge)

    rows = _fueltype_row(engine)
    assert len(rows) == 1
    mn, mx, av, cnt = rows[0]
    # Unchanged from the first run — avg stays 18.0, count stays 10.
    assert mn == 5.0
    assert mx == 25.0
    assert cnt == 10
    assert av == 18.0


# --- livelink_parameters (no-slot, plain-unique DELETE branch) --------------


def _make_livelink_parameters(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE livelink_parameters (id {pk}, param_key VARCHAR)"))
        # mixed-case + its uppercase twin (unique on param_key alone) → mixed dropped;
        # mixed-only → rekeyed up; canonical → untouched.
        for k in ("51-FuelType", "51-FUELTYPE", "0C-EngineRPM", "ODOMETER"):
            conn.execute(
                text("INSERT INTO livelink_parameters (param_key) VALUES (:k)"),
                {"k": k},
            )


def test_059_livelink_parameters_no_slot_branch(engine_for_migration):
    """Exercise the empty-slot DELETE path (distinct SQL from the self-join)."""
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)
    _load("059_param_key_casing_merge").upgrade(engine)
    with engine.begin() as conn:
        keys = sorted(r[0] for r in conn.execute(text("SELECT param_key FROM livelink_parameters")))
    # casing twin collapsed to one canonical row; mixed-only rekeyed; canonical kept
    assert keys == ["0C-ENGINERPM", "51-FUELTYPE", "ODOMETER"]


def test_059_canon_matches_live_normalizer():
    """Tripwire: the migration's frozen canonical form must match the live helper.

    The migration re-derives ``canonical_param_key`` inline (a migration must not
    import live app code that can drift). This test turns that docstring contract
    into a CI gate: if someone deepens ``canonical_param_key``, the migration's
    silent divergence is caught here instead of shipping a re-dup on prod.
    """
    from app.utils.autopid_normalizer import canonical_param_key

    mod = _load("059_param_key_casing_merge")
    for key in ("51-FuelType", "A6-Odometer", "ENGINE RPM", "0C-EngineRPM", "ODOMETER", "a b c"):
        assert mod._canon_py(key) == canonical_param_key(key)
