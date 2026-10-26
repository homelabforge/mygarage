"""What a replay drain costs, and the debounced refresh behind it (B6-12).

A replayed drive is a CLOSED session from its second frame, so every later frame
of the drain lands inside a closed window and would recompute the session's
aggregates: O(n) per frame, O(n^2) per drain. The refresh is queued behind the
commit and debounced per session instead (D-7). These tests measure the drain
(statements the observer issues per frame, refreshes per drain) and pin the
debounce's edges: a rolled-back transaction leaves nothing behind (E-3), and a
shutdown mid-sleep still refreshes once (E-12).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.drive_session import DriveSession
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services import post_commit
from app.services import telemetry_service as telemetry_module
from app.services.session_boundaries import BOUNDARY_ALGORITHM_MOVEMENT
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService, queue_session_refresh
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.asyncio

logger = logging.getLogger(__name__)

GAP = 15
TIMEOUT = 5
FRAMES = 400
CYCLE_SECONDS = 3
FILLER_KEYS = 12

#: Statements the observer may issue per replayed frame once the drive exists.
#: Written from the first run (section 4 of the spec); the test fails if a
#: change makes the per-frame cost grow with the drive.
OBSERVER_BUDGET = 3


def _now() -> datetime:
    return utc_now().replace(tzinfo=None, microsecond=0)


class _Counter:
    """Counts statements on one connection: the observer's.

    Engine-wide, the debounced refresh job's own statements landed in whatever
    frame they overlapped, and a drain past 30 s would trip the budget on a
    slow runner (review I2).
    """

    def __init__(self) -> None:
        self.n = 0
        self.connection: object | None = None

    def __call__(self, conn: object, *_: Any) -> None:
        if conn is self.connection:
            self.n += 1


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    db.expire_all()
    rows = await db.execute(
        select(DriveSession)
        .where(DriveSession.device_id == device_id)
        .order_by(DriveSession.started_at)
    )
    return list(rows.scalars().all())


async def _pin_movement_mode(db: AsyncSession, keep_rows) -> None:
    from app.models.settings import Setting

    values = {
        "livelink_session_boundary_mode": "movement",
        "livelink_session_gap_minutes": str(GAP),
        "livelink_session_timeout_minutes": str(TIMEOUT),
    }
    await keep_rows(*values)
    for key, value in values.items():
        row = await db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value, category="livelink"))
        else:
            row.value = value
    await db.commit()


def _frame(i: int) -> dict[str, float]:
    data = {
        "SPEED": 40.0 + (i % 30),
        "ENGINE_RPM": 1800.0,
        "ODOMETER": 1000.0 + 0.05 * i,
    }
    for k in range(FILLER_KEYS):
        data[f"T4COST_{k:02d}"] = float(k)
    return data


async def test_a_drain_costs_a_constant_per_frame_and_a_handful_of_refreshes(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measurement (D-7, E-13). With the real debounce constants, a drain
    of FRAMES replayed frames issues a constant number of observer statements
    per frame once the drive exists, and refreshes the closed session at most
    once per 30 s plus once at the end. The aggregates are right afterwards."""
    await _pin_movement_mode(db_session, keep_rows)
    monkeypatch.setattr(telemetry_module, "SESSION_REFRESH_DEBOUNCE_SECONDS", 2.0)
    monkeypatch.setattr(telemetry_module, "SESSION_REFRESH_MAX_DELAY_SECONDS", 30.0)
    vin, device = await make_livelink_vehicle("t4cost", "1")
    device_id = device.device_id
    telemetry = TelemetryService(db_session)

    statements = _Counter()
    engine = db_session.bind
    assert engine is not None
    event.listen(engine.sync_engine, "before_cursor_execute", statements)
    per_frame: list[int] = []
    original_observe = SessionService.observe_telemetry

    async def counted_observe(self: SessionService, *args: Any, **kwargs: Any) -> Any:
        statements.connection = (await self.db.connection()).sync_connection
        before = statements.n
        try:
            return await original_observe(self, *args, **kwargs)
        finally:
            per_frame.append(statements.n - before)

    refreshes: list[int] = []
    original_refresh = SessionService.refresh_aggregates

    async def counted_refresh(self: SessionService, session: DriveSession, **kwargs: Any) -> None:
        refreshes.append(session.id)
        await original_refresh(self, session, **kwargs)

    monkeypatch.setattr(SessionService, "observe_telemetry", counted_observe)
    monkeypatch.setattr(SessionService, "refresh_aggregates", counted_refresh)

    start = _now() - timedelta(hours=2)
    stamps = [start + timedelta(seconds=CYCLE_SECONDS * i) for i in range(FRAMES)]
    began = time.perf_counter()
    try:
        for i, at in enumerate(stamps):
            await telemetry.store_telemetry(vin, device_id, _frame(i), {}, timestamp=at)
            await db_session.commit()
        drained_in = time.perf_counter() - began
        await post_commit.drain()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", statements)

    [session] = await _sessions(db_session, device_id)
    assert (session.started_at, session.ended_at) == (stamps[0], stamps[-1])
    assert session.boundary_algorithm_version == BOUNDARY_ALGORITHM_MOVEMENT
    assert session.max_speed == pytest.approx(69.0)
    # Storage keeps the odometer in whole km.
    assert session.distance_km == pytest.approx(round(1000.0 + 0.05 * (FRAMES - 1)) - 1000.0)

    steady = per_frame[2:]
    logger.info(
        "replay drain: %d frames in %.1fs, observer statements/frame min %d max %d, refreshes %d",
        FRAMES,
        drained_in,
        min(steady),
        max(steady),
        len(refreshes),
    )
    assert max(steady) - min(steady) <= 2, per_frame
    assert max(steady) <= OBSERVER_BUDGET, per_frame
    assert len(refreshes) <= math.ceil(drained_in / 30) + 1, refreshes


