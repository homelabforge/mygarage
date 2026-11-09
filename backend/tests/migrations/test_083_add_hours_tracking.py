"""Tests for migration 083 — hours-usage foundation.

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset).

Covers:
  - ``hours_records`` table + its columns/indexes created (both dialects).
  - The four additive columns (``vehicles.secondary_usage_enabled``,
    ``fuel_records.engine_hours``, ``service_visits.engine_hours``,
    ``vehicle_reminders.due_hours``).
  - ``reminder_type`` CHECK widened to accept ``'hours'`` and reject a bogus
    value, name-agnostically, while existing reminder rows + indexes + the vin
    FK survive the (SQLite) rebuild.
  - ``current_hours`` backfilled into a single seed ``hours_records`` row.
  - Full idempotency (``upgrade`` run twice).
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vin_fk_is_cascade(dialect, engine):
    """True iff vehicle_reminders' vin FK keeps ON DELETE CASCADE.

    SQLite reflection does not expose the FK action, so read it from the table
    SQL; PostgreSQL exposes it via the reflected FK ``options``.
    """
    if dialect == "pg":
        vin_fks = [
            fk
            for fk in inspect(engine).get_foreign_keys("vehicle_reminders")
            if fk["referred_table"] == "vehicles"
        ]
        return (vin_fks[0].get("options") or {}).get("ondelete", "").upper() == "CASCADE"
    with engine.connect() as conn:
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='vehicle_reminders'")
        ).scalar()
    return "cascade" in (sql or "").lower()


def _make_deps(engine, *, with_current_hours=None):
    """Create the minimal FK-target tables migration 083 operates on.

    Mirrors a real *post-053* schema: ``vehicle_reminders`` carries the legacy
    4-value ``reminder_type`` CHECK + its three indexes + the vin FK, so the
    widening/rebuild path is exercised. ``vehicles`` gets a ``current_hours``
    column so the seed-backfill path is exercised too.
    """
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, current_hours NUMERIC(10,1))")
        )
        conn.execute(text(f"CREATE TABLE service_line_items (id {pk})"))
        conn.execute(text(f"CREATE TABLE fuel_records (id {pk}, vin VARCHAR(17))"))
        conn.execute(text(f"CREATE TABLE service_visits (id {pk}, vin VARCHAR(17))"))
        conn.execute(
            text(f"""
            CREATE TABLE vehicle_reminders (
                id               {pk},
                vin              VARCHAR(17)  NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                line_item_id     INTEGER,
                title            VARCHAR(200) NOT NULL,
                reminder_type    VARCHAR(10)  NOT NULL
                                 CHECK (reminder_type IN ('date','mileage','both','smart')),
                due_date         DATE,
                due_mileage_km   NUMERIC(10,2),
                status           VARCHAR(10)  NOT NULL DEFAULT 'pending',
                notes            TEXT,
                last_notified_at {ts},
                created_at       {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at       {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
        )
        for stmt in (
            "CREATE INDEX ix_reminders_vin_status ON vehicle_reminders(vin, status)",
            "CREATE INDEX ix_reminders_due_date ON vehicle_reminders(due_date)",
            "CREATE INDEX ix_reminders_due_mileage_km ON vehicle_reminders(due_mileage_km)",
        ):
            conn.execute(text(stmt))
        # A vehicle (optionally with a current_hours reading to backfill).
        conn.execute(
            text("INSERT INTO vehicles (vin, current_hours) VALUES ('1FT0000000000000X', :ch)"),
            {"ch": with_current_hours},
        )
        # Two existing reminder rows that must survive the rebuild.
        conn.execute(
            text(
                "INSERT INTO vehicle_reminders (vin, title, reminder_type, due_mileage_km) "
                "VALUES ('1FT0000000000000X', 'Oil', 'mileage', 12000)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicle_reminders (vin, title, reminder_type, due_date) "
                "VALUES ('1FT0000000000000X', 'Registration', 'date', '2027-01-01')"
            )
        )


def test_083_creates_hours_records_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load("083_add_hours_tracking").upgrade(engine)

    insp = inspect(engine)
    assert insp.has_table("hours_records")
    cols = {c["name"] for c in insp.get_columns("hours_records")}
    assert {
        "id",
        "vin",
        "date",
        "engine_hours",
        "notes",
        "source",
        "fuel_record_id",
        "service_visit_id",
        "created_at",
    } <= cols

    index_cols = {tuple(ix["column_names"]) for ix in insp.get_indexes("hours_records")}
    assert ("vin",) in index_cols
    assert ("date",) in index_cols
    assert ("engine_hours",) in index_cols
    assert ("vin", "date") in index_cols
    assert ("vin", "engine_hours") in index_cols
    assert ("source",) in index_cols
    assert ("fuel_record_id",) in index_cols
    assert ("service_visit_id",) in index_cols

    # The hours_records FKs target the parent fuel record and service visit.
    fk_targets = {fk["referred_table"] for fk in insp.get_foreign_keys("hours_records")}
    assert {"vehicles", "fuel_records", "service_visits"} <= fk_targets


def test_083_adds_the_four_columns(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load("083_add_hours_tracking").upgrade(engine)

    insp = inspect(engine)
    assert "secondary_usage_enabled" in {c["name"] for c in insp.get_columns("vehicles")}
    assert "engine_hours" in {c["name"] for c in insp.get_columns("fuel_records")}
    assert "engine_hours" in {c["name"] for c in insp.get_columns("service_visits")}
    assert "due_hours" in {c["name"] for c in insp.get_columns("vehicle_reminders")}

    # secondary_usage_enabled must be non-null and default to false.
    with engine.connect() as conn:
        val = conn.execute(text("SELECT secondary_usage_enabled FROM vehicles LIMIT 1")).scalar()
    assert bool(val) is False


def test_083_widens_reminder_type_check(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load("083_add_hours_tracking").upgrade(engine)

    vin = "1FT0000000000000X"
    # 'hours' must now be accepted.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicle_reminders (vin, title, reminder_type, due_hours) "
                "VALUES (:vin, 'Valve service', 'hours', 250)"
            ),
            {"vin": vin},
        )
    # An invalid value must still be rejected (the widened CHECK is real).
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO vehicle_reminders (vin, title, reminder_type) "
                    "VALUES (:vin, 'Bad', 'bogus')"
                ),
                {"vin": vin},
            )


