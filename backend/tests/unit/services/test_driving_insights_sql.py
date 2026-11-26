"""Driving insights computed in SQL must match the Python loop they replaced.

`_calculate_driving_insights` used to pull every SPEED row for the window into
Python and walk consecutive pairs. `_reference_insights` below is that loop,
copied verbatim except for the explicit (timestamp, id) sort, and every case in
CASES asserts the service agrees with it AND with literal expected values. The
one place they part is idle time that float seconds drift across N.5 s: SQL sums
whole microseconds, and the loop's drift was the bug (see the test at the end).

The edges that matter: gaps over 120 s, duplicate timestamps (dt = 0), a single
sample, idle stretches that land on N.5 s, rates on the harsh threshold, and
sub-second fractions that SQLite's strftime rounds up (Fable F-1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_service import IDLE_THRESHOLD_KMH, SessionService, SessionWindow

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, 4, 0, 0)
WINDOW = SessionWindow(start=T0, end=T0 + timedelta(minutes=10), start_exclusive=False)
OTHER = "other"

#: make_closed_drive_session's factory: (prefix, suffix, **columns) -> (vin, device, session).
SessionFactory = Callable[..., Awaitable[tuple[str, str, DriveSession]]]
#: (id, timestamp, speed), the rows the old loop read.
Kept = list[tuple[int, datetime, float]]


def _reference_insights(rows: Sequence[tuple[int, datetime, float]]) -> tuple[int, int, int]:
    """Today's loop, fed (id, timestamp, speed) rows. Returns (idle, accel, brake)."""
    ordered = [(ts, speed) for _, ts, speed in sorted(rows, key=lambda r: (r[1], r[0]))]
    if len(ordered) < 2:
        return 0, 0, 0

    idle_seconds = 0.0
    harsh_accel = 0
    harsh_brake = 0
    idle_threshold_kmh = IDLE_THRESHOLD_KMH
    harsh_ms2 = 3.5
    harsh_kmh_per_s = harsh_ms2 / (1000.0 / 3600.0)

    prev_ts, prev_speed = ordered[0]
    for ts, speed in ordered[1:]:
        dt = (ts - prev_ts).total_seconds()
        if dt <= 0 or dt > 120:
            prev_ts, prev_speed = ts, speed
            continue
        if float(prev_speed) < idle_threshold_kmh and float(speed) < idle_threshold_kmh:
            idle_seconds += dt
        dv_dt = (float(speed) - float(prev_speed)) / dt
        if dv_dt >= harsh_kmh_per_s:
            harsh_accel += 1
        elif dv_dt <= -harsh_kmh_per_s:
            harsh_brake += 1
        prev_ts, prev_speed = ts, speed

    return int(round(idle_seconds)), harsh_accel, harsh_brake


@dataclass(frozen=True)
class Sample:
    at: datetime
    speed: float
    key: str = "SPEED"
    device: str | None = None  # None is the session's own device


def _s(seconds: float, speed: float, **kwargs: Any) -> Sample:
    return Sample(T0 + timedelta(seconds=seconds), speed, **kwargs)


def _at(stamp: str, speed: float) -> Sample:
    return Sample(datetime.fromisoformat(f"2026-09-01 {stamp}"), speed)


# (case id, samples in insert order, expected (idle_seconds, accel, brake))
CASES: list[tuple[str, list[Sample], tuple[int, int, int]]] = [
    ("steady_idle", [_s(0, 0.0), _s(10, 1.0), _s(20, 2.0), _s(30, 0.0)], (30, 0, 0)),
    # 2.5 s and 3.5 s of idle: round() goes to even, both before and after.
    ("idle_2_5", [_s(i * 0.5, 0.0) for i in range(6)], (2, 0, 0)),
    ("idle_3_5", [_s(i * 0.5, 0.0) for i in range(8)], (4, 0, 0)),
    ("accel_0_to_20", [_s(0, 0.0), _s(1, 20.0)], (0, 1, 0)),
    ("brake_30_to_10", [_s(0, 30.0), _s(1, 10.0)], (0, 0, 1)),
    # The threshold is 12.6 km/h/s; 1 s and 0.5 s are exact in microseconds.
    ("accel_at_threshold", [_s(0, 0.0), _s(1, 12.6)], (0, 1, 0)),
    ("accel_at_threshold_half_second", [_s(0, 0.0), _s(0.5, 6.3)], (0, 1, 0)),
    ("accel_just_under", [_s(0, 0.0), _s(1, 12.599)], (0, 0, 0)),
    ("accel_just_over", [_s(0, 0.0), _s(1, 12.601)], (0, 1, 0)),
    ("brake_at_threshold", [_s(0, 12.6), _s(1, 0.0)], (0, 0, 1)),
    ("brake_just_under", [_s(0, 12.599), _s(1, 0.0)], (0, 0, 0)),
    ("brake_just_over", [_s(0, 12.601), _s(1, 0.0)], (0, 0, 1)),
    ("gap_exactly_120s", [_s(0, 0.0), _s(120, 0.0)], (120, 0, 0)),
    ("gap_120s_and_1us", [_s(0, 0.0), _s(120.000001, 0.0)], (0, 0, 0)),
    ("one_microsecond_apart", [_s(0, 10.0), _s(0.000001, 10.00002)], (0, 1, 0)),
    # 0.012915 km/h in 1,025 us: the rate is 12.599999999999998, just under, but
    # multiplied through by dt both sides come out 12915.0 and it counted (R1-M3).
    ("accel_rate_under_by_float", [_s(0, 0.0), _s(0.001025, 0.012915)], (0, 0, 0)),
    ("brake_rate_under_by_float", [_s(0, 0.012915), _s(0.001025, 0.0)], (0, 0, 0)),
    # strftime('%s') rounds .9996 up a whole second; true dt 0.2004 s and 0.9997 s.
    (
        "fraction_999600_first",
        [_at("04:00:00.999600", 10.0), _at("04:00:01.200000", 13.0)],
        (0, 1, 0),
    ),
    (
        "fraction_999700_second",
        [_at("04:00:00.000000", 10.0), _at("04:00:00.999700", 23.0)],
        (0, 1, 0),
    ),
    # Same instant on two spellings: the lower id sorts first, so 20 km/h pairs
    # with the next sample (a brake). The other order would read as 1 s of idle.
    (
        "tie_broken_by_id",
        [_s(0, 0.0), _s(0, 20.0, key="0D-VehicleSpeed"), _s(1, 0.0)],
        (0, 0, 1),
    ),
    ("single_sample", [_s(0, 30.0)], (0, 0, 0)),
    # Outside the window or off another device: each would add a harsh event
    # or cut the idle run if it leaked in.
    (
        "excluded_rows",
        [
            _s(-1, 50.0),
            _s(0, 0.0),
            _s(5, 50.0, device=OTHER),
            _s(6, 0.0, device=OTHER),
            _s(10, 0.0),
            _s(600, 0.0),
            _s(601, 50.0),
        ],
        (10, 0, 0),
    ),
]


