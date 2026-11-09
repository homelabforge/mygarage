"""Add the tables that hold user-saved reminder packs.

Two new tables and nothing else: no column dropped, no row rewritten, no
existing table touched. So this needs no backup warning, unlike 107 and 108.

FATAL = False, and that is a real choice rather than the default. The ORM maps
both tables, so a silent skip would 500 every pack list; but `create_all` runs
BEFORE migrations (`app/database.py:144`) and creates them from the models, so on
the ordinary startup path the tables exist whether or not this migration runs.
This migration is what gets them onto a database whose `create_all` already ran
in an older release, and it must not stop a boot if, say, the `users` table it
references is unexpectedly absent.

That same ordering is why every statement here is `IF NOT EXISTS` and why the
re-entrancy check tolerates one table existing without the other: `create_all`
may have made both, this migration may have made both, or a half-finished run
may have made one.

It is also why the column TYPES here have to match the models and not merely be
compatible with them: whichever of the two runs first is the one that decides
what the table looks like, so `vehicle_types` is `JSON` in both places.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False

_PACKS = "reminder_packs"
_ITEMS = "reminder_pack_items"


def _packs_ddl(serial: str, timestamp: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {_PACKS} (
            id {serial},
            pack_id VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            vehicle_types JSON NOT NULL DEFAULT '[]',
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at {timestamp} DEFAULT CURRENT_TIMESTAMP,
            updated_at {timestamp}
        )
    """


def _items_ddl(serial: str) -> str:
    """The item table.

    Interval CHECKs mirror `vehicle_maintenance_rules`, plus the
    distance-versus-hours rule that the rule table leaves to its request schema.
    Both ends of this table are ours, so the database can hold the line.
    """
    return f"""
        CREATE TABLE IF NOT EXISTS {_ITEMS} (
            id {serial},
            pack_id INTEGER NOT NULL REFERENCES {_PACKS}(id) ON DELETE CASCADE,
            item_key VARCHAR(64) NOT NULL,
            title VARCHAR(200) NOT NULL,
            maintenance_type VARCHAR(50),
            interval_km NUMERIC(10, 2),
            interval_months INTEGER,
            interval_days INTEGER,
            interval_hours NUMERIC(10, 1),
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_reminder_pack_item UNIQUE (pack_id, item_key),
            CONSTRAINT check_pack_item_interval_km
                CHECK (interval_km IS NULL OR interval_km > 0),
            CONSTRAINT check_pack_item_interval_months
                CHECK (interval_months IS NULL OR interval_months > 0),
            CONSTRAINT check_pack_item_interval_days
                CHECK (interval_days IS NULL OR interval_days > 0),
            CONSTRAINT check_pack_item_interval_hours
                CHECK (interval_hours IS NULL OR interval_hours > 0),
            CONSTRAINT check_pack_item_has_interval
                CHECK (interval_km IS NOT NULL OR interval_months IS NOT NULL
                       OR interval_days IS NOT NULL OR interval_hours IS NOT NULL),
            CONSTRAINT check_pack_item_distance_or_hours
                CHECK (interval_km IS NULL OR interval_hours IS NULL)
        )
    """


_INDEX = f"CREATE INDEX IF NOT EXISTS idx_reminder_pack_items_pack ON {_ITEMS} (pack_id)"


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("users"):
        print("  → users missing; skip (run the earlier migrations first)")
        return

    if inspector.has_table(_PACKS) and inspector.has_table(_ITEMS):
        print("✓ Reminder pack tables already present")
        return

    if engine.dialect.name == "postgresql":
        serial, timestamp = "SERIAL PRIMARY KEY", "TIMESTAMP"
    else:
        serial, timestamp = "INTEGER PRIMARY KEY AUTOINCREMENT", "DATETIME"

    with engine.begin() as conn:
        conn.execute(text(_packs_ddl(serial, timestamp)))
        print(f"✓ Created {_PACKS}")
        conn.execute(text(_items_ddl(serial)))
        print(f"✓ Created {_ITEMS}")
        conn.execute(text(_INDEX))


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 109 is forward-only.")


if __name__ == "__main__":
    upgrade()
