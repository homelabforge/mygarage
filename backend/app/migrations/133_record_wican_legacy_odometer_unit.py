"""Record main's miles reading of a WiCAN's bare ODOMETER, so 3.10 reads it the same (D6a).

3.10 reads a bare `ODOMETER` as km, as upstream WiCAN defines it (N-1). Main
guessed miles, so a WiCAN with no `odometer_unit` that already reported one
has odometer records in that scale, and reading it as km now would put every
new reading below its own floor (the monotonic guard drops them silently).
For each such device this inserts a `legacy` row in `livelink_device_units`:
`ODOMETER` in `mi`, class `distance`. Nothing else changes.

`odometer_unit` is deliberately left alone. A device unit wins for EVERY key,
so stamping 'mi' would read a standard `A6-ODOMETER` 1.609x low, and a device
with both keys keeps both scales this way (Codex R1-H4).

Evidence, per WiCAN with `odometer_unit IS NULL` and no row for the key yet:

- a raw `vehicle_telemetry` row with `param_key='ODOMETER'` (EXISTS, served by
  `uq_telemetry_dedup`, not a scan of a multi-million-row table);
- a `vehicle_telemetry_latest` `ODOMETER` row on its VIN with `timestamp >=`
  the device's `created_at`. That table is never pruned, so a car parked past
  the 90-day retention still counts (Fable F3-1). It's keyed by VIN, so a
  second unit-less WiCAN on that VIN gets the row too, which is main's reading
  for it anyway;
- `odometer_param_key='ODOMETER'`.

A device with no raw rows at all takes the VIN check unbounded (Fable F5-5):
one deleted and re-discovered (same MAC id, new `created_at`) whose VIN's last
bare `ODOMETER` predates it would otherwise land below the floor its earlier
self recorded. The bounded guard in `device_has_odometer_history` then still
lets the user change the unit.

The cost (Fable F2-3): a device whose bare `ODOMETER` really is km keeps being
read as miles, exactly as on main, until it's repaired by hand (B6-10).

FATAL: a failure must not boot with the km default under these devices. Data
only, idempotent (skips a device that already has the row), both dialects.
`livelink_device_units` comes from `create_all` (or migration 132) first.
Prod is a no-op: both WiCANs have a unit set.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text

FATAL = True

#: Inlined, like 096: a migration is a snapshot of intent, not the live rule.
_KEY = "ODOMETER"

#: The unit-less WiCANs, split by whether they declare ODOMETER as their key.
#: `{held}` drops the ones that already have a row, when the table exists.
_DEVICES = (
    "SELECT device_id, vin, created_at FROM livelink_devices "
    "WHERE kind = 'wican' AND odometer_unit IS NULL "
    "AND (odometer_param_key IS NULL OR UPPER(odometer_param_key) <> :k){held}"
)
_DECLARED = (
    "SELECT device_id FROM livelink_devices "
    "WHERE kind = 'wican' AND odometer_unit IS NULL AND UPPER(odometer_param_key) = :k{held}"
)
_NOT_HELD = (
    " AND NOT EXISTS (SELECT 1 FROM livelink_device_units u "
    "WHERE u.device_id = livelink_devices.device_id AND u.param_key = :k)"
)

_RAW_KEY = text("SELECT 1 FROM vehicle_telemetry WHERE device_id = :d AND param_key = :k LIMIT 1")
_RAW_ANY = text("SELECT 1 FROM vehicle_telemetry WHERE device_id = :d LIMIT 1")
_LATEST_SINCE = text(
    "SELECT 1 FROM vehicle_telemetry_latest "
    "WHERE vin = :v AND param_key = :k AND timestamp >= :since LIMIT 1"
)
_LATEST_ANY = text(
    "SELECT 1 FROM vehicle_telemetry_latest WHERE vin = :v AND param_key = :k LIMIT 1"
)

_INSERT = text(
    "INSERT INTO livelink_device_units "
    "(device_id, param_key, unit, param_class, source, created_at) "
    "VALUES (:d, :k, 'mi', 'distance', 'legacy', CURRENT_TIMESTAMP)"
)


def _get_fallback_engine() -> Engine:
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _reported(conn: Connection, device_id: str, vin: str | None, created_at: object) -> bool:
    """Whether the device has reported a bare ODOMETER, by the evidence above."""
    if conn.execute(_RAW_KEY, {"d": device_id, "k": _KEY}).first():
        return True
    if not vin:
        return False
    # No raw rows at all (re-discovered, or pruned), or no creation time to
    # bound by: any latest row on the VIN counts.
    if created_at is None or conn.execute(_RAW_ANY, {"d": device_id}).first() is None:
        return conn.execute(_LATEST_ANY, {"v": vin, "k": _KEY}).first() is not None
    since = {"v": vin, "k": _KEY, "since": created_at}
    return conn.execute(_LATEST_SINCE, since).first() is not None


def legacy_odometer_devices(conn: Connection) -> list[str]:
    """The WiCANs main read a bare ODOMETER on as miles, with no row for it yet.

    Public because the odometer repair tools call it when they run before the
    first boot, when this hasn't run and there's no R12 table to read: they
    have to read those devices the way the first boot will.
    """
    inspector = inspect(conn)
    if not inspector.has_table("livelink_devices") or not inspector.has_table("vehicle_telemetry"):
        return []
    held = _NOT_HELD if inspector.has_table("livelink_device_units") else ""
    has_latest = inspector.has_table("vehicle_telemetry_latest")

    found = [row.device_id for row in conn.execute(text(_DECLARED.format(held=held)), {"k": _KEY})]
    for row in conn.execute(text(_DEVICES.format(held=held)), {"k": _KEY}).all():
        if has_latest:
            reported = _reported(conn, row.device_id, row.vin, row.created_at)
        else:
            reported = conn.execute(_RAW_KEY, {"d": row.device_id, "k": _KEY}).first() is not None
        if reported:
            found.append(row.device_id)
    return found


def upgrade(engine: Engine | None = None) -> None:
    """Insert the legacy row for each WiCAN that main read a bare ODOMETER on."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("livelink_device_units"):
        print("  → livelink_device_units missing; skip (nothing to record into)")
        return

    with engine.begin() as conn:
        found = legacy_odometer_devices(conn)
        for device_id in found:
            conn.execute(_INSERT, {"d": device_id, "k": _KEY})

    if found:
        print(f"  ✓ Kept the miles reading of ODOMETER on {len(found)} WiCAN(s)")
    else:
        print("  → no unit-less WiCAN has reported a bare ODOMETER; nothing to record")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 133 is forward-only.")


if __name__ == "__main__":
    upgrade()
