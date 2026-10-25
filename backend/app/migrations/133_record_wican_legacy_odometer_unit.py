"""Record main's reading of each WiCAN odometer key, so 3.10 reads them the same (D6a, R1-H1).

3.10 reads a bare `ODOMETER` as km, as upstream WiCAN defines it (N-1), and
honours a unit the device declares in its HTTPS config for every key (R12).
Main did neither: a PID key (`A6-ODOMETER`) read km and any bare key
(`ODOMETER`, `MILEAGE`, `ODO`, ...) read miles, whatever the config said. A
unit-less WiCAN's odometer records are in that scale, so reading a key any
other way now would put every new reading below its own floor (the monotonic
guard drops them silently) or past the jump guard.

For each such device and odometer key this inserts a `legacy` row in
`livelink_device_units` with main's unit, class `distance`. `DeviceUnitService`
keeps it against a conflicting declaration while the history stands. Nothing
else changes. `odometer_unit` is deliberately left alone: a device unit wins
for EVERY key, so stamping one would read the other keys wrong (Codex R1-H4).

Keys, by main's own matching: a device's `odometer_param_key` replaces name
matching, so a device that declares one gets only that key (Fable FB-4). Every
other device gets the odometer-named keys (`A6-ODOMETER`, `ODOMETER`,
`ODOMETER_MI`, `ODO`, `MILEAGE`, `TOTAL_DISTANCE`, `DISTANCE_TOTAL`, with any
PID prefix). `ODOMETER_MI` wasn't in main's set, but main's store path matched
it by substring and read it as miles too.

Evidence, per device and key, any of:

- a raw `vehicle_telemetry` row from the device under the key. The device's
  keys are walked with one `MIN(param_key) > :prev` probe per key, each a seek
  on `uq_telemetry_dedup`, not a scan of a multi-million-row table;
- a `vehicle_telemetry_latest` row for the key on its VIN, whenever it was
  written. That table is never pruned, so a car parked past the 90-day
  retention still counts (Fable F3-1), and a device deleted and re-discovered
  (same MAC id, new `created_at`) gets the reading its earlier self recorded
  under (Fable F5-5). Raw rows of OTHER keys don't override it: a re-discovered
  WiCAN sends COOLANT before it sends an odometer (Fable FB-2). It's keyed by
  VIN, so a second unit-less WiCAN on that VIN gets the row too, which is
  main's reading for it anyway. The bound by `created_at` lives in
  `device_has_odometer_history` (the 409), which still lets a replacement
  dongle change its unit;
- `odometer_param_key='ODOMETER'` on its own, for that key.

The cost (Fable F2-3): a key whose real unit isn't main's guess keeps being
read as on main until the owner runs `tools/repair_wican_odometer_unit.py`.

FATAL: a failure must not boot with the km default under these devices. Data
only, idempotent (skips a key the device already has a row for), both
dialects. `livelink_device_units` comes from `create_all` (or migration 132)
first. Prod is a no-op: both WiCANs have a unit set.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text

FATAL = True

# Inlined, like 096: a migration is a snapshot of intent, not the live rule.
_PID_PREFIX = re.compile(r"^[0-9A-F]{2}-")
_BARE_KEYS = frozenset(
    {"ODOMETER", "ODOMETER_MI", "ODO", "MILEAGE", "TOTAL_DISTANCE", "DISTANCE_TOTAL"}
)
#: The one key a declaration alone is evidence for (the plan's clause).
_DECLARED_ALONE = "ODOMETER"

#: Columns the device query can't do without. `odometer_param_key` (migration
#: 112) is optional: before it nothing was declared, which reads as NULL.
REQUIRED_DEVICE_COLUMNS = ("device_id", "vin", "kind", "odometer_unit")

_DEVICES = (
    "SELECT device_id, vin, {declared} AS declared FROM livelink_devices "
    "WHERE kind = 'wican' AND odometer_unit IS NULL"
)
_NEXT_KEY = text(
    "SELECT MIN(param_key) FROM vehicle_telemetry WHERE device_id = :d AND param_key > :p"
)
_VIN_KEYS = text("SELECT DISTINCT param_key FROM vehicle_telemetry_latest WHERE vin = :v")
_HELD = text("SELECT param_key FROM livelink_device_units WHERE device_id = :d")

_INSERT = text(
    "INSERT INTO livelink_device_units "
    "(device_id, param_key, unit, param_class, source, created_at) "
    "VALUES (:d, :k, :u, 'distance', 'legacy', CURRENT_TIMESTAMP)"
)


def _get_fallback_engine() -> Engine:
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _is_odometer(key: str, declared: str | None) -> bool:
    """Main's `is_odometer_param_key`: a declaration replaces the name match."""
    if declared:
        return key.upper() == declared.upper()
    return _PID_PREFIX.sub("", key.upper()) in _BARE_KEYS


