"""Repair an odometer key that MyGarage read in the wrong unit.

Only the owner knows which unit a device's odometer really reports, so this
never runs on its own. Two ways a WiCAN with no `odometer_unit` set gets it
wrong:

- ``--to km``: the key really reports km, but it was read as miles. That's a
  bare ``ODOMETER`` that main read as miles, kept by migration 133's legacy row
  so the records stayed comparable. Everything stored for it is 1.609x high.
- ``--to mi``: the key really reports miles, but it was read as km. That's a
  bare ``ODOMETER`` on 3.10, which follows upstream and reads it as km from the
  first frame. Everything stored for it is 1.609x low, and the unit change in
  Device settings answers 409 once there's history.

And one way a Torque phone does (``--key TORQUE_ODOMETER --to km``): Torque
sends that total in km, but a phone declared with it and odometer unit ``mi``
stored every reading from that switch on 1.609x high. What it sent before,
undeclared, went in as km and is right.

For one device and key it:

- on a WiCAN, points the key at the right unit in the per-device unit store.
  When the key rule already gives that unit and the row isn't the device's own
  config, the key's legacy row is dropped; otherwise a ``legacy`` row holds the
  unit, and a boot config that says otherwise (the same ``wire`` declaration
  coming back, say) can't flip it while there's history. The device-wide
  ``odometer_unit`` stays unset: it wins for every key, so it would read an
  ``A6-`` key 1.609x off. On a Torque phone it clears ``odometer_unit``
  instead (auto, which reads TORQUE_ODOMETER as km);
- rescales what this device wrote on its current vehicle from a boundary B:
  its raw rows for the key there, the vehicle's latest value for it, the
  ``livelink`` odometer records written from it (their notes name the key),
  its sessions there, and the vehicle's daily summaries for the key. A
  session's distance moves too, but only when it was the odometer's delta,
  not a finer counter's. Readings keep their fraction, as ingest stores them;
  records are whole km. Summaries for days after B's are scaled; B's own day
  is rebuilt from its surviving raw rows when they're all there, and left
  alone and named otherwise (scaled instead on a WiCAN nothing else ever
  reported the key beside).

On a WiCAN, B is when the device reached the vehicle. On a Torque phone it's
the switch to ``mi``: the one step by the miles factor in the phone's rows
here, ``--switch-at`` when that can't be found, or, when the km rows are gone,
the first record ingest wrote under the declaration (dated on the server's
clock alone, so check the dry run's gap before applying).

It refuses, changing nothing, when there's nothing to repair (the key already
reads that unit, so a second run is a no-op) or when the repair can't be
scoped to one key: another device may have recorded the key on the vehicle
in that time (raw rows, or a link or a session with odometers, which don't
prune; on a Torque phone, any other phone on the car from the switch day on),
the device has a second odometer key, or, on a WiCAN, the key's history
already mixes units.
On a WiCAN it also refuses before migration 133 has run, which would write
its row after this one and undo it, so run it on this version, after its
first start.

Usage (dry run is the default; nothing is written without --apply):

    python tools/repair_wican_odometer_unit.py --device-id 7cdfa1b2c3d4 --to km
    python tools/repair_wican_odometer_unit.py --device-id 7cdfa1b2c3d4 --to km --apply
    python tools/repair_wican_odometer_unit.py --device-id <id> --key TORQUE_ODOMETER --to km

Back up the database first, through the backup API rather than `cp`, and run
it with MyGarage stopped or in maintenance mode (``MYGARAGE_MAINTENANCE_MODE=1``)
so no reading lands halfway through.
"""

from __future__ import annotations

import argparse
import sys
from bisect import bisect_left, bisect_right
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, inspect, text

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
    MIXED_STEP_HIGH,
    MIXED_STEP_LOW,
    as_date,
    create_tool_engine,
    legacy_migration_applied,
    mixed_units_step,
)

#: A session's distance is the odometer's delta when it matches it this closely.
_DELTA_TOLERANCE_KM = 0.01

#: The phone kind, and the total every Torque phone sends, in km (kff120c).
TORQUE_DEVICE_KIND = "torque"
TORQUE_ODOMETER_KEY = "TORQUE_ODOMETER"

#: A backfilled record can round up to a km past its day's top reading. One
#: converted twice sits 1.609x above it.
_RECORD_SLACK_KM = 1.0

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


#: A daily summary's (min, max, avg).
Aggregate = tuple[float | None, float | None, float | None]


@dataclass(frozen=True)
class SummaryChange:
    """One daily summary's values, old and new. `sample_count` never moves."""

    id: int
    day: date
    #: "scaled" for a day after B's, "rebuilt" for B's day from its raw rows.
    how: str
    old: Aggregate
    new: Aggregate


