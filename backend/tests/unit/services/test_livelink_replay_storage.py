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
from sqlalchemy import Select, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.location_point import LocationPoint
from app.models.settings import Setting
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import Reading, StoragePolicy
from app.services.location_service import LocationService
from app.services.session_boundaries import BOUNDARY_ALGORITHM_MOVEMENT, extract_signals
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


@pytest.mark.parametrize("policy", ["always", "if_newer"])
async def test_a_future_dated_latest_row_heals_on_the_next_sane_reading(
    db_session: AsyncSession, make_livelink_vehicle, policy: str
) -> None:
    """T4-a: one reading with a bad future clock mustn't freeze the latest value.

    Both writers refuse older readings, so a row dated tomorrow would refuse
    every real one until tomorrow. A stored timestamp past now is overwritten.
    """
    vin, device = await make_livelink_vehicle("t4fut", policy)
    key = f"T4_FUTURE_{policy.upper()}"
    poisoned_at = _now() + timedelta(days=1)
    await _seed_latest(db_session, vin, [(key, 999.0, poisoned_at)])
    await db_session.commit()

    sane_at = _now() - timedelta(minutes=1)
    await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, 42.0)],
        timestamp=sane_at,
        policy=StoragePolicy(latest=policy),
    )
    await db_session.commit()
    db_session.expire_all()

    latest = (
        await db_session.execute(
            select(VehicleTelemetryLatest).where(
                VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == key
            )
        )
    ).scalar_one()
    assert (latest.value, latest.timestamp) == (42.0, sane_at)


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
    """The odometer branch needs a second instant too, not just a bigger number.

    Regression guard, through `store_telemetry` since B6-12: a replay is built
    from its stored rows, and two readings at one instant are one row (the
    dedup index) and one stamp for `group_drives`. A whole km apart, since
    storage keeps the odometer in whole km and a half km would be no rise."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4odi", "1")
    device_id = device.device_id
    at = _now() - timedelta(hours=2)

    telemetry = TelemetryService(db_session)
    await telemetry.store_telemetry(vin, device_id, {"ODOMETER": 1000.0}, {}, timestamp=at)
    await telemetry.store_telemetry(vin, device_id, {"ODOMETER": 1001.0}, {}, timestamp=at)
    await db_session.flush()

    assert await _sessions(db_session, device_id) == []


async def test_an_older_live_sample_confirming_a_newer_candidate_does_not_invert_the_span(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard (G4-64): two live frames can land out of order, and the
    span runs from the earlier reading to the later one. Kills dropping the
    min/max in `_open_session_for_movement`."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4inv", "1")
    later = _now() - timedelta(seconds=10)
    earlier = later - timedelta(seconds=40)

    service = SessionService(db_session)
    await service.observe_telemetry(device, {"SPEED": 40.0}, later, live=True)
    session = await service.observe_telemetry(device, {"SPEED": 45.0}, earlier, live=True)
    await db_session.flush()

    assert session is not None
    assert (session.movement_started_at, session.movement_ended_at) == (earlier, later)


async def test_an_out_of_order_replay_is_built_with_its_span_the_right_way_round(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """The same pair as a replay: the builder sorts stored rows by stamp, so the
    order they arrived in can't invert anything, and the drive is closed at its
    later reading. Red on 177e04d9 (an open pointed session)."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4inv2", "1")
    device_id = device.device_id
    later = _now() - timedelta(hours=2)
    earlier = later - timedelta(seconds=40)

    telemetry = TelemetryService(db_session)
    await telemetry.store_telemetry(vin, device_id, {"SPEED": 40.0}, {}, timestamp=later)
    await telemetry.store_telemetry(vin, device_id, {"SPEED": 45.0}, {}, timestamp=earlier)
    await db_session.flush()

    [session] = await _sessions(db_session, device_id)
    assert (
        session.started_at,
        session.movement_started_at,
        session.movement_ended_at,
        session.ended_at,
    ) == (earlier, earlier, later, later)


# --- G4-65: an older replayed sample inside an open session ----------------------


