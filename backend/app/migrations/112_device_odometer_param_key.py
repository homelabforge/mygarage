"""Add ``livelink_devices.odometer_param_key``: which parameter carries this device's odometer.

Name matching does not generalise. ``ODOMETER_PID_PATTERNS`` matches WiCAN's
``A6-ODOMETER`` and nothing Torque sends, so a Torque-only user gets no odometer
records at all, and odometer drives maintenance intervals, fuel economy and
reminders. Rather than grow a vendor pattern list forever, a device declares its
own parameter and that declaration REPLACES the matching.

Nullable with no backfill. NULL means "declares nothing", which is what keeps
every existing install behaving exactly as it does today.

FATAL = True, unlike 111 next door. 111 creates a TABLE, and ``create_all``
(``app/database.py:144``) creates tables anyway on the ordinary boot path. That
reasoning does NOT transfer to an ADD COLUMN: ``create_all`` never ALTERs an
existing table. If this fails on an established database and startup continues,
the ORM maps the column and every SELECT against ``livelink_devices``
references one that does not exist, breaking device queries and all ingestion.
Every add-column migration in this repo is FATAL, including 096 next door,
which adds a column to this same table.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "livelink_devices"
_COLUMN = "odometer_param_key"


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the column when it is not already there."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table(_TABLE):
        print(f"  \u2192 {_TABLE} missing; skip (run the earlier migrations first)")
        return

    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        print(f"\u2713 {_TABLE}.{_COLUMN} already present")
        return

    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(100)"))
        print(f"\u2713 Added {_TABLE}.{_COLUMN}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 112 is forward-only.")


if __name__ == "__main__":
    upgrade()
