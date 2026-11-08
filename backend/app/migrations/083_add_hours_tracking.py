"""Add engine-hours usage tracking (hours_records, engine_hours, due_hours, secondary_usage_enabled).

Foundation for the dual-track hours-usage feature: engine hours become a
co-equal usage dimension alongside distance. This migration:

  1. Creates ``hours_records`` — the hours history table mirroring
     ``odometer_records``, plus real FKs to the parent fuel record and service
     visit (source identity, not note-parsing).
  2. Adds ``vehicles.secondary_usage_enabled`` (BOOLEAN NOT NULL DEFAULT false),
     ``fuel_records.engine_hours``, ``service_visits.engine_hours`` and
     ``vehicle_reminders.due_hours`` (all nullable NUMERIC(10,1)).
  3. Widens the ``vehicle_reminders.reminder_type`` CHECK to accept ``'hours'``.
  4. Backfills existing ``vehicles.current_hours`` into a seed manual
     ``hours_records`` row so latest-hours derivation is consistent.

FATAL: the ``Vehicle`` model declares ``secondary_usage_enabled`` non-nullable
and serializes it on every vehicle read; the runner log-and-continues on
non-FATAL failure, so a silent skip would boot the app against a missing column.

Dialect-aware + idempotent:
  - ``hours_records`` and the column adds are state-checked (skip if already in
    the desired state). ``Base.metadata.create_all()`` runs before the runner
    and creates a missing ``hours_records`` table, so that step no-ops. It
    never adds columns to an existing table, though, so on an existing DB the
    column adds do the real work; only a fresh DB gets them from create_all.
  - The ``reminder_type`` CHECK widening is NAME-AGNOSTIC and PARITY-PRESERVING:
    it acts only when a legacy ``reminder_type`` CHECK *without* ``'hours'`` is
    present. The ``Reminder`` model declares no such CHECK, so on a fresh
    ``create_all`` schema the step is a no-op — keeping
    ``create_all == create_all + migrations`` parity on both dialects
    (``test_schema_parity``). SQLite widens via a full FK-safe table rebuild
    (migration 070 pattern, PRAGMA foreign_keys=OFF outside the transaction);
    PostgreSQL discovers the constraint via ``pg_constraint`` and swaps it.

Forward-only. Restore from the pre-migration backup for rollback.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

# Matches a ``CHECK (reminder_type IN (...))`` clause (SQLite table SQL). The
# captured group is the value list, so we can tell a legacy 4-value CHECK from
# an already-widened one without hard-coding a constraint name.
_REMINDER_CHECK_RE = re.compile(r"check\s*\(\s*reminder_type\s+in\s*\(([^)]*)\)", re.IGNORECASE)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Create the hours schema, widen the reminder CHECK, and backfill current_hours."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("vehicles"):
        return

    is_pg = engine.dialect.name == "postgresql"

    _create_hours_records(engine, is_pg)
    _add_columns(engine, is_pg)
    _widen_reminder_type_check(engine, is_pg)
    _backfill_current_hours(engine)

    print("✓ Migration 083 (hours tracking) completed")


# ============================================================================
#  hours_records table
# ============================================================================


def _create_hours_records(engine, is_pg) -> None:
    """Create ``hours_records`` + its indexes (skip if it already exists).

    In production ``create_all`` builds this table before the runner, so this is
    a no-op there; it runs on standalone/PG-CI paths where the FK-target tables
    (``vehicles``, ``fuel_records``, ``service_visits``) already exist.
    """
    inspector = inspect(engine)
    if inspector.has_table("hours_records"):
        return
    for dep in ("vehicles", "fuel_records", "service_visits"):
        if not inspector.has_table(dep):
            return

    pk_type = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"
    with engine.begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE hours_records (
                id {pk_type},
                vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                date DATE NOT NULL,
                engine_hours NUMERIC(10,1) NOT NULL,
                notes TEXT,
                source VARCHAR(20) DEFAULT 'manual',
                fuel_record_id INTEGER REFERENCES fuel_records(id) ON DELETE CASCADE,
                service_visit_id INTEGER REFERENCES service_visits(id) ON DELETE CASCADE,
                created_at {ts_type} DEFAULT CURRENT_TIMESTAMP
            )
            """)
        )
        for stmt in (
            "CREATE INDEX idx_hours_records_vin ON hours_records(vin)",
            "CREATE INDEX idx_hours_records_date ON hours_records(date)",
            "CREATE INDEX idx_hours_records_engine_hours ON hours_records(engine_hours)",
            "CREATE INDEX idx_hours_vin_date ON hours_records(vin, date)",
            "CREATE INDEX idx_hours_vin_engine_hours ON hours_records(vin, engine_hours)",
            "CREATE INDEX idx_hours_source ON hours_records(source)",
            "CREATE INDEX ix_hours_records_fuel_record_id ON hours_records(fuel_record_id)",
            "CREATE INDEX ix_hours_records_service_visit_id ON hours_records(service_visit_id)",
        ):
            conn.execute(text(stmt))
    print("  ✓ Created hours_records")


