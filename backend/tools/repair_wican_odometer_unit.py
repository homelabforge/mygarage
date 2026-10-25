"""Repair a WiCAN odometer key that MyGarage read in the wrong unit.

Only the owner knows which unit a device's odometer autopid really reports, so
this never runs on its own. Two ways a WiCAN with no `odometer_unit` set gets
it wrong:

- ``--to km``: the key really reports km, but it was read as miles. That's a
  bare ``ODOMETER`` that main read as miles, kept by migration 133's legacy row
  so the records stayed comparable. Everything stored for it is 1.609x high.
- ``--to mi``: the key really reports miles, but it was read as km. That's a
  bare ``ODOMETER`` on 3.10, which follows upstream and reads it as km from the
  first frame. Everything stored for it is 1.609x low, and the unit change in
  Device settings answers 409 once there's history.

For one device and key it:

- points the key at the right unit in the per-device unit store. When the key
  rule already gives that unit and the row isn't the device's own config, the
  key's legacy row is dropped; otherwise a ``legacy`` row holds the unit, and
  a boot config that says otherwise (the same ``wire`` declaration coming
  back, say) can't flip it while there's history. The device-wide
  ``odometer_unit`` stays unset: it wins for every key, so it would read an
  ``A6-`` key 1.609x off;
- rescales what this device wrote on its current vehicle: its raw rows for
  the key there, the vehicle's latest value for it, the ``livelink`` odometer
  records written from it (their notes name the key) dated since the device
  started on the vehicle, and its sessions there. A session's distance moves
  too, but only when it was the odometer's delta, not a finer counter's.
  Odometer readings come out in whole km, as live ingest writes them.

It refuses, changing nothing, when there's nothing to repair (the key already
reads that unit, so a second run is a no-op) or when the repair can't be
scoped to one key: another device may have recorded the key on the vehicle
in that time (raw rows, or a link or a session with odometers, which don't
prune), the device has a second odometer key, or the key's history already
mixes units.
It also refuses before migration 133 has run, which would write its row after
this one and undo it, so run it on this version, after its first start.

Usage (dry run is the default; nothing is written without --apply):

    python tools/repair_wican_odometer_unit.py --device-id 7cdfa1b2c3d4 --to km
    python tools/repair_wican_odometer_unit.py --device-id 7cdfa1b2c3d4 --to km --apply

Back up the database first, through the backup API rather than `cp`, and run
it with MyGarage stopped or in maintenance mode (``MYGARAGE_MAINTENANCE_MODE=1``)
so no reading lands halfway through.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, create_engine, inspect, text

sys.path.insert(0, ".")

from app.utils.odometer_units import (  # noqa: E402
    ODOMETER_UNIT_KM,
    ODOMETER_UNIT_MI,
    WICAN_DEVICE_KIND,
    infer_odometer_unit,
    is_recorded_odometer_key,
    resolve_odometer_unit,
)
from app.utils.units import UnitConverter  # noqa: E402
from tools._tool_db import (  # noqa: E402
    as_date,
    legacy_migration_applied,
    mixed_units_step,
    resolve_sync_url,
)

#: A session's distance is the odometer's delta when it matches it this closely.
_DELTA_TOLERANCE_KM = 0.01

_BACKUP_WARNING = (
    "Back up first: Settings > Backup > Create Full Backup, or POST /api/backup/create-full "
    "as an admin. Never cp a live database."
)


class RepairRefusedError(Exception):
    """The repair can't be done safely, or there's nothing to repair."""


@dataclass(frozen=True)
class SessionChange:
    """One session's odometer fields, each as (old, new), or None when untouched."""

    id: int
    start: tuple[float, float] | None
    end: tuple[float, float] | None
    distance: tuple[float, float] | None


