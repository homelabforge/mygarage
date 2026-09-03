"""The reconstruction tool's safety rules.

This tool deletes and rebounds session history, so the tests that matter are the
ones proving it REFUSES. A reconstruction that rebuilds correctly 90% of the
time and silently erases the other 10% is worse than no tool at all: the live
fix can be reversed with a setting, and deleted history cannot.

Every refusal case below comes from a specific way the naive version would have
destroyed data:

- **No telemetry.** Sessions are kept forever, telemetry is pruned on a 90-day
  schedule. An old session has an empty window, which is indistinguishable from
  "the vehicle never moved" -- so a rebuild deletes it and reconstructs nothing.
- **Straddling the retention horizon.** Retention prunes by TIMESTAMP, so such
  a session keeps its later rows and loses its movement rows. "Telemetry
  present, no movement" is exactly what a phantom looks like.
- **An unproven boundary.** Samples only in the middle mean the ends were
  pruned, and the tool would narrow the window to the surviving rows and call
  that the drive.
- **A coverage gap.** A drive taken out of broker range has no live samples at
  all, and its session looks empty.
- **GPS points.** `location_points.drive_session_id` is `ON DELETE CASCADE` and
  SQLite FK enforcement is on, so the cascade fires. The development instance
  has zero rows in that table, which is precisely why the risk was invisible
  when this was first proposed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.location_point import LocationPoint
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_reconstruction import (
    REFUSAL_HAS_LOCATION_POINTS,
    REFUSAL_INSUFFICIENT_COVERAGE,
    REFUSAL_NO_TELEMETRY,
    REFUSAL_OUTSIDE_RETENTION,
    REFUSAL_UNPROVEN_BOUNDARY,
    SessionReconstructionService,
)

pytestmark = pytest.mark.asyncio

GAP = 15
RETENTION = 90

#: "Now" for every test, and a base recent enough to sit inside the horizon.
NOW = datetime(2026, 9, 1, 12, 0, 0)
T0 = datetime(2026, 8, 20, 8, 0, 0)


async def _seed(
    db: AsyncSession, vin: str, device_id: str, specs: list[tuple[int, str, float]]
) -> None:
    for minute, key, value in specs:
        db.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key=key,
                value=value,
                timestamp=T0 + timedelta(minutes=minute),
            )
        )
    await db.flush()


async def _session(
    db: AsyncSession,
    vin: str,
    device_id: str,
    *,
    start_minute: int = 0,
    end_minute: int = 60,
    **kwargs,
) -> DriveSession:
    session = DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=T0 + timedelta(minutes=start_minute),
        ended_at=T0 + timedelta(minutes=end_minute),
        boundary_algorithm_version=0,
        **kwargs,
    )
    db.add(session)
    await db.flush()
    return session


async def _run(db: AsyncSession, vin: str | None = None, retention: int = RETENTION):
    return await SessionReconstructionService(db).reconstruct(
        gap_minutes=GAP, retention_days=retention, vin=vin, now=NOW
    )


async def _exists(db: AsyncSession, session_id: int) -> bool:
    return (
        await db.execute(select(DriveSession.id).where(DriveSession.id == session_id))
    ).scalar_one_or_none() is not None


def _reasons(plan) -> set[str]:
    return {str(entry["reason"]) for entry in plan.refusals}


class TestItRefuses:
    async def test_a_session_with_no_surviving_telemetry_is_untouched(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("recref", "1")
        session = await _session(db_session, vin, device.device_id)
        before = (session.started_at, session.ended_at)

        plan = await _run(db_session, vin)

        assert await _exists(db_session, session.id)
        assert (session.started_at, session.ended_at) == before
        assert _reasons(plan) == {REFUSAL_NO_TELEMETRY}

    async def test_a_session_older_than_the_horizon_is_untouched(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Retention prunes by timestamp, so this session's MOVEMENT rows are
        gone while its later rows survive -- and nothing about the survivors
        says so."""
        vin, device = await make_livelink_vehicle("recref", "2")
        old_start = NOW - timedelta(days=RETENTION - 2)
        session = DriveSession(
            vin=vin,
            device_id=device.device_id,
            started_at=old_start,
            ended_at=old_start + timedelta(minutes=60),
            boundary_algorithm_version=0,
        )
        db_session.add(session)
        await db_session.flush()
        db_session.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device.device_id,
                param_key="BATTERY_VOLTAGE",
                value=12.4,
                timestamp=old_start + timedelta(minutes=59),
            )
        )
        await db_session.flush()

        plan = await _run(db_session, vin)

        assert await _exists(db_session, session.id)
        assert _reasons(plan) == {REFUSAL_OUTSIDE_RETENTION}

    async def test_a_window_with_samples_only_in_the_middle_is_untouched(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The ends were pruned. Narrowing to the survivors would call the
        middle of a drive the whole drive."""
        vin, device = await make_livelink_vehicle("recref", "3")
        session = await _session(db_session, vin, device.device_id, end_minute=180)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [(88, "SPEED", 50.0), (90, "SPEED", 55.0), (92, "SPEED", 48.0)],
        )

        plan = await _run(db_session, vin)

        assert await _exists(db_session, session.id)
        assert _reasons(plan) == {REFUSAL_UNPROVEN_BOUNDARY}

    async def test_a_window_with_a_coverage_gap_is_untouched(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A drive out of broker range leaves a hole. Silence inside a hole is
        not evidence the vehicle was stopped."""
        vin, device = await make_livelink_vehicle("recref", "4")
        session = await _session(db_session, vin, device.device_id, end_minute=600)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [
                (5, "SPEED", 50.0),
                (10, "SPEED", 52.0),
                # Nearly eight hours of nothing.
                (590, "SPEED", 48.0),
                (595, "SPEED", 46.0),
            ],
        )

        plan = await _run(db_session, vin)

        assert await _exists(db_session, session.id)
        assert _reasons(plan) == {REFUSAL_INSUFFICIENT_COVERAGE}

    async def test_a_phantom_carrying_gps_points_is_untouched(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """GPS is evidence of movement this predicate cannot read.

        `drive_session_id` is ON DELETE CASCADE, so deleting the session takes
        the trace with it, permanently and silently.
        """
        vin, device = await make_livelink_vehicle("recref", "5")
        session = await _session(db_session, vin, device.device_id)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [(m, "BATTERY_VOLTAGE", 12.4) for m in (1, 30, 59)],
        )
        db_session.add(
            LocationPoint(
                vin=vin,
                drive_session_id=session.id,
                source="torque",
                timestamp=T0 + timedelta(minutes=20),
                latitude=Decimal("47.62"),
                longitude=Decimal("-122.35"),
            )
        )
        await db_session.flush()

        plan = await _run(db_session, vin)

        assert await _exists(db_session, session.id)
        assert _reasons(plan) == {REFUSAL_HAS_LOCATION_POINTS}

    async def test_a_torque_session_is_never_a_candidate(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Excluded by `external_session_id`, not by heuristic.

        The phone supplies an authoritative session id, so re-bounding it on a
        gap threshold replaces good evidence with inference. Note it is not even
        REFUSED -- it never enters the candidate set, so it produces no refusal
        row for an admin to wonder about.
        """
        vin, device = await make_livelink_vehicle("recref", "6")
        session = await _session(db_session, vin, device.device_id, external_session_id="phone-9")
        before = (session.started_at, session.ended_at)
        await _seed(
            db_session, vin, device.device_id, [(m, "BATTERY_VOLTAGE", 12.4) for m in (1, 30, 59)]
        )

        plan = await _run(db_session, vin)

        assert await _exists(db_session, session.id)
        assert (session.started_at, session.ended_at) == before
        assert plan.refusals == []

    async def test_a_session_already_cut_by_this_algorithm_is_skipped(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Version 1 means "already correct". This is the field whose default
        had to be 0: stamping history as 1 would make every pre-098 session look
        already-correct and be skipped here forever."""
        vin, device = await make_livelink_vehicle("recref", "7")
        session = await _session(db_session, vin, device.device_id)
        session.boundary_algorithm_version = 1
        await db_session.flush()
        before = (session.started_at, session.ended_at)

        plan = await _run(db_session, vin)

        assert (session.started_at, session.ended_at) == before
        assert plan.refusals == []


class TestItRebuilds:
    async def test_a_phantom_with_a_proven_empty_window_is_removed(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The 83% case: a session that is a battery heartbeat.

        Removed only because all three coverage proofs passed -- the window is
        inside the horizon, samples sit at both ends, and the cadence is
        plausible throughout -- so the silence really does mean stopped.
        """
        vin, device = await make_livelink_vehicle("recbuild", "1")
        session = await _session(db_session, vin, device.device_id)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [(m, "BATTERY_VOLTAGE", 12.4) for m in (1, 15, 30, 45, 59)],
        )

        plan = await _run(db_session, vin)

        assert not await _exists(db_session, session.id)
        assert plan.closed == 1
        assert plan.refusals == []

    async def test_a_session_holding_one_drive_is_narrowed_to_it(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("recbuild", "2")
        session = await _session(db_session, vin, device.device_id, end_minute=60)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [
                (1, "BATTERY_VOLTAGE", 12.4),
                (20, "A6-ODOMETER", 30_000.0),
                (21, "SPEED", 50.0),
                (22, "SPEED", 55.0),
                (25, "A6-ODOMETER", 30_006.0),
                (40, "BATTERY_VOLTAGE", 12.4),
                (59, "BATTERY_VOLTAGE", 12.4),
            ],
        )

        plan = await _run(db_session, vin)

        assert plan.refusals == []
        assert session.boundary_algorithm_version == 1
        assert session.effective_gap_minutes == GAP
        assert session.ended_at == T0 + timedelta(minutes=25), (
            "the tail of parked heartbeats must not stay inside the drive"
        )
        assert session.distance_km == pytest.approx(6.0)

    async def test_narrowing_drops_the_wide_windows_aggregates(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The defect PR #157 fixed, which this tool would otherwise reintroduce."""
        vin, device = await make_livelink_vehicle("recbuild", "3")
        session = await _session(db_session, vin, device.device_id, end_minute=60)
        session.max_speed = 90.0
        session.distance_km = 400.0
        await db_session.flush()
        await _seed(
            db_session,
            vin,
            device.device_id,
            [
                (1, "SPEED", 0.0),
                (20, "SPEED", 30.0),
                (21, "SPEED", 32.0),
                (40, "SPEED", 0.0),
                (59, "SPEED", 0.0),
            ],
        )

        await _run(db_session, vin)

        assert session.max_speed == pytest.approx(32.0), (
            "90 km/h came from a window this session no longer covers"
        )
        assert session.distance_km != pytest.approx(400.0)

    async def test_a_session_spanning_two_drives_is_split(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("recbuild", "4")
        await _session(db_session, vin, device.device_id, end_minute=120)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [
                (1, "SPEED", 45.0),
                (2, "SPEED", 50.0),
                (30, "BATTERY_VOLTAGE", 12.4),
                (60, "BATTERY_VOLTAGE", 12.4),
                (90, "SPEED", 48.0),
                (91, "SPEED", 52.0),
                (119, "BATTERY_VOLTAGE", 12.4),
            ],
        )

        plan = await _run(db_session, vin)

        assert plan.split == 1
        assert plan.created == 1
        sessions = list(
            (
                await db_session.execute(
                    select(DriveSession)
                    .where(DriveSession.device_id == device.device_id)
                    .order_by(DriveSession.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(sessions) == 2
        assert all(s.boundary_algorithm_version == 1 for s in sessions)

    async def test_no_two_output_sessions_overlap(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Nothing forbids overlapping windows -- the session time indexes are
        non-unique -- and every aggregate is a window scan, so two overlapping
        sessions both claim the same samples and both report the same distance.
        Extending a session toward its true bounds is exactly the operation that
        creates one."""
        vin, device = await make_livelink_vehicle("recbuild", "5")
        await _session(db_session, vin, device.device_id, end_minute=200)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [
                (1, "SPEED", 45.0),
                (2, "SPEED", 50.0),
                (40, "SPEED", 48.0),
                (41, "SPEED", 52.0),
                (100, "SPEED", 44.0),
                (101, "SPEED", 46.0),
                (160, "SPEED", 40.0),
                (161, "SPEED", 42.0),
                (199, "BATTERY_VOLTAGE", 12.4),
            ],
        )

        await _run(db_session, vin)

        sessions = list(
            (
                await db_session.execute(
                    select(DriveSession)
                    .where(DriveSession.device_id == device.device_id)
                    .order_by(DriveSession.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(sessions) == 4
        for earlier, later in zip(sessions, sessions[1:], strict=False):
            assert earlier.ended_at <= later.started_at, (
                f"{earlier.id} ends {earlier.ended_at}, {later.id} starts {later.started_at}"
            )

    async def test_a_split_reassigns_every_gps_point(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """ "Never delete a session with points" cannot express a split: the
        second half's points belong to a session that did not exist a moment
        ago. An orphan is invisible in the trip view and dies with the next
        cascade."""
        vin, device = await make_livelink_vehicle("recbuild", "6")
        session = await _session(db_session, vin, device.device_id, end_minute=120)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [
                (1, "SPEED", 45.0),
                (2, "SPEED", 50.0),
                (30, "BATTERY_VOLTAGE", 12.4),
                (60, "BATTERY_VOLTAGE", 12.4),
                (90, "SPEED", 48.0),
                (91, "SPEED", 52.0),
                (119, "BATTERY_VOLTAGE", 12.4),
            ],
        )
        for minute in (1, 2, 90, 91):
            db_session.add(
                LocationPoint(
                    vin=vin,
                    drive_session_id=session.id,
                    source="torque",
                    timestamp=T0 + timedelta(minutes=minute),
                    latitude=Decimal("47.62"),
                    longitude=Decimal(f"-122.{minute:02d}"),
                )
            )
        await db_session.flush()

        await _run(db_session, vin)

        points = list(
            (await db_session.execute(select(LocationPoint).where(LocationPoint.vin == vin)))
            .scalars()
            .all()
        )
        assert len(points) == 4, "no point may be deleted by a split"
        assert all(p.drive_session_id is not None for p in points), "a point was orphaned"

        # Each point must sit inside the window of the session it now belongs to.
        owners = {
            s.id: (s.started_at, s.ended_at)
            for s in (
                await db_session.execute(
                    select(DriveSession).where(DriveSession.device_id == device.device_id)
                )
            )
            .scalars()
            .all()
        }
        for point in points:
            start, end = owners[point.drive_session_id]
            assert start <= point.timestamp <= end, (
                f"point at {point.timestamp} assigned to a session covering {start}..{end}"
            )


class TestTheRunRecord:
    async def test_it_records_the_counts_and_the_refusals(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """A log rotates and a container restart loses it. The one question an
        admin asks afterwards -- what did this change, and what did it refuse? --
        must survive both."""
        vin, device = await make_livelink_vehicle("recrun", "1")
        refused = await _session(db_session, vin, device.device_id)  # no telemetry
        service = SessionReconstructionService(db_session)

        started = NOW
        plan = await service.reconstruct(
            gap_minutes=GAP, retention_days=RETENTION, vin=vin, now=NOW
        )
        run = await service.record_run(plan, dry_run=True, gap_minutes=GAP, started_at=started)

        assert run.dry_run is True
        assert run.gap_minutes == GAP
        assert run.boundary_version == 1
        assert run.sessions_refused == 1
        assert json.loads(run.refusals) == [
            {"session_id": refused.id, "reason": REFUSAL_NO_TELEMETRY}
        ]

    async def test_a_clean_run_records_no_refusals(self, db_session: AsyncSession):
        """Distinguishing "refused nothing" from "wrote nothing to the column"
        is the whole reason the column is nullable."""
        service = SessionReconstructionService(db_session)
        plan = await service.reconstruct(
            gap_minutes=GAP, retention_days=RETENTION, vin="NOSUCHVIN000000", now=NOW
        )
        run = await service.record_run(plan, dry_run=True, gap_minutes=GAP, started_at=NOW)

        assert run.sessions_refused == 0
        assert run.refusals is None

    async def test_reason_counts_summarise_a_mixed_run(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("recrun", "2")
        await _session(db_session, vin, device.device_id)  # no telemetry
        gapped = await _session(
            db_session, vin, device.device_id, start_minute=700, end_minute=1400
        )
        await _seed(
            db_session,
            vin,
            device.device_id,
            [(705, "SPEED", 40.0), (710, "SPEED", 42.0), (1395, "SPEED", 44.0)],
        )

        plan = await _run(db_session, vin)

        assert plan.reason_counts() == {
            REFUSAL_NO_TELEMETRY: 1,
            REFUSAL_INSUFFICIENT_COVERAGE: 1,
        }, plan.refusals
        assert await _exists(db_session, gapped.id)


class TestTheDryRunWritesNothing:
    async def test_a_rollback_undoes_every_change_including_points(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Asserting session counts alone is not enough.

        Deletion goes through `db.delete()` on loaded objects specifically so a
        rollback can undo it AND so the cascade to `location_points` is visible
        to the session. A bulk `DELETE` would satisfy a session-count assertion
        and take the traces with it.
        """
        vin, device = await make_livelink_vehicle("recdry", "1")
        # Held as plain strings/ints. The rollback below EXPIRES every loaded
        # object, so touching `device.device_id` afterwards fires a synchronous
        # lazy load and raises MissingGreenlet rather than failing the
        # assertion it was part of.
        device_id: str = device.device_id
        session = await _session(db_session, vin, device_id, end_minute=120)
        session_id = session.id
        await _seed(
            db_session,
            vin,
            device_id,
            [
                (1, "SPEED", 45.0),
                (2, "SPEED", 50.0),
                (30, "BATTERY_VOLTAGE", 12.4),
                (60, "BATTERY_VOLTAGE", 12.4),
                (90, "SPEED", 48.0),
                (91, "SPEED", 52.0),
                (119, "BATTERY_VOLTAGE", 12.4),
            ],
        )
        db_session.add(
            LocationPoint(
                vin=vin,
                drive_session_id=session_id,
                source="torque",
                timestamp=T0 + timedelta(minutes=91),
                latitude=Decimal("47.62"),
                longitude=Decimal("-122.35"),
            )
        )
        await db_session.commit()

        sessions_before = (
            await db_session.execute(
                select(func.count(DriveSession.id)).where(DriveSession.device_id == device_id)
            )
        ).scalar()
        points_before = (
            await db_session.execute(
                select(func.count(LocationPoint.id)).where(LocationPoint.vin == vin)
            )
        ).scalar()
        original_end = session.ended_at

        plan = await _run(db_session, vin)
        assert plan.split == 1, "the fixture must actually change something"

        await db_session.rollback()

        sessions_after = (
            await db_session.execute(
                select(func.count(DriveSession.id)).where(DriveSession.device_id == device_id)
            )
        ).scalar()
        points_after = (
            await db_session.execute(
                select(func.count(LocationPoint.id)).where(LocationPoint.vin == vin)
            )
        ).scalar()

        assert sessions_after == sessions_before
        assert points_after == points_before
        reloaded = (
            await db_session.execute(select(DriveSession).where(DriveSession.id == session_id))
        ).scalar_one()
        assert reloaded.ended_at == original_end
        assert reloaded.boundary_algorithm_version == 0


class TestTheCommandLineContract:
    """Exit codes and the dry-run default, exercised through `run()` itself.

    Worth testing rather than eyeballing: the dry-run default and the exit-2
    convention are the two things an operator relies on before pointing this at
    real history, and both live in the CLI rather than the service. A tool that
    silently defaulted to `--apply` would be indistinguishable from a correct
    one until it had already rewritten a database.
    """

    @staticmethod
    def _session_factory(db_session: AsyncSession):
        """`AsyncSessionLocal` stand-in that hands back the test session.

        `contextlib.nullcontext` rather than the real factory: the real one
        closes the session on exit, and closing the shared test session takes
        every later assertion with it.
        """
        import contextlib

        return lambda: contextlib.nullcontext(db_session)

    async def test_the_default_is_a_dry_run(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ):
        import argparse

        from app.models.livelink_reconstruction_run import LiveLinkReconstructionRun
        from tools import reconstruct_session_boundaries as tool

        vin, device = await make_livelink_vehicle("reccli", "1")
        session = await _session(db_session, vin, device.device_id, end_minute=60)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [(m, "BATTERY_VOLTAGE", 12.4) for m in (1, 15, 30, 45, 59)],
        )
        await db_session.commit()
        session_id = session.id

        monkeypatch.setattr(tool, "AsyncSessionLocal", self._session_factory(db_session))
        code = await tool.run(argparse.Namespace(vin=vin, gap_minutes=GAP, apply=False))

        assert code == 0
        assert await _exists(db_session, session_id), (
            "a dry run must not delete the phantom it found"
        )
        run_row = (
            (
                await db_session.execute(
                    select(LiveLinkReconstructionRun).order_by(LiveLinkReconstructionRun.id.desc())
                )
            )
            .scalars()
            .first()
        )
        assert run_row is not None, "the dry run must still leave an audit row"
        assert run_row.dry_run is True
        assert run_row.sessions_closed == 1, (
            "the audit row records what it WOULD have done, which is the only "
            "thing that makes a preview worth more than reassurance"
        )

    async def test_apply_writes_and_the_audit_row_says_so(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ):
        import argparse

        from app.models.livelink_reconstruction_run import LiveLinkReconstructionRun
        from tools import reconstruct_session_boundaries as tool

        vin, device = await make_livelink_vehicle("reccli", "2")
        session = await _session(db_session, vin, device.device_id, end_minute=60)
        await _seed(
            db_session,
            vin,
            device.device_id,
            [(m, "BATTERY_VOLTAGE", 12.4) for m in (1, 15, 30, 45, 59)],
        )
        await db_session.commit()
        session_id = session.id

        monkeypatch.setattr(tool, "AsyncSessionLocal", self._session_factory(db_session))
        code = await tool.run(argparse.Namespace(vin=vin, gap_minutes=GAP, apply=True))

        assert code == 0
        assert not await _exists(db_session, session_id)
        run_row = (
            (
                await db_session.execute(
                    select(LiveLinkReconstructionRun).order_by(LiveLinkReconstructionRun.id.desc())
                )
            )
            .scalars()
            .first()
        )
        assert run_row is not None
        assert run_row.dry_run is False

    async def test_a_refusal_exits_two(
        self, db_session: AsyncSession, make_livelink_vehicle, monkeypatch
    ):
        """Exit 2 is not a failure -- it is "some sessions were left alone, on
        purpose". Following `backfill_livelink_odometer.py` and
        `fix_session_odometer_units.py`, both of which use 2 for a refusal."""
        import argparse

        from tools import reconstruct_session_boundaries as tool

        vin, device = await make_livelink_vehicle("reccli", "3")
        await _session(db_session, vin, device.device_id)  # no telemetry at all
        await db_session.commit()

        monkeypatch.setattr(tool, "AsyncSessionLocal", self._session_factory(db_session))
        code = await tool.run(argparse.Namespace(vin=vin, gap_minutes=GAP, apply=False))

        assert code == 2

    async def test_nothing_to_do_exits_zero(self, db_session: AsyncSession, monkeypatch):
        import argparse

        from tools import reconstruct_session_boundaries as tool

        monkeypatch.setattr(tool, "AsyncSessionLocal", self._session_factory(db_session))
        code = await tool.run(
            argparse.Namespace(vin="NOSUCHVIN000000", gap_minutes=GAP, apply=False)
        )

        assert code == 0