@dataclass(frozen=True)
class _Raw:
    """One raw row for the key on the vehicle, from any device."""

    id: int
    device_id: str
    value: float
    at: datetime


@dataclass(frozen=True)
class _Record:
    """A `livelink` odometer record naming the key."""

    id: int
    day: date
    created_at: datetime
    km: float
    notes: str


@dataclass
class RepairPlan:
    """Everything a repair would write, worked out before anything is."""

    device_id: str
    vin: str
    key: str
    to: str
    #: ("drop", None) to delete the key's row, ("hold", unit) for a legacy row,
    #: ("clear_device_unit", None) to put the device's odometer_unit back to auto.
    unit_action: tuple[str, str | None]
    #: Raw rows for the key, oldest first, as (old, new).
    raw: list[tuple[float, float]] = field(default_factory=list)
    raw_ids: list[int] = field(default_factory=list)
    latest: tuple[float, float] | None = None
    #: (record id, old, new)
    records: list[tuple[int, float, float]] = field(default_factory=list)
    sessions: list[SessionChange] = field(default_factory=list)
    #: B, where the wrong history starts: a WiCAN's window start, a phone's
    #: switch to mi. None when nothing bounds it.
    boundary: datetime | None = None
    #: How B was found, for the report.
    boundary_source: str = ""
    summaries: list[SummaryChange] = field(default_factory=list)
    #: B's day, when its summary can be neither rebuilt nor safely scaled.
    summaries_left: list[date] = field(default_factory=list)
    #: Sessions kept whole because no rows survive to say which side of B they
    #: read, as (id, started_at, ended_at).
    sessions_kept: list[tuple[int, datetime, datetime | None]] = field(default_factory=list)
    #: Backfilled records still above their day's readings after the scale.
    flagged_records: list[int] = field(default_factory=list)
    #: The latest value, when it predates B and so stays: (value, timestamp).
    stale_latest: tuple[float, datetime] | None = None
    #: Report lines on how B was placed.
    context: list[str] = field(default_factory=list)


def _scale(value: float, to: str) -> Decimal:
    """``value`` moved to the right unit: deflated for km, inflated for mi."""
    exact = Decimal(str(value))
    if to == ODOMETER_UNIT_KM:
        return exact / UnitConverter.MILES_TO_KM
    return exact * UnitConverter.MILES_TO_KM


def _reading(value: float, to: str) -> float:
    """A raw, latest or session reading, rescaled with its fraction, as ingest stores it."""
    return float(_scale(value, to))


def _record_km(value: float, to: str) -> float:
    """An odometer record, rescaled to whole km the way ingest's ``int(round(...))`` does."""
    return float(round(float(_scale(value, to))))


def _as_datetime(value: object) -> datetime | None:
    """A DateTime column as the driver gave it back (SQLite text, PG datetime)."""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(str(value))


def _at(value: object) -> datetime:
    """A NOT NULL DateTime column, as a datetime."""
    at = _as_datetime(value)
    if at is None:
        raise ValueError("expected a timestamp, got null")
    return at


def _bind(conn: Connection, at: datetime | None) -> object:
    """``at`` as a bind value.

    SQLite holds these as text and its default datetime adapter is
    deprecated, so bind the text form there.
    """
    if at is not None and conn.dialect.name == "sqlite":
        return at.isoformat(sep=" ")
    return at


def _fmt(at: datetime) -> str:
    """A timestamp for the report."""
    return at.isoformat(sep=" ", timespec="seconds")


def _raw_rows(conn: Connection, vin: str, key: str) -> list[_Raw]:
    """Every raw row for ``key`` on the vehicle, any device, oldest first."""
    return [
        _Raw(row.id, row.device_id, float(row.value), _at(row.timestamp))
        for row in conn.execute(
            text(
                "SELECT id, device_id, value, timestamp FROM vehicle_telemetry "
                "WHERE vin = :v AND param_key = :k ORDER BY timestamp, id"
            ),
            {"v": vin, "k": key},
        )
    ]


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
    *,
    torque_ignore: frozenset[str] | None = None,
) -> None:
    """Refuse a repair that would rescale rows another key or device wrote.

    Another device is found by what doesn't prune as well as by raw rows: one
    linked to the vehicle, or with a drive session with odometers on it since
    ``since``, that could record this key. ``torque_ignore`` (a set, even
    empty) switches to the Torque phone's rules: any other phone counts, and
    a deleted id only by Torque evidence, less the ids the owner vouched for.
    """
    bound = _bind(conn, since)
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
    if torque_ignore is None:
        # A deleted device's odometer sessions outlive it (no FK), and with no
        # kind on file it may have recorded anything (N3).
        others |= nearby - on_file
        if others:
            raise RepairRefusedError(
                f"{', '.join(sorted(others))} may also have recorded {key} on this vehicle while "
                "this device did. Its records and latest value are the vehicle's, so they can't "
                "be split between devices."
            )
    else:
        others |= _torque_senders(conn, device_id, vin, since, on_file)
        others -= torque_ignore
        if others:
            raise _other_phones_refused(conn, vin, key, since, sorted(others), on_file)

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