@dataclass
class RepairPlan:
    """Everything a repair would write, worked out before anything is."""

    device_id: str
    vin: str
    key: str
    to: str
    #: ("drop", None) to delete the key's row, ("hold", unit) for a legacy row.
    unit_action: tuple[str, str | None]
    #: Raw rows for the key, oldest first, as (old, new).
    raw: list[tuple[float, float]] = field(default_factory=list)
    raw_ids: list[int] = field(default_factory=list)
    latest: tuple[float, float] | None = None
    #: (record id, old, new)
    records: list[tuple[int, float, float]] = field(default_factory=list)
    sessions: list[SessionChange] = field(default_factory=list)


def _scale(value: float, to: str) -> Decimal:
    """``value`` moved to the right unit: deflated for km, inflated for mi."""
    exact = Decimal(str(value))
    if to == ODOMETER_UNIT_KM:
        return exact / UnitConverter.MILES_TO_KM
    return exact * UnitConverter.MILES_TO_KM


def _reading(value: float, to: str) -> float:
    """An odometer reading, rescaled and in whole km like live ingest stores it."""
    return float(_scale(value, to).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _as_datetime(value: object) -> datetime | None:
    """A DateTime column as the driver gave it back (SQLite text, PG datetime)."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value))


def _window_start(
    conn: Connection, device_id: str, vin: str, key: str, created_at: object
) -> datetime | None:
    """When this device reached this vehicle, by what survives pruning.

    A device has no link history, so its own rows say where it was: if it
    reported on another car (raw rows, or a drive session, which never prune),
    it reached this one after the last of those, not at its device-wide
    `created_at` (N3). Otherwise its `created_at`, or earlier when its rows or
    sessions on this VIN say so (a device deleted and re-discovered keeps its
    MAC id). A device that went back and forth can't be scoped, so it's refused.
    """
    here = [
        _as_datetime(
            conn.execute(
                text(
                    "SELECT MIN(timestamp) FROM vehicle_telemetry "
                    "WHERE device_id = :d AND vin = :v AND param_key = :k"
                ),
                {"d": device_id, "v": vin, "k": key},
            ).scalar()
        ),
        _as_datetime(
            conn.execute(
                text(
                    "SELECT MIN(started_at) FROM drive_sessions WHERE device_id = :d AND vin = :v"
                ),
                {"d": device_id, "v": vin},
            ).scalar()
        ),
    ]
    elsewhere = [
        _as_datetime(
            conn.execute(
                text(
                    "SELECT MAX(timestamp) FROM vehicle_telemetry WHERE device_id = :d AND vin <> :v"
                ),
                {"d": device_id, "v": vin},
            ).scalar()
        ),
        _as_datetime(
            conn.execute(
                text(
                    "SELECT MAX(started_at) FROM drive_sessions WHERE device_id = :d AND vin <> :v"
                ),
                {"d": device_id, "v": vin},
            ).scalar()
        ),
    ]
    first_here = min((at for at in here if at is not None), default=None)
    last_elsewhere = max((at for at in elsewhere if at is not None), default=None)
    if last_elsewhere is not None:
        if first_here is not None and last_elsewhere > first_here:
            raise RepairRefusedError(
                f"{device_id} reported on another vehicle after it started on this one, so "
                "which of this vehicle's records it wrote can't be told."
            )
        return last_elsewhere
    known = [at for at in (_as_datetime(created_at), first_here) if at is not None]
    return min(known) if known else None


def _refuse_unless_scoped(
    conn: Connection,
    device_id: str,
    vin: str,
    key: str,
    declared: str | None,
    since: datetime | None,
) -> None:
    """Refuse a repair that would rescale rows another key or device wrote.

    Another device is found by what doesn't prune as well as by raw rows: one
    linked to the vehicle, or with a drive session with odometers on it since
    this device started, that could record this key.
    """
    # SQLite holds these as text and its default datetime adapter is
    # deprecated, so bind the text form there.
    bound: object = since
    if since is not None and conn.dialect.name == "sqlite":
        bound = since.isoformat(sep=" ")
    since_sql = " AND timestamp >= :s" if since is not None else ""
    others = {
        row.device_id
        for row in conn.execute(
            text(
                "SELECT DISTINCT device_id FROM vehicle_telemetry "
                "WHERE vin = :v AND param_key = :k AND device_id <> :d" + since_sql
            ),
            {"v": vin, "k": key, "d": device_id, "s": bound},
        )
    }
    session_sql = " AND started_at >= :s" if since is not None else ""
    nearby = {
        row.device_id
        for row in conn.execute(
            text(
                "SELECT device_id FROM livelink_devices WHERE vin = :v AND device_id <> :d "
                "UNION SELECT device_id FROM drive_sessions WHERE vin = :v AND device_id <> :d "
                "AND (start_odometer IS NOT NULL OR end_odometer IS NOT NULL)" + session_sql
            ),
            {"v": vin, "d": device_id, "s": bound},
        )
    }
    on_file: set[str] = set()
    for row in conn.execute(
        text("SELECT device_id, kind, odometer_param_key FROM livelink_devices"),
    ):
        on_file.add(row.device_id)
        if row.device_id in nearby and is_recorded_odometer_key(
            key, row.kind, row.odometer_param_key
        ):
            others.add(row.device_id)
    # A deleted device's odometer sessions outlive it (no FK), and with no
    # kind on file it may have recorded anything (N3).
    others |= nearby - on_file
    if others:
        raise RepairRefusedError(
            f"{', '.join(sorted(others))} may also have recorded {key} on this vehicle while "
            "this device did. Its records and latest value are the vehicle's, so they can't "
            "be split between devices."
        )

    keys = {
        row.param_key
        for row in conn.execute(
            text(
                "SELECT DISTINCT param_key FROM vehicle_telemetry WHERE device_id = :d AND vin = :v"
            ),
            {"d": device_id, "v": vin},
        )
    }
    keys |= {
        row.param_key
        for row in conn.execute(
            text("SELECT param_key FROM vehicle_telemetry_latest WHERE vin = :v"), {"v": vin}
        )
    }
    second = sorted(
        k for k in keys if k != key and is_recorded_odometer_key(k, WICAN_DEVICE_KIND, declared)
    )
    if second:
        raise RepairRefusedError(
            f"this device also has odometer history under {', '.join(second)}, and a session's "
            "odometer may have come from either key, so which ones to rescale can't be told."
        )

    mixed = mixed_units_step(conn, device_id, key)
    if mixed:
        before, after = mixed
        raise RepairRefusedError(
            f"{key}'s history mixes units: it steps {before:,.0f} -> {after:,.0f}, a factor of "
            f"{max(before, after) / min(before, after):.3f}. Restore the backup from before the "
            "units changed and repair that."
        )


def plan_repair(conn: Connection, device_id: str, key: str, to: str) -> RepairPlan:
    """Work out the repair for ``key`` on ``device_id``, reading only.

    Raises:
        RepairRefusedError: With the reason, when the repair isn't safe or isn't needed.
    """
    if to not in (ODOMETER_UNIT_KM, ODOMETER_UNIT_MI):
        raise RepairRefusedError(f"--to must be km or mi, not {to!r}")
    device = conn.execute(
        text(
            "SELECT device_id, vin, kind, odometer_unit, odometer_param_key, created_at "
            "FROM livelink_devices WHERE device_id = :d"
        ),
        {"d": device_id},
    ).first()
    if device is None:
        raise RepairRefusedError(f"no device {device_id}")
    if device.kind != WICAN_DEVICE_KIND:
        raise RepairRefusedError(f"{device_id} is a {device.kind} device; this repairs WiCANs only")
    if device.odometer_unit:
        raise RepairRefusedError(
            f"{device_id} has odometer_unit={device.odometer_unit!r}, which wins for every key, "
            "so a per-key repair can't change how it reads. This tool repairs a device with no "
            "odometer_unit set."
        )
    if not device.vin:
        raise RepairRefusedError(f"{device_id} isn't linked to a vehicle")
    if not inspect(conn).has_table("livelink_device_units") or not legacy_migration_applied(conn):
        raise RepairRefusedError(
            "migration 133 hasn't run on this database, and it would write its own row for this "
            "key afterwards. Start this version once (MYGARAGE_MAINTENANCE_MODE=1 is fine), "
            "then run this."
        )
    key = key.upper()
    declared = device.odometer_param_key
    if not is_recorded_odometer_key(key, device.kind, declared):
        raise RepairRefusedError(f"{key} isn't this device's odometer")

    stored = conn.execute(
        text(
            "SELECT unit, source FROM livelink_device_units WHERE device_id = :d AND param_key = :k"
        ),
        {"d": device_id, "k": key},
    ).first()
    current = resolve_odometer_unit(key, None, WICAN_DEVICE_KIND, stored.unit if stored else None)
    if current == to:
        raise RepairRefusedError(f"nothing to repair: {device_id} / {key} already reads {to}")

    since = _window_start(conn, device_id, device.vin, key, device.created_at)
    _refuse_unless_scoped(conn, device_id, device.vin, key, declared, since)

    # A `wire` row is the device's own config, and its next boot declares it
    # again, so dropping it undoes the repair: hold the right unit instead,
    # which the legacy guard keeps against that declaration (I2).
    from_config = stored is not None and stored.source != "legacy"
    drop = infer_odometer_unit(key) == to and not from_config
    plan = RepairPlan(
        device_id=device_id,
        vin=device.vin,
        key=key,
        to=to,
        unit_action=("drop", None) if drop else ("hold", to),
    )
    # This vehicle's rows only: a car the device was on before keeps its own history.
    for row in conn.execute(
        text(
            "SELECT id, value FROM vehicle_telemetry "
            "WHERE device_id = :d AND vin = :v AND param_key = :k ORDER BY timestamp, id"
        ),
        {"d": device_id, "v": device.vin, "k": key},
    ):
        plan.raw.append((float(row.value), _reading(row.value, to)))
        plan.raw_ids.append(row.id)

    latest = conn.execute(
        text("SELECT value FROM vehicle_telemetry_latest WHERE vin = :v AND param_key = :k"),
        {"v": device.vin, "k": key},
    ).first()
    if latest is not None:
        plan.latest = (float(latest.value), _reading(latest.value, to))

    # Live ingest notes the key it recorded from, "... from LiveLink (KEY)". A
    # record names no device, so only those dated since this device started on
    # the vehicle are its: an earlier dongle's stay as they are (M1).
    for row in conn.execute(
        text(
            "SELECT id, odometer_km, notes, date FROM odometer_records "
            "WHERE vin = :v AND source = 'livelink' ORDER BY date, id"
        ),
        {"v": device.vin},
    ):
        if since is not None and as_date(row.date) < since.date():
            continue
        if (row.notes or "").endswith(f"({key})"):
            old = float(row.odometer_km)
            plan.records.append((row.id, old, _reading(old, to)))

    for row in conn.execute(
        text(
            "SELECT id, start_odometer, end_odometer, distance_km FROM drive_sessions "
            "WHERE device_id = :d AND vin = :v ORDER BY started_at, id"
        ),
        {"d": device_id, "v": device.vin},
    ):
        start, end, distance = row.start_odometer, row.end_odometer, row.distance_km
        if start is None and end is None:
            continue
        from_delta = (
            distance is not None
            and start is not None
            and end is not None
            and abs(distance - (end - start)) <= _DELTA_TOLERANCE_KM
        )
        plan.sessions.append(
            SessionChange(
                id=row.id,
                start=(float(start), _reading(start, to)) if start is not None else None,
                end=(float(end), _reading(end, to)) if end is not None else None,
                distance=(float(distance), float(_scale(distance, to))) if from_delta else None,
            )
        )
    return plan


def apply_repair(conn: Connection, plan: RepairPlan) -> None:
    """Write a plan from `plan_repair`. The caller owns the transaction."""
    conn.execute(
        text("DELETE FROM livelink_device_units WHERE device_id = :d AND param_key = :k"),
        {"d": plan.device_id, "k": plan.key},
    )
    action, unit = plan.unit_action
    if action == "hold":
        conn.execute(
            text(
                "INSERT INTO livelink_device_units "
                "(device_id, param_key, unit, param_class, source, created_at) "
                "VALUES (:d, :k, :u, 'distance', 'legacy', CURRENT_TIMESTAMP)"
            ),
            {"d": plan.device_id, "k": plan.key, "u": unit},
        )
    if plan.raw_ids:
        conn.execute(
            text("UPDATE vehicle_telemetry SET value = :new WHERE id = :id"),
            [{"id": i, "new": new} for i, (_old, new) in zip(plan.raw_ids, plan.raw, strict=True)],
        )
    if plan.latest is not None:
        conn.execute(
            text(
                "UPDATE vehicle_telemetry_latest SET value = :new WHERE vin = :v AND param_key = :k"
            ),
            {"new": plan.latest[1], "v": plan.vin, "k": plan.key},
        )
    if plan.records:
        conn.execute(
            text("UPDATE odometer_records SET odometer_km = :new WHERE id = :id"),
            [{"id": i, "new": new} for i, _old, new in plan.records],
        )
    for change in plan.sessions:
        values: dict[str, float] = {}
        if change.start is not None:
            values["start_odometer"] = change.start[1]
        if change.end is not None:
            values["end_odometer"] = change.end[1]
        if change.distance is not None:
            values["distance_km"] = change.distance[1]
        sets = ", ".join(f"{column} = :{column}" for column in values)
        conn.execute(
            text(f"UPDATE drive_sessions SET {sets} WHERE id = :id"),  # noqa: S608
            {**values, "id": change.id},
        )


def _report(plan: RepairPlan) -> None:
    """Print what the plan changes."""
    was = ODOMETER_UNIT_MI if plan.to == ODOMETER_UNIT_KM else ODOMETER_UNIT_KM
    print(f"\n{plan.device_id} / {plan.key}: read as {was}, really {plan.to}")
    action, unit = plan.unit_action
    if action == "drop":
        print(f"  unit store: drop the key's row ({plan.key} then reads {plan.to} by its key rule)")
    else:
        print(f"  unit store: hold {plan.key} in {unit} (a legacy row)")
    if plan.raw:
        (first_old, first_new), (last_old, last_new) = plan.raw[0], plan.raw[-1]
        print(
            f"  raw telemetry: {len(plan.raw):,} row(s), {first_old:,.0f} -> {first_new:,.0f} "
            f"... {last_old:,.0f} -> {last_new:,.0f} km"
        )
    if plan.latest is not None:
        print(f"  latest value: {plan.latest[0]:,.0f} -> {plan.latest[1]:,.0f} km")
    for record_id, old, new in plan.records:
        print(f"  odometer record {record_id}: {old:,.0f} -> {new:,.0f} km")
    if plan.sessions:
        moved = sum(1 for s in plan.sessions if s.distance is not None)
        print(
            f"  sessions: {len(plan.sessions)} with odometers, {moved} with a distance from "
            "the odometer that moves with them"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        help=(
            "Database to operate on: a path to mygarage.db, or a full SQLAlchemy URL "
            "(postgresql+asyncpg://...). Omit to use the instance's configured database, "
            "which is the right choice when running inside the container."
        ),
    )
    parser.add_argument("--device-id", required=True, help="The WiCAN to repair")
    parser.add_argument("--key", default="ODOMETER", help="The odometer key (default ODOMETER)")
    parser.add_argument(
        "--to",
        required=True,
        choices=(ODOMETER_UNIT_KM, ODOMETER_UNIT_MI),
        help="The unit the device really reports the key in",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the repair. Without this the script only reports.",
    )
    return parser.parse_args()


def main() -> int:
    """Plan, and with --apply write, one device's odometer unit repair."""
    args = _parse_args()
    print(_BACKUP_WARNING)
    engine = create_engine(resolve_sync_url(args.db))
    try:
        with engine.begin() as conn:
            try:
                plan = plan_repair(conn, args.device_id, args.key, args.to)
            except RepairRefusedError as refused:
                print(f"\n✗ Not repaired: {refused}")
                return 2
            _report(plan)
            if not args.apply:
                print("\nDRY RUN - nothing written. Re-run with --apply.")
                return 0
            apply_repair(conn, plan)
        print("\n✓ Repaired.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
