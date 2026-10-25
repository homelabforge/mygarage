"""An SD-card backfill creates the sessions its rows describe. C10.

This is the motivating case for the whole boundary rework, and the case the
design's first revision did not fix.

``bulk_backfill`` called only ``_refresh_sessions_in_span``, which selects
``WHERE DriveSession.ended_at IS NOT NULL`` -- sessions that **already exist and
are already closed**. It had never created one. Every decision in that first
revision changed live ingest, and the SD card is the only path for anything
driven out of broker range: off home WiFi the WiCAN reaches no broker at all, so
a whole drive arrives here hours later. On 2026-09-01 the Ram drove 16.0 km and
was credited 3.0 across three sessions; the Mirage drove 10.0 km and was
credited 0.0 across fifteen, thirteen of which held no telemetry at all.

Two constraints shape the implementation and each has a test:

**Once per call, not once per row.** Running the live side-effects per row is
precisely what ``bulk_backfill`` exists to avoid, and a pull is tens of
thousands of rows.

**The span must not be narrowed to inserted rows.** It is built from all
*parsed* rows on purpose: the rows commit in batches here while
``SdBackfillService`` saves the file watermark only after this returns, so a
crash between the two leaves the rows imported and their sessions never
recomputed. The retry re-parses, every row conflicts, and a span built from
inserts would be empty -- losing the refresh permanently. An earlier design
revision described this as a "quadratic" defect and would have had an
implementer narrow exactly that.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.drive_session import DriveSession
from app.services.sd_log_parser import SdRow
from app.services.session_boundaries import group_drives
from app.services.telemetry_service import TelemetryService

T0 = datetime(2026, 9, 1, 8, 0, 0)
GAP = 15


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    return list(
        (
            await db.execute(
                select(DriveSession)
                .where(DriveSession.device_id == device_id)
                # `id` breaks ties deterministically when two sessions share a
                # `started_at` -- a zero-length drive and a later drive
                # backdated to the same instant both do. PostgreSQL and
                # SQLite order ties differently on `started_at` alone.
                .order_by(DriveSession.started_at, DriveSession.id)
            )
        )
        .scalars()
        .all()
    )


def _rows(*specs: tuple[int, str, float]) -> list[SdRow]:
    """`(minute_offset, param_key, value)` triples as SdRows."""
    return [
        SdRow(param_key=key, value=value, timestamp=T0 + timedelta(minutes=offset))
        for offset, key, value in specs
    ]


class TestItCreatesSessions:
    async def test_a_replayed_drive_creates_a_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The Ram's missing kilometres, in the smallest form that shows them."""
        vin, device = await make_livelink_vehicle("sdcreate", "1")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "A6-ODOMETER", 50_000.0),
                (1, "SPEED", 45.0),
                (2, "SPEED", 62.0),
                (3, "A6-ODOMETER", 50_004.0),
                (4, "SPEED", 40.0),
            ),
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1, "the SD path has never created a session before this"
        assert sessions[0].boundary_algorithm_version == 1
        assert sessions[0].effective_gap_minutes == GAP
        assert sessions[0].ended_at is not None, "a replayed drive is over; it must not be open"

    async def test_the_created_session_gets_its_distance(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Creating the row is only half of it: the point is the credited distance."""
        vin, device = await make_livelink_vehicle("sdcreate", "2")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "A6-ODOMETER", 50_000.0),
                (1, "SPEED", 45.0),
                (5, "SPEED", 55.0),
                (9, "A6-ODOMETER", 50_013.0),
            ),
        )

        session = (await _sessions(db_session, device.device_id))[0]
        assert session.distance_km == pytest.approx(13.0)

    async def test_the_window_keeps_the_opening_odometer(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """C5 applies to replay too, or the two paths disagree about one drive."""
        vin, device = await make_livelink_vehicle("sdcreate", "3")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "ENGINE_RPM", 700.0),
                (0, "A6-ODOMETER", 60_000.0),
                (3, "SPEED", 50.0),
                (4, "SPEED", 50.0),
                (8, "A6-ODOMETER", 60_009.0),
            ),
        )

        session = (await _sessions(db_session, device.device_id))[0]
        assert session.started_at == T0, "the ignition-time burst must be in the window"
        assert session.start_odometer == 60_000.0

    async def test_two_drives_separated_by_the_gap_become_two_sessions(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("sdcreate", "4")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "SPEED", 45.0),
                (1, "SPEED", 50.0),
                # 40 minutes parked, well past the 15-minute drive gap.
                (41, "SPEED", 48.0),
                (42, "SPEED", 52.0),
            ),
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 2

    async def test_a_stop_inside_the_gap_stays_one_session(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The same rule the live path uses, so a drive is cut the same way
        whichever path it arrived by. Scoping the gap to reconstruction only --
        which an earlier revision did -- means one journey gets two different
        answers depending on how it reached the database."""
        vin, device = await make_livelink_vehicle("sdcreate", "5")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "SPEED", 45.0),
                (1, "SPEED", 50.0),
                (8, "SPEED", 48.0),  # 7 minutes later: inside the gap
                (9, "SPEED", 52.0),
            ),
        )

        assert len(await _sessions(db_session, device.device_id)) == 1