def _torque_senders(
    conn: Connection, device_id: str, vin: str, since: datetime | None, on_file: set[str]
) -> set[str]:
    """Other phones that may have sent TORQUE_ODOMETER here from ``since`` on (F3-1).

    Every Torque phone sends it, declared or not, and the latest value and
    summaries take it from any device on the VIN. A WiCAN never sends it, so
    one beside the phone doesn't count (F4-1). A deleted id counts by a Torque
    session id, which WiCAN sessions never carry (F5-3); raw rows of the key
    are the shared check's, whoever sent them.
    """
    window = " AND (started_at >= :s OR ended_at >= :s)" if since is not None else ""
    params = {"v": vin, "d": device_id, "t": TORQUE_DEVICE_KIND, "s": _bind(conn, since)}
    phones = {
        row.device_id
        for row in conn.execute(
            text(
                "SELECT device_id FROM livelink_devices "
                "WHERE vin = :v AND kind = :t AND device_id <> :d"
            ),
            params,
        )
    }
    phones |= {
        row.device_id
        for row in conn.execute(
            text(
                "SELECT DISTINCT device_id FROM drive_sessions WHERE vin = :v AND device_id <> :d "
                "AND device_id IN (SELECT device_id FROM livelink_devices WHERE kind = :t)" + window
            ),
            params,
        )
    }
    ghosts = {
        row.device_id
        for row in conn.execute(
            text(
                "SELECT DISTINCT device_id FROM drive_sessions WHERE vin = :v AND device_id <> :d "
                "AND external_session_id IS NOT NULL" + window
            ),
            params,
        )
    }
    return phones | (ghosts - on_file)


def _other_phones_refused(
    conn: Connection,
    vin: str,
    key: str,
    since: datetime | None,
    others: list[str],
    on_file: set[str],
) -> RepairRefusedError:
    """The refusal naming the other senders, with what the owner can do about each."""
    parts: list[str] = []
    phones = [d for d in others if d in on_file]
    if phones:
        day = since.date().isoformat() if since is not None else "the start"
        parts.append(
            f"{', '.join(phones)} may also have sent {key} on this vehicle from {day} on, and "
            "the latest value, summaries and records take it from any device, so they can't be "
            "split. A phone that no longer drives this car can be unlinked first."
        )
    for ghost in (d for d in others if d not in on_file):
        parts.append(
            f"{ghost}, no longer on file, sent {key} or a Torque session here on "
            f"{_first_seen(conn, ghost, vin, key, since)}. A re-added phone gets a new id, so "
            f"if that was this phone, pass --ignore-device {ghost}."
        )
    return RepairRefusedError(" ".join(parts))


def _first_seen(
    conn: Connection, device_id: str, vin: str, key: str, since: datetime | None
) -> str:
    """The first day from ``since`` on that ``device_id`` left Torque evidence here."""
    bound = _bind(conn, since)
    raw_sql = " AND timestamp >= :s" if since is not None else ""
    window = " AND (started_at >= :s OR ended_at >= :s)" if since is not None else ""
    params = {"d": device_id, "v": vin, "k": key, "s": bound}
    seen = [
        _as_datetime(
            conn.execute(
                text(
                    "SELECT MIN(timestamp) FROM vehicle_telemetry "
                    "WHERE device_id = :d AND vin = :v AND param_key = :k" + raw_sql
                ),
                params,
            ).scalar()
        ),
        _as_datetime(
            conn.execute(
                text(
                    "SELECT MIN(started_at) FROM drive_sessions WHERE device_id = :d AND vin = :v "
                    "AND external_session_id IS NOT NULL" + window
                ),
                params,
            ).scalar()
        ),
    ]
    first = min((at for at in seen if at is not None), default=since)
    if first is None:
        return "an unknown day"
    if since is not None:
        first = max(first, since)
    return first.date().isoformat()


def _no_other_trace(conn: Connection, device_id: str, vin: str, key: str) -> bool:
    """Whether nothing but this device ever left a trace of ``key`` on the vehicle.

    The scope guard's evidence (a link, an odometer session, a raw row of the
    key) over all time. Then a pruned day's summary is all this device's.
    """
    found = conn.execute(
        text(
            "SELECT device_id FROM livelink_devices WHERE vin = :v AND device_id <> :d "
            "UNION SELECT device_id FROM drive_sessions WHERE vin = :v AND device_id <> :d "
            "AND (start_odometer IS NOT NULL OR end_odometer IS NOT NULL) "
            "UNION SELECT device_id FROM vehicle_telemetry "
            "WHERE vin = :v AND param_key = :k AND device_id <> :d"
        ),
        {"v": vin, "d": device_id, "k": key},
    ).first()
    return found is None


