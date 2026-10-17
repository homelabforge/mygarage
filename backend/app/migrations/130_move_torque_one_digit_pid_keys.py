"""Move Torque's one-digit PID keys onto the keys the parser files them under now (#223).

Torque sends a PID below 0x10 without its leading zero (`kc`, `kd`), and the
parser only knew the padded spelling, so every Torque install stored RPM,
speed, coolant and the rest as `KC`, `KD`, `K5`. The parser pads them now;
this moves what is already stored, for Torque sources only: raw telemetry,
latest values, daily summaries, a device's declared odometer key and the
parameter registry.

A reading on file under both keys is one reading, so the raw key's copy goes,
and the summaries follow: a day that lost a duplicate is rebuilt from the raw
rows left when raw still holds the whole day, and otherwise loses the
duplicates received that day from its count and mean and keeps its min and
max (logged).

Torque sources are kind 'torque' devices plus deleted ones, whose trips and
telemetry are kept; their `tq_` ids are still on drive_sessions.

Latest values and summaries are per vehicle, so a raw key another device also
sends on a Torque vehicle (a WiCAN autopid someone named `KC`) goes per key:
each key's latest value is its own newest raw reading, and a summary day raw
still holds whole is rebuilt for both keys, while any other day is left as it
was (logged). A device whose readings under the raw key were all pruned can't
be seen, so its older summary days merge as before.

It also lists the closed trips whose coolant, RPM or speed it moves, in the
settings row `torque_session_repair`, for app/services/session_repair.py to
recompute at the next start: refresh_aggregates is async and this runs on a
sync engine.

Non-FATAL, and upgrade() swallows its own errors (125's reasoning): a data
move must never stop the migrations queued behind it. One transaction with no
DDL, so a failure rolls back on both dialects, logs at ERROR and leaves the old
keys. An error importing this file isn't covered and stops the chain like any
migration's, so it has no `from __future__ import annotations`: the runner
loads it without registering it in sys.modules, where a frozen dataclass under
that import fails (fable-plan/F-1).

The raw telemetry UPDATE is the heavy part: one pass per key on the
(device_id, param_key, timestamp) unique index, about a million rows for an
hour of driving a day over 90 days of retention at one upload every five
seconds. Back up first, through the backup API.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BindParameter,
    Connection,
    DateTime,
    Engine,
    RowMapping,
    bindparam,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.exc import SQLAlchemyError

FATAL = False

logger = logging.getLogger(__name__)

#: Torque's one-digit keys and where the parser files them now. Frozen here.
_MOVES: dict[str, str] = {
    "K0": "K00",
    "K1": "K01",
    "K2": "K02",
    "K3": "K03",
    "K4": "ENGINE_LOAD",
    "K5": "COOLANT_TMP",
    "K6": "K06",
    "K7": "K07",
    "K8": "K08",
    "K9": "K09",
    "KA": "K0A",
    "KB": "INTAKE_PRESSURE",
    "KC": "ENGINE_RPM",
    "KD": "SPEED",
    "KE": "TIMING_ADVANCE",
    "KF": "INTAKE_TEMP",
}

#: The moved keys refresh_aggregates reads under their new names: coolant,
#: RPM and speed (speed also drives idle and harsh counts).
_AGGREGATE_INPUTS = ("K5", "KC", "KD")

#: The settings row app/services/session_repair.py reads at startup.
_PENDING_KEY = "torque_session_repair"

#: What auto_register_parameter gives a new row of each target, frozen here, with
#: Torque's default unit: (display_name, unit, param_class, category, archive_only).
_NEW_ROWS: dict[str, tuple[str, str | None, str | None, str, bool]] = {
    "K00": ("K00", None, None, "other", True),
    "K01": ("K01", None, None, "other", True),
    "K02": ("K02", None, None, "other", True),
    "K03": ("K03", None, None, "other", True),
    "ENGINE_LOAD": ("Engine Load", "%", None, "other", True),
    "COOLANT_TMP": ("Coolant Tmp", "°C", None, "other", True),
    "K06": ("K06", None, None, "other", True),
    "K07": ("K07", None, None, "other", True),
    "K08": ("K08", None, None, "other", True),
    "K09": ("K09", None, None, "other", True),
    "K0A": ("K0A", None, None, "other", True),
    "INTAKE_PRESSURE": ("Intake Pressure", "kPa", "pressure", "engine", True),
    "ENGINE_RPM": ("Engine Rpm", "rpm", "frequency", "engine", False),
    "SPEED": ("Speed", "km/h", "speed", "engine", False),
    "TIMING_ADVANCE": ("Timing Advance", "°", None, "other", True),
    "INTAKE_TEMP": ("Intake Temp", "°C", "temperature", "temperature", False),
}

_LINES = ("warning_min", "critical_min", "warning_max")
_PARAM_COLUMNS = ("id", "display_name", "unit", "category", "icon", *_LINES)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _torque_sources(conn: Connection, tables: set[str]) -> tuple[list[str], list[str]]:
    """Torque device ids, live and deleted, and the vehicles they reported for."""
    rows = conn.execute(
        text("SELECT device_id, vin FROM livelink_devices WHERE kind = 'torque'")
    ).all()
    ids = {device_id for device_id, _vin in rows}
    vins = {vin for _device_id, vin in rows if vin}
    if "drive_sessions" in tables:
        # Only TorqueService makes `tq_` ids, and a deleted source keeps its trips.
        trips = conn.execute(
            text(
                "SELECT DISTINCT device_id, vin FROM drive_sessions "
                "WHERE device_id IN (SELECT device_id FROM livelink_devices WHERE kind = 'torque') "
                "OR (SUBSTR(device_id, 1, 3) = 'tq_' "
                "AND device_id NOT IN (SELECT device_id FROM livelink_devices))"
            )
        ).all()
        ids |= {device_id for device_id, _vin in trips}
        vins |= {vin for _device_id, vin in trips if vin}
    return sorted(ids), sorted(vins)


def _move_telemetry(conn: Connection, ids: list[str]) -> set[str]:
    """Rename the raw rows; a reading already on file under the new key wins."""
    moved: set[str] = set()
    for raw, new in _MOVES.items():
        params = {"ids": ids, "raw": raw, "new": new}
        dropped = conn.execute(
            text(
                "DELETE FROM vehicle_telemetry WHERE device_id IN :ids AND param_key = :raw "
                "AND EXISTS (SELECT 1 FROM vehicle_telemetry t "
                "WHERE t.device_id = vehicle_telemetry.device_id AND t.param_key = :new "
                "AND t.timestamp = vehicle_telemetry.timestamp)"
            ).bindparams(bindparam("ids", expanding=True)),
            params,
        ).rowcount
        renamed = conn.execute(
            text(
                "UPDATE vehicle_telemetry SET param_key = :new "
                "WHERE device_id IN :ids AND param_key = :raw"
            ).bindparams(bindparam("ids", expanding=True)),
            params,
        ).rowcount
        if dropped or renamed:
            moved.add(raw)
    return moved


def _find_shared(conn: Connection, ids: list[str], vins: list[str]) -> set[tuple[str, str]]:
    """The (vin, raw key) pairs another device also sends; those go per key."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT vin, param_key FROM vehicle_telemetry "
            "WHERE vin IN :vins AND param_key IN :raws AND device_id NOT IN :ids"
        ).bindparams(
            bindparam("vins", expanding=True),
            bindparam("raws", expanding=True),
            bindparam("ids", expanding=True),
        ),
        {"vins": vins, "raws": list(_MOVES), "ids": ids},
    ).all()
    return {(vin, key) for vin, key in rows}