class TestItRefusesToInventDrives:
    async def test_a_parked_heartbeat_file_creates_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A month of SD rows from a parked vehicle must stay a month of nothing.

        This is the assertion that makes the rest safe: a replay path that
        creates a session per contact burst would manufacture thousands of
        phantom drives from history, which is strictly worse than the bug being
        fixed because there is no upgrade that undoes it.
        """
        vin, device = await make_livelink_vehicle("sdrefuse", "1")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(*[(m * 95, "BATTERY_VOLTAGE", 12.4) for m in range(20)]),
        )

        assert await _sessions(db_session, device.device_id) == []

    async def test_an_idle_only_file_creates_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("sdrefuse", "2")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(*[(m, "ENGINE_RPM", 750.0) for m in range(12)]),
        )

        assert await _sessions(db_session, device.device_id) == []

    async def test_a_single_speed_spike_creates_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The same debounce the live path applies. One sample is not a drive."""
        vin, device = await make_livelink_vehicle("sdrefuse", "3")

        await TelemetryService(db_session).bulk_backfill(
            vin, device.device_id, _rows((0, "SPEED", 48.0))
        )

        assert await _sessions(db_session, device.device_id) == []

    async def test_an_unchanged_odometer_creates_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("sdrefuse", "4")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows((0, "A6-ODOMETER", 70_000.0), (95, "A6-ODOMETER", 70_000.0)),
        )

        assert await _sessions(db_session, device.device_id) == []

    async def test_an_unlinked_device_creates_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("sdrefuse", "5")
        device.vin = None
        await db_session.flush()

        await TelemetryService(db_session).bulk_backfill(
            vin, device.device_id, _rows((0, "SPEED", 45.0), (1, "SPEED", 50.0))
        )

        assert await _sessions(db_session, device.device_id) == []


class TestItDoesNotOverlapExistingSessions:
    async def test_a_drive_already_recorded_is_extended_not_duplicated(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The common case on a device with intermittent WiFi.

        Part of the drive reached the broker live and opened a session; the rest
        arrives off the SD card. Creating a second session for the same journey
        would leave two overlapping windows, and every aggregate here is a
        window scan -- so both would claim the same samples and both report the
        same distance, doubling the vehicle's apparent mileage.
        """
        vin, device = await make_livelink_vehicle("sdoverlap", "1")
        live_part = DriveSession(
            vin=vin,
            device_id=device.device_id,
            started_at=T0,
            ended_at=T0 + timedelta(minutes=2),
            boundary_algorithm_version=1,
            effective_gap_minutes=GAP,
        )
        db_session.add(live_part)
        await db_session.flush()

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "A6-ODOMETER", 80_000.0),
                (1, "SPEED", 45.0),
                (2, "SPEED", 50.0),
                (6, "SPEED", 55.0),
                (7, "A6-ODOMETER", 80_011.0),
            ),
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1, f"expected the session to be extended, got {len(sessions)}"
        assert sessions[0].id == live_part.id
        assert sessions[0].ended_at >= T0 + timedelta(minutes=6)
        assert sessions[0].distance_km == pytest.approx(11.0)

    async def test_a_torque_session_is_never_extended(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Torque supplies an authoritative session id from the phone.

        Re-bounding it on a gap threshold replaces good evidence with inference.
        Excluded by `external_session_id`, not by heuristic.
        """
        vin, device = await make_livelink_vehicle("sdoverlap", "2")
        torque = DriveSession(
            vin=vin,
            device_id=device.device_id,
            started_at=T0,
            ended_at=T0 + timedelta(minutes=2),
            external_session_id="phone-1",
        )
        db_session.add(torque)
        await db_session.flush()
        original_end = torque.ended_at

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows((1, "SPEED", 45.0), (2, "SPEED", 50.0), (6, "SPEED", 55.0)),
        )

        await db_session.refresh(torque)
        assert torque.ended_at == original_end, "a phone-bounded session must not be re-bounded"

    async def test_no_two_output_sessions_overlap(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Nothing in the schema forbids overlapping windows -- the time indexes
        are non-unique -- so this is asserted rather than assumed."""
        vin, device = await make_livelink_vehicle("sdoverlap", "3")

        await TelemetryService(db_session).bulk_backfill(
            vin,
            device.device_id,
            _rows(
                (0, "SPEED", 45.0),
                (1, "SPEED", 50.0),
                (40, "SPEED", 48.0),
                (41, "SPEED", 52.0),
                (90, "SPEED", 44.0),
                (91, "SPEED", 46.0),
            ),
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 3
        for earlier, later in zip(sessions, sessions[1:], strict=False):
            assert earlier.ended_at <= later.started_at, (
                f"session {earlier.id} ends {earlier.ended_at}, "
                f"session {later.id} starts {later.started_at}"
            )


class TestItRunsOncePerCall:
    async def test_reconstruction_runs_once_regardless_of_row_count(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ):
        """Running the live side-effects per row is what this method exists to
        avoid, and a real pull is tens of thousands of rows."""
        vin, device = await make_livelink_vehicle("sdonce", "1")
        service = TelemetryService(db_session)

        calls = []
        original = service._reconstruct_sessions_from_batch

        async def counting(*args, **kwargs):
            calls.append(args)
            return await original(*args, **kwargs)

        monkeypatch.setattr(service, "_reconstruct_sessions_from_batch", counting)

        rows = _rows(*[(m, "SPEED", 45.0 + m) for m in range(60)])
        await service.bulk_backfill(vin, device.device_id, rows)

        assert len(calls) == 1, f"called {len(calls)} times for {len(rows)} rows"

    async def test_the_span_is_built_from_parsed_rows_not_inserted_ones(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Re-running an identical batch must still refresh, though it inserts 0.

        The rows commit in batches here while `SdBackfillService` saves the file
        watermark only after this returns. A crash in between leaves the rows
        imported and their sessions never recomputed; the retry re-parses, every
        row conflicts, and a span built from INSERTS would be empty -- losing
        the refresh permanently rather than redoing it.
        """
        vin, device = await make_livelink_vehicle("sdonce", "2")
        service = TelemetryService(db_session)
        rows = _rows(
            (0, "A6-ODOMETER", 90_000.0),
            (1, "SPEED", 45.0),
            (2, "SPEED", 50.0),
            (5, "A6-ODOMETER", 90_007.0),
        )

        inserted_first = await service.bulk_backfill(vin, device.device_id, rows)
        assert inserted_first > 0

        session = (await _sessions(db_session, device.device_id))[0]
        session.distance_km = 999.0  # a stale figure a refresh must correct
        await db_session.flush()

        inserted_again = await service.bulk_backfill(vin, device.device_id, rows)
        assert inserted_again == 0, "every row should have conflicted"

        await db_session.refresh(session)
        assert session.distance_km == pytest.approx(7.0), (
            "the refresh was skipped, which is what a span built from inserts does"
        )


# Session reconstruction at a boundary two drives share.
#
# Drive 1 moves at minutes 0 and 5. A contact-only sample at minute 15 (RPM,
# below the movement floor, no odometer proof) chains `group_drives`' walk-back
# for drive 2 all the way back through drive 1's own burst, so the "never reach
# back into a drive already accounted for" clamp fires: drive 2's `started_at`
# is pinned to drive 1's `movement_ended_at` (minute 5) instead of the earlier
# instant the walk-back would otherwise have found. That shared instant is the
# boundary these tests pin.
#
# Minutes 3 and 27 are each drive's second odometer reading, placed away from
# the shared instant so each session's distance comes from its own two clean
# points rather than a boundary sample two windows both read.
_BOUNDARY_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "A6-ODOMETER", 50_000.0),
    (0, "SPEED", 45.0),
    (3, "A6-ODOMETER", 50_002.0),
    (5, "SPEED", 50.0),
    (15, "ENGINE_RPM", 700.0),
    (25, "SPEED", 48.0),
    (27, "A6-ODOMETER", 50_007.0),
    (30, "SPEED", 52.0),
    (30, "A6-ODOMETER", 50_010.0),
)