async def test_an_older_replayed_sample_leaves_movement_ended_at_where_it_was(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """The open session's movement end only ever moves forward, and a replayed
    in-drive reading can't lower the odometer baseline either (D-10): the
    baseline is the live machine's. The baseline half is red on 177e04d9."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4end", "1")
    t0 = datetime(2026, 9, 3, 8, 0, 0)

    service = SessionService(db_session)
    for i, at in enumerate((t0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=20))):
        session = await service.observe_telemetry(
            device, {"SPEED": 50.0, "ODOMETER": 1000.0 + 0.1 * i}, at, live=True
        )
    assert session is not None
    assert session.movement_ended_at == t0 + timedelta(seconds=20), "fixture must open a session"

    await service.observe_telemetry(
        device, {"SPEED": 50.0, "ODOMETER": 999.9}, t0 + timedelta(seconds=5), live=False
    )
    await db_session.flush()

    assert session.ended_at is None
    assert session.movement_ended_at == t0 + timedelta(seconds=20)
    assert device.movement_baseline_km is not None
    assert float(device.movement_baseline_km) == pytest.approx(1000.2)


async def _closed_drive_around(
    db: AsyncSession, make_livelink_vehicle, prefix: str, t0: datetime
) -> tuple[LiveLinkDevice, int]:
    """A device whose last drive ran from an hour before `t0` to an hour after."""
    vin, device = await make_livelink_vehicle(prefix, "1")
    earlier = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=t0 - timedelta(hours=1),
        ended_at=t0 + timedelta(hours=1),
        duration_seconds=7200,
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db.add(earlier)
    await db.flush()
    return device, earlier.id


async def test_a_replay_wholly_inside_the_previous_drive_opens_no_session(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Carry 11 (T4-c): the clamp moved its start up to the previous close and
    opened a session there with nothing in it. Those samples are the previous
    drive's. Red on 4954e3a3 (a session clamped to the close)."""
    await _pin_session_settings(db_session, keep_rows)
    t0 = datetime(2026, 9, 6, 9, 0, 0)
    device, earlier_id = await _closed_drive_around(db_session, make_livelink_vehicle, "t4clp", t0)

    service = SessionService(db_session)
    await service.observe_telemetry(device, {"SPEED": 40.0}, t0, live=False)
    session = await service.observe_telemetry(
        device, {"SPEED": 45.0}, t0 + timedelta(minutes=1), live=False
    )
    await db_session.flush()

    assert session is None
    assert device.movement_candidate_at is None
    assert [s.id for s in await _sessions(db_session, device.device_id)] == [earlier_id]


async def test_a_replay_that_runs_past_the_previous_close_extends_that_drive(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """A replayed sample one minute past the previous drive's close is inside
    the gap of its end, so it extends that drive by a minute, which is what a
    live reopen within the gap does. Red on 177e04d9 (a new session clamped to
    the close)."""
    await _pin_session_settings(db_session, keep_rows)
    t0 = datetime(2026, 9, 6, 9, 0, 0)
    device, earlier_id = await _closed_drive_around(db_session, make_livelink_vehicle, "t4cls", t0)
    close = t0 + timedelta(hours=1)
    after = close + timedelta(minutes=1)

    service = SessionService(db_session)
    await service.observe_telemetry(
        device, {"SPEED": 40.0}, close - timedelta(minutes=1), live=False
    )
    session = await service.observe_telemetry(device, {"SPEED": 45.0}, after, live=False)
    await db_session.flush()

    assert session is None
    [earlier] = await _sessions(db_session, device.device_id)
    assert (earlier.id, earlier.ended_at, earlier.movement_ended_at) == (earlier_id, after, after)


async def test_ecu_offline_leaves_a_held_closed_session_alone(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """T4-b: the pointer can name a CLOSED session, one awaiting a reopen.

    An ECU offline with no grace period used to re-end it at wall-clock now,
    stretching an hours-old drive over the parked tail.
    """
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4ecu", "1", ecu_status="online")
    started = _now() - timedelta(hours=3)
    ended = started + timedelta(minutes=20)
    held = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=started,
        ended_at=ended,
        duration_seconds=1200,
        movement_started_at=started,
        movement_ended_at=ended,
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db_session.add(held)
    await db_session.flush()
    device.current_session_id = held.id
    device_id, held_id = device.device_id, held.id
    await db_session.commit()

    result = await SessionService(db_session).handle_ecu_offline(vin, device_id)
    await db_session.commit()

    assert result is None
    db_session.expire_all()
    after = (
        await db_session.execute(select(DriveSession).where(DriveSession.id == held_id))
    ).scalar_one()
    assert (after.ended_at, after.duration_seconds) == (ended, 1200)
    # Still held: reopening or letting go is the gap clock's call, not this one's.
    assert (await _device(db_session, device_id)).current_session_id == held_id


# --- B6-12: replays never hold the pointer ---------------------------------------


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


async def _quiet(db: AsyncSession, device_id: str, *, minutes: int) -> None:
    """The device's last word, and every row it sent, `minutes` ago."""
    then = _now() - timedelta(minutes=minutes)
    await db.execute(
        update(VehicleTelemetry)
        .where(VehicleTelemetry.device_id == device_id)
        .values(received_at=then)
    )
    await db.execute(
        update(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id).values(last_seen=then)
    )
    await db.commit()


async def _replay(
    client: AsyncClient,
    token: str,
    start: datetime,
    *,
    odometer_from: float | None = None,
) -> list[datetime]:
    """Five buffered SPEED readings, 30 s apart, posted in order.

    With ``odometer_from``, each reading also carries an ODOMETER climbing half
    a kilometre per reading, the way a WiCAN with the odometer PID configured
    logs it on every frame.
    """
    stamps = [start + timedelta(seconds=30 * i) for i in range(5)]
    for i, (at, speed) in enumerate(zip(stamps, (40.0, 45.0, 50.0, 55.0, 50.0), strict=True)):
        frame: dict[str, float] = {"SPEED": speed}
        if odometer_from is not None:
            frame["ODOMETER"] = odometer_from + 0.5 * i
        await _post(client, token, at, **frame)
    return stamps


async def _closed_session(
    db: AsyncSession,
    vin: str,
    device_id: str,
    start: datetime,
    end: datetime,
    *,
    movement_end: datetime | None = None,
) -> DriveSession:
    """A closed movement-mode drive on record, with its movement span filled in."""
    session = DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=start,
        ended_at=end,
        duration_seconds=int((end - start).total_seconds()),
        movement_started_at=start,
        movement_ended_at=movement_end or end,
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db.add(session)
    await db.flush()
    return session


async def _awaiting(
    db: AsyncSession,
    make_livelink_vehicle,
    prefix: str,
    *,
    start: datetime,
    end: datetime,
    movement_end: datetime | None = None,
) -> tuple[str, str, str, int]:
    """A live drive the contact clock closed at `end`, pointer kept, device awake now."""
    vin, device, token = await _linked(db, make_livelink_vehicle, prefix)
    session = await _closed_session(
        db, vin, device.device_id, start, end, movement_end=movement_end
    )
    device.last_movement_at = end
    device.current_session_id = session.id
    device.last_seen = _now()
    device_id, session_id = device.device_id, session.id
    await db.commit()
    return vin, device_id, token, session_id


def _spans(sessions: list[DriveSession]) -> list[tuple[datetime, datetime | None]]:
    return [(s.started_at, s.ended_at) for s in sessions]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_drive_is_closed_from_its_second_sample_and_never_pointed(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B6-12: a replay is built into a CLOSED session by sample time, without the
    device pointer. There's nothing for the gap clock to close or hold, so a
    tick changes nothing. Red on 177e04d9 (open until the tick, and pointed)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4rpo"
    )
    device_id = device.device_id  # a commit expires the object
    stamps = await _replay(client, token, _now() - timedelta(hours=2))

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]
    assert (await _device(db_session, device_id)).current_session_id is None

    await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]
    assert (await _device(db_session, device_id)).current_session_id is None


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replay_spanning_three_ticks_is_one_session(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Three batches with a scheduler tick after each still make one drive.

    Each batch extends the closed session by sample time; the ticks have
    nothing to do with it. Red on 177e04d9 (open and pointed between batches).
    """
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4rp3"
    )
    device_id = device.device_id
    start = _now() - timedelta(hours=2)
    stamps: list[datetime] = []
    for batch in range(3):
        stamps += await _replay(client, token, start + timedelta(minutes=3 * batch))
        await _tick(db_session, caplog)
        replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
        assert _spans(replayed) == [(stamps[0], stamps[-1])]
        assert (await _device(db_session, device_id)).current_session_id is None

    await _quiet(db_session, device_id, minutes=GAP + 1)
    await _tick(db_session, caplog)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replays_last_sample_extends_its_closed_session(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B6-9's tail, under B6-12: one more sample within the gap of the closed
    session's end moves that end. No hold, no reopen. Red on 177e04d9 (the
    session was open until a quiet tick)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4tail"
    )
    device_id = device.device_id
    stamps = await _replay(client, token, _now() - timedelta(hours=2))
    await _tick(db_session, caplog)
    tail = stamps[-1] + timedelta(seconds=30)
    await _post(client, token, tail, SPEED=35.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], tail)]


@pytest.mark.usefixtures("livelink_enabled")
async def test_two_replayed_drives_in_one_upload_stay_two(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Wave B review I-1: a dongle off WiFi all day uploads a morning and an
    evening drive together. `group_drives` cuts them on the gap by sample time,
    and both are closed before any tick runs. Red on 177e04d9 (the evening one
    was open)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4two"
    )
    device_id = device.device_id
    morning = await _replay(client, token, _now() - timedelta(hours=10))
    await _tick(db_session, caplog)
    evening = await _replay(client, token, _now() - timedelta(hours=2))

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(morning[0], morning[-1]), (evening[0], evening[-1])]

    await _tick(db_session, caplog)
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(morning[0], morning[-1]), (evening[0], evening[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_contact_mode_drive_survives_a_switch_to_movement_mode(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Re-review (FW-B-r2): a drive opened in contact mode has no movement
    fields, so an ingest gap check measured from its start and closed it there,
    zero minutes long, on the first sample after the switch. The gap clock
    leaves a pre-movement session to the contact rule, and so does ingest.
    Red on ca2e0603."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4ctm")
    drive = DriveSession(
        vin=vin, device_id=device.device_id, started_at=_now() - timedelta(minutes=30)
    )
    db_session.add(drive)
    await db_session.flush()
    device.current_session_id = drive.id
    device.ecu_status = "online"
    await db_session.commit()
    device_id, drive_id = device.device_id, drive.id

    await _post(client, token, _now(), SPEED=60.0)

    contact = next(s for s in await _sessions(db_session, device_id) if s.id == drive_id)
    assert (contact.ended_at, contact.duration_seconds) == (None, None)


@pytest.mark.usefixtures("livelink_enabled")
async def test_one_future_dated_frame_does_not_split_a_live_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Re-review (FW-B-r2): a bad device clock stamped one frame an hour ahead.
    A live session is the gap clock's to close, on the tick, and the tick
    anchors on the live movement, not on the future `movement_ended_at` that
    frame left behind (B6-12, D-8's `<= now`). Red on ca2e0603 (two sessions);
    the tick half is a regression guard that kills dropping `<= now`."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4fut2")
    device_id = device.device_id
    t = _now()
    await _post(client, token, t - timedelta(seconds=20), SPEED=40.0)
    await _post(client, token, t - timedelta(seconds=10), SPEED=45.0)
    await _post(client, token, t + timedelta(hours=1), SPEED=50.0)
    await _post(client, token, t, SPEED=50.0)
    await _post(client, token, t + timedelta(seconds=5), SPEED=52.0)

    sessions = await _sessions(db_session, device_id)
    assert [s.ended_at for s in sessions] == [None]

    await SessionService(db_session).check_session_timeouts(
        TIMEOUT, GAP, now=t + timedelta(minutes=GAP + 1)
    )

    assert _spans(await _sessions(db_session, device_id)) == [
        (t - timedelta(seconds=20), t + timedelta(seconds=5))
    ]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_stop_inside_the_gap_is_still_one_replayed_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """A ten-minute stop is under the 15-minute gap, so the second batch
    extends the first drive's closed session instead of building another.
    Kills extending at any distance in sample time. Red on 177e04d9 (open)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4stop"
    )
    device_id = device.device_id
    first = await _replay(client, token, _now() - timedelta(hours=3))
    second = await _replay(client, token, first[-1] + timedelta(minutes=10))

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], second[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_parked_live_frame_between_replay_batches_keeps_one_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """An awake, parked car's live frame lands between two batches of a replay.
    The replay's drive is a closed session the live machine never sees, and a
    parked frame with no pointed session opens nothing, so the second batch
    extends the drive. Red on 177e04d9 (open until a tick)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4pkb"
    )
    device_id = device.device_id
    first = await _replay(client, token, _now() - timedelta(hours=2))
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], first[-1])]
    second = await _replay(client, token, first[-1] + timedelta(seconds=30))

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], second[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_live_moving_frame_hours_after_a_replay_opens_its_own_drive(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
) -> None:
    """Regression guard: the device is back and driving now, hours after the
    replay's last movement, so the replay's closed drive is out of the reopen
    window and the live one is its own. Kills reopening at any distance."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4lmv"
    )
    device_id = device.device_id
    replay = await _replay(client, token, _now() - timedelta(hours=2))
    now = _now()
    await _post(client, token, now - timedelta(seconds=10), SPEED=50.0)
    await _post(client, token, now, SPEED=55.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [
        (replay[0], replay[-1]),
        (now - timedelta(seconds=10), None),
    ]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replay_batch_after_a_live_frame_extends_its_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """One live moving frame between two replay batches is one live candidate
    and nothing more; the second batch extends the replay's closed drive by
    sample time, and the pointer stays empty. Red on 177e04d9 (the live frame
    split the held drive and left the pointer on it)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4rjn"
    )
    device_id = device.device_id
    first = await _replay(client, token, _now() - timedelta(hours=2))
    await _post(client, token, _now(), SPEED=50.0)
    second = await _replay(client, token, first[-1] + timedelta(seconds=30))

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], second[-1])]
    assert (await _device(db_session, device_id)).current_session_id is None


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_parked_live_frame_between_a_replays_first_two_samples_does_not_lose_it(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """The replay's evidence is its stored rows, not a slot on the device, so a
    live frame in between can't expire it. Red on 177e04d9 (an open session)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4cand"
    )
    device_id = device.device_id
    s1 = _now() - timedelta(hours=2)
    await _post(client, token, s1, SPEED=40.0)
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0)
    s2 = s1 + timedelta(seconds=30)
    await _post(client, token, s2, SPEED=45.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(s1, s2)]