def _latest_from_raw(conn: Connection, vin: str, key: str, *, keep_newer: bool) -> None:
    """Give a vehicle's key its newest raw reading as the latest value.

    With keep_newer, a latest row at least as new as that reading stays.
    """
    newest = conn.execute(
        text(
            "SELECT id FROM vehicle_telemetry WHERE vin = :vin AND param_key = :k "
            "ORDER BY timestamp DESC, id DESC LIMIT 1"
        ),
        {"vin": vin, "k": key},
    ).scalar()
    if newest is None:
        return
    current = conn.execute(
        text(
            "SELECT id, CASE WHEN timestamp >= "
            "(SELECT timestamp FROM vehicle_telemetry WHERE id = :rid) THEN 1 ELSE 0 END "
            "FROM vehicle_telemetry_latest WHERE vin = :vin AND param_key = :k"
        ),
        {"rid": newest, "vin": vin, "k": key},
    ).first()
    if current is None:
        conn.execute(
            text(
                "INSERT INTO vehicle_telemetry_latest (vin, param_key, value, timestamp, received_at) "
                "SELECT vin, param_key, value, timestamp, received_at FROM vehicle_telemetry "
                "WHERE id = :rid"
            ),
            {"rid": newest},
        )
    elif not (keep_newer and current[1]):
        conn.execute(
            text(
                "UPDATE vehicle_telemetry_latest SET "
                "value = (SELECT value FROM vehicle_telemetry WHERE id = :rid), "
                "timestamp = (SELECT timestamp FROM vehicle_telemetry WHERE id = :rid), "
                "received_at = (SELECT received_at FROM vehicle_telemetry WHERE id = :rid) "
                "WHERE id = :id"
            ),
            {"rid": newest, "id": current[0]},
        )


