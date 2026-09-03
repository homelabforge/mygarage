"""The measured production day, replayed end to end.

Every other test in this change exercises one rule. This one replays the pattern
that motivated the whole rework and asserts the outcome a user would describe,
because a set of individually correct rules can still compose into a wrong day.

The pattern is from Diamond on 2026-09-01, not invented:

- the Mirage sat parked and published a battery-voltage heartbeat about every 95
  minutes, and every recorded session began within 0.1s of one, twelve for
  twelve;
- fifteen sessions were recorded, thirteen of which held no telemetry at all;
- the vehicle actually drove 10.0 km, and was credited 0.0.

Under the old rule this day is fifteen drives and no distance. It should be one
drive with its distance, and nothing else.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.services import telemetry_service as telemetry_module
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService

pytestmark = pytest.mark.asyncio

DAY = datetime(2026, 9, 1, 0, 0, 0)
HEARTBEAT_MINUTES = 95
GAP = 15
TIMEOUT = 5


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    return list(
        (
            await db.execute(
                select(DriveSession)
                .where(DriveSession.device_id == device_id)
                .order_by(DriveSession.started_at)
            )
        )
        .scalars()
        .all()
    )


class TestAMeasuredDay:
    async def test_a_parked_day_records_no_drives_and_one_trip_records_one(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ):
        vin, device = await make_livelink_vehicle("scenario", "1")
        service = SessionService(db_session)

        # Through `store_telemetry`, the real ingest entry point that MQTT and
        # HTTPS both funnel into, rather than calling the observer directly.
        # Driving the observer by hand would test the state machine and skip the
        # wiring, and the wiring is where a previous design revision hooked only
        # one of three paths.
        telemetry = TelemetryService(db_session)

        async def feed(at: datetime, samples: dict) -> None:
            # `store_telemetry` compares the sample time against its own
            # `utc_now()` to decide whether a reading is live or a replay, so the
            # clock has to move with the scenario or every payload here reads as
            # a year-old replay.
            monkeypatch.setattr(telemetry_module, "utc_now", lambda: at)
            device.last_seen = at
            await telemetry.store_telemetry(
                vin=vin,
                device_id=device.device_id,
                autopid_data=dict(samples),
                config={},
                timestamp=at,
            )
            await service.check_session_timeouts(
                timeout_minutes=TIMEOUT, gap_minutes=GAP, now=at
            )
            await db_session.flush()

        # 00:00 to 14:00 parked: nine heartbeats at the measured interval.
        minute = 0
        while minute < 14 * 60:
            await feed(DAY + timedelta(minutes=minute), {"BATTERY_VOLTAGE": 12.4})
            minute += HEARTBEAT_MINUTES

        assert await _sessions(db_session, device.device_id) == [], (
            "a parked morning recorded a drive; under the old rule this alone "
            "produced nine of the day's fifteen sessions"
        )

        # 14:00 the vehicle is started, warms up for two minutes, then drives
        # 10.0 km, stopping once at a light.
        drive_start = DAY + timedelta(hours=14)
        await feed(drive_start, {"ENGINE_RPM": 700, "SPEED": 0, "A6-ODOMETER": 40_000.0})
        await feed(drive_start + timedelta(minutes=1), {"ENGINE_RPM": 900, "SPEED": 0})
        await feed(drive_start + timedelta(minutes=2), {"SPEED": 35, "ENGINE_RPM": 1800})
        await feed(drive_start + timedelta(minutes=3), {"SPEED": 52, "ENGINE_RPM": 2200})
        await feed(drive_start + timedelta(minutes=5), {"SPEED": 0, "ENGINE_RPM": 800})
        await feed(drive_start + timedelta(minutes=6), {"SPEED": 48, "ENGINE_RPM": 2000})
        await feed(
            drive_start + timedelta(minutes=12),
            {"SPEED": 30, "ENGINE_RPM": 1500, "A6-ODOMETER": 40_010.0},
        )

        # Parked again for the evening, still checking in.
        minute = 14 * 60 + HEARTBEAT_MINUTES
        while minute < 24 * 60:
            await feed(DAY + timedelta(minutes=minute), {"BATTERY_VOLTAGE": 12.4})
            minute += HEARTBEAT_MINUTES

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1, (
            f"the day recorded {len(sessions)} drives; the vehicle made one"
        )

        drive = sessions[0]
        assert drive.started_at == drive_start, (
            "the window must open at the ignition burst, which is where the "
            "opening odometer reading is"
        )
        assert drive.ended_at == drive_start + timedelta(minutes=12), (
            "the drive must end at the last movement, not at the evening's "
            "heartbeats, which would pad it by hours"
        )
        assert drive.distance_km == pytest.approx(10.0), (
            "this is the 10.0 km that was credited as 0.0"
        )
        assert drive.max_speed == pytest.approx(52.0)
        assert drive.boundary_algorithm_version == 1

    async def test_the_light_stop_did_not_split_the_drive(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ):
        """Stated separately because it is the thing the two clocks buy.

        A one-minute stop is inside both clocks; the assertion that matters is
        that the CONTACT clock, at five minutes, is not what decides it. So this
        stops for eight minutes: past the contact timeout, inside the drive gap.
        """
        vin, device = await make_livelink_vehicle("scenario", "2")
        service = SessionService(db_session)

        telemetry = TelemetryService(db_session)

        async def feed(at: datetime, samples: dict) -> None:
            monkeypatch.setattr(telemetry_module, "utc_now", lambda: at)
            device.last_seen = at
            await telemetry.store_telemetry(
                vin=vin,
                device_id=device.device_id,
                autopid_data=dict(samples),
                config={},
                timestamp=at,
            )
            await service.check_session_timeouts(
                timeout_minutes=TIMEOUT, gap_minutes=GAP, now=at
            )
            await db_session.flush()

        start = DAY + timedelta(hours=9)
        await feed(start, {"SPEED": 40, "ENGINE_RPM": 1900})
        await feed(start + timedelta(minutes=1), {"SPEED": 55, "ENGINE_RPM": 2300})
        for offset in range(2, 10):
            await feed(start + timedelta(minutes=offset), {"SPEED": 0, "ENGINE_RPM": 750})
        await feed(start + timedelta(minutes=10), {"SPEED": 45, "ENGINE_RPM": 2000})
        await feed(start + timedelta(minutes=11), {"SPEED": 50, "ENGINE_RPM": 2100})

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1, (
            "an eight-minute stop split the drive; that is the five-minute "
            "connection-loss detector being used to end drives"
        )
        assert sessions[0].ended_at is None