async def test_a_moving_live_frame_still_expires_a_stale_candidate(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard: a live frame that shows movement is evidence, so an
    hours-old live candidate isn't consecutive with it and goes. Kills skipping
    the stale check."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4cexp", "1")
    now = _now()

    service = SessionService(db_session)
    await service.observe_telemetry(device, {"SPEED": 40.0}, now - timedelta(hours=2), live=True)
    session = await service.observe_telemetry(device, {"SPEED": 50.0}, now, live=True)

    assert session is None
    assert device.movement_candidate_at == now


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_parked_live_frame_with_an_odometer_between_replay_batches_keeps_one_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Re-review 3 (FW-B-r4), under B6-12: the parked car's live odometer is
    never measured against the replay's, because the replay never writes the
    device's baseline and its drive is a closed session the live machine
    doesn't see. Red on 177e04d9 (open until a tick)."""
    await _pin_session_settings(db_session, keep_rows)
    (
        _vin,
        device,
        token,
        earlier_id,
        last_drive_end,
    ) = await _device_with_an_earlier_drive(db_session, make_livelink_vehicle, "t4pko")
    device_id = device.device_id
    first = await _replay(client, token, _now() - timedelta(hours=2), odometer_from=1000.0)
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0, ODOMETER=1050.0)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], first[-1])]
    assert (await _device(db_session, device_id)).last_movement_at == last_drive_end
    second = await _replay(client, token, first[-1] + timedelta(seconds=30), odometer_from=1002.5)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], second[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_two_replayed_drives_with_a_parked_odometer_frame_between_stay_two(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The I-1 upload with a parked odometer frame between the two drives. Both
    are closed sessions before any tick. Red on 177e04d9 (the evening one open)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4twoo"
    )
    device_id = device.device_id
    morning = await _replay(client, token, _now() - timedelta(hours=10), odometer_from=1000.0)
    await _tick(db_session, caplog)
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0, ODOMETER=1080.0)
    evening = await _replay(client, token, _now() - timedelta(hours=2), odometer_from=1040.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(morning[0], morning[-1]), (evening[0], evening[-1])]

    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(morning[0], morning[-1]), (evening[0], evening[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_parked_live_frame_with_an_odometer_after_a_replay_opens_no_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """The replay's drive is closed the moment it has two samples, and the
    parked car's odometer meets no baseline (replays never write one) and
    reports a speed under the floor (1h), so it opens nothing. Red on 177e04d9
    (the replay's session was still open)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4pkc"
    )
    device_id = device.device_id
    stamps = await _replay(client, token, _now() - timedelta(hours=2), odometer_from=1000.0)
    closed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(closed) == [(stamps[0], stamps[-1])]

    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0, ODOMETER=1050.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]
    assert (await _device(db_session, device_id)).current_session_id is None


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_parked_live_frame_with_an_odometer_after_a_live_moving_frame_opens_no_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """One live moving frame is a candidate; the parked frame five seconds later
    reports a speed under the floor, so its odometer proves nothing (1h). The
    replay's drive is untouched by either. Red on 177e04d9 (the live frame
    split the held drive and left the pointer on it)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4pks"
    )
    device_id = device.device_id
    replay = await _replay(client, token, _now() - timedelta(hours=2), odometer_from=1000.0)
    now = _now()
    await _post(client, token, now, SPEED=50.0)
    await _post(
        client,
        token,
        now + timedelta(seconds=5),
        ENGINE_RPM=800.0,
        SPEED=0.0,
        ODOMETER=1050.0,
    )

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(replay[0], replay[-1])]
    assert (await _device(db_session, device_id)).current_session_id is None


async def test_a_live_drive_closed_on_contact_loss_reopens_on_one_odometer_reading(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard: a device whose speed nothing recognises moves by its
    odometer alone, and the baseline from its last movement survives a LIVE
    close, so the first reading past it after a six-minute WiFi dropout reopens
    the drive. Kills clearing the baseline when the gap clock closes a drive."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4odol", "1")
    service = SessionService(db_session)
    t0 = _now() - timedelta(minutes=TIMEOUT + 2)
    await service.observe_telemetry(device, {"ODOMETER": 1000.0}, t0)
    session = await service.observe_telemetry(
        device, {"ODOMETER": 1000.2}, t0 + timedelta(seconds=30)
    )
    assert session is not None
    device.last_seen = t0 + timedelta(seconds=30)
    await db_session.flush()

    closed = await service.check_session_timeouts(TIMEOUT, GAP)
    assert [s.id for s in closed] == [session.id]
    assert device.current_session_id == session.id

    reopened = await service.observe_telemetry(device, {"ODOMETER": 1000.5}, _now())

    assert reopened is not None
    assert (reopened.id, reopened.ended_at) == (session.id, None)


# --- B6-12: the live tail of a drained drive (D-1) --------------------------------


@pytest.mark.usefixtures("livelink_enabled")
async def test_the_live_tail_of_a_drained_drive_reopens_its_closed_session(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression guard (D-1): coming home, the WiCAN drains its buffer. Frames
    older than five minutes at receipt are a replay and build a closed drive;
    the last minutes arrive live, with no pointed session. Within the gap of
    that closed drive they reopen it instead of opening a second one. Kills
    dropping the reopen of the latest closed drive."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4home"
    )
    device_id = device.device_id
    stamps = await _replay(client, token, _now() - timedelta(minutes=8))
    now = _now()
    tail_end = now - timedelta(minutes=3, seconds=50)
    await _post(client, token, now - timedelta(minutes=4), SPEED=50.0)
    await _post(client, token, tail_end, SPEED=55.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], None)]
    reopened_id = replayed[0].id
    assert (await _device(db_session, device_id)).current_session_id == reopened_id

    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], tail_end)]


@pytest.mark.usefixtures("livelink_enabled")
async def test_an_odometer_only_device_drains_and_then_drives_on_live(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """1g, under B6-12: a device whose speed nothing recognises. Its replay is
    built from the odometer rise (E-6 lets the first rising reading in), and
    its live tail reopens the closed drive through the odometer debounce. Red
    on 177e04d9 (the live odometer frames were held off at the round-4 return
    and the drive closed at the replay's last sample)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4odot"
    )
    device_id = device.device_id
    base = _now() - timedelta(minutes=8)
    stamps = [base + timedelta(seconds=30 * i) for i in range(5)]
    for i, at in enumerate(stamps):
        await _post(client, token, at, ODOMETER=1000.0 + 0.5 * i)
    now = _now()
    tail_end = now - timedelta(minutes=3, seconds=50)
    await _post(client, token, now - timedelta(minutes=4), ODOMETER=1003.0)
    await _post(client, token, tail_end, ODOMETER=1003.5)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], None)]
    reopened_id = replayed[0].id
    assert (await _device(db_session, device_id)).current_session_id == reopened_id

    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], tail_end)]


# --- B6-12: a replayed drive next to a pointed one --------------------------------


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_drive_during_a_live_one_gets_its_own_session(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Item 3 (1a): drive B, buffered two hours ago, drains while live drive C is
    open. B becomes its own closed session; C keeps its end, its live anchor
    and its odometer baseline. Red on 177e04d9 (B was absorbed into C and C's
    baseline fell to B's odometer)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4bdc"
    )
    device_id = device.device_id
    now = _now()
    await _post(client, token, now - timedelta(seconds=20), SPEED=40.0, ODOMETER=2000.0)
    await _post(client, token, now - timedelta(seconds=10), SPEED=45.0, ODOMETER=2000.1)
    b = await _replay(client, token, now - timedelta(hours=2), odometer_from=1000.0)

    sessions = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(sessions) == [(b[0], b[-1]), (now - timedelta(seconds=20), None)]
    assert sessions[1].movement_ended_at == now - timedelta(seconds=10)
    device = await _device(db_session, device_id)
    assert device.last_movement_at == now - timedelta(seconds=10)
    assert device.movement_baseline_km is not None
    assert float(device.movement_baseline_km) == pytest.approx(2000.1)


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_drive_during_an_awaiting_one_gets_its_own_session(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Item 3 (1b): the same drain while C is closed and awaiting a reopen. B's
    samples are older than C's start, so they build B and never reach
    `_reopen_awaiting`. Red on 177e04d9 (a negative delta reopened C)."""
    await _pin_session_settings(db_session, keep_rows)
    now = _now()
    _vin, device_id, token, p_id = await _awaiting(
        db_session,
        make_livelink_vehicle,
        "t4bdca",
        start=now - timedelta(minutes=30),
        end=now - timedelta(minutes=20),
    )
    b = await _replay(client, token, now - timedelta(hours=2))

    sessions = await _sessions(db_session, device_id)
    assert _spans(sessions) == [
        (b[0], b[-1]),
        (now - timedelta(minutes=30), now - timedelta(minutes=20)),
    ]
    assert (await _device(db_session, device_id)).current_session_id == p_id


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_drained_drive_ending_within_the_gap_of_a_live_one_merges_into_it(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """D-3: B ran from forty to ten minutes ago and C opened live a minute ago,
    so by the gap rule they are one drive. B drains in order: the builder makes
    B's closed session far from C, the fast path extends it frame by frame,
    and the frame that brings its end within the gap of C's start backdates C
    to B's start (R10) and removes B's row. Red on 177e04d9 (B was absorbed and
    C kept its start)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4mrg"
    )
    device_id = device.device_id
    now = _now()
    await _post(client, token, now - timedelta(seconds=70), SPEED=40.0)
    await _post(client, token, now - timedelta(seconds=60), SPEED=45.0)
    c = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(c) == [(now - timedelta(seconds=70), None)]
    c_id = c[0].id

    b = [now - timedelta(minutes=40) + timedelta(minutes=2 * i) for i in range(16)]
    for at in b:
        await _post(client, token, at, SPEED=50.0)

    sessions = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.id, s.started_at, s.ended_at) for s in sessions] == [(c_id, b[0], None)]
    assert (await _device(db_session, device_id)).current_session_id == c_id


@pytest.mark.usefixtures("livelink_enabled")
async def test_the_drained_head_of_a_live_drive_backdates_it(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """D-3, the head variant: the car came into WiFi range mid-drive, so C opened
    live a minute ago, and the half hour before that drains afterwards. The
    head builds a closed drive, and once its end is within the gap of C's start
    it merges into C, so C starts where the drive did. Red on 177e04d9 (the
    head was absorbed and C kept its start)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4mrgh"
    )
    device_id = device.device_id
    now = _now()
    await _post(client, token, now - timedelta(seconds=70), SPEED=40.0)
    await _post(client, token, now - timedelta(seconds=60), SPEED=45.0)
    [c] = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    c_id = c.id

    head = [now - timedelta(minutes=32) + timedelta(minutes=2 * i) for i in range(15)]
    for at in head:
        await _post(client, token, at, SPEED=50.0)

    sessions = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.id, s.started_at, s.ended_at) for s in sessions] == [(c_id, head[0], None)]
    assert (await _device(db_session, device_id)).current_session_id == c_id


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_drained_drive_ending_within_the_gap_of_an_awaiting_one_merges_into_it(
    db_session: AsyncClient,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-3 and E-4: the same merge into a drive the contact clock has closed.
    The closed drive's start moves, its duration follows, and its aggregates
    are recomputed over the new span once the debounced refresh runs. Red on
    177e04d9 (B's samples reopened C on a negative delta)."""
    from app.services import post_commit

    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4mrga"
    )
    device_id = device.device_id
    now = _now()
    await _post(client, token, now - timedelta(seconds=70), SPEED=40.0)
    await _post(client, token, now - timedelta(seconds=60), SPEED=45.0)
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)
    c = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(c) == [(now - timedelta(seconds=70), now - timedelta(seconds=60))]
    c_id = c[0].id

    b = [now - timedelta(minutes=40) + timedelta(minutes=2 * i) for i in range(16)]
    for at in b:
        await _post(client, token, at, SPEED=50.0)
    await post_commit.drain()

    sessions = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.id, s.started_at, s.ended_at) for s in sessions] == [
        (c_id, b[0], now - timedelta(seconds=60))
    ]
    merged = sessions[0]
    assert merged.duration_seconds == int((now - timedelta(seconds=60) - b[0]).total_seconds())
    assert merged.max_speed == 50.0


