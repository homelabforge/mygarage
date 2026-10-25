"""Replay and storage correctness (G4-70, G4-64, G4-65, R9, G4-07, G3b-04, S1a-14).

A WiCAN off home WiFi buffers readings and replays them later with their
original timestamps, and a WiCAN can also re-POST a frame it already sent. Each
test here is one way that used to corrupt what got stored: the latest value
going backwards, one reading confirming itself as a drive, a replay-only
session closing before it started (or splitting per scheduler tick), a
replayed reading rejected against the wall clock, the wrong odometer key
opening a session, and a prune reporting a pre-delete count.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import Select, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.location_point import LocationPoint
from app.models.settings import Setting
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_service import LiveLinkService
from app.services.location_service import LocationService
from app.services.session_boundaries import BOUNDARY_ALGORITHM_MOVEMENT
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.asyncio

GAP = 15
TIMEOUT = 5

_SEQ = itertools.count()

#: A speed-classed key nothing else registers (see the rate-check test).
RATE_KEY = "T4_RATE_SPEED"


def _now() -> datetime:
    return utc_now().replace(tzinfo=None, microsecond=0)


async def _pin_session_settings(
    db: AsyncSession, keep_rows: Callable[..., Awaitable[None]]
) -> None:
    """Movement mode, a 15-minute gap and a 5-minute timeout, whatever the shared DB holds."""
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


async def _linked(
    db: AsyncSession, make_livelink_vehicle, prefix: str, **device_fields: Any
) -> tuple[str, LiveLinkDevice, str]:
    """A linked WiCAN with its own token, so a telemetry-only POST finds it."""
    n = next(_SEQ)
    token = f"t4-{prefix}-{n}-{utc_now().timestamp()}"
    vin, device = await make_livelink_vehicle(
        prefix, str(n), device_token_hash=LiveLinkService.hash_token(token)
    )
    for field, value in device_fields.items():
        setattr(device, field, value)
    await db.commit()
    return vin, device, token


async def _post(client: AsyncClient, token: str, at: datetime, **autopid: float) -> Response:
    """A telemetry-only HTTPS POST carrying the device's own timestamp."""
    with patch("app.routes.livelink.validate_livelink_token", new_callable=AsyncMock) as ok:
        ok.return_value = True
        response = await client.post(
            "/api/v1/livelink/ingest",
            json={"autopid_data": dict(autopid), "timestamp": at.isoformat()},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 202
    assert "processing_error" not in response.json(), response.json()
    return response


async def _tick(db: AsyncSession, caplog: pytest.LogCaptureFixture) -> None:
    """Run the WHOLE scheduled session-timeout job against the test session.

    `check_session_timeouts` then `expire_stale_movement_state`, as the
    scheduler runs them. The job swallows its own exceptions, so an error
    logged here fails the test instead of passing silently.
    """
    from app.tasks import livelink_tasks

    with (
        patch.object(livelink_tasks, "AsyncSessionLocal", lambda: contextlib.nullcontext(db)),
        caplog.at_level(logging.ERROR, logger="app.tasks.livelink_tasks"),
    ):
        caplog.clear()
        await livelink_tasks.check_session_timeouts()
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], errors


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    db.expire_all()
    rows = await db.execute(
        select(DriveSession)
        .where(DriveSession.device_id == device_id)
        .order_by(DriveSession.started_at)
    )
    return list(rows.scalars().all())


async def _device(db: AsyncSession, device_id: str) -> LiveLinkDevice:
    db.expire_all()
    return (
        await db.execute(select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id))
    ).scalar_one()


# --- G4-70: the latest value never goes backwards --------------------------------


@pytest.mark.usefixtures("livelink_enabled")
async def test_an_older_https_sample_leaves_the_latest_value_at_the_newer_one(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
) -> None:
    """A buffered reading landing after a live one must not roll the dashboard back."""
    vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4lat")
    device_id = device.device_id  # a commit expires the object
    newer = _now() - timedelta(seconds=10)
    older = newer - timedelta(hours=1)

    await _post(client, token, newer, T4_LATEST_PROBE=90.0)
    # A key of its own, unclassed: parameter rows are global and the suite
    # shares one database, and no rate check can hide the bug behind a rejection.
    await _post(client, token, older, T4_LATEST_PROBE=89.0)

    db_session.expire_all()
    latest = (
        await db_session.execute(
            select(VehicleTelemetryLatest).where(
                VehicleTelemetryLatest.vin == vin,
                VehicleTelemetryLatest.param_key == "T4_LATEST_PROBE",
            )
        )
    ).scalar_one()
    assert (latest.value, latest.timestamp) == (90.0, newer)
    # The older reading still lands in history; only "latest" ignores it.
    history = await db_session.execute(
        select(VehicleTelemetry.value).where(
            VehicleTelemetry.device_id == device_id,
            VehicleTelemetry.param_key == "T4_LATEST_PROBE",
            VehicleTelemetry.timestamp == older,
        )
    )
    assert history.scalars().all() == [89.0]


