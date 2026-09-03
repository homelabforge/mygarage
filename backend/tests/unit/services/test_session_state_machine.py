"""C9b's state machine, one test per cell, against real rows.

The transitions were originally described in prose spread across four decisions,
and review found four sequences the prose did not answer: a 20-minute connected
stop, a 6-minute silent gap, an explicit ECU-offline inside its grace period,
and a pending drive that survives a dropout. Prose across four sections cannot
be checked for completeness, so the design collapsed it into one table and this
file walks it.

States, per device: ``idle``, ``pending`` (engine on, nothing moving yet),
``driving``, ``stopped`` (moved before, connected now, not moving), ``awaiting``
(closed on contact loss, still reopenable).

Two things make these tests worth reading rather than skimming:

**Every assertion has to be false at t=0.** A phantom-session test that passes
because no session was created *for any reason* is not a test -- and this is a
suite where "no session" is the default state, so a mis-seeded test passes
trivially. Each test below either asserts a session exists with specific bounds,
or asserts none exists after seeding a state where the old code created one.

**The device row is the state.** Not process memory. The MQTT subscriber, the
HTTPS route and the scheduler are three execution contexts; an in-memory
candidate is invisible to two of them and lost on restart, which silently turns
"keep the warm-up samples" into "drop them" every time the container cycles.
``test_a_pending_drive_survives_a_process_restart`` is that claim, tested by
re-reading the row through a fresh service instance.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_service import SessionService

pytestmark = pytest.mark.asyncio

GAP = 15
TIMEOUT = 5

#: A fixed, past base time. Relative-to-now seeding is a calendar bomb: one such
#: test failed the v3.0.0 publish because a "30 days ago" fixture crossed a
#: month boundary.
T0 = datetime(2026, 9, 1, 8, 0, 0)

BATTERY = {"BATTERY_VOLTAGE": 12.4}
IDLING = {"ENGINE_RPM": 780.0, "SPEED": 0.0}
MOVING = {"SPEED": 48.0, "ENGINE_RPM": 2100.0}
EV_MOVING = {"SPEED": 48.0}
STOPPED_CONNECTED = {"SPEED": 0.0, "ENGINE_RPM": 750.0}


async def _open_session(db: AsyncSession, device_id: str) -> DriveSession | None:
    return (
        await db.execute(
            select(DriveSession)
            .where(DriveSession.device_id == device_id)
            .where(DriveSession.ended_at.is_(None))
        )
    ).scalar_one_or_none()


async def _all_sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
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


async def _seed_telemetry(
    db: AsyncSession, vin: str, device_id: str, at: datetime, samples: dict
) -> None:
    """Persist a batch, so window-scanning aggregates have something to find."""
    for key, value in samples.items():
        db.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key=key,
                value=float(value),
                timestamp=at,
            )
        )
    await db.flush()


async def _drive(
    service: SessionService,
    db: AsyncSession,
    vin: str,
    device,
    batches: list[tuple[datetime, dict]],
    *,
    live: bool = True,
    persist: bool = False,
) -> DriveSession | None:
    """Feed batches in order, mirroring what an ingest path does per payload."""
    result = None
    for at, samples in batches:
        if persist:
            await _seed_telemetry(db, vin, device.device_id, at, samples)
        device.last_seen = at
        result = await service.observe_telemetry(device, samples, at, live=live)
        await db.flush()
    return result


# ---------------------------------------------------------------------------
# idle
# ---------------------------------------------------------------------------


class TestFromIdle:
    async def test_a_battery_heartbeat_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The payload that produced 2,975 of this instance's 3,238 sessions.

        Under the old rule any telemetry inferred ECU-online and opened a
        session, so a parked vehicle recorded a drive roughly every 95 minutes.
        """
        vin, device = await make_livelink_vehicle("smidle", "1")
        service = SessionService(db_session)

        await _drive(service, db_session, vin, device, [(T0, BATTERY)])

        assert await _open_session(db_session, device.device_id) is None
        assert await _all_sessions(db_session, device.device_id) == []

    async def test_two_heartbeats_ninety_five_minutes_apart_open_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The measured heartbeat interval, which is also the phantom period.

        Seeded at the real cadence rather than back-to-back, because a debounce
        keyed on "consecutive samples" without a time bound would pair these two
        and call them movement.
        """
        vin, device = await make_livelink_vehicle("smidle", "2")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, BATTERY), (T0 + timedelta(minutes=95), BATTERY)],
        )

        assert await _all_sessions(db_session, device.device_id) == []

    async def test_engine_on_becomes_pending_and_not_a_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """RPM above zero is engine-on, which is not a drive.

        Remote start, a diagnostic session, a winter warm-up, or the
        eleven-minute driveway idle that was credited with 14 km.
        """
        vin, device = await make_livelink_vehicle("smidle", "3")
        service = SessionService(db_session)

        await _drive(service, db_session, vin, device, [(T0, IDLING)])

        assert await _all_sessions(db_session, device.device_id) == []
        assert device.pending_since == T0
        assert device.pending_source == "rpm"

    async def test_a_long_idle_never_becomes_a_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Eleven minutes of idling, at the sampling cadence, still zero drives."""
        vin, device = await make_livelink_vehicle("smidle", "4")
        service = SessionService(db_session)

        batches = [(T0 + timedelta(minutes=m), IDLING) for m in range(12)]
        await _drive(service, db_session, vin, device, batches)

        assert await _all_sessions(db_session, device.device_id) == []