def _move_latest(conn: Connection, vins: list[str], shared: set[tuple[str, str]]) -> set[str]:
    """One latest row per vehicle and key: the newer value stays, under the new key.

    A shared key goes per key instead, from raw, since nobody knows which
    device wrote its latest row.
    """
    moved: set[str] = set()
    for raw, new in _MOVES.items():
        pairs = conn.execute(
            text(
                "SELECT r.id, t.id, CASE WHEN r.timestamp > t.timestamp THEN 1 ELSE 0 END, r.vin "
                "FROM vehicle_telemetry_latest r LEFT JOIN vehicle_telemetry_latest t "
                "ON t.vin = r.vin AND t.param_key = :new "
                "WHERE r.param_key = :raw AND r.vin IN :vins"
            ).bindparams(bindparam("vins", expanding=True)),
            {"raw": raw, "new": new, "vins": vins},
        ).all()
        for raw_id, new_id, raw_is_newer, vin in pairs:
            moved.add(raw)
            if (vin, raw) in shared:
                continue
            if new_id is None:
                conn.execute(
                    text("UPDATE vehicle_telemetry_latest SET param_key = :new WHERE id = :id"),
                    {"new": new, "id": raw_id},
                )
                continue
            if raw_is_newer:
                conn.execute(
                    text(
                        "UPDATE vehicle_telemetry_latest SET "
                        "value = (SELECT value FROM vehicle_telemetry_latest WHERE id = :raw_id), "
                        "timestamp = (SELECT timestamp FROM vehicle_telemetry_latest WHERE id = :raw_id), "
                        "received_at = (SELECT received_at FROM vehicle_telemetry_latest WHERE id = :raw_id) "
                        "WHERE id = :new_id"
                    ),
                    {"raw_id": raw_id, "new_id": new_id},
                )
            conn.execute(
                text("DELETE FROM vehicle_telemetry_latest WHERE id = :id"), {"id": raw_id}
            )
    for vin, raw in sorted(shared):
        # The raw key holds only the other devices' readings now. The new key takes
        # its newest, Torque's moved ones included, unless its own row is newer.
        _latest_from_raw(conn, vin, raw, keep_newer=False)
        _latest_from_raw(conn, vin, _MOVES[raw], keep_newer=True)
    return moved


#: One summary day as min, max, sum and count. Sums keep a merged mean exact.
_Stats = tuple[float | None, float | None, float, int]


@dataclass(frozen=True)
class _Duplicates:
    """The readings D8 drops from one raw-key summary's day (vehicle, key, UTC day)."""

    #: Only the ones received before the day ended: the daily job builds a day
    #: once, the day after, so a later one was never in its summary.
    count: int
    total: float
    #: Raw holds at least what both keys' summaries counted that day (none counts 0).
    complete: bool


def _stats(low: float | None, high: float | None, avg: float | None, count: int | None) -> _Stats:
    """A summary row as sums; a row with no mean counts nothing."""
    n = (count or 0) if avg is not None else 0
    return (low, high, avg * n if avg is not None else 0.0, n)