# ============================================================================
#  Additive columns
# ============================================================================


def _add_columns(engine, is_pg) -> None:
    """Add the four hours columns, each guarded by column-existence."""
    # vehicles.secondary_usage_enabled — NOT NULL with a constant default, so a
    # plain ADD COLUMN is accepted on SQLite without a rebuild (A5).
    inspector = inspect(engine)
    if "secondary_usage_enabled" not in {c["name"] for c in inspector.get_columns("vehicles")}:
        default_literal = "FALSE" if is_pg else "0"
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE vehicles ADD COLUMN secondary_usage_enabled "
                    f"BOOLEAN NOT NULL DEFAULT {default_literal}"
                )
            )
            # Belt-and-braces backfill (some SQLite paths leave NULL when adding
            # a NOT NULL DEFAULT column to an existing table).
            conn.execute(
                text(
                    "UPDATE vehicles SET secondary_usage_enabled = "
                    f"{default_literal} WHERE secondary_usage_enabled IS NULL"
                )
            )
        print("  ✓ Added vehicles.secondary_usage_enabled")

    # Nullable NUMERIC(10,1) columns — plain ADD COLUMN on both dialects.
    for table, column in (
        ("fuel_records", "engine_hours"),
        ("service_visits", "engine_hours"),
        ("vehicle_reminders", "due_hours"),
    ):
        insp = inspect(engine)
        if not insp.has_table(table):
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} NUMERIC(10,1)"))
        print(f"  ✓ Added {table}.{column}")


# ============================================================================
#  reminder_type CHECK widening (name-agnostic, parity-preserving)
# ============================================================================


def _widen_reminder_type_check(engine, is_pg) -> None:
    """Widen the ``reminder_type`` CHECK to accept ``'hours'`` when a legacy
    CHECK is present. A no-op on schemas that carry no such CHECK (fresh
    ``create_all``) or one that already includes ``'hours'``."""
    if not inspect(engine).has_table("vehicle_reminders"):
        return
    if is_pg:
        _widen_reminder_type_check_pg(engine)
    else:
        _widen_reminder_type_check_sqlite(engine)


def _widen_reminder_type_check_pg(engine) -> None:
    """PostgreSQL: discover any reminder_type CHECK, drop it, add the widened one."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
            SELECT conname, pg_get_constraintdef(oid) AS cdef
            FROM pg_constraint
            WHERE conrelid = 'vehicle_reminders'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%reminder_type%'
            """)
        ).fetchall()
        if not rows:
            # No legacy CHECK — leave as-is to preserve create_all parity.
            return
        if any("'hours'" in (cdef or "").lower() for _conname, cdef in rows):
            # Already widened — idempotent no-op.
            return
        for conname, _cdef in rows:
            conn.execute(text(f'ALTER TABLE vehicle_reminders DROP CONSTRAINT "{conname}"'))
        conn.execute(
            text(
                "ALTER TABLE vehicle_reminders ADD CONSTRAINT vehicle_reminders_reminder_type_check "
                "CHECK (reminder_type IN ('date','mileage','both','smart','hours'))"
            )
        )
    print("  ✓ Widened vehicle_reminders.reminder_type CHECK (PG)")


def _sqlite_vehicle_reminders_sql(engine) -> str:
    """Return the CREATE TABLE SQL for vehicle_reminders (SQLite)."""
    with engine.connect() as conn:
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='vehicle_reminders'")
        ).scalar()
    return sql or ""


def _reminder_check_needs_widening(table_sql: str) -> bool:
    """True iff a legacy ``reminder_type`` CHECK exists that lacks ``'hours'``."""
    match = _REMINDER_CHECK_RE.search(table_sql)
    if not match:
        return False  # no reminder_type CHECK → nothing to widen (parity)
    return "'hours'" not in match.group(1).lower()