def _mains_unit(key: str) -> str:
    """Main's reading of a unit-less WiCAN key: a PID is km, a bare key miles."""
    return "km" if _PID_PREFIX.match(key.upper()) else "mi"


def _device_keys(conn: Connection, device_id: str) -> set[str]:
    """Every key the device has raw rows under, one index seek per key."""
    keys: set[str] = set()
    prev = ""
    while (key := conn.execute(_NEXT_KEY, {"d": device_id, "p": prev}).scalar()) is not None:
        keys.add(key)
        prev = key
    return keys


def missing_device_columns(conn: Connection) -> list[str]:
    """The required `livelink_devices` columns this database lacks.

    Public for the odometer tools, which can run before the first boot on a
    database older than the migrations that added them.
    """
    inspector = inspect(conn)
    if not inspector.has_table("livelink_devices"):
        return []
    have = {col["name"] for col in inspector.get_columns("livelink_devices")}
    return [col for col in REQUIRED_DEVICE_COLUMNS if col not in have]


def legacy_odometer_rows(conn: Connection) -> list[tuple[str, str, str]]:
    """``(device_id, param_key, unit)`` for each key main read that 3.10 must keep.

    Public because the odometer repair tools call it when they run before the
    first boot, when this hasn't run and there may be no R12 table to read:
    they have to read those devices the way the first boot will.
    """
    inspector = inspect(conn)
    if not inspector.has_table("livelink_devices") or not inspector.has_table("vehicle_telemetry"):
        return []
    if missing_device_columns(conn):
        return []
    columns = {col["name"] for col in inspector.get_columns("livelink_devices")}
    declared_expr = "odometer_param_key" if "odometer_param_key" in columns else "NULL"
    has_units = inspector.has_table("livelink_device_units")
    has_latest = inspector.has_table("vehicle_telemetry_latest")

    found: list[tuple[str, str, str]] = []
    devices = conn.execute(text(_DEVICES.format(declared=declared_expr))).all()
    for device_id, vin, declared in devices:
        keys = _device_keys(conn, device_id)
        if vin and has_latest:
            keys |= {key for (key,) in conn.execute(_VIN_KEYS, {"v": vin})}
        wanted = {key for key in keys if _is_odometer(key, declared)}
        if declared and declared.upper() == _DECLARED_ALONE:
            wanted.add(_DECLARED_ALONE)
        if has_units:
            wanted -= {key for (key,) in conn.execute(_HELD, {"d": device_id})}
        found.extend((device_id, key, _mains_unit(key)) for key in sorted(wanted))
    return found


def upgrade(engine: Engine | None = None) -> None:
    """Insert a legacy row for each odometer key main read on a unit-less WiCAN."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("livelink_device_units"):
        print("  → livelink_device_units missing; skip (nothing to record into)")
        return

    with engine.begin() as conn:
        found = legacy_odometer_rows(conn)
        for device_id, key, unit in found:
            conn.execute(_INSERT, {"d": device_id, "k": key, "u": unit})

    if found:
        devices = len({device_id for device_id, _key, _unit in found})
        print(f"  ✓ Kept main's reading of {len(found)} odometer key(s) on {devices} WiCAN(s)")
    else:
        print("  → no unit-less WiCAN has odometer history; nothing to record")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 133 is forward-only.")


if __name__ == "__main__":
    upgrade()
