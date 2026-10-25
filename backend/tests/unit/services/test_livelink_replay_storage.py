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


async def test_a_replay_that_runs_past_the_previous_close_is_clamped_to_it(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """Regression guard: one sample after the close is enough to open, with the
    start clamped to the close and the movement span running forwards. Kills
    declining on the candidate alone."""
    await _pin_session_settings(db_session, keep_rows)
    t0 = datetime(2026, 9, 6, 9, 0, 0)
    device, _earlier_id = await _closed_drive_around(db_session, make_livelink_vehicle, "t4cls", t0)
    close = t0 + timedelta(hours=1)
    after = close + timedelta(minutes=1)

    service = SessionService(db_session)
    await service.observe_telemetry(
        device, {"SPEED": 40.0}, close - timedelta(minutes=1), live=False
    )
    session = await service.observe_telemetry(device, {"SPEED": 45.0}, after, live=False)
    await db_session.flush()

    assert session is not None
    assert session.started_at == close
    assert (session.movement_started_at, session.movement_ended_at) == (close, after)


async def test_ecu_offline_leaves_a_held_closed_session_alone(
    db_session: AsyncSession, make_livelink_vehicle, keep_rows
) -> None:
    """T4-b: the pointer can name a CLOSED session (awaiting, or a held replay).

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
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)

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

    The replay-built session is held open while its samples keep arriving
    (B6-9), so no tick closes it mid-replay. It closes once they stop, and the
    pointer goes once the device has been quiet for the gap.
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
    assert [(s.started_at, s.ended_at) for s in replayed] == [(stamps[0], None)]
    session_id = replayed[0].id
    assert (await _device(db_session, device_id)).current_session_id == session_id

    # The replay has stopped arriving: the next tick closes it at its last
    # sample and keeps the pointer, the way any replay-built close does.
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [(stamps[0], stamps[-1])]
    assert (await _device(db_session, device_id)).current_session_id == session_id

    # Once the device goes quiet past the gap, the next tick lets go.
    await _quiet(db_session, device_id, minutes=GAP + 1)
    await _tick(db_session, caplog)

    assert (await _device(db_session, device_id)).current_session_id is None
    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [(stamps[0], stamps[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_replays_last_sample_lands_in_its_session_after_a_tick(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B6-9: a tick mid-replay closed the replay-built session, and one sample
    after it was only a candidate, so the drive ended before its last reading.
    Held open while the replay arrives, the tail extends it, and the close
    once the replay stops takes it in. Red on 4954e3a3 (ended at stamps[-1])."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4tail"
    )
    device_id = device.device_id
    stamps = await _replay(client, token, _now() - timedelta(hours=2))
    await _tick(db_session, caplog)
    tail = stamps[-1] + timedelta(seconds=30)
    await _post(client, token, tail, SPEED=35.0)

    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [(stamps[0], tail)]


@pytest.mark.usefixtures("livelink_enabled")
async def test_two_replayed_drives_in_one_upload_stay_two(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Wave B review I-1: a dongle off WiFi all day uploads a morning and an
    evening drive together. Held open for the replay, the morning session took
    the evening's movement too: one 8-hour drive. Movement more than the gap
    after the held session's last is a new drive, by sample time, the same
    rule `_reopen_awaiting` uses (R9). Red on f3a8b81c (one session)."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4two"
    )
    device_id = device.device_id
    morning = await _replay(client, token, _now() - timedelta(hours=10))
    await _tick(db_session, caplog)
    evening = await _replay(client, token, _now() - timedelta(hours=2))
    await _tick(db_session, caplog)
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [
        (morning[0], morning[-1]),
        (evening[0], evening[-1]),
    ]


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_contact_mode_drive_survives_a_switch_to_movement_mode(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
) -> None:
    """Re-review (FW-B-r2): a drive opened in contact mode has no movement
    fields, so the ingest gap check measured from its start and closed it there,
    zero minutes long, on the first sample after the switch. The gap clock
    leaves a pre-movement session to the contact rule, and so does this now.
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
    """Re-review (FW-B-r2): a bad device clock stamped one frame an hour ahead,
    and the ingest gap check closed the live drive 10 s in. A live session is
    the gap clock's to close, on the tick. Red on ca2e0603 (two sessions)."""
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


@pytest.mark.usefixtures("livelink_enabled")
async def test_a_stop_inside_the_gap_is_still_one_replayed_drive(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression guard: a ten-minute stop is under the 15-minute gap, so the
    split leaves it one drive. Kills splitting at any distance in sample time."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4stop"
    )
    device_id = device.device_id
    first = await _replay(client, token, _now() - timedelta(hours=3))
    await _tick(db_session, caplog)
    second = await _replay(client, token, first[-1] + timedelta(minutes=10))
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _tick(db_session, caplog)

    replayed = [s for s in await _sessions(db_session, device_id) if s.id != earlier_id]
    assert [(s.started_at, s.ended_at) for s in replayed] == [(first[0], second[-1])]


@pytest.mark.usefixtures("livelink_enabled")
async def test_live_frames_from_a_parked_car_do_not_hold_a_replay_built_session(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    keep_rows,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression guard (F2-6): only replayed samples hold it. A car awake and
    parked keeps sending live frames, and those mustn't stop the drive-gap
    clock. Kills holding on any recent row."""
    await _pin_session_settings(db_session, keep_rows)
    _vin, device, token, earlier_id, _end = await _device_with_an_earlier_drive(
        db_session, make_livelink_vehicle, "t4park"
    )
    device_id = device.device_id
    stamps = await _replay(client, token, _now() - timedelta(hours=2))
    await _quiet(db_session, device_id, minutes=TIMEOUT + 1)
    await _post(client, token, _now(), ENGINE_RPM=800.0, SPEED=0.0)

    await _tick(db_session, caplog)

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
