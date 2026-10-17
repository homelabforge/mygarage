"""The startup repair recomputes the trips migration 130 listed, once (#223)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError

import app.migrations as _migrations
from app.migrations.runner import MigrationRunner
from app.models.settings import Setting
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services import session_repair
from app.services.livelink_service import LiveLinkService
from app.services.session_repair import (
    PENDING_KEY,
    _cutoff,
    _oldest_reading,
    recompute_pending_sessions,
)
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now

P = "sessrep"
#: Older than any telemetry the suite writes, so a trip from then has lost its start.
LONG_AGO = datetime(2001, 1, 1)
#: What a trip had before 130: stats the repair must not trade for a pruned tail's.
_ESTABLISHED = {
    "max_speed": 20.0,
    "avg_speed": 10.0,
    "avg_throttle": 22.0,
    "max_throttle": 40.0,
    "avg_fuel_level": 55.0,
    "distance_km": 12.5,
    "idle_seconds": 300,
    "harsh_accel_count": 2,
    "harsh_brake_count": 1,
}


@pytest_asyncio.fixture(autouse=True)
async def _no_list_left_behind(db_session):
    """The settings table is shared by the whole suite."""
    yield
    await db_session.rollback()
    await db_session.execute(delete(Setting).where(Setting.key == PENDING_KEY))
    await db_session.commit()


async def _list(db_session, ids: list[int] | str) -> None:
    value = ids if isinstance(ids, str) else json.dumps(ids)
    db_session.add(Setting(key=PENDING_KEY, value=value, category="livelink"))
    await db_session.commit()


def _speed(db_session, vin: str, device_id: str, at: datetime, kmh: float) -> None:
    db_session.add(
        VehicleTelemetry(
            vin=vin, device_id=device_id, param_key="SPEED", value=kmh, timestamp=at, received_at=at
        )
    )


async def _retained_trip(db_session, make_closed_drive_session, suffix: str):
    """A closed trip whose first reading sits at its start, so the oldest
    reading on file can't be newer than the trip."""
    vin, device_id, trip = await make_closed_drive_session(P, suffix)
    _speed(db_session, vin, device_id, trip.started_at, 30.0)
    _speed(db_session, vin, device_id, trip.started_at + timedelta(minutes=5), 85.0)
    return trip


def _figures(trip) -> dict:
    return {name: getattr(trip, name) for name in _ESTABLISHED}


@pytest.mark.asyncio
async def test_a_wholly_retained_trip_is_recomputed_and_the_list_dropped(
    db_session, make_closed_drive_session
):
    trip = await _retained_trip(db_session, make_closed_drive_session, "01")
    await _list(db_session, [trip.id])

    assert await recompute_pending_sessions(db_session) == 1

    await db_session.refresh(trip)
    # The fixture stored max 20 and avg 10; the window holds 30 and 85.
    assert (trip.max_speed, trip.avg_speed) == (85.0, 57.5)
    assert await db_session.get(Setting, PENDING_KEY) is None


@pytest.mark.asyncio
async def test_a_trip_that_lost_its_start_to_pruning_keeps_its_stats(
    db_session, make_closed_drive_session
):
    """D13: recomputed from the one reading left, it would read 90 km/h and no idle."""
    vin, device_id, trip = await make_closed_drive_session(
        P, "03", started_at=LONG_AGO, **_ESTABLISHED
    )
    _speed(db_session, vin, device_id, utc_now().replace(tzinfo=None) - timedelta(minutes=25), 90.0)
    await _list(db_session, [trip.id])
    oldest = (await db_session.execute(select(func.min(VehicleTelemetry.timestamp)))).scalar()
    assert oldest > LONG_AGO  # setup: nothing in the suite is older than the trip

    assert await recompute_pending_sessions(db_session) == 0

    await db_session.refresh(trip)
    assert _figures(trip) == _ESTABLISHED
    assert await db_session.get(Setting, PENDING_KEY) is None  # skipped trips leave the list