def test_083_reminder_rows_indexes_and_fk_survive(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load("083_add_hours_tracking").upgrade(engine)

    insp = inspect(engine)
    # Existing rows survived the rebuild.
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM vehicle_reminders")).scalar()
    assert count == 2

    # All three indexes survived.
    index_names = {ix["name"] for ix in insp.get_indexes("vehicle_reminders")}
    assert {
        "ix_reminders_vin_status",
        "ix_reminders_due_date",
        "ix_reminders_due_mileage_km",
    } <= index_names

    # The vin -> vehicles FK survived the rebuild.
    vin_fks = [
        fk
        for fk in insp.get_foreign_keys("vehicle_reminders")
        if fk["referred_table"] == "vehicles"
    ]
    assert vin_fks, "vin FK to vehicles must survive the rebuild"
    assert vin_fks[0]["constrained_columns"] == ["vin"]
    # ...and it kept ON DELETE CASCADE. SQLite reflection doesn't expose the FK
    # action, so read it from the table SQL; PG reflects it in options.
    assert _vin_fk_is_cascade(_dialect, engine)


def test_083_backfills_current_hours_seed(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine, with_current_hours=123.4)
    _load("083_add_hours_tracking").upgrade(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT engine_hours, source, notes, date FROM hours_records "
                "WHERE vin = '1FT0000000000000X'"
            )
        ).fetchall()
    assert len(rows) == 1
    engine_hours, source, notes, _date = rows[0]
    assert float(engine_hours) == pytest.approx(123.4)
    assert source == "manual"
    assert "[SEED from current_hours]" in (notes or "")


def test_083_no_backfill_when_current_hours_null(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine, with_current_hours=None)
    _load("083_add_hours_tracking").upgrade(engine)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM hours_records")).scalar()
    assert count == 0


def test_083_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine, with_current_hours=99.9)
    mod = _load("083_add_hours_tracking")
    mod.upgrade(engine)
    mod.upgrade(engine)  # second run must not raise

    insp = inspect(engine)
    assert insp.has_table("hours_records")
    # Only a single hours_records column set (not doubled) and one seed row.
    with engine.connect() as conn:
        seed_count = conn.execute(text("SELECT COUNT(*) FROM hours_records")).scalar()
    assert seed_count == 1
    # Columns still single (rebuild didn't duplicate anything).
    cols = [c["name"] for c in insp.get_columns("vehicle_reminders")]
    assert cols.count("due_hours") == 1


def test_083_missing_vehicles_table_skips(engine_for_migration):
    """A bare DB without the ``vehicles`` table must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    _load("083_add_hours_tracking").upgrade(engine)


def test_083_tolerates_preexisting_orphans_in_other_tables(migration_db, sync_engine):
    """A legacy DB with an orphaned row in an UNRELATED table must not abort
    the ``vehicle_reminders`` CHECK-widening rebuild (SQLite only).

    Real legacy prod DBs accumulated orphaned child rows in other tables
    before this repo's ``PRAGMA foreign_keys=ON`` fix started enforcing FKs.
    The pre-commit integrity gate in ``_widen_reminder_type_check_sqlite``
    must be scoped to ``vehicle_reminders`` (the table it just rebuilt, per
    migration 053's pattern) — not a whole-database
    ``PRAGMA foreign_key_check``, which would also surface those unrelated
    orphans, raise, roll back, and — because migration 083 is
    ``FATAL=True`` — abort app startup even though the reminder rebuild
    itself was clean.
    """

    db_file, db_url = migration_db
    engine = sync_engine(db_url)
    _make_deps(engine)

    # A second FK-constrained table, unrelated to vehicle_reminders, that
    # already carries an orphaned row — the legacy-prod scenario.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE odometer_records ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE, "
                "reading NUMERIC(10,2))"
            )
        )
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(
            text("INSERT INTO odometer_records (vin, reading) VALUES ('DOES-NOT-EXIST-VIN', 100)")
        )
        conn.commit()

    # Confirm the seeded orphan is real and would trip a whole-database check
    # (i.e. this test actually exercises the bug the fix addresses).
    with engine.connect() as conn:
        whole_db_violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    assert whole_db_violations, "test setup must produce a real whole-DB FK violation"

    # Migration 083 must succeed anyway — the orphan lives outside the table
    # it rebuilds and pre-commit-checks.
    _load("083_add_hours_tracking").upgrade(engine)

    # ...and the CHECK widening itself took effect.
    vin = "1FT0000000000000X"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicle_reminders (vin, title, reminder_type, due_hours) "
                "VALUES (:vin, 'Valve service', 'hours', 250)"
            ),
            {"vin": vin},
        )