def _plan_summaries(
    conn: Connection, plan: RepairPlan, rows: list[_Raw], *, pruned_day_scales: bool
) -> None:
    """The vehicle's daily summaries for the key, from B (R1-M2, R2-M2).

    A summary holds the vehicle's whole day, any device, and outlives the raw
    rows. Days after B's are scaled (min, max and avg scale linearly). B's own
    day can hold readings from before B, so it's rebuilt from its raw rows
    when all of them survive, scaling only those this repair scales.
    Otherwise it's scaled when ``pruned_day_scales`` says it's all this
    device's, and left alone and reported when not.
    """
    scaled = dict(zip(plan.raw_ids, (new for _old, new in plan.raw), strict=True))
    b_day = plan.boundary.date() if plan.boundary is not None else None
    for row in conn.execute(
        text(
            "SELECT id, date, min_value, max_value, avg_value, sample_count "
            "FROM telemetry_daily_summary WHERE vin = :v AND param_key = :k ORDER BY date, id"
        ),
        {"v": plan.vin, "k": plan.key},
    ):
        day = _at(row.date).date()
        if b_day is not None and day < b_day:
            continue
        old: Aggregate = (
            _maybe_float(row.min_value),
            _maybe_float(row.max_value),
            _maybe_float(row.avg_value),
        )
        values = (
            [Decimal(str(scaled.get(r.id, r.value))) for r in rows if r.at.date() == day]
            if day == b_day
            else []
        )
        if day == b_day and row.sample_count and len(values) == row.sample_count:
            mean = sum(values, Decimal(0)) / len(values)
            new: Aggregate = (float(min(values)), float(max(values)), float(mean))
            plan.summaries.append(SummaryChange(row.id, day, "rebuilt", old, new))
        elif day != b_day or pruned_day_scales:
            lo, hi, avg = (None if v is None else _reading(v, plan.to) for v in old)
            plan.summaries.append(SummaryChange(row.id, day, "scaled", old, (lo, hi, avg)))
        else:
            plan.summaries_left.append(day)


def _maybe_float(value: Any) -> float | None:
    """A nullable numeric column as a float."""
    return None if value is None else float(value)