@pytest.mark.asyncio
async def test_a_failure_part_way_keeps_the_list_and_every_trips_stats_then_a_retry_finishes(
    db_session, make_closed_drive_session, monkeypatch
):
    first = await _retained_trip(db_session, make_closed_drive_session, "04")
    second = await _retained_trip(db_session, make_closed_drive_session, "05")
    # Read now: the rollback below expires both, and a lazy load can't run here.
    first_id, second_id = first.id, second.id
    await _list(db_session, [first_id, second_id])
    real = SessionService.refresh_aggregates
    calls: list[int] = []

    async def _fails_on_the_second(self, session, **kwargs):
        calls.append(session.id)
        if len(calls) == 2:
            raise OperationalError("UPDATE drive_sessions", {}, Exception("boom"))
        await real(self, session, **kwargs)

    monkeypatch.setattr(SessionService, "refresh_aggregates", _fails_on_the_second)
    with pytest.raises(OperationalError):
        await recompute_pending_sessions(db_session)
    await db_session.rollback()

    await db_session.refresh(first)
    assert calls == [first_id, second_id]
    assert (first.max_speed, first.avg_speed) == (20.0, 10.0)  # its refresh rolled back too
    assert await db_session.get(Setting, PENDING_KEY) is not None

    monkeypatch.undo()
    assert await recompute_pending_sessions(db_session) == 2
    for trip in (first, second):
        await db_session.refresh(trip)
        assert (trip.max_speed, trip.avg_speed) == (85.0, 57.5)
    assert await db_session.get(Setting, PENDING_KEY) is None


@pytest.mark.asyncio
async def test_an_open_trip_on_the_list_is_left_for_its_close(
    db_session, make_closed_drive_session
):
    vin, device_id, trip = await make_closed_drive_session(P, "02", ended_at=None)
    # A reading at its start passes the cutoff, so only being open can skip it.
    _speed(db_session, vin, device_id, trip.started_at, 30.0)
    await _list(db_session, [trip.id])
    assert await recompute_pending_sessions(db_session) == 0


def test_the_cutoff_is_the_later_of_the_oldest_reading_and_the_retention_line():
    now = datetime(2026, 10, 16, 12, 0)
    # A reading older than retention landed late: retention decides.
    assert _cutoff(datetime(2026, 9, 1), now, 30) == datetime(2026, 9, 16, 12, 0)
    # Retention raised after a prune: the oldest reading decides.
    assert _cutoff(datetime(2026, 10, 1), now, 30) == datetime(2026, 10, 1)
    assert _cutoff(None, now, 30) is None


@pytest.mark.asyncio
async def test_a_late_old_reading_does_not_pass_a_trip_that_lost_its_start(
    db_session, make_closed_drive_session, monkeypatch
):
    """D13: a reading older than the retention line lowers the oldest reading
    below a trip that pruning cut; the retention term still skips it."""

    async def _thirty(_self) -> int:
        return 30

    monkeypatch.setattr(LiveLinkService, "get_retention_days", _thirty)
    now = utc_now()
    vin, device_id, trip = await make_closed_drive_session(
        P,
        "06",
        started_at=now - timedelta(days=31),
        ended_at=now - timedelta(days=29),
        **_ESTABLISHED,
    )
    _speed(
        db_session, vin, device_id, now - timedelta(days=29, hours=12), 90.0
    )  # all that's left of it
    _speed(
        db_session, vin, device_id, now - timedelta(days=40), 50.0
    )  # landed late, never pruned yet
    await _list(db_session, [trip.id])
    assert (
        await _oldest_reading(db_session) <= trip.started_at
    )  # the oldest reading alone would pass it

    assert await recompute_pending_sessions(db_session) == 0

    await db_session.refresh(trip)
    assert _figures(trip) == _ESTABLISHED
    assert await db_session.get(Setting, PENDING_KEY) is None


@pytest.mark.asyncio
async def test_no_list_or_an_empty_one_reads_no_telemetry(db_session, monkeypatch):
    """The oldest-reading lookups run only for a list with trips on it."""
    calls: list[object] = []

    async def _counted(db) -> None:
        calls.append(db)
        return None

    monkeypatch.setattr(session_repair, "_oldest_reading", _counted)
    assert await recompute_pending_sessions(db_session) == 0
    await _list(db_session, [])
    assert await recompute_pending_sessions(db_session) == 0
    assert calls == []
    assert await db_session.get(Setting, PENDING_KEY) is None


@pytest.mark.asyncio
async def test_an_unreadable_list_is_dropped(db_session):
    await _list(db_session, "not json")
    assert await recompute_pending_sessions(db_session) == 0
    assert await db_session.get(Setting, PENDING_KEY) is None


def test_the_repair_reads_the_row_migration_130_writes():
    name = "130_move_torque_one_digit_pid_keys"
    path = Path(_migrations.__file__).parent / f"{name}.py"
    module = MigrationRunner("sqlite://", path.parent)._load_module(name, path)
    assert module._PENDING_KEY == PENDING_KEY