# ---------------------------------------------------------------------------
# The floor and the debounce
# ---------------------------------------------------------------------------


class TestTheFloorAndDebounce:
    async def test_one_sample_above_the_floor_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A single noisy sample is effectively unvalidatable.

        `validate_rate_of_change` skips entirely when the previous reading is
        older than 120 seconds, which is exactly the parked-heartbeat case, so
        nothing upstream would have caught a spurious 48 km/h either.
        """
        vin, device = await make_livelink_vehicle("smfloor", "1")
        service = SessionService(db_session)

        await _drive(service, db_session, vin, device, [(T0, MOVING)])

        assert await _all_sessions(db_session, device.device_id) == []
        assert device.movement_candidate_at == T0, "the sample is remembered as a candidate"

    async def test_two_consecutive_samples_above_the_floor_open_a_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("smfloor", "2")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, MOVING), (T0 + timedelta(seconds=30), MOVING)],
        )

        session = await _open_session(db_session, device.device_id)
        assert session is not None
        assert session.boundary_algorithm_version == 1
        assert session.effective_gap_minutes == GAP

    @pytest.mark.parametrize("speed", [1.0, 4.9])
    async def test_two_samples_below_the_floor_open_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle, speed: float
    ):
        vin, device = await make_livelink_vehicle("smfloor", f"3{int(speed * 10)}")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, {"SPEED": speed}), (T0 + timedelta(seconds=30), {"SPEED": speed})],
        )

        assert await _all_sessions(db_session, device.device_id) == []

    async def test_a_debounce_pair_straddling_a_disconnect_is_not_consecutive(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Two samples separated by a dropout are not consecutive in any sense
        that matters. A speed spike before a device drops off, matched against
        another spike hours later, is precisely the phantom the debounce exists
        to suppress -- so the pair must fall inside one gap window."""
        vin, device = await make_livelink_vehicle("smfloor", "4")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, MOVING), (T0 + timedelta(minutes=GAP + 1), MOVING)],
        )

        assert await _all_sessions(db_session, device.device_id) == [], (
            "the first spike should have expired as a candidate, not paired"
        )


# ---------------------------------------------------------------------------
# The odometer signal
# ---------------------------------------------------------------------------