async def test_a_flat_odometer_idle_never_fetches_a_window(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-6: a parked car with the odometer on every frame, replayed with nothing
    in reach. The odometer never rises past the device's last stored reading,
    so the slow path's windowed fetch never runs."""
    await _pin_movement_mode(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4cost", "2")
    device_id = device.device_id
    telemetry = TelemetryService(db_session)
    fetches: list[datetime] = []
    original_fetch = SessionService._replay_window_rows  # noqa: SLF001 - the slow path under test

    async def counted_fetch(self: SessionService, *args: Any, **kwargs: Any) -> Any:
        fetches.append(args[1])
        return await original_fetch(self, *args, **kwargs)

    monkeypatch.setattr(SessionService, "_replay_window_rows", counted_fetch)
    start = _now() - timedelta(hours=2)
    for i in range(20):
        await telemetry.store_telemetry(
            vin,
            device_id,
            {"ODOMETER": 1000.0, "ENGINE_RPM": 0.0},
            {},
            timestamp=start + timedelta(seconds=CYCLE_SECONDS * i),
        )
    await db_session.commit()

    assert fetches == []
    assert await _sessions(db_session, device_id) == []


async def test_a_stopped_car_with_a_rising_odometer_never_fetches_a_window(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-5 on the fast path: a frame that reports a speed under the floor can't
    prove a drive, so with nothing in reach it doesn't go looking for one, even
    with the odometer up a km on each frame. Regression guard; kills dropping
    the stopped-frame return before the slow path."""
    await _pin_movement_mode(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4cost", "5")
    device_id = device.device_id
    telemetry = TelemetryService(db_session)
    fetches: list[datetime] = []
    original_fetch = SessionService._replay_window_rows  # noqa: SLF001 - the slow path under test

    async def counted_fetch(self: SessionService, *args: Any, **kwargs: Any) -> Any:
        fetches.append(args[1])
        return await original_fetch(self, *args, **kwargs)

    monkeypatch.setattr(SessionService, "_replay_window_rows", counted_fetch)
    start = _now() - timedelta(hours=2)
    for i in range(3):
        await telemetry.store_telemetry(
            vin,
            device_id,
            {"SPEED": 3.0, "ODOMETER": 1000.0 + i},
            {},
            timestamp=start + timedelta(minutes=5 * i),
        )
    await db_session.commit()

    assert fetches == []
    assert await _sessions(db_session, device_id) == []


async def test_a_rolled_back_refresh_leaves_nothing_behind(
    db_session: AsyncSession, make_closed_drive_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-3: the debounce registry is written by the job, not when it's queued, so
    a transaction that rolls back after queueing a refresh leaves no entry to
    suppress the next one. Regression guard; kills registering at queue time."""
    now = _now()
    vin, device_id, session = await make_closed_drive_session(
        "t4cost",
        "3",
        started_at=now - timedelta(minutes=10),
        ended_at=now - timedelta(minutes=5),
        duration_seconds=300,
    )
    db_session.add(
        VehicleTelemetry(
            vin=vin,
            device_id=device_id,
            param_key="SPEED",
            value=50.0,
            timestamp=session.started_at + timedelta(minutes=1),
            received_at=now,
        )
    )
    await db_session.commit()
    telemetry = TelemetryService(db_session)
    inside = session.started_at + timedelta(minutes=2)

    await telemetry.store_telemetry(vin, device_id, {"SPEED": 85.0}, {}, timestamp=inside)
    await db_session.rollback()
    await telemetry.store_telemetry(
        vin, device_id, {"SPEED": 90.0}, {}, timestamp=inside + timedelta(seconds=10)
    )
    await db_session.commit()
    await post_commit.drain()

    await db_session.refresh(session)
    assert session.max_speed == 90.0


async def test_a_refresh_whose_session_was_merged_away_logs_no_error(
    db_session: AsyncSession,
    make_closed_drive_session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """M5: a merge can delete a builder row while its queued refresh is mid-way
    through recomputing it. Nothing's lost, so it isn't an ERROR. Red on
    3c744c37 (the job's commit raised `StaleDataError` and logged a traceback)."""
    now = _now()
    _vin, _device_id, session = await make_closed_drive_session(
        "t4cost",
        "6",
        started_at=now - timedelta(minutes=10),
        ended_at=now - timedelta(minutes=5),
        duration_seconds=300,
    )
    await db_session.commit()
    session_id = session.id
    original_refresh = SessionService.refresh_aggregates

    async def refresh_then_lose_the_row(
        self: SessionService, target: DriveSession, **kwargs: Any
    ) -> None:
        await original_refresh(self, target, **kwargs)
        target.max_speed = 123.0  # something to write
        bind = self.db.bind
        assert isinstance(bind, AsyncEngine)
        async with AsyncSession(bind) as merge:
            await merge.execute(delete(DriveSession).where(DriveSession.id == target.id))
            await merge.commit()

    monkeypatch.setattr(SessionService, "refresh_aggregates", refresh_then_lose_the_row)
    with caplog.at_level(logging.ERROR, logger="app.services.post_commit"):
        queue_session_refresh(db_session, session_id)
        await db_session.commit()
        await post_commit.drain()

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_a_shutdown_mid_debounce_still_refreshes_once(
    db_session: AsyncSession, make_closed_drive_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-12: a job cancelled while it sleeps on the debounce runs its refresh
    once before it goes, so a restart ten seconds after a drain doesn't lose
    the drain's last thirty seconds. Regression guard; kills dropping the
    cancellation handler."""
    monkeypatch.setattr(telemetry_module, "SESSION_REFRESH_DEBOUNCE_SECONDS", 10.0)
    monkeypatch.setattr(telemetry_module, "SESSION_REFRESH_MAX_DELAY_SECONDS", 30.0)
    now = _now()
    vin, device_id, session = await make_closed_drive_session(
        "t4cost",
        "4",
        started_at=now - timedelta(minutes=10),
        ended_at=now - timedelta(minutes=5),
        duration_seconds=300,
    )
    await db_session.commit()
    telemetry = TelemetryService(db_session)

    await telemetry.store_telemetry(
        vin, device_id, {"SPEED": 85.0}, {}, timestamp=session.started_at + timedelta(minutes=2)
    )
    await db_session.commit()
    await asyncio.sleep(0)
    await post_commit.shutdown(0.1)

    await db_session.refresh(session)
    assert session.max_speed == 85.0
