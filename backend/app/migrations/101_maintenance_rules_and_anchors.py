"""Maintenance rules, service anchors and canonical types for the reminder lifecycle.

Adds:
  1. ``vehicle_maintenance_rules``: per-vehicle recurrence rules (WHEN).
  2. ``service_line_items.maintenance_type``: the canonical type of the work
     (WHAT HAPPENED), matched by code from now on, never by text.
  3. Twelve nullable columns on ``vehicle_reminders``: the rule, the type, the
     anchor snapshot the thresholds count from, how it was completed, and a
     supersession pointer.
  4. ``uq_reminders_rule_pending``: one pending reminder per rule, a partial
     unique index whose syntax is the same on both dialects.
  5. A backfill that fills NULLs only: line items and reminders get the type
     the classifier is sure of, and a reminder linked to a line item gets that
     visit's date and readings as its anchor snapshot.

Every column is added with plain ``ALTER TABLE ... ADD COLUMN``. SQLite accepts
``REFERENCES`` in ``ADD COLUMN`` when the default is NULL (probed on 3.46), so
there is no table rebuild and none of migration 097's FK-pragma handling.

The backfill never deletes, merges or re-statuses a row. Duplicate reminders
on an upgraded installation stay exactly as they were; they become
DETECTABLE (same type, both pending) and the app offers to reconcile them.

FATAL: the ``Reminder`` and ``ServiceLineItem`` ORMs map these columns, so a
silent skip would fail every reminder and service-visit read (precedent: 095,
099, 100). Idempotent, dialect-aware, forward-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

from app.utils.maintenance_types import classify

FATAL = True

RULES_TABLE = "vehicle_maintenance_rules"

#: (name, SQLite DDL, PostgreSQL DDL) for every column added to vehicle_reminders.
REMINDER_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "rule_id",
        "INTEGER REFERENCES vehicle_maintenance_rules(id) ON DELETE SET NULL",
        "INTEGER REFERENCES vehicle_maintenance_rules(id) ON DELETE SET NULL",
    ),
    ("maintenance_type", "VARCHAR(50)", "VARCHAR(50)"),
    ("anchor_kind", "VARCHAR(12)", "VARCHAR(12)"),
    ("anchor_date", "DATE", "DATE"),
    ("anchor_odometer_km", "NUMERIC(10, 2)", "NUMERIC(10, 2)"),
    ("anchor_hours", "NUMERIC(10, 1)", "NUMERIC(10, 1)"),
    ("completed_at", "DATETIME", "TIMESTAMP"),
    ("completed_date", "DATE", "DATE"),
    ("completed_odometer_km", "NUMERIC(10, 2)", "NUMERIC(10, 2)"),
    ("completed_hours", "NUMERIC(10, 1)", "NUMERIC(10, 1)"),
    (
        "completed_line_item_id",
        "INTEGER REFERENCES service_line_items(id) ON DELETE SET NULL",
        "INTEGER REFERENCES service_line_items(id) ON DELETE SET NULL",
    ),
    (
        "superseded_by_id",
        "INTEGER REFERENCES vehicle_reminders(id) ON DELETE SET NULL",
        "INTEGER REFERENCES vehicle_reminders(id) ON DELETE SET NULL",
    ),
)

_RULE_CHECKS = """
    CONSTRAINT check_rule_interval_km CHECK (interval_km IS NULL OR interval_km > 0),
    CONSTRAINT check_rule_interval_months CHECK (interval_months IS NULL OR interval_months > 0),
    CONSTRAINT check_rule_interval_days CHECK (interval_days IS NULL OR interval_days > 0),
    CONSTRAINT check_rule_interval_hours CHECK (interval_hours IS NULL OR interval_hours > 0),
    CONSTRAINT check_rule_has_interval CHECK (interval_km IS NOT NULL OR interval_months IS NOT NULL OR interval_days IS NOT NULL OR interval_hours IS NOT NULL)