class TestTheOdometerSignal:
    async def test_a_rising_odometer_alone_opens_a_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The signal the first design lacked entirely.

        A vehicle whose speed arrives under a name nothing recognises still
        proves it moved. Without this, that cohort records no drives at all --
        and the reconstruction tool, which requires positive evidence of
        movement before touching anything, would then erase its history.
        """
        vin, device = await make_livelink_vehicle("smodo", "1")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [
                (T0, {"A6-ODOMETER": 120_000.0}),
                (T0 + timedelta(minutes=8), {"A6-ODOMETER": 120_012.0}),
            ],
        )

        assert await _open_session(db_session, device.device_id) is not None

    async def test_an_unchanged_odometer_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A parked vehicle reports the same odometer on every heartbeat."""
        vin, device = await make_livelink_vehicle("smodo", "2")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [
                (T0, {"A6-ODOMETER": 120_000.0}),
                (T0 + timedelta(minutes=95), {"A6-ODOMETER": 120_000.0}),
            ],
        )

        assert await _all_sessions(db_session, device.device_id) == []

    async def test_a_falling_odometer_opens_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Out-of-order replay, not a reversing vehicle."""
        vin, device = await make_livelink_vehicle("smodo", "3")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [
                (T0, {"A6-ODOMETER": 120_050.0}),
                (T0 + timedelta(minutes=5), {"A6-ODOMETER": 120_000.0}),
            ],
        )

        assert await _all_sessions(db_session, device.device_id) == []

    async def test_an_ev_with_no_rpm_at_all_gets_sessions(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The test that would have caught the original RPM-only design.

        A stationary EV reports neither speed nor RPM, and a moving one reports
        no RPM ever. An RPM-only predicate gives it zero sessions, forever, with
        nothing in the log to say why.
        """
        vin, device = await make_livelink_vehicle("smev", "1")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, EV_MOVING), (T0 + timedelta(minutes=1), EV_MOVING)],
        )

        assert await _open_session(db_session, device.device_id) is not None


# ---------------------------------------------------------------------------
# pending
# ---------------------------------------------------------------------------