def _without(stats: _Stats, dropped: _Duplicates) -> _Stats:
    """Take the duplicates out of a summary's count and sum; min and max stay."""
    count = stats[3] - dropped.count
    if count <= 0:
        return (None, None, 0.0, 0)
    return (stats[0], stats[1], stats[2] - dropped.total, count)


def _combined(a: _Stats, b: _Stats) -> tuple[float | None, float | None, float | None, int]:
    """Two summaries of one day as one row: 059's rules."""
    lows = [s[0] for s in (a, b) if s[0] is not None]
    highs = [s[1] for s in (a, b) if s[1] is not None]
    count = a[3] + b[3]
    return (
        min(lows) if lows else None,
        max(highs) if highs else None,
        (a[2] + b[2]) / count if count else None,
        count,
    )


def _day_window(day: datetime) -> dict[str, datetime]:
    return {"start": day, "end": day + timedelta(days=1)}


def _typed_day() -> tuple[BindParameter[datetime], BindParameter[datetime]]:
    """Day bounds bound as DateTime, so SQLite compares them in its stored format."""
    return bindparam("start", type_=DateTime), bindparam("end", type_=DateTime)


def _raw_count(conn: Connection, vin: str, key: str, day: datetime) -> int:
    """Raw readings of a key on a vehicle's UTC day, every device, as the summary job counts."""
    return conn.execute(
        text(
            "SELECT COUNT(*) FROM vehicle_telemetry WHERE vin = :vin AND param_key = :k "
            "AND timestamp >= :start AND timestamp < :end"
        ).bindparams(*_typed_day()),
        {"vin": vin, "k": key, **_day_window(day)},
    ).scalar_one()


def _whole_day(
    conn: Connection, vin: str, raw: str, new: str, day: datetime, raw_n: int, new_n: int | None
) -> bool:
    """Whether raw still holds at least what both keys' summaries counted that day.

    Pruning only removes rows, so raw at or above a summary's count holds
    everything that summary saw, plus any rows that came later. A new key with
    no summary that day counted nothing.
    """
    return _raw_count(conn, vin, raw, day) >= raw_n and _raw_count(conn, vin, new, day) >= (
        new_n or 0
    )


def _find_duplicates(
    conn: Connection, ids: list[str], vins: list[str], shared: set[tuple[str, str]]
) -> dict[int, _Duplicates]:
    """Before the raw move: for each raw-key summary, the readings its day loses (D8, D10).

    Shared keys are skipped: their whole days get rebuilt for both keys anyway.
    """
    found: dict[int, _Duplicates] = {}
    for raw, new in _MOVES.items():
        days = conn.execute(
            text(
                "SELECT r.id, r.vin, r.date, r.sample_count AS raw_count, t.sample_count AS new_count "
                "FROM telemetry_daily_summary r LEFT JOIN telemetry_daily_summary t "
                "ON t.vin = r.vin AND t.date = r.date AND t.param_key = :new "
                "WHERE r.param_key = :raw AND r.vin IN :vins"
            )
            .bindparams(bindparam("vins", expanding=True))
            .columns(date=DateTime),
            {"raw": raw, "new": new, "vins": vins},
        ).all()
        for summary_id, vin, day, raw_count, new_count in days:
            if (vin, raw) in shared:
                continue
            seen, dropped, total = conn.execute(
                text(
                    "SELECT COUNT(*), COUNT(CASE WHEN r.received_at < :end THEN 1 END), "
                    "COALESCE(SUM(CASE WHEN r.received_at < :end THEN r.value END), 0) "
                    "FROM vehicle_telemetry r "
                    "WHERE r.vin = :vin AND r.device_id IN :ids AND r.param_key = :raw "
                    "AND r.timestamp >= :start AND r.timestamp < :end "
                    "AND EXISTS (SELECT 1 FROM vehicle_telemetry t WHERE t.device_id = r.device_id "
                    "AND t.param_key = :new AND t.timestamp = r.timestamp)"
                ).bindparams(bindparam("ids", expanding=True), *_typed_day()),
                {"vin": vin, "ids": ids, "raw": raw, "new": new, **_day_window(day)},
            ).one()
            if not seen:
                continue
            complete = _whole_day(conn, vin, raw, new, day, raw_count, new_count)
            found[summary_id] = _Duplicates(dropped, float(total), complete)
    return found