# A later pull that widens both drives without crossing the shared instant:
# minute -10 joins drive 1's burst (drive 1's own end stays at minute 5), and
# minute 35 joins drive 2's (drive 2's own start stays at minute 5).
_EXTENSION_SPECS: tuple[tuple[int, str, float], ...] = (
    (-10, "SPEED", 55.0),
    (35, "SPEED", 60.0),
)


def _samples(
    *spec_groups: tuple[tuple[int, str, float], ...],
) -> list[tuple[datetime, str, float]]:
    """One or more `(minute_offset, param_key, value)` spec tuples, merged
    and stamped from `T0`, in the shape `group_drives` takes directly."""
    flat = (spec for specs in spec_groups for spec in specs)
    return [(r.timestamp, r.param_key, r.value) for r in _rows(*flat)]


async def _session_rows(
    maker: async_sessionmaker[AsyncSession], device_id: str
) -> list[tuple[int, datetime, datetime | None, float | None, float | None]]:
    """`(id, started_at, ended_at, distance_km, max_speed)` for every session.

    Read into plain tuples inside the session block on purpose: the objects
    themselves must not be touched after their session closes.
    """
    async with maker() as db:
        rows = await _sessions(db, device_id)
        return [(s.id, s.started_at, s.ended_at, s.distance_km, s.max_speed) for s in rows]


