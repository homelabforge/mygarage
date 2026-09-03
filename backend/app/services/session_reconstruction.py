"""Rebuild historic drive-session boundaries from surviving telemetry.

Opt-in, dry-run by default, and never a migration. Every session recorded before
migration 098 was bounded on *contact* -- any sign the dongle could reach the
broker -- so on this instance 83% of them are a parked WiCAN's battery
heartbeat, and real drives taken out of broker range were recorded as nothing.

The live fix is mandatory and immediate; this is neither. So most instances will
hold a session history whose definition of "a drive" changes at the upgrade
date, and on a default 90-day retention this tool can never reach further back
than that. That cannot be fixed, only disclosed: each session records the
algorithm version and gap that produced it, and the changelog says plainly that
earlier sessions were counted differently.

WHAT A NAIVE REBUILD WOULD DESTROY
----------------------------------
1. **GPS traces.** ``location_points.drive_session_id`` is ``ON DELETE
   CASCADE`` and SQLite FK enforcement is on, so the cascade actually fires. The
   development instance has zero rows in that table, which is exactly why the
   risk was invisible when this was first proposed.
2. **History older than retention.** Older sessions have no telemetry to
   rebuild from, so a rebuild deletes them and reconstructs nothing.
3. **EV history**, under any RPM-dependent predicate.

COVERAGE MUST BE PROVEN, NOT INFERRED
-------------------------------------
"The window contains surviving telemetry" is **not** proof. Retention prunes by
timestamp, so a session straddling the boundary keeps its *later* rows and loses
its movement rows; and a real drive out of broker range may have no live samples
at all. Either reads as "telemetry present, no movement" -- a phantom -- and
gets deleted.

So deletion and rebounding require **positive** evidence, all three:

* the whole window sits inside the retention horizon, with a margin;
* samples are present at both boundaries, not only in the middle;
* the device reported at a plausible cadence across it, so silence inside the
  window means the vehicle was stopped rather than that the rows were pruned.

Anything short of that leaves the session exactly as it is and reports a reason.
Refusal is a routine outcome here, not an exceptional one, which is why the run
record exists: in a quiet log a safe refusal and a broken tool look identical.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_reconstruction_run import LiveLinkReconstructionRun
from app.models.location_point import LocationPoint
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_boundaries import BOUNDARY_ALGORITHM_MOVEMENT, group_drives
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

#: How far inside the retention horizon a session must sit before its silence
#: can be read as "the vehicle was stopped" rather than "the rows were pruned".
#: A session ending the day before the horizon has already lost its opening
#: rows, and nothing about the surviving ones says so.
RETENTION_MARGIN_DAYS = 7

#: A sample must appear within this long of each end of the window, or the
#: boundary is unproven. The heartbeat interval measured on this instance is
#: about 95 minutes, so a window whose first sample is two hours in has lost
#: rows rather than started quietly.
BOUNDARY_PROOF_MINUTES = 30

#: The largest internal silence that can still be read as a stopped vehicle
#: rather than pruned rows. Above this the window is not proven and the session
#: is left alone.
MAX_INTERNAL_GAP_MINUTES = 180

#: Refusal reasons. Rendered on the LiveLink admin page, so each is a key with a
#: translated label rather than a sentence built here.
REFUSAL_NO_TELEMETRY = "no_telemetry"
REFUSAL_OUTSIDE_RETENTION = "outside_retention_horizon"
REFUSAL_UNPROVEN_BOUNDARY = "unproven_boundary"
REFUSAL_INSUFFICIENT_COVERAGE = "insufficient_coverage"
REFUSAL_HAS_LOCATION_POINTS = "has_location_points"
REFUSAL_AMBIGUOUS_OVERLAP = "ambiguous_overlap"

ALL_REFUSAL_REASONS = (
    REFUSAL_NO_TELEMETRY,
    REFUSAL_OUTSIDE_RETENTION,
    REFUSAL_UNPROVEN_BOUNDARY,
    REFUSAL_INSUFFICIENT_COVERAGE,
    REFUSAL_HAS_LOCATION_POINTS,
    REFUSAL_AMBIGUOUS_OVERLAP,
)


@dataclass
class Plan:
    """What a run did, or would do. The dry run's plan and the applied run's
    result are the same shape on purpose, so one can be compared to the other."""

    created: int = 0
    merged: int = 0
    split: int = 0
    closed: int = 0
    refusals: list[dict[str, object]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def refused(self) -> int:
        return len(self.refusals)

    def refuse(self, session_id: int, reason: str) -> None:
        self.refusals.append({"session_id": session_id, "reason": reason})

    def reason_counts(self) -> dict[str, int]:
        return dict(Counter(str(entry["reason"]) for entry in self.refusals))


class SessionReconstructionService:
    """Rebuild pre-098 session boundaries for one device at a time."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def reconstruct(
        self,
        *,
        gap_minutes: int,
        retention_days: int,
        vin: str | None = None,
        now: datetime | None = None,
    ) -> Plan:
        """Rebound every provable pre-098 session. Writes into the open transaction.

        Nothing is committed here: the caller owns the transaction, so a dry run
        is a rollback and its plan is exactly what an applied run would do. That
        is also why deletion goes through ``db.delete()`` on loaded objects
        rather than a bulk ``DELETE`` -- a rollback has to be able to undo it,
        and the cascade to ``location_points`` has to be visible to the session.
        """
        now = (now or utc_now()).replace(tzinfo=None)
        plan = Plan()

        candidates = await self._candidate_sessions(vin)
        if not candidates:
            plan.notes.append("No pre-098 sessions found; nothing to reconstruct.")
            return plan

        by_device: dict[str, list[DriveSession]] = {}
        for session in candidates:
            by_device.setdefault(session.device_id, []).append(session)

        for device_id, sessions in sorted(by_device.items()):
            await self._reconstruct_device(
                device_id, sessions, plan, gap_minutes, retention_days, now
            )

        return plan

    async def _candidate_sessions(self, vin: str | None) -> list[DriveSession]:
        """Closed, pre-098, non-Torque sessions.

        Torque is excluded by ``external_session_id``, not by heuristic: the
        phone supplies an authoritative session id, so re-bounding it on a gap
        threshold replaces good evidence with inference. An earlier design
        revision instead proposed "never delete a session carrying
        location_points", which was either vacuous or contradictory -- Torque is
        the only writer of those points, so the guard protected exactly the
        population already declared untouched, and its proposed test would have
        passed trivially.

        Version-1 sessions are excluded because they were already cut by the
        current rule. This is the field whose default had to be 0: stamping
        history as 1 would make every pre-098 session look already-correct and
        be skipped here forever.
        """
        query = (
            select(DriveSession)
            .where(DriveSession.ended_at.is_not(None))
            .where(DriveSession.external_session_id.is_(None))
            .where(DriveSession.boundary_algorithm_version < BOUNDARY_ALGORITHM_MOVEMENT)
            .order_by(DriveSession.device_id, DriveSession.started_at)
        )
        if vin:
            query = query.where(DriveSession.vin == vin)
        return list((await self.db.execute(query)).scalars().all())

    async def _reconstruct_device(
        self,
        device_id: str,
        sessions: list[DriveSession],
        plan: Plan,
        gap_minutes: int,
        retention_days: int,
        now: datetime,
    ) -> None:
        horizon = now - timedelta(days=max(0, retention_days - RETENTION_MARGIN_DAYS))

        for session in sessions:
            started = _naive(session.started_at)
            ended = _naive(session.ended_at)
            if started is None or ended is None:
                plan.refuse(session.id, REFUSAL_NO_TELEMETRY)
                continue

            if started < horizon:
                # Its opening rows are gone or going, and nothing about the
                # survivors says so. Silence here cannot be read as "stopped".
                plan.refuse(session.id, REFUSAL_OUTSIDE_RETENTION)
                continue

            samples = await self._window_samples(session.vin, device_id, started, ended)
            if not samples:
                plan.refuse(session.id, REFUSAL_NO_TELEMETRY)
                continue

            reason = _coverage_refusal(started, ended, [stamp for stamp, _k, _v in samples])
            if reason is not None:
                plan.refuse(session.id, reason)
                continue

            point_count = await self._point_count(session.id)
            drives = group_drives(samples, gap_minutes)

            if not drives:
                # A proven window with no movement in it is a phantom.
                if point_count:
                    # GPS is evidence of movement this predicate cannot see.
                    # Cheap defence rather than a reachable path today (Torque
                    # is the only writer and is excluded above), and stated as
                    # defence so the next reader need not re-derive it.
                    plan.refuse(session.id, REFUSAL_HAS_LOCATION_POINTS)
                    continue
                await self.db.delete(session)
                plan.closed += 1
                continue

            await self._apply_drives(session, drives, plan, gap_minutes, point_count)

    async def _apply_drives(
        self,
        session: DriveSession,
        drives: list,
        plan: Plan,
        gap_minutes: int,
        point_count: int,
    ) -> None:
        """Rebound `session` onto the first drive, and create the rest."""
        from app.services.session_service import SessionService

        service = SessionService(self.db)
        first = drives[0]

        session.started_at = first.started_at
        session.ended_at = first.movement_ended_at
        session.movement_started_at = first.movement_started_at
        session.movement_ended_at = first.movement_ended_at
        session.boundary_algorithm_version = BOUNDARY_ALGORITHM_MOVEMENT
        session.effective_gap_minutes = gap_minutes
        session.duration_seconds = max(
            0, int((first.movement_ended_at - first.started_at).total_seconds())
        )
        # `clear_first`, because the window has NARROWED: the recompute steps
        # assign only when they find samples and never clear, so without this
        # a session cut from 95 minutes of parked heartbeats down to the four
        # the vehicle moved would keep the `avg_speed` the wide window produced.
        await service.refresh_aggregates(session, clear_first=True)

        new_sessions: list[DriveSession] = []
        for drive in drives[1:]:
            extra = DriveSession(
                vin=session.vin,
                device_id=session.device_id,
                started_at=drive.started_at,
                ended_at=drive.movement_ended_at,
                movement_started_at=drive.movement_started_at,
                movement_ended_at=drive.movement_ended_at,
                duration_seconds=max(
                    0, int((drive.movement_ended_at - drive.started_at).total_seconds())
                ),
                boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
                effective_gap_minutes=gap_minutes,
            )
            self.db.add(extra)
            new_sessions.append(extra)

        if new_sessions:
            await self.db.flush()
            for extra in new_sessions:
                await service.refresh_aggregates(extra, clear_first=True)
            plan.split += 1
            plan.created += len(new_sessions)
            if point_count:
                await self._reassign_points(session, new_sessions)
        else:
            plan.closed += 1

    async def _reassign_points(self, original: DriveSession, extras: list[DriveSession]) -> None:
        """Move GPS points into whichever session now covers their timestamp.

        "Never delete a session with points" cannot express a split: the points
        of the second half belong to a session that did not exist a moment ago.
        Every point is checked to still have a home afterwards, because
        ``drive_session_id`` is ``ON DELETE CASCADE`` and an orphan here is a
        trace that vanishes the next time its old session is touched.
        """
        points = list(
            (
                await self.db.execute(
                    select(LocationPoint).where(LocationPoint.drive_session_id == original.id)
                )
            )
            .scalars()
            .all()
        )
        if not points:
            return

        windows = [(original, _naive(original.started_at), _naive(original.ended_at))]
        windows += [(extra, _naive(extra.started_at), _naive(extra.ended_at)) for extra in extras]

        for point in points:
            stamp = _naive(point.timestamp)
            home = next(
                (
                    owner
                    for owner, start, end in windows
                    if start is not None and end is not None and start <= stamp <= end
                ),
                None,
            )
            if home is None:
                # Between two drives: keep it on the nearest window rather than
                # orphaning it. A point with no session is invisible in the trip
                # view and dies with the next cascade.
                home = min(
                    windows,
                    key=lambda w: min(
                        abs((stamp - w[1]).total_seconds()) if w[1] else float("inf"),
                        abs((stamp - w[2]).total_seconds()) if w[2] else float("inf"),
                    ),
                )[0]
            point.drive_session_id = home.id

        await self.db.flush()

    async def _window_samples(
        self, vin: str, device_id: str, started: datetime, ended: datetime
    ) -> list[tuple[datetime, str, float]]:
        rows = await self.db.execute(
            select(VehicleTelemetry.timestamp, VehicleTelemetry.param_key, VehicleTelemetry.value)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.device_id == device_id)
            .where(VehicleTelemetry.timestamp >= started)
            .where(VehicleTelemetry.timestamp <= ended)
            .order_by(VehicleTelemetry.timestamp)
        )
        return [
            (_naive(stamp), key, float(value))
            for stamp, key, value in rows.all()
            if stamp is not None and value is not None
        ]

    async def _point_count(self, session_id: int) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count(LocationPoint.id)).where(
                        LocationPoint.drive_session_id == session_id
                    )
                )
            ).scalar()
            or 0
        )

    async def record_run(
        self,
        plan: Plan,
        *,
        dry_run: bool,
        gap_minutes: int,
        started_at: datetime,
        finished_at: datetime | None = None,
    ) -> LiveLinkReconstructionRun:
        """Persist what this run did, including what it refused and why.

        A log rotates and a container restart loses it, so the one question
        asked afterwards -- what did this change, and what did it refuse? --
        becomes unanswerable at exactly the moment it matters. It also gives the
        dry run a purpose beyond reassurance: the plan is recorded, so the
        applied run can be compared with what was previewed.
        """
        run = LiveLinkReconstructionRun(
            started_at=started_at,
            finished_at=finished_at or utc_now().replace(tzinfo=None),
            dry_run=dry_run,
            gap_minutes=gap_minutes,
            boundary_version=BOUNDARY_ALGORITHM_MOVEMENT,
            sessions_created=plan.created,
            sessions_merged=plan.merged,
            sessions_split=plan.split,
            sessions_closed=plan.closed,
            sessions_refused=plan.refused,
            refusals=json.dumps(plan.refusals) if plan.refusals else None,
        )
        self.db.add(run)
        await self.db.flush()
        return run


def _naive(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


def _coverage_refusal(started: datetime, ended: datetime, stamps: list[datetime]) -> str | None:
    """None if the window's coverage is PROVEN, else the reason it is not.

    All three checks are positive evidence. "There is telemetry in the window"
    is not: retention prunes by timestamp, so a session straddling the boundary
    keeps its later rows and loses its movement rows, and a drive taken out of
    broker range may have no live samples at all. Both read as "telemetry
    present, no movement" -- which is what a phantom looks like, and phantoms
    get deleted.
    """
    if not stamps:
        return REFUSAL_NO_TELEMETRY

    boundary = timedelta(minutes=BOUNDARY_PROOF_MINUTES)
    if stamps[0] - started > boundary or ended - stamps[-1] > boundary:
        return REFUSAL_UNPROVEN_BOUNDARY

    limit = timedelta(minutes=MAX_INTERNAL_GAP_MINUTES)
    for earlier, later in zip(stamps, stamps[1:], strict=False):
        if later - earlier > limit:
            return REFUSAL_INSUFFICIENT_COVERAGE

    return None