"""

_RULES_DDL_SQLITE = f"""
CREATE TABLE {RULES_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    maintenance_type VARCHAR(50),
    title VARCHAR(200) NOT NULL,
    interval_km NUMERIC(10, 2),
    interval_months INTEGER,
    interval_days INTEGER,
    interval_hours NUMERIC(10, 1),
    source VARCHAR(20) NOT NULL,
    source_pack_id VARCHAR(64),
    source_pack_key VARCHAR(64),
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME,
{_RULE_CHECKS}
)
"""

_RULES_DDL_PG = f"""
CREATE TABLE {RULES_TABLE} (
    id SERIAL PRIMARY KEY,
    vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
    maintenance_type VARCHAR(50),
    title VARCHAR(200) NOT NULL,
    interval_km NUMERIC(10, 2),
    interval_months INTEGER,
    interval_days INTEGER,
    interval_hours NUMERIC(10, 1),
    source VARCHAR(20) NOT NULL,
    source_pack_id VARCHAR(64),
    source_pack_key VARCHAR(64),
    notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP,
{_RULE_CHECKS}
)
"""


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _column_names(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _index_names(engine: Engine, table: str) -> set[str]:
    return {name for ix in inspect(engine).get_indexes(table) if (name := ix.get("name"))}


# ============================================================================
#  Schema
# ============================================================================


def _create_rules_table(engine: Engine, is_pg: bool) -> None:
    if inspect(engine).has_table(RULES_TABLE):
        print(f"  = {RULES_TABLE} already exists")
        return
    with engine.begin() as conn:
        conn.execute(text(_RULES_DDL_PG if is_pg else _RULES_DDL_SQLITE))
        conn.execute(
            text(
                f"CREATE INDEX ix_maintenance_rules_vin_type ON {RULES_TABLE} (vin, maintenance_type)"
            )
        )
    print(f"  ✓ Created {RULES_TABLE}")


def _add_line_item_type(engine: Engine) -> None:
    if not inspect(engine).has_table("service_line_items"):
        print("  = service_line_items absent, skipping")
        return
    with engine.begin() as conn:
        if "maintenance_type" not in _column_names(engine, "service_line_items"):
            conn.execute(
                text("ALTER TABLE service_line_items ADD COLUMN maintenance_type VARCHAR(50)")
            )
            print("  ✓ Added service_line_items.maintenance_type")
        if "ix_service_line_items_maintenance_type" not in _index_names(
            engine, "service_line_items"
        ):
            conn.execute(
                text(
                    "CREATE INDEX ix_service_line_items_maintenance_type "
                    "ON service_line_items (maintenance_type)"
                )
            )
            print("  ✓ Added ix_service_line_items_maintenance_type")


def _add_reminder_columns(engine: Engine, is_pg: bool) -> None:
    if not inspect(engine).has_table("vehicle_reminders"):
        print("  = vehicle_reminders absent, skipping")
        return
    existing = _column_names(engine, "vehicle_reminders")
    with engine.begin() as conn:
        for name, sqlite_ddl, pg_ddl in REMINDER_COLUMNS:
            if name in existing:
                continue
            ddl = pg_ddl if is_pg else sqlite_ddl
            conn.execute(text(f"ALTER TABLE vehicle_reminders ADD COLUMN {name} {ddl}"))
            print(f"  ✓ Added vehicle_reminders.{name}")
        if "uq_reminders_rule_pending" not in _index_names(engine, "vehicle_reminders"):
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_reminders_rule_pending "
                    "ON vehicle_reminders (rule_id) WHERE status = 'pending'"
                )
            )
            print("  ✓ Added uq_reminders_rule_pending")


# ============================================================================
#  Backfill (fills NULLs only)
# ============================================================================


def _backfill_line_item_types(engine: Engine) -> int:
    if "description" not in _column_names(engine, "service_line_items"):
        return 0
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, description FROM service_line_items WHERE maintenance_type IS NULL")
        ).fetchall()
        updates = [
            {"id": row_id, "code": code}
            for row_id, description in rows
            if (code := classify(description)) is not None
        ]
        if updates:
            conn.execute(
                text("UPDATE service_line_items SET maintenance_type = :code WHERE id = :id"),
                updates,
            )
    return len(updates)


def _backfill_reminders(engine: Engine) -> tuple[int, int]:
    """Type and anchor every reminder that lacks them.

    A reminder linked to a line item takes that line item's type (as just
    classified) and the visit's date and readings as a 'service' anchor. An
    unlinked one is classified from its title. Tire-sourced reminders
    (`source IS NOT NULL`) are left alone: they are identified by tire, not by
    maintenance type.
    """
    typed = 0
    anchored = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT r.id, r.title, r.line_item_id, r.maintenance_type, r.anchor_kind,
                       li.maintenance_type AS li_type,
                       sv.date AS sv_date, sv.odometer_km AS sv_odometer, sv.engine_hours AS sv_hours
                FROM vehicle_reminders r
                LEFT JOIN service_line_items li ON li.id = r.line_item_id
                LEFT JOIN service_visits sv ON sv.id = li.visit_id
                WHERE r.source IS NULL
                  AND (r.maintenance_type IS NULL
                       OR (r.line_item_id IS NOT NULL AND r.anchor_kind IS NULL))
                """
            )
        ).fetchall()
        for row in rows:
            (
                reminder_id,
                title,
                line_item_id,
                current_type,
                current_anchor_kind,
                li_type,
                sv_date,
                sv_odometer,
                sv_hours,
            ) = row
            assignments: dict[str, object] = {}
            if current_type is None:
                code = li_type if (line_item_id is not None and li_type) else classify(title)
                if code is not None:
                    assignments["maintenance_type"] = code
                    typed += 1
            if line_item_id is not None and current_anchor_kind is None and sv_date is not None:
                assignments["anchor_kind"] = "service"
                assignments["anchor_date"] = sv_date
                assignments["anchor_odometer_km"] = sv_odometer
                assignments["anchor_hours"] = sv_hours
                anchored += 1
            if not assignments:
                continue
            set_clause = ", ".join(f"{column} = :{column}" for column in assignments)
            conn.execute(
                text(f"UPDATE vehicle_reminders SET {set_clause} WHERE id = :id"),
                {"id": reminder_id, **assignments},
            )
    return typed, anchored


# ============================================================================
#  Entry point
# ============================================================================


def upgrade(engine: Engine | None = None) -> None:
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()
    is_pg = engine.dialect.name == "postgresql"
    print("Migration 101: maintenance rules, service anchors and canonical types...")

    if not inspect(engine).has_table("vehicles"):
        print("  = vehicles absent (fresh database before create_all), skipping")
        return

    _create_rules_table(engine, is_pg)
    _add_line_item_type(engine)
    _add_reminder_columns(engine, is_pg)

    inspector = inspect(engine)
    if inspector.has_table("service_line_items"):
        typed_items = _backfill_line_item_types(engine)
        print(f"  ✓ Classified {typed_items} service line item(s)")
    if inspector.has_table("vehicle_reminders") and inspector.has_table("service_line_items"):
        if inspector.has_table("service_visits"):
            typed, anchored = _backfill_reminders(engine)
            print(f"  ✓ Typed {typed} reminder(s), anchored {anchored}")
        else:
            print("  = service_visits absent, reminder backfill skipped")
    print("✓ Migration 101 complete")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 101 is forward-only.")


if __name__ == "__main__":
    upgrade()