def plan_repair(
    conn: Connection,
    device_id: str,
    key: str,
    to: str,
    *,
    switch_at: datetime | None = None,
    ignore_devices: Collection[str] = (),
) -> RepairPlan:
    """Work out the repair for ``key`` on ``device_id``, reading only.

    Args:
        conn: The connection to read through.
        device_id: The WiCAN or Torque phone.
        key: The odometer key.
        to: The unit the device really reports it in.
        switch_at: Torque only: when the phone was set to mi (naive UTC).
        ignore_devices: Torque only: deleted ids that were this same phone.

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
    key = key.upper()
    if device.kind == TORQUE_DEVICE_KIND:
        return _plan_torque(conn, device, key, to, switch_at, frozenset(ignore_devices))
    if device.kind != WICAN_DEVICE_KIND:
        raise RepairRefusedError(
            f"{device_id} is a {device.kind} device; this repairs WiCANs and Torque phones only"
        )
    if switch_at is not None or ignore_devices:
        raise RepairRefusedError("--switch-at and --ignore-device are for a Torque phone")
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
    # A phone's step is its switch to mi, so this one is the WiCAN's alone (F3-3).
    mixed = mixed_units_step(conn, device_id, key)
    if mixed:
        before, after = mixed
        raise RepairRefusedError(
            f"{key}'s history mixes units: it steps {before:,.0f} -> {after:,.0f}, a factor of "
            f"{max(before, after) / min(before, after):.3f}. Restore the backup from before the "
            "units changed and repair that."
        )

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
        boundary=since,
        boundary_source="when the device reached this vehicle",
    )
    # This vehicle's rows only: a car the device was on before keeps its own history.
    rows = _raw_rows(conn, device.vin, key)
    for row in rows:
        if row.device_id == device_id:
            plan.raw.append((row.value, _reading(row.value, to)))
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
            plan.records.append((row.id, old, _record_km(old, to)))

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
        plan.sessions.append(
            SessionChange(
                id=row.id,
                start=(float(start), _reading(start, to)) if start is not None else None,
                end=(float(end), _reading(end, to)) if end is not None else None,
                distance=(
                    (float(distance), float(_scale(distance, to)))
                    if _from_delta(start, end, distance)
                    else None
                ),
            )
        )

    _plan_summaries(
        conn, plan, rows, pruned_day_scales=_no_other_trace(conn, device_id, device.vin, key)
    )
    return plan


def _from_delta(start: Any, end: Any, distance: Any) -> bool:
    """Whether a session's distance was its odometer delta, not a finer counter's."""
    return (
        distance is not None
        and start is not None
        and end is not None
        and abs(distance - (end - start)) <= _DELTA_TOLERANCE_KM
    )


def _plan_torque(
    conn: Connection,
    device: Any,
    key: str,
    to: str,
    switch_at: datetime | None,
    ignore: frozenset[str],
) -> RepairPlan:
    """A Torque phone that stored TORQUE_ODOMETER as miles since the owner set mi (R10)."""
    device_id = device.device_id
    if key != TORQUE_ODOMETER_KEY:
        raise RepairRefusedError(
            f"{device_id} is a Torque phone; this repairs its {TORQUE_ODOMETER_KEY} only. A "
            "custom PID reads in the unit the device is set to, which is the owner's call."
        )
    if to != ODOMETER_UNIT_KM:
        raise RepairRefusedError(f"Torque sends {key} in km, so the repair is --to km")
    if (device.odometer_param_key or "").upper() != key:
        raise RepairRefusedError(
            f"nothing to repair: {key} isn't {device_id}'s declared odometer, so its readings "
            "went in as sent, in km"
        )
    if device.odometer_unit != ODOMETER_UNIT_MI:
        raise RepairRefusedError(
            f"nothing to repair: {device_id} reads {key} as km "
            f"(odometer_unit={device.odometer_unit or 'auto'})"
        )
    if not device.vin:
        raise RepairRefusedError(f"{device_id} isn't linked to a vehicle")
    on_file = set(conn.execute(text("SELECT device_id FROM livelink_devices")).scalars())
    listed = sorted(ignore & on_file)
    if listed:
        raise RepairRefusedError(
            f"--ignore-device {', '.join(listed)}: still on file. It's for a deleted phone's old "
            "id; unlink a phone that no longer drives this car instead."
        )

    vin = device.vin
    since = _window_start(conn, device_id, vin, key, device.created_at)
    rows = _raw_rows(conn, vin, key)
    mine = [r for r in rows if r.device_id == device_id]
    records = _torque_records(conn, vin, key, since)
    plan = RepairPlan(
        device_id=device_id, vin=vin, key=key, to=to, unit_action=("clear_device_unit", None)
    )
    series = [r for r in mine if since is None or r.at >= since]
    boundary, from_record = _place_switch(plan, series, records, since, switch_at)
    plan.boundary = boundary
    # Bound at B's day, not the window start: a second phone that left before
    # the switch day doesn't block (F4-3).
    _refuse_unless_scoped(
        conn,
        device_id,
        vin,
        key,
        key,
        datetime.combine(boundary.date(), time()),
        torque_ignore=ignore,
    )

    for row in mine:
        if row.at >= boundary:
            plan.raw.append((row.value, _reading(row.value, to)))
            plan.raw_ids.append(row.id)

    # Ingest upserts latest for every reading, so it's at or after the last
    # raw row. One before B wasn't left by ingest: name it, don't touch it.
    latest = conn.execute(
        text(
            "SELECT value, timestamp FROM vehicle_telemetry_latest WHERE vin = :v AND param_key = :k"
        ),
        {"v": vin, "k": key},
    ).first()
    if latest is not None:
        at = _at(latest.timestamp)
        if at >= boundary:
            plan.latest = (float(latest.value), _reading(latest.value, to))
        else:
            plan.stale_latest = (float(latest.value), at)

    # Ingest writes this key's records only under the declaration, so all of
    # them are inflated. Backfill converts with the device's mi too, so one
    # built from a post-switch row was converted twice and stays high (F3-5).
    scaled = dict(zip(plan.raw_ids, (new for _old, new in plan.raw), strict=True))
    day_top: dict[date, float] = {}
    for r in rows:
        value = scaled.get(r.id, r.value)
        day_top[r.at.date()] = max(day_top.get(r.at.date(), value), value)
    for record in records:
        new = _record_km(record.km, to)
        plan.records.append((record.id, record.km, new))
        top = day_top.get(record.day)
        if (
            record.notes.startswith("Backfilled")
            and top is not None
            and new > top + _RECORD_SLACK_KM
        ):
            plan.flagged_records.append(record.id)

    _plan_torque_sessions(conn, plan, mine, boundary, from_record)
    _plan_summaries(conn, plan, rows, pruned_day_scales=False)
    return plan


def _torque_records(conn: Connection, vin: str, key: str, since: datetime | None) -> list[_Record]:
    """The vehicle's `livelink` records naming ``key``, written since ``since``, oldest first.

    By `created_at`, not `date`: a re-added phone's new id would otherwise take
    the old id's record dated the re-add day (F2-5).
    """
    found: list[_Record] = []
    for row in conn.execute(
        text(
            "SELECT id, date, created_at, odometer_km, notes FROM odometer_records "
            "WHERE vin = :v AND source = 'livelink'"
        ),
        {"v": vin},
    ):
        notes = row.notes or ""
        created = _as_datetime(row.created_at)
        if not notes.endswith(f"({key})") or created is None:
            continue
        if since is not None and created < since:
            continue
        found.append(_Record(row.id, as_date(row.date), created, float(row.odometer_km), notes))
    return sorted(found, key=lambda r: (r.created_at, r.id))


def _steps(series: list[_Raw]) -> list[tuple[int, bool]]:
    """Each in-band step in ``series``, as (index of the row after it, upward)."""
    found: list[tuple[int, bool]] = []
    for i in range(1, len(series)):
        prev, value = series[i - 1].value, series[i].value
        if prev <= 0 or value <= 0:
            continue
        if MIXED_STEP_LOW <= value / prev <= MIXED_STEP_HIGH:
            found.append((i, True))
        elif MIXED_STEP_LOW <= prev / value <= MIXED_STEP_HIGH:
            found.append((i, False))
    return found


def _step_text(series: list[_Raw], i: int) -> str:
    """A step for the report: the readings either side, the ratio and when."""
    prev, row = series[i - 1], series[i]
    return (
        f"{prev.value:,.0f} -> {row.value:,.0f} (x{row.value / prev.value:.3f}) at {_fmt(row.at)}"
    )


def _place_switch(
    plan: RepairPlan,
    series: list[_Raw],
    records: list[_Record],
    since: datetime | None,
    switch_at: datetime | None,
) -> tuple[datetime, bool]:
    """When the phone's readings turned to miles, and whether a record said so (F2-1).

    Placed only on positive evidence: ``--switch-at``, exactly one upward step
    by the miles factor, or, with no step, the first record ingest wrote under
    the declaration when it predates every surviving row. A profile correction
    at the switch can push the step out of band, so no step proves nothing.
    """
    steps = _steps(series)
    if switch_at is not None:
        if since is not None and switch_at < since:
            raise RepairRefusedError(
                f"--switch-at {_fmt(switch_at)} is before {plan.device_id} reached this vehicle "
                f"({_fmt(since)})"
            )
        # Past the last reading there's nothing left to tell the switch by.
        latest = series[-1].at if series else datetime.now(UTC).replace(tzinfo=None)
        if switch_at > latest:
            what = "the latest surviving reading" if series else "now"
            raise RepairRefusedError(
                f"--switch-at {_fmt(switch_at)} is after {what} ({_fmt(latest)})"
            )
        plan.boundary_source = "--switch-at"
        if not (len(steps) == 1 and steps[0][1] and series[steps[0][0]].at == switch_at):
            plan.context += [
                f"  step detection disagrees: {_step_text(series, i)} ({'up' if up else 'down'})"
                for i, up in steps
            ]
        _around(plan, series, switch_at)
        return switch_at, False
    if not series:
        raise RepairRefusedError(
            f"{plan.device_id} has no surviving {plan.key} rows on this vehicle, so the switch to "
            "mi can't be placed or checked; pass --switch-at with when the unit was set"
        )
    if len(steps) == 1 and steps[0][1]:
        i = steps[0][0]
        plan.boundary_source = f"the step {_step_text(series, i)}"
        _around(plan, series, series[i].at)
        return series[i].at, False
    if steps:
        # A phone that flushes its queue after the switch stores inflated
        # readings under pre-switch times (F2-4).
        raise RepairRefusedError(
            f"{plan.key} steps by the miles factor more than once or downward "
            f"({'; '.join(_step_text(series, i) for i, _up in steps)}), so no single switch "
            "exists; pass --switch-at with when the unit was set"
        )
    # Either form: the next frame rewrites Auto-recorded to Auto-updated and
    # keeps created_at. The declaration guard refuses the key change over any
    # livelink record on the VIN, so this one is post-switch (F5-1).
    first = next((r for r in records if r.notes.startswith("Auto-")), None)
    earliest = series[0]
    if first is not None and first.created_at <= earliest.at:
        plan.boundary_source = f"record {first.id}'s created_at (no step survives)"
        plan.context += [
            f"  first record {first.id}: dated {first.day}, created {_fmt(first.created_at)}, "
            f"{first.km:,.0f} km",
            f"  earliest surviving raw row: {_fmt(earliest.at)}, {earliest.value:,.0f}",
            f"  gap: {earliest.at - first.created_at}. The days between are scaled on the "
            "record's server timestamp alone.",
        ]
        return first.created_at, True
    raise RepairRefusedError(
        "the switch to mi can't be placed from what survives; pass --switch-at with when the "
        "unit was set (the dry run shows the readings on each side)"
    )


def _around(plan: RepairPlan, series: list[_Raw], at: datetime) -> None:
    """The three rows each side of B and the ratio across it, for the owner to check."""
    before = [r for r in series if r.at < at][-3:]
    after = [r for r in series if r.at >= at][:3]
    plan.context += [f"    before: {_fmt(r.at)}  {r.value:,.0f}" for r in before]
    plan.context += [f"    after:  {_fmt(r.at)}  {r.value:,.0f}" for r in after]
    if before and after and before[-1].value > 0:
        plan.context.append(f"  ratio across it: x{after[0].value / before[-1].value:.3f}")


def _plan_torque_sessions(
    conn: Connection,
    plan: RepairPlan,
    mine: list[_Raw],
    boundary: datetime,
    from_record: bool,
) -> None:
    """Each session's odometer columns, by the rows inside it (F2-2).

    A Torque session's start and end odometers are the low and high of the
    key's rows inside it, not its edge frames, so each column follows the
    earliest or latest row in the window. With no rows left, its edges say,
    unless it spans B: then either column may be either unit and a mixed
    pair recomputes a negative distance, so it's kept whole. B from a record
    is only good to the day, so a no-row session touching that day is too.
    """
    times = [r.at for r in mine]
    for row in conn.execute(
        text(
            "SELECT id, started_at, ended_at, start_odometer, end_odometer, distance_km "
            "FROM drive_sessions WHERE device_id = :d AND vin = :v ORDER BY started_at, id"
        ),
        {"d": plan.device_id, "v": plan.vin},
    ):
        start, end, distance = row.start_odometer, row.end_odometer, row.distance_km
        if start is None and end is None:
            continue
        started = _at(row.started_at)
        ended = _as_datetime(row.ended_at)
        inside = mine[bisect_left(times, started) : bisect_right(times, ended or datetime.max)]
        # Pruning goes by age, so it can cut a session's head. A session that
        # started before B with no row of it left from before B may have had
        # its km low in rows since pruned: kept whole like a no-row one. A row
        # older than the session proves the head is all there.
        head_gone = (
            bool(inside)
            and started < boundary <= inside[0].at
            and inside[0].at > started
            and not (mine and mine[0].at < started)
        )
        if head_gone:
            plan.sessions_kept.append((row.id, started, ended))
            continue
        if inside:
            scale_start, scale_end = inside[0].at >= boundary, inside[-1].at >= boundary
        else:
            last = ended or started
            touches = from_record and boundary.date() in (started.date(), last.date())
            if started < boundary <= last or touches:
                plan.sessions_kept.append((row.id, started, ended))
                continue
            scale_start = scale_end = started >= boundary
        start_change = (
            (float(start), _reading(start, plan.to)) if scale_start and start is not None else None
        )
        end_change = (float(end), _reading(end, plan.to)) if scale_end and end is not None else None
        if start_change is None and end_change is None:
            continue
        moved = None
        if _from_delta(start, end, distance):
            new_start = start_change[1] if start_change else start
            new_end = end_change[1] if end_change else end
            moved = (float(distance), float(Decimal(str(new_end)) - Decimal(str(new_start))))
        plan.sessions.append(SessionChange(row.id, start_change, end_change, moved))


def apply_repair(conn: Connection, plan: RepairPlan) -> None:
    """Write a plan from `plan_repair`. The caller owns the transaction."""
    action, unit = plan.unit_action
    if action == "clear_device_unit":
        # Auto reads TORQUE_ODOMETER as km, so the next frame agrees with the
        # repaired history. No unit-store row on this path (F1-9).
        conn.execute(
            text("UPDATE livelink_devices SET odometer_unit = NULL WHERE device_id = :d"),
            {"d": plan.device_id},
        )
    else:
        conn.execute(
            text("DELETE FROM livelink_device_units WHERE device_id = :d AND param_key = :k"),
            {"d": plan.device_id, "k": plan.key},
        )
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
    if plan.summaries:
        conn.execute(
            text(
                "UPDATE telemetry_daily_summary "
                "SET min_value = :lo, max_value = :hi, avg_value = :avg WHERE id = :id"
            ),
            [{"id": c.id, "lo": c.new[0], "hi": c.new[1], "avg": c.new[2]} for c in plan.summaries],
        )


def _report(plan: RepairPlan) -> None:
    """Print what the plan changes."""
    action, unit = plan.unit_action
    if action == "clear_device_unit":
        print(f"\n{plan.device_id} / {plan.key}: read as mi since the switch, really km")
        print(f"  device: clear odometer_unit (auto, which reads {plan.key} as km)")
        if plan.boundary is not None:
            print(f"  switch to mi: {_fmt(plan.boundary)}, from {plan.boundary_source}")
    else:
        was = ODOMETER_UNIT_MI if plan.to == ODOMETER_UNIT_KM else ODOMETER_UNIT_KM
        print(f"\n{plan.device_id} / {plan.key}: read as {was}, really {plan.to}")
        if action == "drop":
            print(
                f"  unit store: drop the key's row ({plan.key} then reads {plan.to} by its key rule)"
            )
        else:
            print(f"  unit store: hold {plan.key} in {unit} (a legacy row)")
        if plan.boundary is not None:
            print(f"  from: {_fmt(plan.boundary)}, {plan.boundary_source}")
    for line in plan.context:
        print(line)
    if plan.raw:
        (first_old, first_new), (last_old, last_new) = plan.raw[0], plan.raw[-1]
        print(
            f"  raw telemetry: {len(plan.raw):,} row(s), {first_old:,.0f} -> {first_new:,.0f} "
            f"... {last_old:,.0f} -> {last_new:,.0f} km"
        )
    if plan.latest is not None:
        print(f"  latest value: {plan.latest[0]:,.0f} -> {plan.latest[1]:,.0f} km")
    if plan.stale_latest is not None:
        value, at = plan.stale_latest
        print(
            f"  latest value: {value:,.0f} at {_fmt(at)} is before the switch, so it stays. "
            "Ingest can't leave one there; check it."
        )
    for record_id, old, new in plan.records:
        line = f"  odometer record {record_id}: {old:,.0f} -> {new:,.0f} km"
        if record_id in plan.flagged_records:
            line += (
                ", still above its day's readings: backfill likely converted it twice, so it "
                "stays 1.609x high. Fix it by hand."
            )
        print(line)
    if plan.sessions:
        moved = sum(1 for s in plan.sessions if s.distance is not None)
        print(
            f"  sessions: {len(plan.sessions)} with odometers, {moved} with a distance from "
            "the odometer that moves with them"
        )
    for session_id, started, ended in plan.sessions_kept:
        until = _fmt(ended) if ended is not None else "open"
        print(
            f"  session {session_id} ({_fmt(started)} to {until}): not enough rows left to say "
            "which side of the switch its odometers read, so it stays as is"
        )
    if plan.summaries or plan.summaries_left:
        scaled = sum(1 for c in plan.summaries if c.how == "scaled")
        rebuilt = len(plan.summaries) - scaled
        print(
            f"  daily summaries: {scaled} scaled, {rebuilt} rebuilt, "
            f"{len(plan.summaries_left)} left as is"
        )
        which = "the switch day" if action == "clear_device_unit" else "the window-start day"
        for day in plan.summaries_left:
            print(f"    {day}: {which}, its raw rows are gone and it may mix readings, so it stays")


def _switch_at(value: str) -> datetime:
    """``--switch-at``: an ISO timestamp, as the naive UTC the database holds."""
    try:
        at = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO timestamp: {value!r}") from exc
    if at.tzinfo is not None:
        at = at.astimezone(UTC).replace(tzinfo=None)
    return at


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db",
        help=(
            "Database to operate on: a path to mygarage.db, or a full SQLAlchemy URL "
            "(postgresql+asyncpg://...). Omit to use the instance's configured database, "
            "which is the right choice when running inside the container."
        ),
    )
    parser.add_argument("--device-id", required=True, help="The WiCAN or Torque phone to repair")
    parser.add_argument(
        "--key",
        default="ODOMETER",
        help="The odometer key (default ODOMETER; TORQUE_ODOMETER for a Torque phone)",
    )
    parser.add_argument(
        "--to",
        required=True,
        choices=(ODOMETER_UNIT_KM, ODOMETER_UNIT_MI),
        help="The unit the device really reports the key in (km for TORQUE_ODOMETER)",
    )
    parser.add_argument(
        "--switch-at",
        type=_switch_at,
        help=(
            "Torque only: when the phone was set to mi, as an ISO timestamp (UTC unless it "
            "carries an offset). Wins over detection; the dry run shows the readings either side."
        ),
    )
    parser.add_argument(
        "--ignore-device",
        action="append",
        default=[],
        metavar="ID",
        help=(
            "Torque only: a deleted phone id that was this same phone before it was re-added. "
            "Repeatable. An id still on file is refused: unlink that phone instead."
        ),
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
    engine = create_tool_engine(args.db)
    try:
        with engine.begin() as conn:
            try:
                plan = plan_repair(
                    conn,
                    args.device_id,
                    args.key,
                    args.to,
                    switch_at=args.switch_at,
                    ignore_devices=args.ignore_device,
                )
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