class TestFromPending:
    async def test_movement_after_engine_on_opens_a_session_at_the_engine_on(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """C5: the window keeps the whole burst; movement only decides it is a drive.

        Setting `started_at` to the first movement sample silently discards
        everything before it, and aggregates are strictly window-bounded -- so
        warm-up coolant, initial fuel level and, critically, the OPENING
        ODOMETER READING fall outside. `_calculate_session_distance` then finds
        exactly one odometer sample in the window and writes
        `start_odometer == end_odometer`, i.e. `distance_km = 0.0`: a confident
        zero rather than a blank.
        """
        vin, device = await make_livelink_vehicle("smpend", "1")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [
                (T0, IDLING),
                (T0 + timedelta(minutes=2), IDLING),
                (T0 + timedelta(minutes=3), MOVING),
                (T0 + timedelta(minutes=4), MOVING),
            ],
        )

        session = await _open_session(db_session, device.device_id)
        assert session is not None
        assert session.started_at == T0, "the warm-up must be inside the window"
        assert session.movement_started_at == T0 + timedelta(minutes=3)
        assert device.pending_since is None, "promotion clears the pending state"

    async def test_a_pending_drive_older_than_the_gap_is_discarded(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Without a bound, an engine-on at 08:00 and a movement sample at 17:00
        are still 'consecutive', and the session backdates nine hours of parked
        telemetry into a drive."""
        vin, device = await make_livelink_vehicle("smpend", "2")
        service = SessionService(db_session)

        much_later = T0 + timedelta(hours=9)
        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, IDLING), (much_later, MOVING), (much_later + timedelta(minutes=1), MOVING)],
        )

        session = await _open_session(db_session, device.device_id)
        assert session is not None
        assert session.started_at >= much_later, (
            f"started_at {session.started_at} backdates into nine hours of parked telemetry"
        )

    async def test_an_expired_pending_drive_never_created_a_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A warm-up that never went anywhere leaves no trace at all."""
        vin, device = await make_livelink_vehicle("smpend", "3")
        service = SessionService(db_session)

        await _drive(service, db_session, vin, device, [(T0, IDLING)])
        await service.expire_stale_movement_state(gap_minutes=GAP, now=T0 + timedelta(minutes=20))
        await db_session.flush()

        assert await _all_sessions(db_session, device.device_id) == []
        assert device.pending_since is None

    async def test_a_pending_drive_survives_a_process_restart(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The claim that the state is durable, not in process memory.

        Three execution contexts observe movement -- the MQTT subscriber, the
        HTTPS route and the scheduler. An in-memory candidate is invisible to
        two of them and lost on every container cycle, which converts "keep the
        warm-up samples" into "drop them" without anything failing.
        """
        vin, device = await make_livelink_vehicle("smpend", "4")

        await _drive(SessionService(db_session), db_session, vin, device, [(T0, IDLING)])
        await db_session.commit()
        db_session.expunge_all()

        # A completely fresh service and a re-read row, standing in for a restart.
        fresh = SessionService(db_session)
        reloaded = await fresh._get_device(device.device_id)
        assert reloaded is not None
        assert reloaded.pending_since == T0

        await _drive(
            fresh,
            db_session,
            vin,
            reloaded,
            [(T0 + timedelta(minutes=2), MOVING), (T0 + timedelta(minutes=3), MOVING)],
        )

        session = await _open_session(db_session, reloaded.device_id)
        assert session is not None
        assert session.started_at == T0, "the pre-restart warm-up is still in the window"


# ---------------------------------------------------------------------------
# driving / stopped
# ---------------------------------------------------------------------------


class TestDrivingAndStopped:
    async def test_continued_movement_extends_one_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("smdrive", "1")
        service = SessionService(db_session)

        batches = [(T0 + timedelta(minutes=m), MOVING) for m in range(10)]
        await _drive(service, db_session, vin, device, batches)

        assert len(await _all_sessions(db_session, device.device_id)) == 1
        assert device.last_movement_at == T0 + timedelta(minutes=9)

    async def test_a_six_minute_connected_stop_does_not_split_the_drive(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The EV-at-a-charger case, and the reason there are two clocks.

        The five-minute setting is a CONNECTION-LOSS detector. Measuring it from
        the last movement instead splits a drive whenever a vehicle stops for
        six minutes while still connected and still sending stationary
        heartbeats: a drive-through, a fuel stop, a school pickup, a drawbridge.
        An ICE vehicle keeps RPM through a stop and survives; a stationary EV
        reports neither speed nor RPM, so it is exactly the vehicle this breaks.
        """
        vin, device = await make_livelink_vehicle("smdrive", "2")
        service = SessionService(db_session)

        batches = [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        # Six minutes stopped but still talking.
        batches += [(T0 + timedelta(minutes=1 + m), STOPPED_CONNECTED) for m in range(1, 7)]
        await _drive(service, db_session, vin, device, batches)

        # The scheduler is what would split it, so run it mid-stop: six minutes
        # past the last MOVEMENT but zero seconds past the last CONTACT.
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=7, seconds=30)
        )
        await db_session.flush()
        assert await _open_session(db_session, device.device_id) is not None, (
            "the contact-loss clock must not be measured from the last movement"
        )

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0 + timedelta(minutes=8), MOVING), (T0 + timedelta(minutes=9), MOVING)],
        )

        sessions = await _all_sessions(db_session, device.device_id)
        assert len(sessions) == 1, "a six-minute stop is one drive, not two"
        assert sessions[0].ended_at is None

    async def test_a_twenty_minute_connected_stop_splits_the_drive(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Fifteen minutes stationary is two trips, which is what a person
        would call them. The session closes at the last MOVEMENT, not at the
        last contact."""
        vin, device = await make_livelink_vehicle("smdrive", "3")
        service = SessionService(db_session)

        last_movement = T0 + timedelta(minutes=1)
        await _drive(service, db_session, vin, device, [(T0, MOVING), (last_movement, MOVING)])

        # Still connected, still stationary, for twenty minutes.
        for m in range(2, 21):
            device.last_seen = T0 + timedelta(minutes=m)
            await service.observe_telemetry(
                device, STOPPED_CONNECTED, T0 + timedelta(minutes=m), live=True
            )
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=21)
        )
        await db_session.flush()

        first = (await _all_sessions(db_session, device.device_id))[0]
        assert first.ended_at == last_movement, (
            f"closed at {first.ended_at}; the contact burst ran to "
            f"{T0 + timedelta(minutes=20)} and must not pad the drive"
        )

    async def test_movement_after_the_gap_starts_a_second_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """And its window may NOT backdate into the closed session's window.

        C5's whole-burst rule applies to the OPENING burst of a drive. It cannot
        apply to a burst already consumed by a previous session, because every
        aggregate is a window scan and two overlapping sessions both claim the
        same samples and both report the same distance.
        """
        vin, device = await make_livelink_vehicle("smdrive", "4")
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )
        for m in range(2, 21):
            device.last_seen = T0 + timedelta(minutes=m)
            await service.observe_telemetry(
                device, STOPPED_CONNECTED, T0 + timedelta(minutes=m), live=True
            )
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=21)
        )
        await db_session.flush()

        resumed = T0 + timedelta(minutes=22)
        await _drive(
            service,
            db_session,
            vin,
            device,
            [(resumed, MOVING), (resumed + timedelta(minutes=1), MOVING)],
        )

        sessions = await _all_sessions(db_session, device.device_id)
        assert len(sessions) == 2
        assert sessions[1].started_at >= sessions[0].ended_at, (
            f"session 2 starts at {sessions[1].started_at}, inside session 1's "
            f"window which ends at {sessions[0].ended_at}"
        )


# ---------------------------------------------------------------------------
# awaiting
# ---------------------------------------------------------------------------


class TestAwaiting:
    async def test_contact_loss_closes_at_the_last_movement(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """`ended_at` is the end of the burst, and no timeout may stamp it.

        `check_session_timeouts` used to select on `last_seen` and then call
        `end_session(device, last_seen)` -- and `update_device_status` sets
        `last_seen` on EVERY call, heartbeat included. Changing only the
        selection predicate would leave `ended_at` at the last contact, padding
        every drive's tail by up to one heartbeat interval (95 minutes,
        measured) and dragging `avg_speed` toward zero with parked samples.
        """
        vin, device = await make_livelink_vehicle("smawait", "1")
        service = SessionService(db_session)

        last_movement = T0 + timedelta(minutes=1)
        await _drive(service, db_session, vin, device, [(T0, MOVING), (last_movement, MOVING)])
        # A parked heartbeat arrives well after movement stopped.
        heartbeat = T0 + timedelta(minutes=30)
        device.last_seen = heartbeat
        await service.observe_telemetry(device, BATTERY, heartbeat, live=True)
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=heartbeat + timedelta(minutes=10)
        )
        await db_session.flush()

        session = (await _all_sessions(db_session, device.device_id))[0]
        assert session.ended_at == last_movement

    async def test_movement_returning_inside_the_gap_reopens_the_same_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """`awaiting` exists to make live and replay agree.

        Without it: movement, six minutes of silence, movement produces TWO
        live sessions (the five-minute contact timeout fired) and ONE replayed
        session (the movement gap was under fifteen). The claim that a drive is
        cut the same way whichever path it arrived by would be aspirational.
        """
        vin, device = await make_livelink_vehicle("smawait", "2")
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )
        original = await _open_session(db_session, device.device_id)
        assert original is not None
        original_id = original.id

        # Six minutes of total silence: past the contact timeout, inside the gap.
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=7)
        )
        await db_session.flush()
        assert await _open_session(db_session, device.device_id) is None, (
            "the contact timeout must still CLOSE promptly, so a device that "
            "never returns is not left open forever"
        )

        resumed = T0 + timedelta(minutes=8)
        await _drive(
            service,
            db_session,
            vin,
            device,
            [(resumed, MOVING), (resumed + timedelta(seconds=30), MOVING)],
        )

        sessions = await _all_sessions(db_session, device.device_id)
        assert len(sessions) == 1, f"expected the drive to be one session, got {len(sessions)}"
        assert sessions[0].id == original_id, "the retained session must be REOPENED, not replaced"
        assert sessions[0].ended_at is None

    async def test_movement_returning_after_the_gap_starts_a_new_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("smawait", "3")
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=7)
        )
        await db_session.flush()

        resumed = T0 + timedelta(minutes=40)
        await _drive(
            service,
            db_session,
            vin,
            device,
            [(resumed, MOVING), (resumed + timedelta(minutes=1), MOVING)],
        )

        sessions = await _all_sessions(db_session, device.device_id)
        assert len(sessions) == 2
        assert sessions[0].ended_at is not None

    async def test_the_gap_elapsing_makes_the_closure_final(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Once finalized, the pointer is clear and nothing can reopen it."""
        vin, device = await make_livelink_vehicle("smawait", "4")
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=7)
        )
        await service.expire_stale_movement_state(gap_minutes=GAP, now=T0 + timedelta(minutes=40))
        await db_session.flush()

        assert device.current_session_id is None