def _shared_days(conn: Connection, shared: set[tuple[str, str]]) -> dict[int, bool]:
    """Before the raw move: each shared key's summary days, and whether raw holds each whole."""
    whole: dict[int, bool] = {}
    for vin, raw in sorted(shared):
        new = _MOVES[raw]
        days = conn.execute(
            text(
                "SELECT r.id, r.date, r.sample_count AS raw_count, t.sample_count AS new_count "
                "FROM telemetry_daily_summary r LEFT JOIN telemetry_daily_summary t "
                "ON t.vin = r.vin AND t.date = r.date AND t.param_key = :new "
                "WHERE r.vin = :vin AND r.param_key = :raw"
            ).columns(date=DateTime),
            {"vin": vin, "raw": raw, "new": new},
        ).all()
        for summary_id, day, raw_count, new_count in days:
            whole[summary_id] = _whole_day(conn, vin, raw, new, day, raw_count, new_count)
    return whole


def _day_stats(
    conn: Connection, vin: str, key: str, day: datetime
) -> tuple[float | None, float | None, float | None, int]:
    """A key's day from the raw readings now on file, as generate_daily_summary builds it."""
    low, high, avg, count = conn.execute(
        text(
            "SELECT MIN(value), MAX(value), AVG(value), COUNT(*) FROM vehicle_telemetry "
            "WHERE vin = :vin AND param_key = :k AND timestamp >= :start AND timestamp < :end"
        ).bindparams(*_typed_day()),
        {"vin": vin, "k": key, **_day_window(day)},
    ).one()
    return low, high, avg, count


def _rebuild(conn: Connection, vin: str, key: str, day: datetime, summary_id: int) -> int:
    """Rebuild a summary day from raw; returns how many readings it holds now."""
    low, high, avg, count = _day_stats(conn, vin, key, day)
    conn.execute(
        text(
            "UPDATE telemetry_daily_summary SET min_value = :low, max_value = :high, "
            "avg_value = :avg, sample_count = :count WHERE id = :id"
        ),
        {"low": low, "high": high, "avg": avg, "count": count, "id": summary_id},
    )
    return count


def _move_shared_day(
    conn: Connection,
    vin: str,
    raw: str,
    new: str,
    day: datetime,
    raw_id: int,
    new_id: int | None,
    whole: bool,
) -> None:
    """A shared key's summary day: both keys rebuilt from raw if raw holds it whole, else left."""
    if not whole:
        logger.warning(
            "130: left %s and %s on %s (%s) as they were: another device sends %s there "
            "and raw no longer holds the whole day",
            raw,
            new,
            day.date(),
            vin[:8],
            raw,
        )
        return
    if new_id is not None:
        _rebuild(conn, vin, new, day, new_id)
    else:
        low, high, avg, count = _day_stats(conn, vin, new, day)
        if count:
            # The date comes off the raw key's row, stored the way the daily job wrote it.
            conn.execute(
                text(
                    "INSERT INTO telemetry_daily_summary (vin, param_key, date, min_value, "
                    "max_value, avg_value, sample_count) VALUES (:vin, :new, "
                    "(SELECT date FROM telemetry_daily_summary WHERE id = :id), "
                    ":low, :high, :avg, :count)"
                ),
                {
                    "vin": vin,
                    "new": new,
                    "id": raw_id,
                    "low": low,
                    "high": high,
                    "avg": avg,
                    "count": count,
                },
            )
    if not _rebuild(conn, vin, raw, day, raw_id):
        conn.execute(text("DELETE FROM telemetry_daily_summary WHERE id = :id"), {"id": raw_id})


