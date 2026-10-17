"""Move Torque's one-digit PID keys onto the keys the parser files them under now (#223).

Torque sends a PID below 0x10 without its leading zero (`kc`, `kd`), and the
parser only knew the padded spelling, so every Torque install stored RPM,
speed, coolant and the rest as `KC`, `KD`, `K5`. The parser pads them now;
this moves what is already stored, for Torque sources only: raw telemetry,
latest values, daily summaries and a device's declared odometer key.

A reading on file under both keys is one reading, so the raw key's copy goes,
and the summaries follow: a day that lost a duplicate is rebuilt from the raw
rows left when raw still holds the whole day, and otherwise loses the
duplicates from its count and mean and keeps its min and max (logged).

Torque sources are kind 'torque' devices plus deleted ones, whose trips and
telemetry are kept; their `tq_` ids are still on drive_sessions.

Non-FATAL, and upgrade() swallows its own errors (125's reasoning): a data
move must never stop the migrations queued behind it. One transaction with no
DDL, so a failure rolls back on both dialects, logs at ERROR and leaves the old
keys. An error importing this file isn't covered and stops the chain like any
migration's, so it has no `from __future__ import annotations`: the runner
loads it without registering it in sys.modules, where a frozen dataclass under
that import fails (fable-plan/F-1).

The raw telemetry UPDATE is the heavy part: one pass per key on
uq_telemetry_dedup, about a million rows for an hour of driving a day over 90
days of retention at one upload every five seconds. Back up first, through the
backup API.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    BindParameter,
    Connection,
    DateTime,
    Engine,
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


def _move_latest(conn: Connection, vins: list[str]) -> set[str]:
    """One latest row per vehicle and key: the newer value stays, under the new key."""
    moved: set[str] = set()
    for raw, new in _MOVES.items():
        pairs = conn.execute(
            text(
                "SELECT r.id, t.id, CASE WHEN r.timestamp > t.timestamp THEN 1 ELSE 0 END "
                "FROM vehicle_telemetry_latest r LEFT JOIN vehicle_telemetry_latest t "
                "ON t.vin = r.vin AND t.param_key = :new "
                "WHERE r.param_key = :raw AND r.vin IN :vins"
            ).bindparams(bindparam("vins", expanding=True)),
            {"raw": raw, "new": new, "vins": vins},
        ).all()
        for raw_id, new_id, raw_is_newer in pairs:
            moved.add(raw)
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
    return moved


#: One summary day as min, max, sum and count. Sums keep a merged mean exact.
_Stats = tuple[float | None, float | None, float, int]


@dataclass(frozen=True)
class _Duplicates:
    """The readings D8 drops from one raw-key summary's day (vehicle, key, UTC day)."""

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


def _find_duplicates(conn: Connection, ids: list[str], vins: list[str]) -> dict[int, _Duplicates]:
    """Before the raw move: for each raw-key summary, the readings its day loses (D8, D10)."""
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
            dropped, total = conn.execute(
                text(
                    "SELECT COUNT(*), SUM(r.value) FROM vehicle_telemetry r "
                    "WHERE r.vin = :vin AND r.device_id IN :ids AND r.param_key = :raw "
                    "AND r.timestamp >= :start AND r.timestamp < :end "
                    "AND EXISTS (SELECT 1 FROM vehicle_telemetry t WHERE t.device_id = r.device_id "
                    "AND t.param_key = :new AND t.timestamp = r.timestamp)"
                ).bindparams(bindparam("ids", expanding=True), *_typed_day()),
                {"vin": vin, "ids": ids, "raw": raw, "new": new, **_day_window(day)},
            ).one()
            if not dropped:
                continue
            # Pruning only removes rows, so raw at or above a summary's count
            # holds everything that summary saw, plus any rows that came later.
            # A new key with no summary that day counted nothing.
            complete = _raw_count(conn, vin, raw, day) >= raw_count and _raw_count(
                conn, vin, new, day
            ) >= (new_count or 0)
            found[summary_id] = _Duplicates(dropped, float(total), complete)
    return found


def _rebuild(conn: Connection, vin: str, key: str, day: datetime, summary_id: int) -> None:
    """A summary day from the raw readings now on file, as generate_daily_summary builds it."""
    low, high, avg, count = conn.execute(
        text(
            "SELECT MIN(value), MAX(value), AVG(value), COUNT(*) FROM vehicle_telemetry "
            "WHERE vin = :vin AND param_key = :k AND timestamp >= :start AND timestamp < :end"
        ).bindparams(*_typed_day()),
        {"vin": vin, "k": key, **_day_window(day)},
    ).one()
    conn.execute(
        text(
            "UPDATE telemetry_daily_summary SET min_value = :low, max_value = :high, "
            "avg_value = :avg, sample_count = :count WHERE id = :id"
        ),
        {"low": low, "high": high, "avg": avg, "count": count, "id": summary_id},
    )


def _move_summaries(
    conn: Connection, vins: list[str], duplicates: dict[int, _Duplicates]
) -> set[str]:
    """Move the daily summaries the way the raw rows moved (D10)."""
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
                    "130: kept min and max for %s on %s (%s): raw no longer holds the whole day",
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
        summaries = bool(vins) and "telemetry_daily_summary" in tables
        # Before the raw move, while the duplicates are still on file.
        duplicates = _find_duplicates(conn, ids, vins) if summaries else {}
        moved = _move_telemetry(conn, ids)
        if vins and "vehicle_telemetry_latest" in tables:
            moved |= _move_latest(conn, vins)
        if summaries:
            moved |= _move_summaries(conn, vins, duplicates)
        if "odometer_param_key" in columns["livelink_devices"]:
            moved |= _move_odometer_keys(conn)
    logger.info("130: moved Torque keys %s", ", ".join(sorted(moved)) or "none")


def upgrade(engine: Engine | None = None) -> None:
    """Move the stored one-digit Torque keys, all or nothing."""
    if engine is None:
        engine = _get_fallback_engine()
    try:
        _move(engine)
    except SQLAlchemyError as e:
        logger.error("130: Torque keys not moved, the old ones stay: %s", e, exc_info=True)


def downgrade() -> None:  # pragma: no cover
    """Rollback not supported."""
    raise NotImplementedError("Migration 130 is forward-only.")


if __name__ == "__main__":
    upgrade()