class TestGroupDrivesSharedBoundary:
    """Where `group_drives` puts an instant two drives share.

    Pure and database-free on purpose -- a bound mutation here proves nothing
    about whether the overlap query in `_reconstruct_sessions_from_batch` can
    see an earlier drive's pending session, which is what the next two tests
    are for.
    """

    def test_group_drives_gives_a_shared_boundary_to_one_drive(self):
        drives = group_drives(_samples(_BOUNDARY_SPECS), GAP)

        assert len(drives) == 2, f"expected 2 drives, got {len(drives)}"
        first, second = drives
        assert first.started_at == T0
        assert first.movement_started_at == T0
        assert first.movement_ended_at == T0 + timedelta(minutes=5)

        assert second.started_at == T0 + timedelta(minutes=5)
        assert second.movement_started_at == T0 + timedelta(minutes=25)
        assert second.movement_ended_at == T0 + timedelta(minutes=30)

        # The shared instant is drive 1's own `movement_ended_at` -- real
        # evidence drive 1 recorded. Drive 2's `started_at` at that same
        # instant is only the clamp floor, not evidence of its own: drive 2's
        # actual movement does not begin until twenty minutes later. The
        # instant belongs to drive 1.
        shared = first.movement_ended_at
        assert second.started_at == shared
        assert second.movement_started_at > shared, (
            "drive 2 has no evidence at the shared instant; it is drive 1's "
            "movement_ended_at, borrowed only as a floor"
        )


class TestReconstructionAtATouchingBoundary:
    """The two drives `TestGroupDrivesSharedBoundary` describes, replayed
    through `_reconstruct_sessions_from_batch` on a session that does not
    autoflush, the way `app/database.py` builds every production session.

    Builds its own session over `test_engine`, pinning `autoflush=False`
    directly rather than depending on conftest's `test_sessionmaker`, so this
    class keeps exercising production's unit of work even if that setting
    ever changes. Matches `test_tire_periods.py`'s
    `TestEditorUnderProductionUnitOfWork`.
    """

    @staticmethod
    def _maker(test_engine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    async def test_two_touching_drives_in_one_batch_make_two_sessions(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdbound", "1")
        await db_session.commit()
        device_id = device.device_id

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, _rows(*_BOUNDARY_SPECS))

        expected = group_drives(_samples(_BOUNDARY_SPECS), GAP)
        rows = await _session_rows(maker, device_id)

        assert len(rows) == 2, f"expected 2 sessions, got {len(rows)}"
        (_, start1, end1, _, _), (_, start2, end2, _, _) = rows
        assert start1 == expected[0].started_at
        assert end1 == expected[0].movement_ended_at
        assert start2 == expected[1].started_at
        assert end2 == expected[1].movement_ended_at

        # Ownership rule: the shared instant is drive 1's, so the windows
        # touch at it without overlapping.
        assert end1 == start2

    async def test_running_the_same_backfill_twice_keeps_the_sessions(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdbound", "2")
        await db_session.commit()
        device_id = device.device_id
        rows_in = _rows(*_BOUNDARY_SPECS)

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, rows_in)
        first_run = await _session_rows(maker, device_id)
        assert len(first_run) == 2, f"expected 2 sessions after the first run, got {len(first_run)}"

        # Pinned from the fixture's own odometer pairs, not read back from the
        # code under test: drive 1 carries 50_000.0 at minute 0 and 50_002.0 at
        # minute 3 (2.0 km); drive 2 carries 50_007.0 at minute 27 and 50_010.0
        # at minute 30 (3.0 km). Both pairs sit away from the shared instant, so
        # neither session's distance is the boundary sample the other reads too.
        assert first_run[0][3] == pytest.approx(2.0), "session 1's distance from its own pair"
        assert first_run[1][3] == pytest.approx(3.0), "session 2's distance from its own pair"

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, rows_in)
        second_run = await _session_rows(maker, device_id)

        assert [r[0] for r in second_run] == [r[0] for r in first_run], (
            "the same replay must not create or drop a session"
        )
        assert [r[1:3] for r in second_run] == [r[1:3] for r in first_run], (
            "the same replay must not move a window"
        )
        assert [r[3:] for r in second_run] == [r[3:] for r in first_run], (
            "the same replay must not change distance or max speed"
        )

    async def test_a_rerun_that_extends_a_touching_drive_updates_its_own_session(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        """A later pull can legitimately widen one drive's window without
        crossing into its neighbour's. That widened drive must still find
        and extend its own session -- not get treated as spanning both
        sessions at the touching boundary, which is what the false
        "ambiguous" match there otherwise causes, silently dropping the
        extension.

        Extends both directions at once: drive 2's real evidence grows
        past its old end, and drive 1's grows before its old start, short
        of the shared instant -- so both of the query's two comparisons
        are exercised, not just the one the second drive's own overlap
        check uses.
        """
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdbound", "3")
        await db_session.commit()
        device_id = device.device_id

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, _rows(*_BOUNDARY_SPECS))
        first_run = await _session_rows(maker, device_id)
        assert len(first_run) == 2, f"expected 2 sessions after the first run, got {len(first_run)}"

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(
                vin, device_id, _rows(*_BOUNDARY_SPECS, *_EXTENSION_SPECS)
            )
        second_run = await _session_rows(maker, device_id)

        expected = group_drives(_samples(_BOUNDARY_SPECS, _EXTENSION_SPECS), GAP)
        assert len(second_run) == 2, f"expected 2 sessions, no third one, got {len(second_run)}"
        assert [r[0] for r in second_run] == [r[0] for r in first_run], (
            "the extension must update the drives' own sessions, not create new ones"
        )
        (_, start1, end1, _, speed1), (_, start2, end2, _, speed2) = second_run
        assert start1 == expected[0].started_at, "drive 1's backward extension must move its start"
        assert end1 == expected[0].movement_ended_at, (
            "drive 1's end must stay at the shared instant"
        )
        assert start2 == expected[1].started_at, "drive 2's start must stay at the shared instant"
        assert end2 == expected[1].movement_ended_at, (
            "drive 2's forward extension must move its end"
        )
        assert speed1 == pytest.approx(55.0), "session 1's aggregates must reflect the new sample"
        assert speed2 == pytest.approx(60.0), "session 2's aggregates must reflect the new sample"


