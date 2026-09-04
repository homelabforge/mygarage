"""Narrowing a session's window must not leave figures from the wider one.

`_calculate_session_aggregates` assigns only when it finds samples (`count > 0`)
and never clears. That is deliberate and correct for the SCHEDULED refresh:
telemetry is pruned on a retention schedule while sessions are kept forever, so
an old session's window is legitimately empty and blanking it would erase real
history that was computed when the drive closed.

It is exactly wrong for a tool that REBOUNDS a session. Narrowing a window from
95 minutes of parked heartbeats down to the four minutes the vehicle actually
moved, and then leaving `avg_speed` at the value the wide window produced, is
the same class of defect PR #157 fixed -- reintroduced by the tool meant to
consolidate it.

So the two callers want opposite things, and the difference is a parameter
rather than a judgement call at the call site. Both directions get a test,
because a `clear_first` that defaults to True would silently blank every old
session on the next scheduler tick, which is a far larger bug than the one it
was added to fix.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_service import SessionService

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, 8, 0, 0)


class TestTheScheduledRefreshNeverBlanks:
    async def test_an_empty_window_keeps_its_stored_figures(
        self, db_session: AsyncSession, make_closed_drive_session
    ):
        """A session older than the retention horizon has no telemetry left.

        Its stored figures are the only record of that drive, and they were
        correct when it closed.
        """
        vin, device_id, session = await make_closed_drive_session(
            "refclear", "1", started_at=T0, ended_at=T0 + timedelta(minutes=20)
        )
        session.max_speed = 88.0
        session.distance_km = 42.0
        await db_session.flush()

        await SessionService(db_session).refresh_aggregates(session)
        await db_session.flush()

        assert session.max_speed == 88.0
        assert session.distance_km == 42.0


class TestClearFirstBlanksThenRecomputes:
    async def test_stale_figures_from_a_wider_window_are_dropped(
        self, db_session: AsyncSession, make_closed_drive_session
    ):
        """The rebound case: the window shrinks and the fast samples fall out."""
        vin, device_id, session = await make_closed_drive_session(
            "refclear", "2", started_at=T0, ended_at=T0 + timedelta(minutes=60)
        )
        for minute, speed in ((5, 90.0), (50, 20.0)):
            db_session.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key="SPEED",
                    value=speed,
                    timestamp=T0 + timedelta(minutes=minute),
                )
            )
        await db_session.flush()

        service = SessionService(db_session)
        await service.refresh_aggregates(session)
        await db_session.flush()
        assert session.max_speed == 90.0, "the wide window sees the fast sample"

        # Rebound to a window that excludes the 90 km/h sample.
        session.started_at = T0 + timedelta(minutes=40)
        session.ended_at = T0 + timedelta(minutes=60)
        await service.refresh_aggregates(session, clear_first=True)
        await db_session.flush()

        assert session.max_speed == 20.0, (
            "without clearing, the narrowed session keeps 90 km/h from a window it no longer covers"
        )

    async def test_clearing_leaves_none_when_the_new_window_is_empty(
        self, db_session: AsyncSession, make_closed_drive_session
    ):
        """A rebound onto an empty window must say "unknown", not repeat itself.

        This is the honest outcome and it is why `clear_first` is opt-in: the
        same behaviour applied to the scheduled refresh would erase history.
        """
        vin, device_id, session = await make_closed_drive_session(
            "refclear", "3", started_at=T0, ended_at=T0 + timedelta(minutes=20)
        )
        session.max_speed = 77.0
        session.avg_speed = 44.0
        session.distance_km = 30.0
        await db_session.flush()

        await SessionService(db_session).refresh_aggregates(session, clear_first=True)
        await db_session.flush()

        assert session.max_speed is None
        assert session.avg_speed is None
        assert session.distance_km is None

    async def test_the_default_is_not_to_clear(self, db_session: AsyncSession):
        """Pinned explicitly. A default of True would blank every pruned session
        on the next scheduler tick -- a far larger bug than the one clearing
        was added to fix, and one that destroys data rather than misreporting."""
        import inspect

        signature = inspect.signature(SessionService.refresh_aggregates)
        assert signature.parameters["clear_first"].default is False


class TestTheColumnListIsComplete:
    """`_DERIVED_SESSION_COLUMNS` is a hand-written list, so it is a floor.

    A column added to `_calculate_session_aggregates`' mapping table but not to
    that list would survive a rebound as a stale figure from the wider window,
    silently, because nothing else reads the list.

    **The first version of this test could not fail.** It built its candidate
    set BY ITERATING `_DERIVED_SESSION_COLUMNS`, so a column removed from the
    list was simply never examined -- and deleting `avg_coolant_temp` from the
    list left all five tests green. Measured, not hypothesised.

    So the candidate set is enumerated from the ORM instead, independently of
    the list under test: every session column that is not identity, timing or
    provenance is a candidate, whatever the list says.
    """

    #: Columns that are NOT derived from the window, so a refresh must not
    #: touch them. Everything else on the model is a candidate, which is what
    #: makes this enumeration independent of the list under test: a new derived
    #: column is picked up by being absent from here rather than present there.
    NOT_DERIVED = frozenset(
        {
            "id",
            "vin",
            "device_id",
            "started_at",
            "ended_at",
            "duration_seconds",
            "created_at",
            "external_session_id",
            "movement_started_at",
            "movement_ended_at",
            "boundary_algorithm_version",
            "effective_gap_minutes",
            # Never computed by `refresh_aggregates` -- no path writes it.
            "fuel_used_estimate",
        }
    )

    async def test_every_column_the_recompute_writes_can_be_cleared(
        self, db_session: AsyncSession, make_closed_drive_session
    ):
        from app.models.drive_session import DriveSession
        from app.services.session_service import _DERIVED_SESSION_COLUMNS

        candidates = sorted(
            name for name in DriveSession.__table__.columns.keys() if name not in self.NOT_DERIVED
        )
        assert candidates, "the exclusion list swallowed every column"

        vin, device_id, session = await make_closed_drive_session(
            "refcols", "1", started_at=T0, ended_at=T0 + timedelta(minutes=20)
        )
        # One sample of every quantity the aggregate mapping covers, plus two
        # SPEED samples so the driving-insight columns are reached as well.
        samples = [
            (1, "SPEED", 40.0),
            (2, "SPEED", 55.0),
            (2, "ENGINE_RPM", 2100.0),
            (2, "COOLANT_TMP", 88.0),
            (2, "THROTTLE", 30.0),
            (2, "FUEL", 60.0),
            (1, "A6-ODOMETER", 10_000.0),
            (3, "A6-ODOMETER", 10_005.0),
        ]
        for minute, key, value in samples:
            db_session.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key=key,
                    value=value,
                    timestamp=T0 + timedelta(minutes=minute),
                )
            )
        await db_session.flush()

        service = SessionService(db_session)
        # Blank every CANDIDATE, so "not None afterwards" means "the recompute
        # wrote it" rather than "the fixture set it".
        for column in candidates:
            setattr(session, column, None)
        await service.refresh_aggregates(session)
        await db_session.flush()

        written = {column for column in candidates if getattr(session, column) is not None}
        assert len(written) >= 10, (
            "guard on the guard: the fixture must exercise most of the recompute, "
            f"or the check below is vacuous. Wrote: {sorted(written)}"
        )
        assert written <= set(_DERIVED_SESSION_COLUMNS), (
            "the recompute writes columns the clear list does not know about, so "
            "they would survive a rebound as stale figures: "
            f"{sorted(written - set(_DERIVED_SESSION_COLUMNS))}"
        )

        # And prove the clearing reaches all of them. A sentinel per column,
        # because asserting `is None` would be asserting something false:
        # `_calculate_driving_insights` legitimately recomputes `idle_seconds`,
        # `harsh_accel_count` and `harsh_brake_count` to ZERO on a window with
        # fewer than two speed samples. Those are fresh values, not survivors.
        sentinel = -987.0
        for column in written:
            setattr(session, column, sentinel)

        session.started_at = T0 + timedelta(days=400)
        session.ended_at = T0 + timedelta(days=400, minutes=10)
        await service.refresh_aggregates(session, clear_first=True)
        await db_session.flush()

        survivors = sorted(column for column in written if getattr(session, column) == sentinel)
        assert survivors == [], (
            f"these columns survived a rebound onto an empty window, so they "
            f"would keep figures from the wider one: {survivors}"
        )
