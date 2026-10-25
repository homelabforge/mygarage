"""Carry LiveLink notification switches over to the keys Settings writes.

Migration 034 seeded four ``notify_livelink_*`` keys, and the notification
dispatcher read those. The switches in Settings -> LiveLink have always written
``livelink_notify_*`` instead, so the dispatcher never saw them: switching
"Parameter threshold breaches" off did nothing. The dispatcher now reads the
``livelink_notify_*`` keys.

An install whose old key was switched off (only possible through the settings
API, since no screen wrote it) had that event silenced. Where the new key is
not set, this copies the "off" across so the event stays silent. A new key
already set is the switch someone actually used, and wins.

An old key counts as on for true, 1 or yes in any case, the dispatcher's words
when this shipped. #243's `parse_bool` also takes 'on' and strips spaces, but
prod has already run this, so it stays as written: an old key hand-set to 'on'
was carried across as off.

FATAL = False: skipped, an event switched off only through the old key starts
notifying again. Nothing fails, and the switch in Settings turns it back off.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = False

#: (old key, the key Settings -> LiveLink writes).
_KEYS: tuple[tuple[str, str], ...] = (
    ("notify_livelink_device_offline", "livelink_notify_device_offline"),
    ("notify_livelink_threshold_alerts", "livelink_notify_threshold_alerts"),
    ("notify_livelink_firmware_update", "livelink_notify_firmware_update"),
    ("notify_livelink_new_device", "livelink_notify_new_device"),
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _is_off(value: str | None) -> bool:
    """Off as the dispatcher read a switch when this shipped: set, and not true/1/yes."""
    return bool(value) and (value or "").lower() not in ("true", "1", "yes")


def upgrade(engine=None) -> None:
    """Copy each switched-off old key to its unset new key."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("settings"):
        print("  → settings missing; skip")
        return

    with engine.begin() as conn:

        def value(key: str) -> str | None:
            return conn.execute(
                text("SELECT value FROM settings WHERE key = :k"), {"k": key}
            ).scalar_one_or_none()

        carried = 0
        for old, new in _KEYS:
            if not _is_off(value(old)) or value(new):
                continue
            conn.execute(text("DELETE FROM settings WHERE key = :k"), {"k": new})
            conn.execute(
                text(
                    "INSERT INTO settings (key, value, category, encrypted) "
                    "VALUES (:k, 'false', 'livelink', FALSE)"
                ),
                {"k": new},
            )
            carried += 1
        print(f"✓ LiveLink notification switches carried over: {carried}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 118 is forward-only.")


if __name__ == "__main__":
    upgrade()