def _move_summaries(
    conn: Connection,
    vins: list[str],
    duplicates: dict[int, _Duplicates],
    shared_days: dict[int, bool],
) -> set[str]:
    """Move the daily summaries the way the raw rows moved (D10).

    A shared key's days go per key, as _shared_days found them before the raw move.
    """
    moved: set[str] = set()
    for raw, new in _MOVES.items():
        pairs = conn.execute(
            text(
                "SELECT r.id, r.vin, r.date, r.min_value, r.max_value, r.avg_value, r.sample_count, "
                "t.id AS new_id, t.min_value AS new_min, t.max_value AS new_max, "
                "t.avg_value AS new_avg, t.sample_count AS new_count "
                "FROM telemetry_daily_summary r LEFT JOIN telemetry_daily_summary t "
                "ON t.vin = r.vin AND t.date = r.date AND t.param_key = :new "
                "WHERE r.param_key = :raw AND r.vin IN :vins"
            )
            .bindparams(bindparam("vins", expanding=True))
            .columns(date=DateTime),
            {"raw": raw, "new": new, "vins": vins},
        ).all()
        for row in pairs:
            moved.add(raw)
            raw_id, vin, day, new_id = row[0], row[1], row[2], row[7]
            whole = shared_days.get(raw_id)
            if whole is not None:
                _move_shared_day(conn, vin, raw, new, day, raw_id, new_id, whole)
                continue
            dropped = duplicates.get(raw_id)
            if dropped is not None and dropped.complete:
                # Raw still holds the whole day: rebuild it from what survived.
                if new_id is None:
                    conn.execute(
                        text("UPDATE telemetry_daily_summary SET param_key = :new WHERE id = :id"),
                        {"new": new, "id": raw_id},
                    )
                    _rebuild(conn, vin, new, day, raw_id)
                else:
                    _rebuild(conn, vin, new, day, new_id)
                    conn.execute(
                        text("DELETE FROM telemetry_daily_summary WHERE id = :id"), {"id": raw_id}
                    )
                continue
            old = _stats(*row[3:7])
            if dropped is not None:
                old = _without(old, dropped)
                logger.warning(
                    "130: kept min and max for %s on %s (%s): raw no longer holds the whole day, "
                    "so only duplicates received that day came off the count",
                    new,
                    day.date(),
                    vin[:8],
                )
            if new_id is None:
                low, high, avg, count = _combined(old, (None, None, 0.0, 0))
                if dropped is None:
                    sql = "UPDATE telemetry_daily_summary SET param_key = :new WHERE id = :id"
                else:
                    sql = (
                        "UPDATE telemetry_daily_summary SET param_key = :new, min_value = :low, "
                        "max_value = :high, avg_value = :avg, sample_count = :count WHERE id = :id"
                    )
                conn.execute(
                    text(sql),
                    {
                        "new": new,
                        "low": low,
                        "high": high,
                        "avg": avg,
                        "count": count,
                        "id": raw_id,
                    },
                )
                continue
            low, high, avg, count = _combined(old, _stats(*row[8:12]))
            conn.execute(
                text(
                    "UPDATE telemetry_daily_summary SET min_value = :low, max_value = :high, "
                    "avg_value = :avg, sample_count = :count WHERE id = :id"
                ),
                {"low": low, "high": high, "avg": avg, "count": count, "id": new_id},
            )
            conn.execute(text("DELETE FROM telemetry_daily_summary WHERE id = :id"), {"id": raw_id})
    return moved


def _move_odometer_keys(conn: Connection) -> set[str]:
    """A Torque device that declared a one-digit key as its odometer keeps it."""
    moved: set[str] = set()
    for raw, new in _MOVES.items():
        if conn.execute(
            text(
                "UPDATE livelink_devices SET odometer_param_key = :new "
                "WHERE kind = 'torque' AND odometer_param_key = :raw"
            ),
            {"raw": raw, "new": new},
        ).rowcount:
            moved.add(raw)
    return moved