@pytest.mark.usefixtures("livelink_enabled")
async def test_in_window_replays_leave_an_awaiting_drive_alone_and_its_tail_reopens_it(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """D-4: a replayed sample inside an awaiting drive's own window is that
    drive's late reading. It never reaches the state machine, so it writes no
    candidate and can't reopen the drive on a negative delta. A sample inside
    the gap after the drive's end is its tail, and that one does reopen it.
    Red on 177e04d9 (the in-window pair reopened the drive)."""
    await _pin_session_settings(db_session, keep_rows)
    now = _now()
    _vin, device_id, token, p_id = await _awaiting(
        db_session,
        make_livelink_vehicle,
        "t4awin",
        start=now - timedelta(minutes=30),
        end=now - timedelta(minutes=20),
    )
    await _post(client, token, now - timedelta(minutes=25), SPEED=60.0)
    await _post(client, token, now - timedelta(minutes=24), SPEED=65.0)

    [p] = await _sessions(db_session, device_id)
    assert (p.id, p.started_at, p.ended_at) == (
        p_id,
        now - timedelta(minutes=30),
        now - timedelta(minutes=20),
    )
    device = await _device(db_session, device_id)
    assert device.current_session_id == p_id
    assert device.movement_candidate_at is None
    assert device.movement_baseline_km is None

    await _post(client, token, now - timedelta(minutes=19), SPEED=50.0)
    await _post(client, token, now - timedelta(minutes=18), SPEED=55.0)

    [p] = await _sessions(db_session, device_id)
    assert (p.id, p.ended_at, p.movement_ended_at) == (
        p_id,
        None,
        now - timedelta(minutes=18),
    )


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_sample_within_reach_of_two_drives_touches_neither(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression guard (D-6): a late sample ten minutes after one drive and
    twelve before the next is within the gap of both. Which one to extend is a
    guess, and SQLite and PostgreSQL would guess differently by row order, so
    neither moves and the sample is logged. Kills extending the first in
    reach."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4brdg")
    device_id = device.device_id
    now = _now()
    await _closed_session(
        db_session,
        vin,
        device_id,
        now - timedelta(minutes=80),
        now - timedelta(minutes=60),
    )
    await _closed_session(
        db_session,
        vin,
        device_id,
        now - timedelta(minutes=38),
        now - timedelta(minutes=20),
    )
    await db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.services.session_service"):
        await _post(client, token, now - timedelta(minutes=50), SPEED=40.0)

    assert _spans(await _sessions(db_session, device_id)) == [
        (now - timedelta(minutes=80), now - timedelta(minutes=60)),
        (now - timedelta(minutes=38), now - timedelta(minutes=20)),
    ]
    assert any("within reach of 2 closed drives" in r.getMessage() for r in caplog.records)


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_tail_moves_the_gap_close_to_its_end(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """1i, folded by D-8: WiFi dropped at the drive's last live movement, the
    car drove on for eight minutes and parked, and the tail replayed when WiFi
    came back. The tail reopens the drive and advances its movement end; the
    tick anchors on that end, not on the last LIVE movement. Red on 177e04d9
    (closed at the drop, tail in no window)."""
    await _pin_session_settings(db_session, keep_rows)
    now = _now()
    _vin, device_id, token, _p_id = await _awaiting(
        db_session,
        make_livelink_vehicle,
        "t4tail8",
        start=now - timedelta(minutes=30),
        end=now - timedelta(minutes=16),
    )
    for minutes in (15, 14, 13, 12, 11, 10, 9, 8):
        await _post(client, token, now - timedelta(minutes=minutes), SPEED=50.0)
    [p] = await _sessions(db_session, device_id)
    assert (p.ended_at, p.movement_ended_at) == (None, now - timedelta(minutes=8))

    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)

    [p] = await _sessions(db_session, device_id)
    assert (p.started_at, p.ended_at) == (
        now - timedelta(minutes=30),
        now - timedelta(minutes=8),
    )


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_future_anchor_does_not_swallow_an_awaiting_drives_tail(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """E-10: one future-dated frame left `movement_ended_at` an hour ahead of
    the close. The awaiting anchor is the earlier of the two, so the tail
    inside the gap of the real close still reopens the drive, and the sweep
    lets the pointer go once the gap has passed. Red on 177e04d9 (the sweep
    kept the pointer against a future anchor)."""
    await _pin_session_settings(db_session, keep_rows)
    now = _now()
    _vin, device_id, token, p_id = await _awaiting(
        db_session,
        make_livelink_vehicle,
        "t4fanc",
        start=now - timedelta(minutes=30),
        end=now - timedelta(minutes=20),
        movement_end=now + timedelta(hours=1),
    )
    await _post(client, token, now - timedelta(minutes=19), SPEED=50.0)
    await _post(client, token, now - timedelta(minutes=18), SPEED=55.0)
    [p] = await _sessions(db_session, device_id)
    assert (p.id, p.ended_at) == (p_id, None)

    # Closed again with the future movement end still on it, awake and parked:
    # the sweep measures from the close, not from the hour ahead.
    p.ended_at = now - timedelta(minutes=20)
    p.movement_ended_at = now + timedelta(hours=1)
    await db_session.commit()
    await SessionService(db_session).expire_stale_movement_state(GAP)
    await db_session.commit()

    assert (await _device(db_session, device_id)).current_session_id is None


@pytest.mark.usefixtures("livelink_enabled")
async def test_frames_from_a_clock_minutes_fast_open_no_pointed_session(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """D-9: an awaiting drive, and two moving frames stamped seventeen minutes
    ahead (so neither live nor inside the reopen window). Nothing is pointed,
    the awaiting drive is untouched, no live evidence is left behind, and the
    builder makes nothing of a drive that ends in the future (M4). Red on
    177e04d9 (a pointed session opened at +17 min, which the tick then closed
    before it started)."""
    await _pin_session_settings(db_session, keep_rows)
    now = _now()
    _vin, device_id, token, p_id = await _awaiting(
        db_session,
        make_livelink_vehicle,
        "t4skw9",
        start=now - timedelta(minutes=30),
        end=now - timedelta(minutes=10),
    )
    await _post(client, token, now + timedelta(minutes=17), SPEED=50.0)
    await _post(client, token, now + timedelta(minutes=17, seconds=30), SPEED=55.0)

    sessions = await _sessions(db_session, device_id)
    assert [(s.id, s.ended_at) for s in sessions] == [(p_id, now - timedelta(minutes=10))]
    device = await _device(db_session, device_id)
    assert device.current_session_id == p_id
    assert device.movement_candidate_at is None


# --- B6-12: the live machine's own guards -----------------------------------------


async def test_a_parked_frame_reporting_speed_cannot_open_a_drive_on_its_odometer(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """1h: a live drive closed on the gap keeps its baseline. The car then drove
    off WiFi and came home; its first frame says SPEED 0 with the odometer up.
    A frame that reports a speed under the floor is a stopped car and proves
    nothing by odometer: it records the odometer and opens nothing. The next
    two moving frames open from the first of them. Red on 177e04d9 (the parked
    frame opened a drive at now)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4onehb", "1")
    service = SessionService(db_session)
    t0 = _now() - timedelta(minutes=20)
    await service.observe_telemetry(device, {"SPEED": 40.0, "ODOMETER": 1000.0}, t0, live=True)
    first = await service.observe_telemetry(
        device,
        {"SPEED": 45.0, "ODOMETER": 1000.2},
        t0 + timedelta(seconds=30),
        live=True,
    )
    assert first is not None
    device.last_seen = t0 + timedelta(seconds=30)
    await db_session.flush()
    closed = await service.check_session_timeouts(TIMEOUT, GAP)
    # The tick is global and the suite shares one database, so only this device's.
    assert [s.id for s in closed if s.device_id == device.device_id] == [first.id]
    assert device.current_session_id is None
    assert device.movement_baseline_km is not None

    now = _now()
    opened = await service.observe_telemetry(
        device, {"SPEED": 0.0, "ENGINE_RPM": 800.0, "ODOMETER": 1003.0}, now, live=True
    )

    assert opened is None
    assert float(device.movement_baseline_km) == pytest.approx(1003.0)
    assert [s.id for s in await _sessions(db_session, device.device_id)] == [first.id]
    await db_session.refresh(device)  # `_sessions` expired it

    await service.observe_telemetry(
        device,
        {"SPEED": 40.0, "ODOMETER": 1003.0},
        now + timedelta(seconds=5),
        live=True,
    )
    second = await service.observe_telemetry(
        device,
        {"SPEED": 45.0, "ODOMETER": 1003.1},
        now + timedelta(seconds=10),
        live=True,
    )
    assert second is not None
    assert (second.id != first.id, second.started_at) == (
        True,
        now + timedelta(seconds=5),
    )


async def test_a_stopped_frame_between_two_moving_ones_leaves_the_candidate_alone(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard (1h): a stopped frame with the odometer up between two
    moving frames proves nothing, but it doesn't throw away the first moving
    frame's candidate either, so the second one opens the drive from the first.
    Kills clearing the candidate in the stopped-frame branch."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4onec", "1")
    service = SessionService(db_session)
    t = _now() - timedelta(seconds=30)
    await service.observe_telemetry(device, {"SPEED": 40.0, "ODOMETER": 1000.0}, t, live=True)
    await service.observe_telemetry(
        device,
        {"SPEED": 0.0, "ODOMETER": 1001.0},
        t + timedelta(seconds=5),
        live=True,
    )
    opened = await service.observe_telemetry(
        device, {"SPEED": 45.0, "ODOMETER": 1001.0}, t + timedelta(seconds=10), live=True
    )

    assert opened is not None
    assert opened.movement_started_at == t


async def test_a_replay_never_opens_a_pointed_session_even_if_it_reaches_the_promote(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """D-9 and E-9: the promote with `live=False` and nothing to reopen opens
    nothing and drops the evidence it was handed, since it was a replay's. Red
    on 177e04d9 (it opened a pointed session)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device = await make_livelink_vehicle("t4prm9", "1")
    service = SessionService(db_session)
    now = _now()
    device.movement_candidate_at = now - timedelta(seconds=30)
    device.movement_baseline_km = Decimal("1000.00")
    await db_session.flush()

    result = await service._promote_to_driving(  # noqa: SLF001 - the guard under test
        device, extract_signals({"SPEED": 50.0}), now, GAP, live=False
    )

    assert result is None
    assert (device.movement_candidate_at, device.movement_baseline_km) == (None, None)
    assert await _sessions(db_session, device.device_id) == []


async def test_a_live_sample_at_or_before_a_future_close_opens_nothing(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard (D-12): a relink can close a drive at a future-dated
    `movement_ended_at`, so the device's last close is ahead of now. Two live
    moving frames before that close are that drive's, not a new one clamped to
    a future start. Kills dropping the T4-c decline."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4dcl", "1")
    now = _now()
    future_close = await _closed_session(
        db_session,
        vin,
        device.device_id,
        now - timedelta(minutes=30),
        now + timedelta(hours=1),
    )
    await db_session.commit()
    service = SessionService(db_session)

    await service.observe_telemetry(device, {"SPEED": 40.0}, now, live=True)
    opened = await service.observe_telemetry(
        device, {"SPEED": 45.0}, now + timedelta(seconds=10), live=True
    )

    assert opened is None
    assert device.movement_candidate_at is None
    assert [s.id for s in await _sessions(db_session, device.device_id)] == [future_close.id]


@pytest.mark.usefixtures("livelink_enabled")
async def test_in_contact_mode_a_replay_is_not_built(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard (D-11): the builder sits behind the observer's contact
    mode return, so a contact-mode instance keeps the contact rule and nothing
    else. Through ingest and through the observer itself, which a caller can
    reach without ingest's own mode gate. Kills routing before the mode check."""
    await _pin_session_settings(db_session, keep_rows)
    row = await db_session.get(Setting, "livelink_session_boundary_mode")
    assert row is not None
    row.value = "contact"
    await db_session.commit()
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4cmode")
    built: list[datetime] = []

    async def record(
        self: SessionService, device, pointed, samples, signals, sample_at, gap
    ) -> None:
        built.append(sample_at)

    monkeypatch.setattr(SessionService, "_reconcile_replayed_sample", record)
    await _replay(client, token, _now() - timedelta(hours=2))
    # Ingest's contact rule has opened a contact session by now, which the
    # verdict would route to the live machine anyway; a device with no session
    # is the one that shows where the mode check sits.
    _vin2, idle = await make_livelink_vehicle("t4cmode2", "1")
    await SessionService(db_session).observe_telemetry(
        idle, {"SPEED": 50.0}, _now() - timedelta(hours=2), live=False
    )

    assert built == []


@pytest.mark.usefixtures("livelink_enabled")
async def test_the_verdict_table(
    db_session: AsyncSession,
    make_livelink_vehicle,
    keep_rows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 1 of the B6-12 spec, row by row: which of the live machine, the
    builder or neither a sample reaches. Red on 177e04d9 (no builder exists)."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4vrdt", "1")
    service = SessionService(db_session)
    seen: list[str] = []

    async def build(
        self: SessionService, device, pointed, samples, signals, sample_at, gap
    ) -> None:
        seen.append("build")

    def confirm(self: SessionService, device, signals, sample_at, open_, *, window) -> bool:
        seen.append("live")
        return False

    monkeypatch.setattr(SessionService, "_reconcile_replayed_sample", build)
    monkeypatch.setattr(SessionService, "_confirm_movement", confirm)
    now = _now()

    async def verdict(at: datetime, *, live: bool) -> str:
        seen.clear()
        await service.observe_telemetry(device, {"SPEED": 50.0}, at, live=live)
        return seen[0] if seen else "none"

    # No pointed session.
    assert await verdict(now, live=True) == "live"
    assert await verdict(now - timedelta(hours=2), live=False) == "build"

    # An open live session P.
    p = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=now - timedelta(minutes=10),
        movement_started_at=now - timedelta(minutes=10),
        movement_ended_at=now - timedelta(minutes=1),
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db_session.add(p)
    await db_session.flush()
    device.current_session_id = p.id
    device.last_movement_at = now - timedelta(minutes=1)
    assert await verdict(now, live=True) == "live"
    assert await verdict(now - timedelta(minutes=11), live=False) == "build"
    # Exactly at its start is P's own first sample.
    assert await verdict(now - timedelta(minutes=10), live=False) == "live"
    assert await verdict(now - timedelta(minutes=5), live=False) == "live"
    assert await verdict(now + timedelta(hours=1), live=False) == "live"

    # Awaiting: closed at its last movement, pointer kept.
    p.ended_at = now - timedelta(minutes=1)
    await db_session.flush()
    assert await verdict(now, live=True) == "live"
    assert await verdict(now - timedelta(minutes=11), live=False) == "build"
    assert await verdict(now - timedelta(minutes=5), live=False) == "none"
    assert await verdict(now - timedelta(minutes=1), live=False) == "none"
    assert await verdict(now - timedelta(seconds=30), live=False) == "live"
    assert await verdict(now + timedelta(minutes=GAP) - timedelta(minutes=1), live=False) == "live"
    assert await verdict(now + timedelta(minutes=GAP), live=False) == "build"

    # A pre-movement (contact-mode) open session keeps the old rule whole.
    p.ended_at = None
    p.boundary_algorithm_version = 0
    await db_session.flush()
    assert await verdict(now - timedelta(minutes=11), live=False) == "live"


# --- B6-12: what the builder is fed ------------------------------------------------


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_creep_under_the_floor_is_not_a_replayed_drive_but_extends_one(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """E-5: two replayed frames under the floor with the odometer a km apart are
    a creep, not a drive, the same answer live gives. (Storage keeps whole km,
    so a creep only shows a rise across minutes.) A stopped frame with the
    odometer up after an established drive extends it, the same as live's open
    branch. Red on 177e04d9 (the live machine opened on the rise)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4crp"
    )
    device_id = device.device_id
    creep = _now() - timedelta(hours=2)
    await _post(client, token, creep, SPEED=2.0, ODOMETER=1000.0)
    await _post(client, token, creep + timedelta(minutes=13), SPEED=4.0, ODOMETER=1001.0)
    assert [s for s in await _sessions(db_session, device_id) if s.id != earlier_id] == []

    # More than a gap after the creep, so the drive's start can't walk back into it.
    drive = await _replay(client, token, creep + timedelta(minutes=30), odometer_from=1001.0)
    stopped = drive[-1] + timedelta(seconds=30)
    await _post(client, token, stopped, SPEED=0.0, ODOMETER=1004.0)
    # Parked after that: 1004.4 is stored as 1004, no higher than the drive's top
    # reading, so it's no rise and the drive stays where it stopped.
    await _post(client, token, stopped + timedelta(seconds=30), SPEED=0.0, ODOMETER=1004.4)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(drive[0], stopped)]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_odometer_under_a_pid_prefix_extends_its_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """E-11: `A6-ODOMETER` is an odometer to `extract_signals`, so the fast
    path's window maximum has to find it under its prefix too, not in a list of
    bare names. Whole km, because storage keeps the odometer in whole km and a
    half-km step would be flat on every other frame. Red on 177e04d9 (an open
    pointed session)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4pfx"
    )
    device_id = device.device_id
    base = _now() - timedelta(hours=2)
    stamps = [base + timedelta(seconds=30 * i) for i in range(5)]
    for i, at in enumerate(stamps):
        await _post(client, token, at, **{"A6-ODOMETER": 1000.0 + i})

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_thinned_replay_is_built_from_what_was_stored(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """D-16: the builder reads stored rows plus the frame in hand. With SPEED
    stored once per 30 s, a drive that starts inside an interval has its first
    frames thinned, so the session appears a frame later than live would open
    it, and its start is the stored burst. Its end is exact. Red on 177e04d9
    (the live machine opened on the second frame regardless)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4thn2"
    )
    device_id = device.device_id
    speed = await TelemetryService(db_session).auto_register_parameter("SPEED", None, None)
    speed.storage_interval_seconds = 30
    await db_session.commit()
    try:
        base = _now() - timedelta(hours=2)
        parked = base - timedelta(seconds=10)
        await _post(client, token, parked, SPEED=0.0)
        stamps = [base + timedelta(seconds=3 * i) for i in range(40)]
        await _post(client, token, stamps[0], SPEED=50.0)
        await _post(client, token, stamps[1], SPEED=52.0)
        assert [s for s in await _sessions(db_session, device_id) if s.id != earlier_id] == []
        for at in stamps[2:]:
            await _post(client, token, at, SPEED=50.0)

        replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
        assert _spans(replayed) == [(parked, stamps[-1])]
    finally:
        speed = await TelemetryService(db_session).auto_register_parameter("SPEED", None, None)
        speed.storage_interval_seconds = 0
        await db_session.commit()


@pytest.mark.usefixtures("livelink_enabled")
async def test_one_replayed_speed_spike_on_a_parked_car_builds_no_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """I1: a parked car reading 1001.4 km is stored as 1001. One frame at 20 km/h
    with the same raw reading used to beat its own stored value, so a single
    above-floor sample counted as odometer-proven and built a drive. On the
    stored scale it's no rise, and one sample is no drive. Red on 3c744c37."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4spk")
    device_id = device.device_id
    t = _now() - timedelta(hours=2)
    for i in range(3):
        await _post(client, token, t + timedelta(seconds=30 * i), SPEED=0.0, ODOMETER=1001.4)
    await _post(client, token, t + timedelta(seconds=90), SPEED=20.0, ODOMETER=1001.4)
    await _post(client, token, t + timedelta(seconds=120), SPEED=0.0, ODOMETER=1001.4)

    assert await _sessions(db_session, device_id) == []


@pytest.mark.parametrize("bad", [1_700_000.0, 18_000.0], ids=["past-the-cap", "jump"])
@pytest.mark.usefixtures("livelink_enabled")
async def test_a_refused_odometer_reading_builds_no_replayed_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows, bad: float
) -> None:
    """I1's second form: an odometer the sanitizer refuses (past its 1.6M km cap,
    or a jump of more than 16,000 km) is never stored, so it can't be the rise
    that builds a drive either. A 0xFFFFFF overflow never gets this far: the
    validator's 2M km range drops it first. Red on 3c744c37."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4odbad")
    device_id = device.device_id
    t = _now() - timedelta(hours=2)
    await _post(client, token, t, ODOMETER=1000.0)
    await _post(client, token, t + timedelta(seconds=30), ODOMETER=1000.0)
    await _post(client, token, t + timedelta(seconds=60), ODOMETER=bad)

    assert await _sessions(db_session, device_id) == []


@pytest.mark.parametrize("bad", [1_700_000.0, 18_000.0], ids=["past-the-cap", "jump"])
@pytest.mark.usefixtures("livelink_enabled")
async def test_a_refused_odometer_reading_opens_no_live_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows, bad: float
) -> None:
    """The live machine's half of I1's second form, the same screen: a refused
    reading isn't evidence there either. Red on 3c744c37 (it beat the baseline
    and opened a drive)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4odbdl")
    device_id = device.device_id
    now = _now()
    await _post(client, token, now - timedelta(seconds=20), ODOMETER=1000.0)
    await _post(client, token, now - timedelta(seconds=10), ODOMETER=bad)

    assert await _sessions(db_session, device_id) == []


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replayed_head_extends_a_drive_that_isnt_the_latest(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """M3: a replayed sample just before an older drive's start is that drive's
    head. The clamp only has to keep it clear of the drive before it; a later
    drive's close used to push the head past the drive's own start, so it was
    refused and the sample landed nowhere. Red on 3c744c37."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4hdcl")
    device_id = device.device_id
    base = _now() - timedelta(hours=3)
    older = await _closed_session(db_session, vin, device_id, base, base + timedelta(minutes=20))
    await _closed_session(
        db_session, vin, device_id, base + timedelta(minutes=60), base + timedelta(minutes=80)
    )
    older_id = older.id
    await db_session.commit()

    await _post(client, token, base - timedelta(minutes=2), SPEED=50.0)

    [first, _later] = await _sessions(db_session, device_id)
    assert (first.id, first.started_at) == (older_id, base - timedelta(minutes=2))


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_fast_clock_builds_no_future_drive_and_live_driving_still_opens(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """M4: two moving frames from a clock seventeen minutes fast used to build a
    closed drive ending in the future, and then every live drive in those
    seventeen minutes was turned away as being before the last close. The
    builder skips a drive that ends after now, so the real drive opens. Red on
    3c744c37."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4fast")
    device_id = device.device_id
    now = _now()
    await _post(client, token, now + timedelta(minutes=17), SPEED=50.0)
    await _post(client, token, now + timedelta(minutes=17, seconds=30), SPEED=55.0)
    assert await _sessions(db_session, device_id) == []

    await _post(client, token, now - timedelta(seconds=10), SPEED=50.0)
    await _post(client, token, now, SPEED=55.0)

    assert _spans(await _sessions(db_session, device_id)) == [(now - timedelta(seconds=10), None)]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_fast_clock_frame_does_not_extend_a_closed_drive_into_the_future(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """M4 on the fast path: a frame ten minutes ahead, within the gap of a drive
    that closed three minutes ago, would move that drive's end into the future,
    with the same effect on live drives. Red on 3c744c37."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4fastx")
    device_id = device.device_id
    now = _now()
    await _closed_session(
        db_session, vin, device_id, now - timedelta(minutes=30), now - timedelta(minutes=3)
    )
    await db_session.commit()

    await _post(client, token, now + timedelta(minutes=10), SPEED=50.0)

    assert _spans(await _sessions(db_session, device_id)) == [
        (now - timedelta(minutes=30), now - timedelta(minutes=3))
    ]


# --- B6-12: a replay never confirms against live evidence (concern 1) -------------


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_live_odometer_frame_then_an_older_replay_keeps_the_replays_bounds(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Re-review 4's probe 1: a replayed drive, a live odometer frame at now,
    then a replay of a drive an hour old. The replay is built from its rows
    and never meets the live candidate. Red on 177e04d9 ((B[0], now))."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4prb1"
    )
    device_id = device.device_id
    first = await _replay(client, token, _now() - timedelta(hours=3), odometer_from=1000.0)
    await _post(client, token, _now(), ODOMETER=1050.0)
    b = await _replay(client, token, _now() - timedelta(hours=1), odometer_from=1020.0)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(first[0], first[-1]), (b[0], b[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_one_live_moving_frame_then_an_older_replay_keeps_the_replays_bounds(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Re-review 4's probe 2: one live above-floor frame (a spike, or rolling
    into WiFi range), then a replay an hour old. Red on 177e04d9 ((B[0], now))."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4prb2"
    )
    device_id = device.device_id
    await _post(client, token, _now(), SPEED=50.0)
    b = await _replay(client, token, _now() - timedelta(hours=1))

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(b[0], b[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_future_dated_frame_leaves_no_candidate_for_live_frames_to_confirm(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """A frame an hour ahead with no pointed session is a replay to the builder,
    which finds nothing near it and builds nothing; it never touches the live
    evidence. The live frames that follow open from themselves. Red on
    177e04d9 (`movement_ended_at` an hour ahead)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t4futc")
    device_id = device.device_id
    t = _now()
    await _post(client, token, t + timedelta(hours=1), SPEED=50.0)
    await _post(client, token, t, SPEED=50.0)
    await _post(client, token, t + timedelta(seconds=5), SPEED=52.0)

    sessions = await _sessions(db_session, device_id)
    assert [(s.started_at, s.movement_ended_at, s.ended_at) for s in sessions] == [
        (t, t + timedelta(seconds=5), None)
    ]


# --- B6-12: a reopen or an extension never crosses a VIN (E-1) ---------------------


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_relinked_devices_first_drive_does_not_reopen_the_old_cars(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard (E-1, R8): the dongle moves from car A to car B within
    the gap of A's last drive. B's first movement opens a new drive on B's VIN;
    A's closed drive is not reopened by time. Kills dropping the VIN from the
    reopen of the latest closed drive."""
    await _pin_session_settings(db_session, keep_rows)
    vin_a, device, token = await _linked(db_session, make_livelink_vehicle, "t4rlka")
    device_id = device.device_id
    vin_b, _device_b = await make_livelink_vehicle("t4rlkb", "1")
    now = _now()
    await _post(client, token, now - timedelta(seconds=40), SPEED=40.0)
    await _post(client, token, now - timedelta(seconds=30), SPEED=45.0)
    assert [(s.vin, s.ended_at) for s in await _sessions(db_session, device_id)] == [(vin_a, None)]

    assert await LiveLinkService(db_session).link_device_to_vehicle(device_id, vin_b)
    await _post(client, token, now - timedelta(seconds=10), SPEED=40.0)
    await _post(client, token, now, SPEED=45.0)

    assert [(s.vin, s.started_at, s.ended_at) for s in await _sessions(db_session, device_id)] == [
        (vin_a, now - timedelta(seconds=40), now - timedelta(seconds=30)),
        (vin_b, now - timedelta(seconds=10), None),
    ]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_relinked_devices_replay_does_not_extend_the_old_cars_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """E-1 on the fast path: car A's closed drive ended five minutes before car
    B's replayed drive begins, on the same dongle. The replay builds B's own
    session on B's VIN. Red on 177e04d9 (an open pointed session)."""
    await _pin_session_settings(db_session, keep_rows)
    vin_a, device, token = await _linked(db_session, make_livelink_vehicle, "t4rlkc")
    device_id = device.device_id
    vin_b, _device_b = await make_livelink_vehicle("t4rlkd", "1")
    now = _now()
    await _closed_session(
        db_session,
        vin_a,
        device_id,
        now - timedelta(minutes=130),
        now - timedelta(minutes=125),
    )
    await db_session.commit()
    assert await LiveLinkService(db_session).link_device_to_vehicle(device_id, vin_b)

    b = await _replay(client, token, now - timedelta(minutes=120))

    assert [(s.vin, s.started_at, s.ended_at) for s in await _sessions(db_session, device_id)] == [
        (vin_a, now - timedelta(minutes=130), now - timedelta(minutes=125)),
        (vin_b, b[0], b[-1]),
    ]


@pytest.mark.usefixtures("livelink_enabled")
async def test_the_builder_never_extends_another_vins_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """E-1, the builder's half: the dongle's last drive on car A ended at the
    very instant car B's drive starts. The two windows touch, which the builder
    read as one drive when it matched on the device alone, and car A's drive
    took car B's movement. B gets a drive of its own. Through the name SD
    backfill calls. Red on 177e04d9 (A's drive was extended)."""
    await _pin_session_settings(db_session, keep_rows)
    vin_a, device, token = await _linked(db_session, make_livelink_vehicle, "t4rlke")
    device_id = device.device_id
    vin_b, _device_b = await make_livelink_vehicle("t4rlkf", "1")
    t = _now() - timedelta(hours=2)
    await _closed_session(db_session, vin_a, device_id, t - timedelta(minutes=20), t)
    await db_session.commit()
    assert await LiveLinkService(db_session).link_device_to_vehicle(device_id, vin_b)

    built = await TelemetryService(db_session)._reconstruct_sessions_from_batch(  # noqa: SLF001
        vin_b,
        device_id,
        [(t, "SPEED", 40.0), (t + timedelta(seconds=30), "SPEED", 45.0)],
    )
    await db_session.flush()

    assert built == 1
    assert [(s.vin, s.started_at, s.ended_at) for s in await _sessions(db_session, device_id)] == [
        (vin_a, t - timedelta(minutes=20), t),
        (vin_b, t, t + timedelta(seconds=30)),
    ]


async def test_a_pointed_drive_with_only_a_future_end_closes_at_its_own_start(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """D-9's tick half: the device's last live movement is an earlier drive's,
    and the open drive's only movement end is a future-dated frame's. The tick
    has nothing to anchor on but the drive's own start, and must never close it
    before that. Red on 177e04d9 (the future end held it open)."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4fut3", "1")
    now = _now()
    start = now - timedelta(hours=1)
    drive = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=start,
        movement_started_at=start,
        movement_ended_at=now + timedelta(hours=1),
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db_session.add(drive)
    await db_session.flush()
    device.current_session_id = drive.id
    device.last_movement_at = now - timedelta(days=3)
    device.last_seen = now
    await db_session.flush()

    closed = await SessionService(db_session).check_session_timeouts(TIMEOUT, GAP)

    assert drive.id in [s.id for s in closed]
    assert drive.ended_at == start


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_tail_sample_older_than_a_live_candidate_by_a_gap_does_not_reopen_its_drive(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """3.5's guard on the one path a replay still meets live evidence: a drive
    the contact clock closed twenty minutes ago, a live moving frame now (a
    candidate), then a replayed sample from just after that close. The sample
    is the drive's tail, but the candidate is more than a gap newer, so it
    isn't the sample that comes next, and one tail sample doesn't reopen the
    drive on it. Red on 177e04d9 (reopened)."""
    await _pin_session_settings(db_session, keep_rows)
    now = _now()
    _vin, device_id, token, p_id = await _awaiting(
        db_session,
        make_livelink_vehicle,
        "t4gclr",
        start=now - timedelta(minutes=40),
        end=now - timedelta(minutes=20),
    )
    await _post(client, token, now, SPEED=50.0)
    await _post(client, token, now - timedelta(minutes=19), SPEED=50.0)

    [p] = await _sessions(db_session, device_id)
    assert (p.id, p.ended_at) == (p_id, now - timedelta(minutes=20))


async def test_live_frames_inside_an_awaiting_drives_window_do_not_reopen_it(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """D-4's live half: two live frames stamped inside the window of a drive
    that closed a minute ago are that drive's late readings, not its return.
    Nothing reopens and nothing opens. Red on 177e04d9 (a negative delta
    reopened it)."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4awlv", "1")
    now = _now()
    p = await _closed_session(
        db_session, vin, device.device_id, now - timedelta(minutes=20), now - timedelta(minutes=1)
    )
    device.current_session_id = p.id
    device.last_movement_at = now - timedelta(minutes=1)
    await db_session.flush()
    service = SessionService(db_session)

    await service.observe_telemetry(
        device, {"SPEED": 40.0}, now - timedelta(minutes=2, seconds=10), live=True
    )
    opened = await service.observe_telemetry(
        device, {"SPEED": 45.0}, now - timedelta(minutes=2), live=True
    )

    assert opened is None
    assert p.ended_at == now - timedelta(minutes=1)
    assert [s.id for s in await _sessions(db_session, device.device_id)] == [p.id]


# --- R9: which sessions the gap clock and the sweep let go -------------------------


async def test_a_live_drive_that_started_on_its_last_movement_is_live(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard: a live session can start on its confirming sample (a
    future candidate made it the start), so `started_at == last_movement_at`.
    The gap clock closes it there and lets the pointer go. Kills keeping the
    pointer on a gap close (B6-12: a gap close always releases it)."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4lvst", "1")
    moved = _now() - timedelta(hours=1)
    db_session.add(
        DriveSession(
            vin=vin,
            device_id=device.device_id,
            started_at=moved - timedelta(hours=3),
            ended_at=moved - timedelta(hours=2),
            duration_seconds=3600,
            boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
        )
    )
    live = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=moved,
        movement_started_at=moved,
        movement_ended_at=moved,
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db_session.add(live)
    await db_session.flush()
    device.last_movement_at = moved
    device.current_session_id = live.id
    await db_session.flush()

    await SessionService(db_session).check_session_timeouts(TIMEOUT, GAP)

    assert live.ended_at == moved
    assert device.current_session_id is None


async def test_a_zero_length_live_drive_awaiting_a_reopen_is_let_go_on_the_gap(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard: a live drive that started on its last movement and was
    closed there by the contact clock is zero-length and closed at its own
    start. Once the gap has passed the sweep lets the pointer go, even with the
    car awake. Kills dropping the sweep's gap compare."""
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4zero", "1")
    moved = _now() - timedelta(minutes=GAP + 1)
    live = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=moved,
        ended_at=moved,
        duration_seconds=0,
        movement_started_at=moved,
        movement_ended_at=moved,
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )
    db_session.add(live)
    await db_session.flush()
    device.last_movement_at = moved
    device.current_session_id = live.id
    device.last_seen = _now()
    await db_session.flush()

    await SessionService(db_session).expire_stale_movement_state(GAP)

    assert device.current_session_id is None


@pytest.mark.usefixtures("livelink_enabled")
async def test_live_frames_from_a_parked_car_do_not_extend_a_replayed_drive(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """F2-6, under B6-12: a car awake and parked keeps sending live frames. The
    replay's drive is a closed session they never see, and a tick changes
    nothing. Red on 177e04d9 (the session was open until the tick)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4park"
    )
    device_id = device.device_id
    stamps = await _replay(client, token, _now() - timedelta(hours=2))
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0)
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0)

    await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert _spans(replayed) == [(stamps[0], stamps[-1])]


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


async def test_two_devices_on_one_car_do_not_rate_check_each_other(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """B6-6: the check read the VIN's latest value, which another device on the
    car had just written. Each device is compared with its own last reading.
    Red on 4954e3a3 (device B's 100 rejected against device A's 0)."""
    vin, first = await make_livelink_vehicle("t4rate2", "1")
    second = LiveLinkDevice(device_id="t4rate2dev0002", vin=vin, enabled=True, kind="wican")
    db_session.add(second)
    await db_session.flush()
    telemetry = TelemetryService(db_session)
    await telemetry.auto_register_parameter(RATE_KEY, "km/h", "speed")

    at = _now() - timedelta(seconds=30)
    await telemetry.store_telemetry(vin, first.device_id, {RATE_KEY: 0.0}, {}, timestamp=at)
    result = await telemetry.store_telemetry(
        vin, second.device_id, {RATE_KEY: 100.0}, {}, timestamp=at + timedelta(seconds=1)
    )

    assert result.validated_data == {RATE_KEY: 100.0}


async def test_a_storage_interval_does_not_thin_the_rate_baseline(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """Wave B review M-1: with a 300 s storage interval the device's newest raw
    row was up to five minutes old, so a frame-to-frame jump went unchecked.
    The check compares with the last reading it accepted from the device, kept
    in memory. 60 degrees in 10 s is 6 C/s, over the 5 C/s line. Red on
    f3a8b81c (stored)."""
    vin, device = await make_livelink_vehicle("t4thin", "1")
    key = "T4_THIN_TEMP"
    telemetry = TelemetryService(db_session)
    param = await telemetry.auto_register_parameter(key, "°C", "temperature")
    param.storage_interval_seconds = 300
    await db_session.flush()
    t0 = _now() - timedelta(minutes=10)
    for i in range(20):
        await telemetry.store_telemetry(
            vin, device.device_id, {key: 20.0}, {}, timestamp=t0 + timedelta(seconds=10 * i)
        )

    result = await telemetry.store_telemetry(
        vin, device.device_id, {key: -40.0}, {}, timestamp=t0 + timedelta(seconds=200)
    )

    assert key not in result.validated_data


async def test_after_a_restart_the_rate_check_falls_back_to_the_stored_row(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """Regression guard: with nothing in memory (a restart) the device's newest
    raw row is the baseline, as before. Kills dropping the fallback."""
    from app.services.telemetry_validator import forget_accepted_readings

    vin, device = await make_livelink_vehicle("t4rest", "1")
    telemetry = TelemetryService(db_session)
    await telemetry.auto_register_parameter(RATE_KEY, "km/h", "speed")
    at = _now() - timedelta(seconds=30)
    await telemetry.store_telemetry(vin, device.device_id, {RATE_KEY: 0.0}, {}, timestamp=at)
    forget_accepted_readings()

    result = await telemetry.store_telemetry(
        vin, device.device_id, {RATE_KEY: 100.0}, {}, timestamp=at + timedelta(seconds=1)
    )

    assert result.validated_data == {}


async def test_one_device_jumping_is_still_rate_rejected(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """Regression guard: the device's own previous reading still counts. Kills
    a check that finds no previous reading at all."""
    vin, device = await make_livelink_vehicle("t4rate3", "1")
    telemetry = TelemetryService(db_session)
    await telemetry.auto_register_parameter(RATE_KEY, "km/h", "speed")

    at = _now() - timedelta(seconds=30)
    await telemetry.store_telemetry(vin, device.device_id, {RATE_KEY: 0.0}, {}, timestamp=at)
    result = await telemetry.store_telemetry(
        vin, device.device_id, {RATE_KEY: 100.0}, {}, timestamp=at + timedelta(seconds=1)
    )

    assert result.validated_data == {}


# --- T4-e and B6-7: when the latest value moves ------------------------------------


async def _latest_row(db: AsyncSession, vin: str, key: str) -> VehicleTelemetryLatest:
    db.expire_all()
    return (
        await db.execute(
            select(VehicleTelemetryLatest).where(
                VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == key
            )
        )
    ).scalar_one()


@pytest.mark.parametrize("policy", ["always", "if_newer"])
@pytest.mark.parametrize(
    ("ahead", "healed"),
    [
        # A dongle a few minutes fast: a replayed older reading must not
        # displace its live value. Red on 4954e3a3 (displaced).
        (timedelta(minutes=3), False),
        # Regression guard: past the tolerance it's still a bad clock, and
        # the next sane reading heals it (T4-a).
        (timedelta(minutes=7), True),
    ],
    ids=["within-5-min", "past-5-min"],
)
async def test_the_future_latest_heal_allows_five_minutes_of_skew(
    db_session: AsyncSession,
    make_livelink_vehicle,
    policy: str,
    ahead: timedelta,
    healed: bool,
) -> None:
    """Carry 12 (T4-e), on both writers."""
    vin, device = await make_livelink_vehicle("t4skw", f"{policy[0]}{ahead.seconds // 60}")
    key = f"T4_SKEW_{policy.upper()}"
    await _seed_latest(db_session, vin, [(key, 999.0, _now() + ahead)])
    await db_session.commit()

    sane_at = _now() - timedelta(minutes=1)
    await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, 42.0)],
        timestamp=sane_at,
        policy=StoragePolicy(latest=policy),
    )
    await db_session.commit()

    latest = await _latest_row(db_session, vin, key)
    assert (latest.value == 42.0) is healed


async def test_an_exact_duplicate_does_not_refresh_the_latest_value(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """B6-7: the same value at the same instant, sent again, left the dashboard
    thinking the reading was fresh. Red on 4954e3a3 (received_at moved)."""
    vin, device = await make_livelink_vehicle("t4dupl", "1")
    key = "T4_DUP_LATEST"
    at = _now() - timedelta(minutes=10)
    db_session.add(
        VehicleTelemetryLatest(vin=vin, param_key=key, value=42.0, timestamp=at, received_at=at)
    )
    await db_session.commit()

    await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, 42.0)],
        timestamp=at,
        policy=StoragePolicy(latest="always"),
    )
    await db_session.commit()

    assert (await _latest_row(db_session, vin, key)).received_at == at


async def test_a_new_value_at_the_same_instant_still_wins(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """Regression guard: T4's tie rule, the later arrival at an equal timestamp
    is the value. Kills a strict `<` for every equal timestamp."""
    vin, device = await make_livelink_vehicle("t4tiev", "1")
    key = "T4_TIE_LATEST"
    at = _now() - timedelta(minutes=10)
    db_session.add(
        VehicleTelemetryLatest(vin=vin, param_key=key, value=42.0, timestamp=at, received_at=at)
    )
    await db_session.commit()

    await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, 43.0)],
        timestamp=at,
        policy=StoragePolicy(latest="always"),
    )
    await db_session.commit()

    latest = await _latest_row(db_session, vin, key)
    assert (latest.value, latest.timestamp) == (43.0, at)
    assert latest.received_at > at


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


async def test_odometer_keys_with_one_timestamp_break_the_tie_on_received_at(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Two odometer keys stamped alike: the one that arrived last wins, every time.

    The later arrival is the key that sorts LATER by name, so the `param_key`
    tie-break alone would pick the other one: `received_at.desc()` is what
    decides. Regression guard; kills dropping that ordering (carry 3).
    """
    await _pin_session_settings(db_session, keep_rows)
    vin, device = await make_livelink_vehicle("t4tie", "1")
    t0 = datetime(2026, 9, 7, 8, 0, 0)
    # Inserted older-arrival first, so storage order alone would pick it.
    for key, value, received in (
        ("A6-ODOMETER", 51000.0, t0),
        ("ODOMETER", 51111.0, t0 + timedelta(seconds=30)),
    ):
        db_session.add(
            VehicleTelemetryLatest(
                vin=vin, param_key=key, value=value, timestamp=t0, received_at=received
            )
        )
        await db_session.flush()

    started = await SessionService(db_session).start_session(device, t0 + timedelta(minutes=1))
    assert started.start_odometer == 51111.0


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