async def _seed(
    db_session: AsyncSession,
    make_closed_drive_session: SessionFactory,
    suffix: str,
    samples: list[Sample],
) -> tuple[DriveSession, Kept]:
    """One session per case; returns it and the rows the loop would have read."""
    vin, device_id, session = await make_closed_drive_session(
        "drvins", suffix, started_at=WINDOW.start, ended_at=WINDOW.end
    )
    kept: Kept = []
    for sample in samples:
        row = VehicleTelemetry(
            vin=vin,
            device_id=device_id if sample.device is None else f"drvinsoth{suffix:0>4}",
            param_key=sample.key,
            value=sample.speed,
            timestamp=sample.at,
        )
        db_session.add(row)
        # Flush one at a time so ids follow insert order for the tie case.
        await db_session.flush()
        if sample.device is None and WINDOW.start <= sample.at <= WINDOW.end:
            kept.append((row.id, row.timestamp, row.value))
    return session, kept


@pytest.mark.parametrize(
    ("suffix", "samples", "expected"),
    [
        pytest.param(str(n), samples, expected, id=case)
        for n, (case, samples, expected) in enumerate(CASES, 1)
    ],
)
async def test_sql_matches_the_loop(
    db_session: AsyncSession,
    make_closed_drive_session: SessionFactory,
    suffix: str,
    samples: list[Sample],
    expected: tuple[int, int, int],
) -> None:
    session, kept = await _seed(db_session, make_closed_drive_session, suffix, samples)

    await SessionService(db_session)._calculate_driving_insights(session, WINDOW)

    got = (session.idle_seconds, session.harsh_accel_count, session.harsh_brake_count)
    assert got == _reference_insights(kept)
    assert got == expected


async def test_the_math_runs_in_one_windowed_query(
    db_session: AsyncSession, make_closed_drive_session: SessionFactory
) -> None:
    """Not one row per sample back to Python: a single SELECT with LAG and sum()."""
    session, _ = await _seed(
        db_session, make_closed_drive_session, "900", [_s(0, 0.0), _s(1, 20.0), _s(2, 0.0)]
    )
    engine = db_session.bind
    assert engine is not None
    statements: list[str] = []

    def record(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await SessionService(db_session)._calculate_driving_insights(session, WINDOW)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)

    assert len(statements) == 1, statements
    sql = statements[0].lower()
    assert "over (" in sql
    assert "sum(" in sql
    assert (session.harsh_accel_count, session.harsh_brake_count) == (1, 1)


async def test_idle_sums_whole_microseconds_not_float_seconds(
    db_session: AsyncSession, make_closed_drive_session: SessionFactory
) -> None:
    """25 steps of 0.1 s idle are 2.5 s, which rounds to even, 2."""
    samples = [_s(i * 0.1, 0.0) for i in range(26)]
    session, kept = await _seed(db_session, make_closed_drive_session, "901", samples)

    await SessionService(db_session)._calculate_driving_insights(session, WINDOW)

    got = (session.idle_seconds, session.harsh_accel_count, session.harsh_brake_count)
    assert got == (2, 0, 0)
    # The old loop summed float seconds to 2.5000000000000004 and said 3: that was the bug.
    assert _reference_insights(kept) == (3, 0, 0)