def _trips_to_recompute(conn: Connection, ids: list[str]) -> list[int]:
    """Closed trips of these sources with coolant, RPM or speed under a raw key."""
    rows = conn.execute(
        text(
            "SELECT s.id FROM drive_sessions s WHERE s.ended_at IS NOT NULL AND s.device_id IN :ids "
            "AND EXISTS (SELECT 1 FROM vehicle_telemetry t WHERE t.device_id = s.device_id "
            "AND t.vin = s.vin AND t.param_key IN :keys "
            "AND t.timestamp >= s.started_at AND t.timestamp <= s.ended_at)"
        ).bindparams(bindparam("ids", expanding=True), bindparam("keys", expanding=True)),
        {"ids": ids, "keys": list(_AGGREGATE_INPUTS)},
    ).all()
    return sorted(row[0] for row in rows)


def _list_trips(conn: Connection, trips: list[int]) -> None:
    """Add the trips to the list the startup repair works through."""
    row = conn.execute(
        text("SELECT value FROM settings WHERE key = :k"), {"k": _PENDING_KEY}
    ).first()
    try:
        waiting = {int(i) for i in json.loads(row[0])} if row and row[0] else set()
    except TypeError, ValueError:
        waiting = set()
    listed = json.dumps(sorted(waiting | set(trips)))
    if row is None:
        conn.execute(
            text(
                "INSERT INTO settings (key, value, category, description, encrypted) "
                "VALUES (:k, :v, 'livelink', :d, FALSE)"
            ),
            {
                "k": _PENDING_KEY,
                "v": listed,
                "d": "Older Torque trips to recompute after migration 130 (#223)",
            },
        )
    else:
        conn.execute(
            text("UPDATE settings SET value = :v WHERE key = :k"), {"k": _PENDING_KEY, "v": listed}
        )


def _param(conn: Connection, key: str) -> RowMapping | None:
    return (
        conn.execute(
            text(
                f"SELECT {', '.join(_PARAM_COLUMNS)} FROM livelink_parameters WHERE param_key = :k"
            ),
            {"k": key},
        )
        .mappings()
        .first()
    )


def _auto_name(key: str) -> str:
    """TelemetryService._format_display_name, frozen."""
    return key.replace("_", " ").title()


def _carry(
    conn: Connection, old: RowMapping, target: RowMapping | dict[str, Any], raw: str, new: str
) -> None:
    """Copy what someone set on the raw row where the new row has none (D11)."""
    sets: dict[str, Any] = {}
    if old["display_name"] not in (None, _auto_name(raw)) and target["display_name"] in (
        None,
        _auto_name(new),
    ):
        sets["display_name"] = old["display_name"]
    if old["category"] not in (None, "other") and target["category"] in (
        None,
        "other",
        _NEW_ROWS[new][3],
    ):
        sets["category"] = old["category"]
    if old["icon"] and not target["icon"]:
        sets["icon"] = old["icon"]
    # Not the alert lines: Torque never alerts, and on a key a WiCAN also
    # sends they would start firing (fable-plan/F-5).
    if sets:
        assignments = ", ".join(f"{name} = :{name}" for name in sets)
        conn.execute(
            text(f"UPDATE livelink_parameters SET {assignments} WHERE id = :id"),
            {**sets, "id": target["id"]},
        )


def _still_used(conn: Connection, key: str, vins: list[str], columns: dict[str, set[str]]) -> bool:
    """Whether a reading, summary, latest value, topic map or device still names `key`."""
    for vin in vins:  # per vehicle, so each probe uses its (vin, param_key) index
        for table in ("vehicle_telemetry", "telemetry_daily_summary"):
            if (
                table in columns
                and conn.execute(
                    text(f"SELECT 1 FROM {table} WHERE vin = :vin AND param_key = :k LIMIT 1"),
                    {"vin": vin, "k": key},
                ).first()
            ):
                return True
    for table, column in (
        ("vehicle_telemetry_latest", "param_key"),
        ("livelink_topic_maps", "param_key"),
        ("livelink_devices", "odometer_param_key"),
    ):
        if (
            column in columns.get(table, set())
            and conn.execute(
                text(f"SELECT 1 FROM {table} WHERE {column} = :k LIMIT 1"), {"k": key}
            ).first()
        ):
            return True
    return False