# A single drive, alone in its batch, with no contact prefix: started_at
# equals movement_started_at.
_SOLO_DRIVE_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "SPEED", 45.0),
    (5, "SPEED", 50.0),
)

# A single drive, alone in its batch, whose started_at is backdated past its
# first movement sample by a leading contact-only reading.
_SOLO_DRIVE_WITH_PREFIX_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "ENGINE_RPM", 700.0),
    (5, "SPEED", 45.0),
    (10, "SPEED", 50.0),
)


class TestCrossSourceTouchesStillMerge:
    """The touch exclusions in `_reconstruct_sessions_from_batch` apply only
    at an instant a drive shares with a neighbour from its own batch. A
    session from anywhere else (the live path, or an earlier SD file's batch)
    that touches a drive at exactly one instant with no batch neighbour there
    is most plausibly the same physical drive seen by two sources, so it
    matches and merges.
    """

    @staticmethod
    def _maker(test_engine) -> async_sessionmaker[AsyncSession]:
        return TestReconstructionAtATouchingBoundary._maker(test_engine)

    async def test_a_live_session_after_the_batch_merges_at_the_shared_instant(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdmergeaft", "1")
        await db_session.commit()
        device_id = device.device_id

        drives = group_drives(_samples(_SOLO_DRIVE_SPECS), GAP)
        assert len(drives) == 1, f"expected 1 drive, got {len(drives)}"
        drive = drives[0]

        async with maker() as db:
            db.add(
                DriveSession(
                    vin=vin,
                    device_id=device_id,
                    started_at=drive.movement_ended_at,
                    ended_at=drive.movement_ended_at + timedelta(minutes=15),
                )
            )
            await db.commit()

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, _rows(*_SOLO_DRIVE_SPECS))

        rows = await _session_rows(maker, device_id)
        assert len(rows) == 1, f"expected the two to merge into one session, got {len(rows)}"
        assert rows[0][1] == drive.started_at, "the merge must keep the drive's own start"
        assert rows[0][2] == drive.movement_ended_at + timedelta(minutes=15), (
            "the merge must keep the live session's later end"
        )

    async def test_a_live_session_before_the_batch_merges_at_the_contact_prefix(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdmergebef", "1")
        await db_session.commit()
        device_id = device.device_id

        drives = group_drives(_samples(_SOLO_DRIVE_WITH_PREFIX_SPECS), GAP)
        assert len(drives) == 1, f"expected 1 drive, got {len(drives)}"
        drive = drives[0]
        assert drive.started_at < drive.movement_started_at, "the drive needs a contact prefix"

        async with maker() as db:
            db.add(
                DriveSession(
                    vin=vin,
                    device_id=device_id,
                    started_at=drive.started_at - timedelta(minutes=20),
                    ended_at=drive.started_at,
                )
            )
            await db.commit()

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(
                vin, device_id, _rows(*_SOLO_DRIVE_WITH_PREFIX_SPECS)
            )

        rows = await _session_rows(maker, device_id)
        assert len(rows) == 1, f"expected the two to merge into one session, got {len(rows)}"
        assert rows[0][1] == drive.started_at - timedelta(minutes=20), (
            "the merge must keep the live session's earlier start"
        )
        assert rows[0][2] == drive.movement_ended_at, "the merge must extend to the drive's own end"


# A single odometer-proven sample, isolated from everything else by more than
# the gap on both sides, so group_drives emits it as its own drive whose
# started_at, movement_started_at and movement_ended_at all land on the same
# instant. Drive 1 (minutes 0-10) is a normal drive; drive 2 (minute 60) is
# the zero-length one, proven only because its odometer reading is higher
# than any seen before it.
_ZERO_LEN_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "A6-ODOMETER", 50_000.0),
    (0, "SPEED", 40.0),
    (5, "SPEED", 45.0),
    (10, "A6-ODOMETER", 50_008.0),
    (10, "SPEED", 0.0),
    (60, "A6-ODOMETER", 50_009.0),
    (60, "ENGINE_RPM", 800.0),
    (65, "ENGINE_RPM", 800.0),
    (65, "A6-ODOMETER", 50_009.0),
    (70, "ENGINE_RPM", 800.0),
)