# --- G4-64: a reading cannot confirm itself --------------------------------------


async def test_the_same_speed_sample_delivered_twice_opens_no_session(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """A re-POSTed frame is one reading, and one reading is not movement."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4dup", "1")
    device_id = device.device_id
    at = _now() - timedelta(seconds=5)

    telemetry = TelemetryService(db_session)
    for _ in range(2):
        await telemetry.store_telemetry(vin, device_id, {"SPEED": 40.0}, {}, timestamp=at)
    await db_session.flush()

    assert await _sessions(db_session, device_id) == []
    # The first copy still recorded its evidence; it's the second that mustn't count.
    assert (await _device(db_session, device_id)).movement_candidate_at == at


async def test_an_odometer_rise_at_the_candidate_instant_opens_no_session(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """The odometer branch needs a second instant too, not just a bigger number."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4odi", "1")
    device_id = device.device_id
    at = datetime(2026, 9, 2, 7, 0, 0)

    service = SessionService(db_session)
    await service.observe_telemetry(device, {"ODOMETER": 1000.0}, at, live=False)
    assert device.movement_candidate_at == at, "fixture must leave a candidate"
    opened = await service.observe_telemetry(device, {"ODOMETER": 1000.5}, at, live=False)
    await db_session.flush()

    assert opened is None
    assert await _sessions(db_session, device_id) == []


async def test_an_older_sample_confirming_a_newer_candidate_does_not_invert_the_movement_span(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Replays arrive out of order: the span runs from the earlier reading to the later one."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4inv", "1")
    later = datetime(2026, 9, 2, 9, 1, 0)
    earlier = later - timedelta(seconds=40)

    service = SessionService(db_session)
    await service.observe_telemetry(device, {"SPEED": 40.0}, later, live=False)
    session = await service.observe_telemetry(device, {"SPEED": 45.0}, earlier, live=False)
    await db_session.flush()

    assert session is not None
    assert (session.movement_started_at, session.movement_ended_at) == (earlier, later)


# --- G4-65: an older replayed sample inside an open session ----------------------


async def test_an_older_replayed_sample_leaves_movement_ended_at_where_it_was(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """The open session's movement end only ever moves forward."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4end", "1")
    t0 = datetime(2026, 9, 3, 8, 0, 0)

    service = SessionService(db_session)
    for at in (t0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=20)):
        session = await service.observe_telemetry(device, {"SPEED": 50.0}, at, live=True)
    assert session is not None
    assert session.movement_ended_at == t0 + timedelta(seconds=20), "fixture must open a session"

    await service.observe_telemetry(device, {"SPEED": 50.0}, t0 + timedelta(seconds=5), live=False)
    await db_session.flush()

    assert session.ended_at is None
    assert session.movement_ended_at == t0 + timedelta(seconds=20)


# --- R9: replay-built sessions under the scheduled job ---------------------------


async def _device_with_an_earlier_drive(
    db: AsyncSession, make_livelink_vehicle, prefix: str
) -> tuple[str, LiveLinkDevice, str, int, datetime]:
    """A WiCAN whose `last_movement_at` belongs to a drive three days ago."""
    last_drive_end = _now() - timedelta(days=3)
    vin, device, token = await _linked(
        db, make_livelink_vehicle, prefix, last_movement_at=last_drive_end
    )
    earlier = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=last_drive_end - timedelta(minutes=30),
        ended_at=last_drive_end,
        duration_seconds=1800,
        movement_started_at=last_drive_end - timedelta(minutes=30),
        movement_ended_at=last_drive_end,
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db.add(earlier)
    await db.commit()
    return vin, device, token, earlier.id, last_drive_end


async def _replay(client: AsyncClient, token: str, start: datetime) -> list[datetime]:
    """Five buffered SPEED readings, 30 s apart, posted in order."""
    stamps = [start + timedelta(seconds=30 * i) for i in range(5)]
    for at, speed in zip(stamps, (40.0, 45.0, 50.0, 55.0, 50.0), strict=True):
        await _post(client, token, at, SPEED=speed)
    return stamps


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replay_only_session_closes_after_it_started(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`last_movement_at` from an earlier drive must not be where a replayed drive ends."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4rpo"
    )
    device_id = device.device_id  # a commit expires the object
    stamps = await _replay(client, token, _now() - timedelta(hours=2))

    await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert len(replayed) == 1
    session = replayed[0]
    assert session.started_at == stamps[0]
    assert session.ended_at is not None
    assert session.ended_at >= session.started_at
    assert session.ended_at == stamps[-1]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replay_spanning_three_ticks_is_one_session(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three batches with a scheduler tick after each still make one drive.

    Accepted cost (R9, Fable F1-14): every tick closes the replay-built
    session, since its movement is older than the wall-clock gap cutoff, and
    keeps the pointer; the next batch's readings reopen it. So this asserts on
    the outcome, one session spanning the replay, not on how often it closed.
    """
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4rp3"
    )
    device_id = device.device_id  # a commit expires the object
    start = _now() - timedelta(hours=2)
    stamps: list[datetime] = []
    for batch in range(3):
        stamps += await _replay(client, token, start + timedelta(minutes=3 * batch))
        await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [(stamps[0], stamps[-1])]
    session_id = replayed[0].id
    # Still reopenable: the device has been talking all along.
    assert (await _device(db_session, device_id)).current_session_id == session_id

    # Once the device goes quiet past the gap, the next tick lets go.
    quiet = await _device(db_session, device_id)
    quiet.last_seen = _now() - timedelta(minutes=GAP + 1)
    await db_session.commit()
    await _tick(db_session, caplog)

    assert (await _device(db_session, device_id)).current_session_id is None
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [(stamps[0], stamps[-1])]