# ---------------------------------------------------------------------------
# Explicit ECU-offline and its grace period
# ---------------------------------------------------------------------------


class TestExplicitOffline:
    async def test_the_finalizer_closes_the_session_directly(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Not by looking for an online-to-offline transition, which no-ops.

        The route persists `ecu_status='offline'` immediately, so when the
        60-second grace expires `handle_ecu_offline` sees no transition and does
        nothing -- leaving the session to a contact timeout anchored on a
        `last_seen` that the finalizer itself advanced. The existing tests mock
        `handle_ecu_offline` and assert only that it was called, so they pass
        with this broken.
        """
        vin, device = await make_livelink_vehicle("smoff", "1")
        service = SessionService(db_session)

        last_movement = T0 + timedelta(minutes=1)
        await _drive(service, db_session, vin, device, [(T0, MOVING), (last_movement, MOVING)])
        device.ecu_status = "offline"  # what the route already wrote

        closed = await service.finalize_offline(device, now=T0 + timedelta(minutes=2))
        await db_session.flush()

        assert closed is not None, "the finalizer must close the session, transition or not"
        assert closed.ended_at == last_movement

    async def test_the_finalizer_does_not_touch_last_seen(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """There was no contact. Fabricating one corrupts every timeout that
        reads `last_seen` -- including the contact-loss clock, which would then
        measure from a moment the device never spoke."""
        vin, device = await make_livelink_vehicle("smoff", "2")
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )
        before = device.last_seen

        await service.finalize_offline(device, now=T0 + timedelta(minutes=2))
        await db_session.flush()

        assert device.last_seen == before

    async def test_a_dropout_inside_the_grace_keeps_the_pending_envelope(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Pending state clears when an offline FINALIZES, not when it arrives.

        Taken separately, "clear pending on explicit offline" and "treat offline
        as provisional for 60 seconds" mean a brief WiFi drop discards the
        warm-up and opening-odometer samples that the pending state exists to
        preserve.
        """
        vin, device = await make_livelink_vehicle("smoff", "3")
        service = SessionService(db_session)

        await _drive(service, db_session, vin, device, [(T0, IDLING)])
        assert device.pending_since == T0

        # Offline arrives; the grace period has not expired.
        await service.begin_provisional_offline(device, now=T0 + timedelta(seconds=10))
        await db_session.flush()
        assert device.pending_since == T0, "provisional offline must not discard the warm-up"

        # Contact returns inside the grace, then the vehicle moves.
        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0 + timedelta(minutes=1), MOVING), (T0 + timedelta(minutes=2), MOVING)],
        )

        session = await _open_session(db_session, device.device_id)
        assert session is not None
        assert session.started_at == T0

    async def test_finalizing_clears_the_pending_state(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("smoff", "4")
        service = SessionService(db_session)

        await _drive(service, db_session, vin, device, [(T0, IDLING)])
        await service.finalize_offline(device, now=T0 + timedelta(minutes=2))
        await db_session.flush()

        assert device.pending_since is None
        assert await _all_sessions(db_session, device.device_id) == []


# ---------------------------------------------------------------------------
# Scope and provenance
# ---------------------------------------------------------------------------


class TestScopeAndProvenance:
    async def test_movement_state_is_per_device_not_per_vin(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A vehicle with both a WiCAN dongle and a Torque phone would otherwise
        let one source confirm the other's pending drive."""
        vin, wican = await make_livelink_vehicle("smscope", "1")
        second = type(wican)(device_id="smscopedev0002", vin=vin, enabled=True, kind="torque")
        db_session.add(second)
        await db_session.flush()

        service = SessionService(db_session)
        await _drive(service, db_session, vin, wican, [(T0, IDLING)])
        await _drive(service, db_session, vin, second, [(T0 + timedelta(minutes=1), MOVING)])

        assert await _all_sessions(db_session, wican.device_id) == [], (
            "the second device's movement must not promote the first's pending drive"
        )
        assert wican.pending_since == T0, "the first device's pending drive is untouched"
        assert wican.movement_candidate_at is None, (
            "and the second device's above-floor sample is not the first's candidate"
        )
        assert second.movement_candidate_at == T0 + timedelta(minutes=1)

    async def test_new_sessions_are_stamped_with_the_new_algorithm(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Defaulting new rows to 0 is not half-right, it is wrong: they would
        masquerade as pre-098 history and a later reconstruction would skip
        them."""
        vin, device = await make_livelink_vehicle("smscope", "2")
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )

        session = await _open_session(db_session, device.device_id)
        assert session is not None
        assert session.boundary_algorithm_version == 1
        assert session.effective_gap_minutes == GAP

    async def test_starting_a_session_does_not_write_ecu_status(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """C8. Once a session is not a proxy for ECU state, a movement timeout
        marking an awake ECU offline is not cosmetic: `device_command_service`
        refuses any `requires_ecu` command when `ecu_status != 'online'`, so the
        remote-command surface would go dead after every drive."""
        vin, device = await make_livelink_vehicle("smscope", "3")
        device.ecu_status = "online"
        service = SessionService(db_session)

        await _drive(
            service, db_session, vin, device, [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)]
        )
        assert device.ecu_status == "online"

        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=30)
        )
        await db_session.flush()

        assert device.ecu_status == "online", "closing a session must not mark an awake ECU offline"

    async def test_replayed_samples_do_not_anchor_live_movement(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """An HTTPS payload carrying an old or future timestamp must not anchor
        a live session hours away from where it belongs."""
        vin, device = await make_livelink_vehicle("smscope", "4")
        service = SessionService(db_session)

        await _drive(
            service,
            db_session,
            vin,
            device,
            [(T0, MOVING), (T0 + timedelta(minutes=1), MOVING)],
            live=False,
        )

        assert device.last_movement_at is None, (
            "replay must not write last_movement_at, which every live timeout reads"
        )


# ---------------------------------------------------------------------------
# The window keeps the opening odometer (C5, measured end to end)
# ---------------------------------------------------------------------------


class TestTheWindowKeepsTheOpeningOdometer:
    async def test_the_opening_odometer_reading_is_inside_the_window(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """C5, driven end to end: ingest, boundaries, close, distance.

        Aggregates are strictly window-bounded, so a `started_at` at the first
        MOVEMENT sample drops every reading taken at ignition -- warm-up
        coolant, initial fuel level, and the opening odometer.

        Measured under mutation (`started_at = sample_at`): `start_odometer`
        becomes 120001 and the drive reports 11 km instead of 12. The design
        also warns of a worse form, a window left holding exactly ONE odometer
        sample, where `_calculate_session_distance` assigns unconditionally and
        writes a confident `distance_km = 0.0` rather than a blank. This test
        does not reproduce that -- with three odometer samples in the drive it
        cannot -- so it is named for what it does pin: the opening reading stays
        in the window. Keeping it there is what makes single-sample windows rare
        rather than routine.
        """
        vin, device = await make_livelink_vehicle("smwindow", "1")
        service = SessionService(db_session)

        batches = [
            # Ignition on: engine turning, odometer read, nothing moving yet.
            (T0, {"ENGINE_RPM": 700.0, "SPEED": 0.0, "A6-ODOMETER": 120_000.0}),
            (T0 + timedelta(minutes=2), {"SPEED": 40.0, "A6-ODOMETER": 120_001.0}),
            (T0 + timedelta(minutes=3), {"SPEED": 55.0, "A6-ODOMETER": 120_003.0}),
            (T0 + timedelta(minutes=10), {"SPEED": 50.0, "A6-ODOMETER": 120_012.0}),
        ]
        await _drive(service, db_session, vin, device, batches, persist=True)
        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=40)
        )
        await db_session.flush()

        session = (await _all_sessions(db_session, device.device_id))[0]
        assert session.started_at == T0
        assert session.start_odometer == 120_000.0, (
            "the opening odometer reading fell outside the window"
        )
        assert session.distance_km == pytest.approx(12.0)