# A zero-length earlier drive at minute 60 (an isolated odometer-proven
# sample, same shape as `_ZERO_LEN_SPECS`'s drive 2), followed by contact-only
# RPM samples that chain `group_drives`' walk-back for a later, genuine drive
# (minutes 90 and 95) all the way back to minute 60 -- so the later drive's
# started_at lands on the exact same instant as the earlier drive's entire
# window. `_ZERO_LEN_NEIGHBOUR_EXTENSION_SPECS` then grows the later drive's
# own end further, without moving minute 60 at all.
_ZERO_LEN_NEIGHBOUR_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "A6-ODOMETER", 50_000.0),
    (60, "A6-ODOMETER", 50_001.0),
    (64, "ENGINE_RPM", 800.0),
    (77, "ENGINE_RPM", 800.0),
    (90, "SPEED", 40.0),
    (95, "SPEED", 45.0),
)
_ZERO_LEN_NEIGHBOUR_EXTENSION_SPECS: tuple[tuple[int, str, float], ...] = ((100, "SPEED", 42.0),)


class TestReconstructionAtDegenerateWindows:
    """Shapes `group_drives` can produce that collapse a window to a single
    instant, distinct from an ordinary touching boundary: a drive with no
    duration at all, a live session still open, and a zero-length drive
    sitting right where a later drive's own start is backdated to. A bound
    exclusion written to fix the touching case can reject these for the same
    reason it fixes that one, so each needs its own case. Every test asserts
    the `group_drives` shape it depends on before touching the database, so
    a fixture that drifts from the shape it is supposed to pin fails loudly
    on that assertion rather than passing for an unrelated reason.
    """

    @staticmethod
    def _maker(test_engine) -> async_sessionmaker[AsyncSession]:
        return TestReconstructionAtATouchingBoundary._maker(test_engine)

    async def test_a_zero_length_drive_matches_itself_across_reruns(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdzero", "1")
        await db_session.commit()
        device_id = device.device_id
        rows_in = _rows(*_ZERO_LEN_SPECS)

        drives = group_drives(_samples(_ZERO_LEN_SPECS), GAP)
        assert len(drives) == 2, f"expected 2 drives, got {len(drives)}"
        zero_length = drives[1]
        assert zero_length.started_at == zero_length.movement_started_at, (
            "drive 2 must be the zero-length one this test pins"
        )
        assert zero_length.movement_started_at == zero_length.movement_ended_at, (
            "drive 2 must be the zero-length one this test pins"
        )

        counts = []
        for _ in range(3):
            async with maker() as db:
                await TelemetryService(db).bulk_backfill(vin, device_id, rows_in)
            counts.append(len(await _session_rows(maker, device_id)))

        assert counts == [2, 2, 2], f"the drive count must stay stable across reruns, got {counts}"

    async def test_an_open_session_at_a_drives_start_is_left_alone(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdopen", "1")
        await db_session.commit()
        device_id = device.device_id

        specs = ((0, "ENGINE_RPM", 800.0), (5, "SPEED", 40.0), (10, "SPEED", 50.0))
        drives = group_drives(_samples(specs), GAP)
        assert len(drives) == 1, f"expected 1 drive, got {len(drives)}"
        assert drives[0].started_at == T0, "the drive's start must match the open session's start"
        assert drives[0].started_at < drives[0].movement_started_at, (
            "the drive needs a contact prefix"
        )

        async with maker() as db:
            db.add(DriveSession(vin=vin, device_id=device_id, started_at=T0, ended_at=None))
            await db.commit()

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, _rows(*specs))

        rows = await _session_rows(maker, device_id)
        assert len(rows) == 1, (
            f"the open session must not get a closed session created beside it, got {len(rows)}"
        )
        assert rows[0][2] is None, "the open session must still be open"

    async def test_a_zero_length_earlier_drive_does_not_block_extending_the_later_one(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        """A zero-length drive at an instant p, followed by a later drive whose
        started_at is backdated to that same p by a contact prefix chained far
        enough back to reach it.

        Both first-run sessions start at p, and the zero-length one also ends
        there. The zero-length drive's right exclusion removes the later
        session (it starts at p and runs on past it), and the later drive's
        left exclusion removes the zero-length session (the previous drive in
        the batch ends at p), so each drive keeps matching only its own
        session. The zero-length drive has no previous neighbour touching it,
        so no left exclusion ever applies to its own query. The re-run extends
        the later drive's end and must move only that drive's session.
        """
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdzeronb", "1")
        await db_session.commit()
        device_id = device.device_id

        drives = group_drives(_samples(_ZERO_LEN_NEIGHBOUR_SPECS), GAP)
        assert len(drives) == 2, f"expected 2 drives, got {len(drives)}"
        p = drives[0].started_at
        assert drives[0].started_at == drives[0].movement_started_at, (
            "drive 1 must be the zero-length one this test pins"
        )
        assert drives[0].movement_started_at == drives[0].movement_ended_at, (
            "drive 1 must be the zero-length one this test pins"
        )
        assert drives[1].started_at == p, "drive 2's start must be backdated to drive 1's instant"
        assert drives[1].movement_started_at > p, "drive 2 must have real evidence after p"

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(
                vin, device_id, _rows(*_ZERO_LEN_NEIGHBOUR_SPECS)
            )
        first_run = await _session_rows(maker, device_id)
        assert len(first_run) == 2, f"expected 2 sessions after the first run, got {len(first_run)}"

        expected = group_drives(
            _samples(_ZERO_LEN_NEIGHBOUR_SPECS, _ZERO_LEN_NEIGHBOUR_EXTENSION_SPECS), GAP
        )
        assert len(expected) == 2, f"expected 2 drives in the extended set, got {len(expected)}"
        assert expected[0].started_at == p, (
            "the zero-length drive must be unaffected by the extension"
        )
        assert (
            expected[0].started_at
            == expected[0].movement_started_at
            == expected[0].movement_ended_at
        ), "the zero-length drive must still be zero-length after the extension"
        assert expected[1].started_at == p, "drive 2's start must still be backdated to p"
        assert expected[1].movement_started_at > p, "drive 2 must still have real evidence after p"

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(
                vin,
                device_id,
                _rows(*_ZERO_LEN_NEIGHBOUR_SPECS, *_ZERO_LEN_NEIGHBOUR_EXTENSION_SPECS),
            )
        second_run = await _session_rows(maker, device_id)

        assert len(second_run) == 2, f"expected 2 sessions, no third one, got {len(second_run)}"
        assert [r[0] for r in second_run] == [r[0] for r in first_run], (
            "the extension must update the later drive's own session, not create a new one"
        )
        (_, start1, end1, _, _), (_, start2, end2, _, _) = second_run
        assert start1 == expected[0].started_at, "the zero-length drive's session must not move"
        assert end1 == expected[0].movement_ended_at, (
            "the zero-length drive's session must not move"
        )
        assert start2 == expected[1].started_at, "the later drive's start must stay put"
        assert end2 == expected[1].movement_ended_at, (
            "the later drive's extension must reach its end"
        )

    async def test_an_open_session_at_a_shared_instant_is_left_for_the_first_drive(
        self, test_engine, init_test_db, db_session, make_livelink_vehicle
    ):
        """Two touching drives, D1 and D2, sharing instant p, plus an open
        session (the live path's, no `external_session_id`) also starting
        at p. D1's own right exclusion applies -- D2 is its batch neighbour
        at p -- and now excludes an open session too, since one still
        running has in reality already run on past p, the same as a closed
        one whose `ended_at` says so. D1 gets its own closed session. D2's
        left exclusion excludes D1's own (closed) session, so the only
        candidate left for D2 is the open one, and D2 matches it and is
        left alone by the open-session branch: no closed session is created
        at p, and the open session itself is untouched.
        """
        maker = self._maker(test_engine)
        vin, device = await make_livelink_vehicle("sdopenmid", "1")
        await db_session.commit()
        device_id = device.device_id

        drives = group_drives(_samples(_BOUNDARY_SPECS), GAP)
        assert len(drives) == 2, f"expected 2 drives, got {len(drives)}"
        shared = drives[0].movement_ended_at
        assert drives[1].started_at == shared, "drive 2 must be backdated to drive 1's own end"

        async with maker() as db:
            db.add(DriveSession(vin=vin, device_id=device_id, started_at=shared, ended_at=None))
            await db.commit()
        before = await _session_rows(maker, device_id)
        assert len(before) == 1
        open_id = before[0][0]

        async with maker() as db:
            await TelemetryService(db).bulk_backfill(vin, device_id, _rows(*_BOUNDARY_SPECS))

        rows = await _session_rows(maker, device_id)
        assert len(rows) == 2, (
            f"expected drive 1's own session plus the untouched open one, got {len(rows)}"
        )
        by_id = {r[0]: r for r in rows}
        assert open_id in by_id, "the open session must still be the same row"
        assert by_id[open_id][2] is None, "the open session must still be open"
        assert by_id[open_id][1] == shared, "the open session must be untouched"

        closed = [r for r in rows if r[0] != open_id]
        assert len(closed) == 1, "no closed session may start at the shared instant"
        assert closed[0][1] == drives[0].started_at, (
            "drive 1's own session must start at its own start"
        )
        assert closed[0][2] == shared, "drive 1's own session must end at the shared instant"


# A drive with a contact prefix: engine on at minute 0, moving at 5, 10 and 20.
_AWAY_DRIVE_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "ENGINE_RPM", 800.0),
    (5, "SPEED", 40.0),
    (10, "SPEED", 50.0),
    (20, "SPEED", 45.0),
)