def _move_registry(conn: Connection, columns: dict[str, set[str]], moved: set[str]) -> None:
    """Give each moved key's target a registry row, then retire the raw row if unused."""
    # Without the vehicles table nothing can be proven unused, so nothing is deleted.
    vins = (
        [r[0] for r in conn.execute(text("SELECT vin FROM vehicles"))]
        if "vehicles" in columns
        else None
    )
    for raw in sorted(moved):
        new = _MOVES[raw]
        name, unit, param_class, category, archive_only = _NEW_ROWS[new]
        target = _param(conn, new)
        if target is None:
            new_id = conn.execute(
                text(
                    "INSERT INTO livelink_parameters (param_key, display_name, unit, param_class, "
                    "category, display_order, show_on_dashboard, archive_only, "
                    "storage_interval_seconds, created_at) "
                    "VALUES (:k, :name, :unit, :cls, :cat, 0, :show, :archive, 0, CURRENT_TIMESTAMP) "
                    "RETURNING id"
                ),
                {
                    "k": new,
                    "name": name,
                    "unit": unit,
                    "cls": param_class,
                    "cat": category,
                    "show": True,
                    "archive": archive_only,
                },
            ).scalar_one()
            target = {
                "id": new_id,
                "display_name": name,
                "unit": unit,
                "category": category,
                "icon": None,
                **{n: None for n in _LINES},
            }
        elif not target["unit"] and unit is not None:  # '' counts as none, as at ingest
            conn.execute(
                text("UPDATE livelink_parameters SET unit = :unit WHERE id = :id"),
                {"unit": unit, "id": target["id"]},
            )
        old = _param(conn, raw)
        if old is None:
            continue
        _carry(conn, old, target, raw, new)
        if vins is not None and not _still_used(conn, raw, vins, columns):
            if any(old[n] is not None for n in _LINES):
                # They never fired, but say so rather than drop them quietly.
                logger.info(
                    "130: dropped the alert lines on %s (warning_min %s, critical_min %s, "
                    "warning_max %s): Torque never sends alerts",
                    raw,
                    old["warning_min"],
                    old["critical_min"],
                    old["warning_max"],
                )
            conn.execute(text("DELETE FROM livelink_parameters WHERE id = :id"), {"id": old["id"]})


def _move(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {
        t: {c["name"] for c in inspector.get_columns(t)} for t in inspector.get_table_names()
    }
    tables = set(columns)
    if (
        not {"livelink_devices", "vehicle_telemetry"} <= tables
        or "kind" not in columns["livelink_devices"]
    ):
        return
    with engine.begin() as conn:
        ids, vins = _torque_sources(conn, tables)
        if not ids:
            return
        # All before the raw move, while the raw keys and duplicates are on file.
        trips = _trips_to_recompute(conn, ids) if "drive_sessions" in tables else []
        shared: set[tuple[str, str]] = _find_shared(conn, ids, vins) if vins else set()
        summaries = bool(vins) and "telemetry_daily_summary" in tables
        duplicates = _find_duplicates(conn, ids, vins, shared) if summaries else {}
        shared_days = _shared_days(conn, shared) if summaries else {}
        moved = _move_telemetry(conn, ids)
        if vins and "vehicle_telemetry_latest" in tables:
            moved |= _move_latest(conn, vins, shared)
        if summaries:
            moved |= _move_summaries(conn, vins, duplicates, shared_days)
        if "odometer_param_key" in columns["livelink_devices"]:
            moved |= _move_odometer_keys(conn)
        if "livelink_parameters" in tables:
            _move_registry(conn, columns, moved)
        if trips and "settings" in tables:
            _list_trips(conn, trips)
    logger.info(
        "130: moved Torque keys %s; %d trip(s) listed to recompute",
        ", ".join(sorted(moved)) or "none",
        len(trips),
    )


def upgrade(engine: Engine | None = None) -> None:
    """Move the stored one-digit Torque keys, all or nothing."""
    if engine is None:
        engine = _get_fallback_engine()
    try:
        _move(engine)
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError) as e:
        logger.error("130: Torque keys not moved, the old ones stay: %s", e, exc_info=True)


def downgrade() -> None:  # pragma: no cover
    """Rollback not supported."""
    raise NotImplementedError("Migration 130 is forward-only.")


if __name__ == "__main__":
    upgrade()
