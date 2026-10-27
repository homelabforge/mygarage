"""Add ``vehicle_reminders.snoozed_until`` for reminder snooze (hide until date).

While ``household_today() < snoozed_until`` a pending reminder is excluded
from overdue and due-soon counts, the inbox, fleet next-due and scheduled
notifications; its real due date/mileage/hours stay untouched, and the field
goes inert the day it passes. Completion clears it.

FATAL for migration 099's reason: the Reminder ORM maps this column, so every
reminder SELECT includes it and a silent skip would 500 all reminder reads
after the model change.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

_COLUMNS: tuple[tuple[str, str], ...] = (("snoozed_until", "DATE"),)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicle_reminders"):
        return

    existing = {c["name"] for c in inspector.get_columns("vehicle_reminders")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    if not missing:
        print("✓ vehicle_reminders.snoozed_until already present")
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE vehicle_reminders ADD COLUMN {name} {ddl}"))
            print(f"✓ Added vehicle_reminders.{name}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 103 is forward-only.")


if __name__ == "__main__":
    upgrade()