class TestAnOpenSessionIsUnboundedOnTheRight:
    """R10 (G4-68): an open session is still running, so it reaches past any
    drive that starts after it. It used to match as a point at its own
    `started_at`, which either dropped the SD drive's head for good or wrote a
    closed session inside the open one."""

    @staticmethod
    async def _open_session(
        db: AsyncSession, vin: str, device_id: str, started_at: datetime
    ) -> DriveSession:
        session = DriveSession(
            vin=vin,
            device_id=device_id,
            started_at=started_at,
            ended_at=None,
            movement_started_at=started_at,
            movement_ended_at=started_at,
            boundary_algorithm_version=1,
            effective_gap_minutes=GAP,
        )
        db.add(session)
        await db.flush()
        return session

    async def test_an_open_session_inside_the_drive_is_backdated_to_its_start(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Home WiFi came back mid-drive: the live path opened a session at
        minute 12, and the SD card holds the drive from the engine-on at 0."""
        vin, device = await make_livelink_vehicle("sdr10", "1")
        drives = group_drives(_samples(_AWAY_DRIVE_SPECS), GAP)
        assert len(drives) == 1, f"expected 1 drive, got {len(drives)}"
        assert drives[0].started_at == T0
        assert drives[0].movement_started_at == T0 + timedelta(minutes=5)

        live = await self._open_session(
            db_session, vin, device.device_id, T0 + timedelta(minutes=12)
        )
        device.current_session_id = live.id
        await db_session.flush()

        await TelemetryService(db_session).bulk_backfill(
            vin, device.device_id, _rows(*_AWAY_DRIVE_SPECS)
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1, f"expected only the open session, got {len(sessions)}"
        session = sessions[0]
        assert session.id == live.id
        assert session.ended_at is None, "the live path still owns the end"
        assert session.started_at == T0, "the drive's head must not be dropped"
        assert session.movement_started_at == T0 + timedelta(minutes=5)
        assert session.movement_ended_at == T0 + timedelta(minutes=12), (
            "the end side is the live path's, so its movement end stays put"
        )

    async def test_an_open_session_that_started_first_gets_no_closed_one_inside(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("sdr10", "2")
        started = T0 - timedelta(minutes=30)
        live = await self._open_session(db_session, vin, device.device_id, started)

        await TelemetryService(db_session).bulk_backfill(
            vin, device.device_id, _rows(*_AWAY_DRIVE_SPECS)
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 1, (
            f"no closed session may be written inside an open one, got {len(sessions)}"
        )
        assert sessions[0].id == live.id
        assert sessions[0].ended_at is None
        assert sessions[0].started_at == started, "an earlier start must not move"

    async def test_the_backdate_stops_at_the_devices_previous_close(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Same clamp `_open_session_for_movement` applies. A phone-bounded
        session never matches a drive, so it's the one closed session that
        can sit inside the backdate's reach."""
        vin, device = await make_livelink_vehicle("sdr10", "3")
        previous_end = T0 + timedelta(minutes=7)
        db_session.add(
            DriveSession(
                vin=vin,
                device_id=device.device_id,
                started_at=T0 - timedelta(minutes=10),
                ended_at=previous_end,
                external_session_id="phone-r10",
            )
        )
        live = await self._open_session(
            db_session, vin, device.device_id, T0 + timedelta(minutes=12)
        )

        await TelemetryService(db_session).bulk_backfill(
            vin, device.device_id, _rows(*_AWAY_DRIVE_SPECS)
        )

        await db_session.refresh(live)
        assert live.ended_at is None
        assert live.started_at == previous_end, "the start must not reach into a closed session"
        assert live.movement_started_at == previous_end, (
            "movement can't start before the clamped start"
        )
        assert len(await _sessions(db_session, device.device_id)) == 2


def _second_rows(*specs: tuple[int, str, float]) -> list[SdRow]:
    """`(second_offset, param_key, value)` triples as SdRows."""
    return [
        SdRow(param_key=key, value=value, timestamp=T0 + timedelta(seconds=offset))
        for offset, key, value in specs
    ]


# Drive 1 ends at 40 km/h at 300 s. Two seconds later the car reads 0, and the
# RPM at 900 s chains drive 2's walk-back to drive 1's end, so the two touch at
# 300 s. Drive 2 never goes faster than 30.
_TOUCHING_PARKED_SPECS: tuple[tuple[int, str, float], ...] = (
    (0, "SPEED", 45.0),
    (300, "SPEED", 40.0),
    (302, "SPEED", 0.0),
    (900, "ENGINE_RPM", 700.0),
    (1500, "SPEED", 25.0),
    (1800, "SPEED", 30.0),
)


class TestTouchingSessionsShareNoSample:
    """R11 (G4-67): the instant two touching drives share is the first one's."""

    async def test_drive_two_does_not_read_drive_ones_last_sample(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("sdr11", "1")
        samples = [
            (r.timestamp, r.param_key, r.value) for r in _second_rows(*_TOUCHING_PARKED_SPECS)
        ]
        drives = group_drives(samples, GAP)
        assert len(drives) == 2, f"expected 2 drives, got {len(drives)}"
        shared = T0 + timedelta(seconds=300)
        assert drives[0].movement_ended_at == shared
        assert drives[1].started_at == shared, "drive 2 must touch drive 1"

        await TelemetryService(db_session).bulk_backfill(
            vin, device.device_id, _second_rows(*_TOUCHING_PARKED_SPECS)
        )

        sessions = await _sessions(db_session, device.device_id)
        assert len(sessions) == 2, f"expected 2 sessions, got {len(sessions)}"
        first, second = sessions
        assert first.ended_at == second.started_at == shared
        assert first.max_speed == pytest.approx(45.0)
        assert second.max_speed == pytest.approx(30.0), "drive 1's 40 km/h isn't drive 2's"
        assert second.harsh_brake_count == 0, (
            "40 to 0 in two seconds straddles the boundary; drive 2 started parked"
        )
