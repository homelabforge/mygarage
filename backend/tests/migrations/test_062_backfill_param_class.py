"""Tests for migration 062 — backfill `param_class` for existing telemetry params.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture. Seeds the live-DB shape (rows with NULL param_class, a row with a
class already set, rows with hand-set vs default categories) and asserts:

- NULL-class rows get the frozen-catalog inference (None inferences skipped)
- rows with a class already set are never touched
- category is recomputed ONLY when NULL or 'other' (Task 11's guard mirrored)
- show_on_dashboard / archive_only / display_order are NEVER modified
- double-run idempotency

Plus a drift guard (`test_062_snapshot_matches_runtime_catalog`) pinning the
migration's frozen ``_infer()`` snapshot against the runtime
``infer_param_class`` over the Task 10 fixture keys at this point in time.
"""

from sqlalchemy import text

from tests.migrations._loader import load_migration

# Seed rows: (param_key, param_class, category, show_on_dashboard, archive_only, display_order)
_SEED_ROWS = [
    # NULL class, NULL category → class backfilled 'percentage';
    # percentage maps to 'other' so category is recomputed to 'other'.
    ("2F-FUELTANKLEVEL", None, None, True, False, 3),
    # NULL class, inference returns None → class stays NULL, row untouched.
    ("9B-DIESELEXHAUSTFLUIDSENSORDATA", None, None, False, True, 7),
    # Class already set (even an unusual one) → migration must not touch it,
    # nor recompute its category.
    ("0C-ENGINERPM", "custom_class", "other", True, False, 1),
    # NULL class + hand-set meaningful category → class backfilled
    # 'temperature', category 'engine' PRESERVED (guard mirrors Task 11).
    ("05-ENGINECOOLANTTEMP", None, "engine", False, False, 2),
    # NULL class + default 'other' category → class backfilled 'voltage',
    # category recomputed to 'electrical'.
    ("42-CONTROLMODULEVOLT", None, "other", False, True, 9),
]


def _make_livelink_parameters(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE livelink_parameters (id {pk}, "
                "param_key VARCHAR(100) UNIQUE NOT NULL, "
                "param_class VARCHAR(50), category VARCHAR(50), "
                "show_on_dashboard BOOLEAN NOT NULL DEFAULT TRUE, "
                "archive_only BOOLEAN NOT NULL DEFAULT FALSE, "
                "display_order INTEGER NOT NULL DEFAULT 0)"
            )
        )
        for key, pclass, category, show, archive, order in _SEED_ROWS:
            conn.execute(
                text(
                    "INSERT INTO livelink_parameters "
                    "(param_key, param_class, category, show_on_dashboard, archive_only, display_order) "
                    "VALUES (:k, :c, :cat, :show, :arch, :ord)"
                ),
                {
                    "k": key,
                    "c": pclass,
                    "cat": category,
                    "show": show,
                    "arch": archive,
                    "ord": order,
                },
            )


def _fetch_rows(engine):
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT param_key, param_class, category, show_on_dashboard, "
                "archive_only, display_order FROM livelink_parameters ORDER BY param_key"
            )
        ).fetchall()
    # Normalize booleans (SQLite returns 0/1, PG returns bool)
    return {r[0]: (r[1], r[2], bool(r[3]), bool(r[4]), r[5]) for r in rows}


def test_062_backfills_null_class_rows(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)
    load_migration("062_backfill_param_class").upgrade(engine)

    rows = _fetch_rows(engine)

    # NULL class + NULL category → percentage; percentage maps to 'other'.
    assert rows["2F-FUELTANKLEVEL"][0] == "percentage"
    assert rows["2F-FUELTANKLEVEL"][1] == "other"

    # No inference → class stays NULL, category untouched.
    assert rows["9B-DIESELEXHAUSTFLUIDSENSORDATA"][0] is None
    assert rows["9B-DIESELEXHAUSTFLUIDSENSORDATA"][1] is None

    # Class already set → completely untouched (class AND category).
    assert rows["0C-ENGINERPM"][0] == "custom_class"
    assert rows["0C-ENGINERPM"][1] == "other"

    # Hand-set meaningful category preserved; class still backfilled.
    assert rows["05-ENGINECOOLANTTEMP"][0] == "temperature"
    assert rows["05-ENGINECOOLANTTEMP"][1] == "engine"

    # Default 'other' category recomputed from the new class.
    assert rows["42-CONTROLMODULEVOLT"][0] == "voltage"
    assert rows["42-CONTROLMODULEVOLT"][1] == "electrical"


def test_062_never_touches_display_state(engine_for_migration):
    """show_on_dashboard / archive_only / display_order are user dashboard state."""
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)
    load_migration("062_backfill_param_class").upgrade(engine)

    rows = _fetch_rows(engine)
    for key, _pclass, _category, show, archive, order in _SEED_ROWS:
        assert rows[key][2] == show, f"{key}: show_on_dashboard modified"
        assert rows[key][3] == archive, f"{key}: archive_only modified"
        assert rows[key][4] == order, f"{key}: display_order modified"


def test_062_idempotent(engine_for_migration):
    """Second run is a no-op — identical end state, no raise."""
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)
    mod = load_migration("062_backfill_param_class")
    mod.upgrade(engine)
    first = _fetch_rows(engine)
    mod.upgrade(engine)
    assert _fetch_rows(engine) == first


def test_062_missing_table_skips(engine_for_migration):
    """Fresh DB without livelink_parameters → migration must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    load_migration("062_backfill_param_class").upgrade(engine)  # no table created


def test_062_snapshot_matches_runtime_catalog():
    """Drift guard: frozen migration snapshot ≡ runtime catalog AT THIS POINT IN TIME.

    Pins the migration's frozen ``_infer()`` output against the runtime
    ``infer_param_class`` over the full Task 10 fixture key list (output
    equality, not object identity). This DOCUMENTS rather than forbids
    future divergence: if the runtime catalog legitimately evolves, this
    test may be updated to reflect the new expected divergence — but the
    MIGRATION's frozen snapshot must NOT change (a historical migration's
    output must stay reproducible forever).
    """
    from app.utils.autopid_normalizer import infer_param_class
    from tests.unit.utils.test_param_class_inference import FIXTURE_TABLE

    mod = load_migration("062_backfill_param_class")
    for param_key, _expected in FIXTURE_TABLE:
        assert mod._infer(param_key) == infer_param_class(param_key), (
            f"snapshot drift for {param_key!r}: migration froze "
            f"{mod._infer(param_key)!r}, runtime now returns "
            f"{infer_param_class(param_key)!r}"
        )
