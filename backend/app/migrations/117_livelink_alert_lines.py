"""Add a critical alert line and a notify-once state to ``livelink_parameters``.

- ``critical_min``: an urgent line below the low one (``warning_min``). A
  propane tank warns at its low line and again at its critical one.
- ``alert_state``: the band a preset sensor's reading last notified. Those
  readings notify once per crossing, not every cooldown window, and re-arm
  when the value comes back clear of the line.
- ``alert_retry_at``: when such a reading may try again after a send that
  reached no service. Without it a tank below its line retried on every
  reading, and a notification service that is down stalls ingest while each
  send retries.

Mopeka sensors added before this release get the lines a new one starts with
(the preset's defaults): level low 25% and critical 10%, battery low 20%. Only
where no line is set, so one someone set through the API stays.

FATAL = True: the ORM maps these columns, so every parameter SELECT names them
and a silent skip would fail every LiveLink read and ingest.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "livelink_parameters"

#: (name, DDL); the timestamp's type is filled in per dialect.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("critical_min", "FLOAT"),
    ("alert_state", "VARCHAR(10)"),
    ("alert_retry_at", "{timestamp}"),
)

#: The Mopeka preset's key shape, `PROPANE_T{n}_{suffix}`, as of this release.
_KEY = re.compile(r"^PROPANE_T\d+_(LEVEL_PCT|SENSOR_BATT_PCT)$")

#: (warning_min, critical_min) by reading, the preset's defaults.
_DEFAULTS: dict[str, tuple[float, float | None]] = {
    "LEVEL_PCT": (25.0, 10.0),
    "SENSOR_BATT_PCT": (20.0, None),
}


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the columns, then give existing Mopeka readings their default lines."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table(_TABLE):
        print(f"  → {_TABLE} missing; skip (run the earlier migrations first)")
        return

    # DATETIME is SQLite-only; PostgreSQL spells it TIMESTAMP.
    timestamp = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    with engine.begin() as conn:
        for name, ddl in _COLUMNS:
            if name not in existing:
                conn.execute(
                    text(
                        f"ALTER TABLE {_TABLE} ADD COLUMN {name} {ddl.format(timestamp=timestamp)}"
                    )
                )
                print(f"✓ Added {_TABLE}.{name}")

        # Matched in Python: LIKE cannot say "digits only" between T and _.
        rows = conn.execute(
            text(
                f"SELECT id, param_key FROM {_TABLE} "
                "WHERE param_key LIKE 'PROPANE_T%' "
                "AND warning_min IS NULL AND critical_min IS NULL"
            )
        ).all()
        filled = 0
        for row_id, key in rows:
            match = _KEY.match(key or "")
            if not match:
                continue
            low, critical = _DEFAULTS[match.group(1)]
            conn.execute(
                text(
                    f"UPDATE {_TABLE} SET warning_min = :low, critical_min = :critical WHERE id = :id"
                ),
                {"low": low, "critical": critical, "id": row_id},
            )
            filled += 1
        print(f"✓ Default alert lines on {filled} Mopeka reading(s)")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 117 is forward-only.")


if __name__ == "__main__":
    upgrade()