# --- G4-07: rate check on sample time --------------------------------------------


async def test_a_replay_an_hour_old_after_a_live_parked_sample_is_not_rate_rejected(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """130 km/h an hour ago is not a jump from 0 km/h eight seconds ago.

    A speed-classed key of its own: parameter rows are global, and a shared
    `SPEED` row some other test registered without a class skips the rate
    check and passes for the wrong reason.
    """
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4rate", "1")
    telemetry = TelemetryService(db_session)
    param = await telemetry.auto_register_parameter(RATE_KEY, "km/h", "speed")
    assert param.param_class == "speed", "the rate check only applies to a classed key"

    parked_at = _now() - timedelta(seconds=8)
    replay_at = parked_at - timedelta(hours=1)
    await telemetry.store_telemetry(vin, device.device_id, {RATE_KEY: 0.0}, {}, timestamp=parked_at)
    result = await telemetry.store_telemetry(
        vin, device.device_id, {RATE_KEY: 130.0}, {}, timestamp=replay_at
    )
    await db_session.flush()

    assert result.validated_data == {RATE_KEY: 130.0}
    stored = await db_session.execute(
        select(VehicleTelemetry.value).where(
            VehicleTelemetry.device_id == device.device_id,
            VehicleTelemetry.param_key == RATE_KEY,
            VehicleTelemetry.timestamp == replay_at,
        )
    )
    assert stored.scalars().all() == [130.0]


# --- G3b-04: which odometer a session starts from --------------------------------


async def _seed_latest(db: AsyncSession, vin: str, rows: list[tuple[str, float, datetime]]) -> None:
    """Latest rows, flushed one at a time so storage order is the list order."""
    for key, value, at in rows:
        db.add(
            VehicleTelemetryLatest(
                vin=vin, param_key=key, value=value, timestamp=at, received_at=_now()
            )
        )
        await db.flush()


async def test_a_session_starts_from_the_newest_odometer_key(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """`A6-ODOMETER` is inserted first and is older; the newer `ODOMETER` wins.

    Inserted in that order because main took the first odometer key in
    storage order, so the other order passes there (Fable F1-8).
    """
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4odo", "1")
    t0 = datetime(2026, 9, 4, 8, 0, 0)
    await _seed_latest(
        db_session,
        vin,
        [("A6-ODOMETER", 50000.0, t0 - timedelta(days=30)), ("ODOMETER", 51234.0, t0)],
    )

    service = SessionService(db_session)
    for at in (t0, t0 + timedelta(seconds=10)):
        session = await service.observe_telemetry(device, {"SPEED": 50.0}, at, live=True)
    assert session is not None
    assert session.start_odometer == 51234.0

    started = await service.start_session(device, t0 + timedelta(minutes=1))
    assert started.start_odometer == 51234.0


async def test_a_declared_odometer_key_wins_over_both(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """The device's declared key is the odometer, even when it's the oldest row."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4dec", "1", odometer_param_key="MY_ODO")
    t0 = datetime(2026, 9, 5, 8, 0, 0)
    await _seed_latest(
        db_session,
        vin,
        [
            ("A6-ODOMETER", 50000.0, t0 - timedelta(days=30)),
            ("MY_ODO", 49000.0, t0 - timedelta(days=60)),
            ("ODOMETER", 51234.0, t0),
        ],
    )

    service = SessionService(db_session)
    for at in (t0, t0 + timedelta(seconds=10)):
        session = await service.observe_telemetry(device, {"SPEED": 50.0}, at, live=True)
    assert session is not None
    assert session.start_odometer == 49000.0

    started = await service.start_session(device, t0 + timedelta(minutes=1))
    assert started.start_odometer == 49000.0


# --- S1a-14: prune returns what the DELETE removed --------------------------------


def _race_after_the_count(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, land: Callable[[], Any]
) -> list[int]:
    """Insert one more old row right after the first SELECT the prune runs.

    That's the window between a pre-delete count and the DELETE. Returns a
    one-slot list that counts rows landed, so the expected total is honest
    whether or not the prune still runs a count first.
    """
    real = db.execute
    landed: list[int] = [0]

    async def racing(statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = await real(statement, *args, **kwargs)
        if isinstance(statement, Select) and landed[0] == 0:
            landed[0] = 1
            await real(land())
        return result

    monkeypatch.setattr(db, "execute", racing)
    return landed


async def test_location_prune_returns_the_rows_it_deleted(
    db_session: AsyncSession, make_livelink_vehicle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row landing between a count and the DELETE is deleted, so it's counted."""
    vin, _device = await make_livelink_vehicle("t4lpr", "1")
    old = _now() - timedelta(days=200)
    db_session.add(
        LocationPoint(
            vin=vin,
            source="torque",
            timestamp=old,
            latitude=Decimal("47.600000"),
            longitude=Decimal("-122.300000"),
        )
    )
    await db_session.commit()
    cutoff = _now() - timedelta(days=90)
    before = (
        await db_session.execute(
            select(func.count(LocationPoint.id)).where(LocationPoint.timestamp < cutoff)
        )
    ).scalar_one()

    landed = _race_after_the_count(
        db_session,
        monkeypatch,
        lambda: insert(LocationPoint).values(
            vin=vin,
            source="torque",
            timestamp=old + timedelta(seconds=1),
            latitude=Decimal("47.700000"),
            longitude=Decimal("-122.400000"),
        ),
    )
    deleted = await LocationService(db_session).prune_old(90)
    monkeypatch.undo()

    left = (
        await db_session.execute(
            select(func.count(LocationPoint.id)).where(LocationPoint.timestamp < cutoff)
        )
    ).scalar_one()
    assert left == 0
    assert deleted == before + landed[0]


async def test_telemetry_prune_returns_the_rows_it_deleted(
    db_session: AsyncSession, make_livelink_vehicle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same race, the raw telemetry table."""
    vin, device = await make_livelink_vehicle("t4tpr", "1")
    old = _now() - timedelta(days=200)
    db_session.add(
        VehicleTelemetry(
            vin=vin,
            device_id=device.device_id,
            param_key="SPEED",
            value=10.0,
            timestamp=old,
            received_at=old,
        )
    )
    await db_session.commit()
    cutoff = _now() - timedelta(days=90)
    before = (
        await db_session.execute(
            select(func.count(VehicleTelemetry.id)).where(VehicleTelemetry.timestamp < cutoff)
        )
    ).scalar_one()

    landed = _race_after_the_count(
        db_session,
        monkeypatch,
        lambda: insert(VehicleTelemetry).values(
            vin=vin,
            device_id=device.device_id,
            param_key="SPEED",
            value=11.0,
            timestamp=old + timedelta(seconds=1),
            received_at=old,
        ),
    )
    deleted = await TelemetryService(db_session).prune_old_telemetry(90)
    monkeypatch.undo()

    left = (
        await db_session.execute(
            select(func.count(VehicleTelemetry.id)).where(VehicleTelemetry.timestamp < cutoff)
        )
    ).scalar_one()
    assert left == 0
    assert deleted == before + landed[0]
