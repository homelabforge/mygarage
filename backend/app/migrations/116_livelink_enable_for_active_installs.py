"""Switch LiveLink on for installs already receiving MQTT or Torque data.

Until now the "Enable LiveLink" master switch gated only the HTTPS ingest route
and the periodic jobs. The MQTT subscriber starts on `livelink_mqtt_enabled`
alone and the Torque route never read the switch, so both stored data with it
off. From this release the switch gates every ingest path. An install that
receives MQTT or Torque data today with the switch off would silently stop on
upgrade, so this turns it on for exactly those installs, once.

Evidence of an install receiving data, not merely configured for it:

- MQTT enabled with a broker host set, AND an enabled, linked non-Torque
  device (WiCAN, generic MQTT) that has reported at least once, or
- an enabled, linked Torque source that has uploaded at least once.

Both branches therefore mean the same thing: a device has actually delivered.

A fresh install (migration 034 seeds the switch 'false', and nothing else is
set) and a dormant Torque source that never uploaded stay as they are. Turning
the switch on also starts the periodic jobs (offline checks, daily summaries,
retention pruning, firmware checks) for those installs; that is what "LiveLink
on" has always meant.

Both switches count as on only when stored as exactly 'true'. That was how the
app read them when this shipped; #243's `parse_bool` later took true, 1, yes
and on in any case. Prod has already run this, so it stays as written: a
`livelink_mqtt_enabled` hand-set to 'on' counted as off here and didn't turn
LiveLink on.

FATAL = True: skipped, a working install's data stops with no error anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _setting(conn, key: str) -> str | None:
    return conn.execute(
        text("SELECT value FROM settings WHERE key = :k"), {"k": key}
    ).scalar_one_or_none()


def upgrade(engine=None) -> None:
    """Enable LiveLink where MQTT or Torque data is already flowing."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("settings"):
        print("  → settings missing; skip")
        return

    with engine.begin() as conn:
        # Exactly 'true', as is_enabled read it when this shipped (it uses
        # parse_bool since #243). See the docstring.
        if _setting(conn, "livelink_enabled") == "true":
            print("✓ LiveLink already enabled")
            return

        def delivered(kind_clause: str) -> bool:
            if not inspector.has_table("livelink_devices"):
                return False
            return (
                conn.execute(
                    text(
                        "SELECT 1 FROM livelink_devices "
                        f"WHERE {kind_clause} AND enabled = TRUE "
                        "AND vin IS NOT NULL AND last_seen IS NOT NULL LIMIT 1"
                    )
                ).first()
                is not None
            )

        mqtt_configured = _setting(conn, "livelink_mqtt_enabled") == "true" and bool(
            (_setting(conn, "livelink_mqtt_broker_host") or "").strip()
        )
        mqtt_live = mqtt_configured and delivered("kind <> 'torque'")
        torque_live = delivered("kind = 'torque'")

        if not (mqtt_live or torque_live):
            print("✓ No MQTT or Torque data flowing; LiveLink left as it is")
            return

        updated = conn.execute(
            text("UPDATE settings SET value = 'true' WHERE key = 'livelink_enabled'")
        ).rowcount
        if not updated:
            conn.execute(
                text(
                    "INSERT INTO settings (key, value, category, description, encrypted) "
                    "VALUES ('livelink_enabled', 'true', 'livelink', "
                    "'Enable LiveLink WiCAN telemetry integration', FALSE)"
                )
            )
        print(
            "✓ LiveLink enabled: it now gates MQTT and Torque, which were "
            f"already receiving data (mqtt={mqtt_live}, torque={torque_live})"
        )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 116 is forward-only.")


if __name__ == "__main__":
    upgrade()
