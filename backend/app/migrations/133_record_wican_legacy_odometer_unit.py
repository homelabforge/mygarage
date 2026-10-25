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

Keys, by the match main converted and recorded odometers with
(`odometer_units.is_converted_odometer_key`, which 3.10's store still uses): a
device's `odometer_param_key` replaces name matching, so a device that
declares one gets only that key (Fable FB-4). Every other device gets each key
the substring scan takes: `A6-` anything, or a name holding `ODOMETER`, `ODO`,
`MILEAGE`, `TOTAL_DISTANCE` or `DISTANCE_TOTAL`. So `ODOMETER_KM` and
`TOTAL_ODO` are covered too, not just the six exact names (fix round 1, I1).
That's main's history, fixed, so importing it is safe.

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

`ODOMETER_MI` is miles on every kind now, stored as km (Codex R1-M1), so the
rows main stored raw move to km too (FW-A1). Main converted it only on a
WiCAN that declares no other odometer key (its substring match), and on
Torque when it was the declared key. Everywhere else (a generic MQTT topic, a
WiCAN declaring another key) it went in raw. Those devices' raw rows convert
whenever the key now reads miles (no `odometer_unit`, or `mi`), in their live
path's rounding: whole km on a WiCAN, hundredths on the simple path. The
vehicle's shared rows (latest value, daily summaries) convert only when every
device that may have sent the key on that VIN is one of them: those with raw
rows for it, plus, since raw rows prune at 90 days, every device linked to
the VIN or with a drive session on it. Nothing else was ever
derived from the key: main's odometer and distance-counter sets left it out,
so no odometer record or session odometer came from it. A `legacy` `mi` row
for the key is written in the same transaction, so a re-run after a commit
the runner didn't stamp converts nothing twice.

The browser reads an odometer's unit from its parameter row, not its name
(FW-A-r3), and a row registered before FB-5 says nothing or mi over the km a
WiCAN stores. So each odometer key a WiCAN records gets `km` on its row when
the row says nothing or miles, unless a device has sent the key raw (another
kind that doesn't declare it, or a WiCAN that declares a different key): the
row is shared, and that device's values aren't km. Live ingest asks the same
question (`stores_odometer_key_raw`) on the next reading; this covers a car
that's parked.

FATAL: a failure must not boot with the km default under these devices. Data
only, idempotent (skips a key the device already has a row for), both
dialects. `livelink_device_units` comes from `create_all` (or migration 132)
first. Prod is a no-op: both WiCANs have a unit set.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text

from app.utils.odometer_units import (
    is_converted_odometer_key,
    is_recorded_odometer_key,
    mains_odometer_unit,
    stores_odometer_key_raw,
)

FATAL = True

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

#: FW-A1: the key that's miles on every kind now, and the factor.
_MI_KEY = "ODOMETER_MI"
_MILES_TO_KM = Decimal("1.609344")

_MI_DEVICES = (
    "SELECT d.device_id, d.vin, d.kind, d.odometer_unit, {declared} AS declared, {held} "
    "FROM livelink_devices d{join}"
)
_MI_JOIN = " LEFT JOIN livelink_device_units u ON u.device_id = d.device_id AND u.param_key = :k"
_MI_RAW = text("SELECT id, value FROM vehicle_telemetry WHERE device_id = :d AND param_key = :k")
_MI_VIN_REPORTERS = text(
    "SELECT DISTINCT device_id FROM vehicle_telemetry WHERE vin = :v AND param_key = :k"
)
_MI_VIN_LINKED = text("SELECT device_id FROM livelink_devices WHERE vin = :v")
_MI_VIN_DRIVEN = text("SELECT DISTINCT device_id FROM drive_sessions WHERE vin = :v")
_SET_RAW = text("UPDATE vehicle_telemetry SET value = :new WHERE id = :id")
_LATEST = text("SELECT id, value FROM vehicle_telemetry_latest WHERE vin = :v AND param_key = :k")
_SET_LATEST = text("UPDATE vehicle_telemetry_latest SET value = :new WHERE id = :id")
_SUMMARIES = text(
    "SELECT id, min_value, max_value, avg_value FROM telemetry_daily_summary "
    "WHERE vin = :v AND param_key = :k"
)
_SET_SUMMARY = text(
    "UPDATE telemetry_daily_summary SET min_value = :lo, max_value = :hi, avg_value = :avg "
    "WHERE id = :id"
)
_HOLD_MI = text(
    "UPDATE livelink_device_units SET unit = 'mi', param_class = 'distance', source = 'legacy' "
    "WHERE device_id = :d AND param_key = :k"
)

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
        wanted = {key for key in keys if is_converted_odometer_key(key, declared)}
        if declared and declared.upper() == _DECLARED_ALONE:
            wanted.add(_DECLARED_ALONE)
        if has_units:
            wanted -= {key for (key,) in conn.execute(_HELD, {"d": device_id})}
        found.extend((device_id, key, mains_odometer_unit(key)) for key in sorted(wanted))
    return found


def _main_converted_odometer_mi(kind: str | None, declared: str | None) -> bool:
    """Whether main stored a device's `ODOMETER_MI` in km already.

    A WiCAN's store path matched it by substring unless another key was
    declared; Torque's simple path converted only its declared key.
    """
    named = bool(declared) and declared.upper() == _MI_KEY
    if kind == "wican":
        return not declared or named
    return kind == "torque" and named


def _reads_odometer_mi_as_miles(kind: str | None, unit: str | None, held: str | None) -> bool:
    """Whether 3.10 reads the device's `ODOMETER_MI` as miles (and so stores km)."""
    if unit and unit.strip().lower() in ("km", "mi"):
        return unit.strip().lower() == "mi"
    if kind == "wican" and held and held.strip().lower() in ("km", "mi"):
        return held.strip().lower() == "mi"
    return True


def odometer_mi_devices(conn: Connection) -> dict[str, tuple[str | None, str | None]]:
    """The devices whose `ODOMETER_MI` main stored raw and 3.10 reads as miles.

    ``{device_id: (vin, kind)}``, whatever the migration has or hasn't done:
    the rule reads only the device. Public for the odometer tools, which leave
    these devices' `ODOMETER_MI` to this migration and never record from it
    (main didn't either).
    """
    inspector = inspect(conn)
    if not inspector.has_table("livelink_devices") or missing_device_columns(conn):
        return {}
    columns = {col["name"] for col in inspector.get_columns("livelink_devices")}
    declared_expr = "d.odometer_param_key" if "odometer_param_key" in columns else "NULL"
    # Before the first boot there may be no units table: nothing is held then.
    if inspector.has_table("livelink_device_units"):
        held_expr, join = "u.unit AS held, u.source AS held_source", _MI_JOIN
    else:
        held_expr, join = "NULL AS held, NULL AS held_source", ""
    query = _MI_DEVICES.format(declared=declared_expr, held=held_expr, join=join)
    found: dict[str, tuple[str | None, str | None]] = {}
    for row in conn.execute(text(query), {"k": _MI_KEY}):
        if _main_converted_odometer_mi(row.kind, row.declared):
            continue
        held = row.held if row.held_source != "legacy" else None
        if _reads_odometer_mi_as_miles(row.kind, row.odometer_unit, held):
            found[row.device_id] = (row.vin, row.kind)
    return found


def _to_km(value: float, *, whole: bool) -> float:
    """Miles to km by the live path's rule: hundredths, then whole km on a WiCAN."""
    km = float(round(Decimal(str(value)) * _MILES_TO_KM, 2))
    return float(round(km)) if whole else km


def _convert_odometer_mi(conn: Connection) -> int:
    """Move the `ODOMETER_MI` rows main stored raw to km. Returns devices converted."""
    inspector = inspect(conn)
    if not inspector.has_table("vehicle_telemetry"):
        return 0
    has_latest = inspector.has_table("vehicle_telemetry_latest")
    has_summary = inspector.has_table("telemetry_daily_summary")
    has_sessions = inspector.has_table("drive_sessions")
    devices = odometer_mi_devices(conn)
    held = {
        device_id
        for (device_id,) in conn.execute(
            text(
                "SELECT device_id FROM livelink_device_units "
                "WHERE param_key = :k AND source = 'legacy'"
            ),
            {"k": _MI_KEY},
        )
    }
    # A legacy row says this already ran on that device.
    pending = {d: info for d, info in devices.items() if d not in held}

    vins: set[str] = set()
    done: set[str] = set()
    for device_id, (vin, kind) in pending.items():
        rows = conn.execute(_MI_RAW, {"d": device_id, "k": _MI_KEY}).all()
        if rows:
            whole = kind == "wican"
            conn.execute(
                _SET_RAW,
                [{"id": r.id, "new": _to_km(r.value, whole=whole)} for r in rows],
            )
            done.add(device_id)
        if vin:
            vins.add(vin)

    for vin in sorted(vins):
        # Who may have sent it: raw rows prune, links and sessions don't (M2).
        candidates = {d for (d,) in conn.execute(_MI_VIN_REPORTERS, {"v": vin, "k": _MI_KEY})}
        candidates |= {d for (d,) in conn.execute(_MI_VIN_LINKED, {"v": vin})}
        if has_sessions:
            candidates |= {d for (d,) in conn.execute(_MI_VIN_DRIVEN, {"v": vin})}
        # Shared by every device on the VIN, so only when all of them sent it raw.
        if not candidates or not candidates <= pending.keys():
            continue
        whole = all(pending[d][1] == "wican" for d in candidates)
        shared = False
        if has_latest:
            for row in conn.execute(_LATEST, {"v": vin, "k": _MI_KEY}).all():
                conn.execute(_SET_LATEST, {"id": row.id, "new": _to_km(row.value, whole=whole)})
                shared = True
        if has_summary:
            for row in conn.execute(_SUMMARIES, {"v": vin, "k": _MI_KEY}).all():
                conn.execute(
                    _SET_SUMMARY,
                    {
                        "id": row.id,
                        "lo": None if row.min_value is None else _to_km(row.min_value, whole=False),
                        "hi": None if row.max_value is None else _to_km(row.max_value, whole=False),
                        "avg": None
                        if row.avg_value is None
                        else _to_km(row.avg_value, whole=False),
                    },
                )
                shared = True
        if shared:
            done |= candidates

    # The marker: each device whose rows moved, so a re-run leaves them be.
    for device_id in sorted(done):
        updated = conn.execute(_HOLD_MI, {"d": device_id, "k": _MI_KEY}).rowcount
        if not updated:
            conn.execute(_INSERT, {"d": device_id, "k": _MI_KEY, "u": "mi"})
    return len(done)


_ALL_DEVICES = "SELECT device_id, vin, kind, {declared} AS declared FROM livelink_devices"
_LABEL_KM = text(
    "UPDATE livelink_parameters SET unit = 'km' WHERE param_key = :k "
    "AND (unit IS NULL OR TRIM(unit) = '' OR LOWER(TRIM(unit)) IN ('mi', 'mile', 'miles'))"
)


_MAP_KEYS = text(
    "SELECT DISTINCT param_key FROM livelink_topic_maps "
    "WHERE device_id = :d AND param_key IS NOT NULL"
)
_NEXT_DEVICE = text("SELECT MIN(device_id) FROM vehicle_telemetry WHERE device_id > :p")
_OTHER_LINKED = text("SELECT 1 FROM livelink_devices WHERE vin = :v AND device_id <> :d LIMIT 1")
_OTHER_DROVE = text("SELECT 1 FROM drive_sessions WHERE vin = :v AND device_id <> :d LIMIT 1")


def _sole_reporter(conn: Connection, device_id: str, vin: str, has_sessions: bool) -> bool:
    """Whether no other device is linked to ``vin`` or has a drive on it.

    Only then are the vehicle's latest rows the device's own (wave B review M-4).
    """
    if conn.execute(_OTHER_LINKED, {"v": vin, "d": device_id}).first() is not None:
        return False
    return (
        not has_sessions or conn.execute(_OTHER_DROVE, {"v": vin, "d": device_id}).first() is None
    )


def _telemetry_device_ids(conn: Connection) -> set[str]:
    """Every device id the raw table holds rows for, one index seek per device."""
    found: set[str] = set()
    prev = ""
    while (device_id := conn.execute(_NEXT_DEVICE, {"p": prev}).scalar()) is not None:
        found.add(device_id)
        prev = device_id
    return found


def _label_odometer_params(conn: Connection) -> int:
    """Label km on the parameter rows of keys WiCANs store as km. Returns rows changed.

    Not a key another device may have sent raw (FW-A-r4b), and raw rows aren't
    the only evidence of that: they prune at 90 days, and a deleted device's
    stay behind under an id that isn't on file (wave A re-review T2). So a
    device's keys here are its raw ones, its topic maps' (generic MQTT), and,
    for a WiCAN, its vehicle's latest rows; and a gone device's raw keys count
    as raw. The vehicle's latest rows count against a WiCAN only when it's the
    only device that has reported on that vehicle (wave B review M-4): with
    company, they're as likely another device's. The live relabel
    (`TelemetryService._another_device_stores_raw`) asks the same.
    """
    inspector = inspect(conn)
    if not inspector.has_table("livelink_parameters") or missing_device_columns(conn):
        return 0
    columns = {col["name"] for col in inspector.get_columns("livelink_devices")}
    declared_expr = "odometer_param_key" if "odometer_param_key" in columns else "NULL"
    has_latest = inspector.has_table("vehicle_telemetry_latest")
    has_maps = inspector.has_table("livelink_topic_maps")
    has_sessions = inspector.has_table("drive_sessions")

    wanted: set[str] = set()
    raw_elsewhere: set[str] = set()
    on_file: set[str] = set()
    for device_id, vin, kind, declared in conn.execute(
        text(_ALL_DEVICES.format(declared=declared_expr))
    ):
        on_file.add(device_id)
        keys = _device_keys(conn, device_id)
        if has_maps:
            keys |= {key for (key,) in conn.execute(_MAP_KEYS, {"d": device_id})}
        vin_keys: set[str] = set()
        if kind == "wican" and vin and has_latest:
            vin_keys = {key for (key,) in conn.execute(_VIN_KEYS, {"v": vin})}
        # What this device stores raw, whatever its kind. The live relabel asks
        # the same question, so the two can't drift (FW-A-r4b).
        sent = (
            keys | vin_keys if vin and _sole_reporter(conn, device_id, vin, has_sessions) else keys
        )
        raw_elsewhere |= {key for key in sent if stores_odometer_key_raw(key, kind, declared)}
        if kind == "wican":
            wanted |= {
                key for key in keys | vin_keys if is_recorded_odometer_key(key, kind, declared)
            }
    for device_id in _telemetry_device_ids(conn) - on_file:
        raw_elsewhere |= {
            key for key in _device_keys(conn, device_id) if stores_odometer_key_raw(key, None)
        }
    changed = 0
    for key in sorted(wanted - raw_elsewhere):
        changed += conn.execute(_LABEL_KM, {"k": key}).rowcount or 0
    return changed


def upgrade(engine: Engine | None = None) -> None:
    """Keep main's reading of each WiCAN odometer key, and move raw ODOMETER_MI to km."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("livelink_device_units"):
        print("  → livelink_device_units missing; skip (nothing to record into)")
        return

    # One transaction: the legacy rows, the conversion and its markers land together.
    with engine.begin() as conn:
        converted = _convert_odometer_mi(conn)
        found = legacy_odometer_rows(conn)
        for device_id, key, unit in found:
            conn.execute(_INSERT, {"d": device_id, "k": key, "u": unit})
        labelled = _label_odometer_params(conn)

    if found:
        devices = len({device_id for device_id, _key, _unit in found})
        print(f"  ✓ Kept main's reading of {len(found)} odometer key(s) on {devices} WiCAN(s)")
    else:
        print("  → no unit-less WiCAN has odometer history; nothing to record")
    if converted:
        print(f"  ✓ Moved ODOMETER_MI from miles to km on {converted} device(s)")
    if labelled:
        print(f"  ✓ Labelled {labelled} odometer parameter(s) km")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 133 is forward-only.")


if __name__ == "__main__":
    upgrade()
