"""Widen ``livelink_devices.kind`` from VARCHAR(10) to VARCHAR(20).

``generic_mqtt`` is twelve characters. SQLite ignores a declared VARCHAR
length so this is a no-op there, but Postgres enforces it and would reject
every generic-MQTT device insert.

FATAL = True. The ORM maps the column, and a silent skip on Postgres leaves a
release that cannot create the device type the release exists to add.

No DB-level CHECK on the value, matching the deliberate precedent for
``vehicles.vehicle_type`` (``app/models/vehicle.py:218``): the set of valid
kinds is owned by the source registry, which a database constraint cannot see.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Widen the column where the dialect enforces width.

    Signature matches migration 109: `runner.py:157` calls
    `module.upgrade(engine=self.engine)`. A `upgrade(conn)` form fails on the
    first run.
    """
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table("livelink_devices"):
        print("  → livelink_devices missing; skip (run the earlier migrations first)")
        return

    if engine.dialect.name != "postgresql":
        print("✓ SQLite does not enforce VARCHAR length; nothing to widen")
        return

    current = {c["name"]: c for c in inspector.get_columns("livelink_devices")}
    width = getattr(current["kind"]["type"], "length", None)
    if width is not None and width >= 20:
        print("✓ livelink_devices.kind already wide enough")
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE livelink_devices ALTER COLUMN kind TYPE VARCHAR(20)"))
        print("✓ Widened livelink_devices.kind to VARCHAR(20)")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 110 is forward-only.")


if __name__ == "__main__":
    upgrade()
