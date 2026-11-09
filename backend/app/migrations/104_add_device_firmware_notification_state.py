"""Add firmware notification state to ``livelink_devices``.

Two nullable columns for the daily 03:00 firmware check (notify once per
version + admin "skip this version"):

- ``firmware_notified_version`` — the latest release a notification was
  actually delivered for (at least one backend accepted the send).
- ``firmware_skipped_version`` — the release the admin chose to skip; the
  next release re-notifies.

FATAL for migration 099's reason: the LiveLinkDevice ORM maps both columns,
so every device SELECT includes them and a silent skip would 500 all
LiveLink reads after the model change.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("firmware_notified_version", "VARCHAR(20)"),
    ("firmware_skipped_version", "VARCHAR(20)"),
)


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
    if not inspector.has_table("livelink_devices"):
        return

    existing = {c["name"] for c in inspector.get_columns("livelink_devices")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    if not missing:
        print("✓ livelink_devices firmware notification state already present")
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE livelink_devices ADD COLUMN {name} {ddl}"))
            print(f"✓ Added livelink_devices.{name}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 104 is forward-only.")


if __name__ == "__main__":
    upgrade()