def _widen_reminder_type_check_sqlite(engine) -> None:
    """SQLite: full FK-safe rebuild widening the CHECK (migration 070 pattern)."""
    if not _reminder_check_needs_widening(_sqlite_vehicle_reminders_sql(engine)):
        return

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # Disable FK enforcement OUTSIDE any transaction (SQLite docs).
        cur.execute("PRAGMA foreign_keys = OFF")
        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 0:
            raise RuntimeError(
                f"PRAGMA foreign_keys = OFF failed; got {fk_state}. "
                "Are we inside an active transaction?"
            )

        try:
            cur.execute("BEGIN")
            _rebuild_vehicle_reminders(cur)

            # Pre-commit FK integrity check — roll back rather than commit a
            # rebuild that orphaned the inbound/outbound FK. Scoped to the
            # rebuilt table only (migration 053 pattern): an unscoped
            # whole-database check would also surface pre-existing orphans in
            # unrelated tables on a legacy DB that predates this repo's
            # ``PRAGMA foreign_keys=ON`` fix, aborting this FATAL migration
            # (and app startup) over a violation this rebuild didn't cause.
            violations = cur.execute("PRAGMA foreign_key_check(vehicle_reminders)").fetchall()
            if violations:
                raise RuntimeError(
                    f"FK violations after vehicle_reminders rebuild (pre-commit): {violations!r}"
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.execute("PRAGMA foreign_keys = ON")

        fk_state = cur.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk_state != 1:
            raise RuntimeError(f"PRAGMA foreign_keys = ON failed; got {fk_state}.")
    finally:
        raw.close()
    print("  ✓ Widened vehicle_reminders.reminder_type CHECK (SQLite rebuild)")


def _rebuild_vehicle_reminders(cur) -> None:
    """Rebuild vehicle_reminders with the widened CHECK, preserving all columns,
    the vin CASCADE FK, and the three model indexes. ``due_hours`` was added by
    ``_add_columns`` before this runs, so the old table already carries it."""
    cur.execute("""
        CREATE TABLE vehicle_reminders_new (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            vin              VARCHAR(17)  NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
            line_item_id     INTEGER      REFERENCES service_line_items(id) ON DELETE SET NULL,
            title            VARCHAR(200) NOT NULL,
            reminder_type    VARCHAR(10)  NOT NULL
                             CHECK (reminder_type IN ('date','mileage','both','smart','hours')),
            due_date         DATE,
            due_mileage_km   NUMERIC(10,2)
                             CHECK (due_mileage_km IS NULL OR due_mileage_km > 0),
            due_hours        NUMERIC(10,1),
            status           VARCHAR(10)  NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','done','dismissed')),
            notes            TEXT,
            last_notified_at DATETIME,
            created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        INSERT INTO vehicle_reminders_new
               (id, vin, line_item_id, title, reminder_type, due_date, due_mileage_km,
                due_hours, status, notes, last_notified_at, created_at, updated_at)
        SELECT  id, vin, line_item_id, title, reminder_type, due_date, due_mileage_km,
                due_hours, status, notes, last_notified_at,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
        FROM vehicle_reminders
    """)
    cur.execute("DROP TABLE vehicle_reminders")
    cur.execute("ALTER TABLE vehicle_reminders_new RENAME TO vehicle_reminders")
    for stmt in (
        "CREATE INDEX ix_reminders_vin_status ON vehicle_reminders(vin, status)",
        "CREATE INDEX ix_reminders_due_date ON vehicle_reminders(due_date)",
        "CREATE INDEX ix_reminders_due_mileage_km ON vehicle_reminders(due_mileage_km)",
    ):
        cur.execute(stmt)


# ============================================================================
#  current_hours backfill
# ============================================================================


def _backfill_current_hours(engine) -> None:
    """Seed one manual ``hours_records`` row from each vehicle's legacy
    ``current_hours`` (only when it is set and the vehicle has no hours rows)."""
    inspector = inspect(engine)
    if not (inspector.has_table("vehicles") and inspector.has_table("hours_records")):
        return
    if "current_hours" not in {c["name"] for c in inspector.get_columns("vehicles")}:
        return

    today = dt.date.today().isoformat()
    with engine.begin() as conn:
        rows = conn.execute(
            text("""
            SELECT v.vin, v.current_hours
            FROM vehicles v
            WHERE v.current_hours IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM hours_records h WHERE h.vin = v.vin)
            """)
        ).fetchall()
        for vin, current_hours in rows:
            conn.execute(
                text("""
                INSERT INTO hours_records (vin, date, engine_hours, notes, source)
                VALUES (:vin, :date, :hours, :notes, 'manual')
                """),
                {
                    "vin": vin,
                    "date": today,
                    "hours": current_hours,
                    "notes": "[SEED from current_hours]",
                },
            )
    if rows:
        print(f"  ✓ Backfilled {len(rows)} current_hours seed row(s)")


def downgrade(engine=None) -> None:  # pragma: no cover
    """Forward-only. Restore from the pre-migration backup instead."""
    raise NotImplementedError(
        "Migration 083 is forward-only. Restore from the pre-migration backup instead."
    )


if __name__ == "__main__":
    upgrade()
