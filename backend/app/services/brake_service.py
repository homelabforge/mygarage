"""Brake tracking business logic: axle setup, measurements, brake jobs and the axle reminders (#202)."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement
from app.models.reminder import Reminder
from app.models.user import User
from app.schemas.brake import (
    DISC_MEASURES,
    DRUM_MEASURES,
    MEASURES,
    BrakeAxleResponse,
    BrakeAxleUpdate,
    BrakeCornerResponse,
    BrakeJobCreate,
    BrakeJobResponse,
    BrakeJobUpdate,
    BrakeMeasurementBatchCreate,
    BrakeMeasurementResponse,
    BrakeMeasurementUpdate,
    BrakeOverviewResponse,
)
from app.services.brake_wear import (
    AXLE_OF,
    AXLES,
    POSITIONS,
    Axle,
    AxleSetup,
    BrakeCondition,
    BrakePosition,
    BrakeWear,
    BrakeWearStatus,
    axle_setup,
    brake_condition,
    latest_job,
    project_brake_wear,
    reminder_due,
    surface_reading,
)
from app.services.reminder_service import start_readings
from app.services.tire_service import TireService
from app.services.usage_axis import VehicleAxes
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.household_time import household_today

logger = logging.getLogger(__name__)

#: `vehicle_reminders.source` for each axle's "brake pads low" reminder. The
#: sync finds its reminder by this and never adopts a row a person wrote.
REMINDER_SOURCE: dict[Axle, str] = {"front": "low_brakes_front", "rear": "low_brakes_rear"}

_LOW = (BrakeCondition.DUE_SOON, BrakeCondition.REPLACE_NOW)
#: What a job writes into its corners' measurements, and moves when it moves.
_JOB_CONTEXT = ("performed_on", "odometer_km", "engine_hours")


@dataclass(frozen=True)
class _Corner:
    """One corner worked out: what its card and its axle reminder read."""

    position: BrakePosition
    setup: AxleSetup
    wear: BrakeWear
    condition: BrakeCondition
    measurements: list[BrakeMeasurement]
    jobs: list[BrakeJob]


def _newest_first(rows: Iterable[BrakeMeasurement | BrakeJob]) -> list:
    def key(row: BrakeMeasurement | BrakeJob) -> tuple[dt.date, int]:
        day = row.recorded_at if isinstance(row, BrakeMeasurement) else row.performed_on
        return (day, row.id or 0)

    return sorted(rows, key=key, reverse=True)


def _reminder_title(setup: AxleSetup) -> str:
    """Title of an axle's low-brakes reminder, read in the calendar and the notification."""
    part = "shoes" if setup.brake_type == "drum" else "pads"
    return f"{setup.axle.capitalize()} brake {part} low"


UNTRACKED_DISTANCE = (
    "This vehicle doesn't track distance, so a brake record can't take an odometer reading. "
    "Use the hour meter instead."
)
UNTRACKED_HOURS = (
    "This vehicle doesn't track engine hours, so a brake record can't take an hour meter reading."
)


def _refuse_untracked(
    axes: VehicleAxes, odometer_km: object | None, engine_hours: object | None
) -> None:
    """422 a brake write carrying a figure for an axis the vehicle doesn't track. A null is fine."""
    if odometer_km is not None and not axes.tracks("distance"):
        raise HTTPException(status_code=422, detail=UNTRACKED_DISTANCE)
    if engine_hours is not None and not axes.tracks("hours"):
        raise HTTPException(status_code=422, detail=UNTRACKED_HOURS)


def _refuse_other_type(position: str, setup: AxleSetup, figures: dict[str, object]) -> None:
    """422 a figure the corner's brake type doesn't take. A null is fine on any."""
    foreign = DRUM_MEASURES if setup.brake_type == "disc" else DISC_MEASURES
    wrong = sorted(name for name in foreign if figures.get(name) is not None)
    if wrong:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{position} is set up as {setup.brake_type} brakes and doesn't take "
                f"{', '.join(wrong)}. Change Axle setup first if that's wrong."
            ),
        )


class BrakeService:
    """Reads and writes one vehicle's brakes, and keeps its axle reminders in step."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _lock(self, vin: str, current_user: User | None) -> VehicleAxes:
        """The vehicle lock, then the axes, for a write already past its access check.

        In the tire order: the access check runs in each public method itself
        (the CI authz tripwire reads one call level down from the route), the
        lock comes next, and only then any brake read, so every read after it
        sees the last committed writer.
        """
        await lock_vehicle_for_write(self.db, vin)
        return await TireService(self.db).request_axes(current_user, vin)

    async def _load(
        self, vin: str
    ) -> tuple[dict[str, BrakeAxle], list[BrakeMeasurement], list[BrakeJob]]:
        """Every brake row of the vehicle, read fresh from the database."""
        fresh = {"populate_existing": True}
        axles = (
            (
                await self.db.execute(
                    select(BrakeAxle).where(BrakeAxle.vin == vin).execution_options(**fresh)
                )
            )
            .scalars()
            .all()
        )
        measurements = (
            (
                await self.db.execute(
                    select(BrakeMeasurement)
                    .where(BrakeMeasurement.vin == vin)
                    .execution_options(**fresh)
                )
            )
            .scalars()
            .all()
        )
        jobs = (
            (
                await self.db.execute(
                    select(BrakeJob).where(BrakeJob.vin == vin).execution_options(**fresh)
                )
            )
            .scalars()
            .all()
        )
        return {row.axle: row for row in axles}, list(measurements), list(jobs)

    async def _corners(
        self, vin: str, axes: VehicleAxes
    ) -> tuple[dict[Axle, AxleSetup], list[_Corner]]:
        """Each axle's setup and each corner worked out, from what is stored now."""
        rows, measurements, jobs = await self._load(vin)
        setups = {axle: axle_setup(axle, rows.get(axle)) for axle in AXLES}
        today = household_today()
        corners = []
        for position in POSITIONS:
            setup = setups[AXLE_OF[position]]
            own_measurements = [m for m in measurements if m.position == position]
            own_jobs = [j for j in jobs if j.position == position]
            wear = project_brake_wear(own_measurements, own_jobs, setup, axes.primary)
            corners.append(
                _Corner(
                    position=position,
                    setup=setup,
                    wear=wear,
                    condition=brake_condition(wear, setup, today),
                    measurements=own_measurements,
                    jobs=own_jobs,
                )
            )
        return setups, corners

    @staticmethod
    def _corner_response(corner: _Corner) -> BrakeCornerResponse:
        wear, setup = corner.wear, corner.setup
        latest = wear.latest
        surface = surface_reading(corner.measurements, corner.jobs, setup)
        last_job = latest_job(corner.jobs, lambda _job: True)
        projected = wear.status in (
            BrakeWearStatus.PROJECTED,
            BrakeWearStatus.AT_OR_BELOW_MINIMUM,
        )
        return BrakeCornerResponse(
            position=corner.position,
            axle=setup.axle,
            brake_type=setup.brake_type,
            condition=corner.condition.value,
            wear_status=wear.status.value,
            thinnest_mm=wear.thinnest_mm,
            inner_pad_mm=wear.inner_pad_mm,
            outer_pad_mm=wear.outer_pad_mm,
            shoe_mm=wear.shoe_mm,
            inner_pad_measured_on=wear.inner_measured_on,
            outer_pad_measured_on=wear.outer_measured_on,
            measured_on=latest.recorded_at if latest is not None else None,
            measured_odometer_km=latest.odometer_km if latest is not None else None,
            measured_hours=latest.engine_hours if latest is not None else None,
            surface_mm=surface.value_mm if surface is not None else None,
            surface_measured_on=surface.measured_on if surface is not None else None,
            surface_past_limit=surface.past_limit if surface is not None else False,
            projected_usage_remaining=wear.usage_remaining if projected else None,
            projected_wear_date=wear.wear_date if projected else None,
            last_job=BrakeJobResponse.model_validate(last_job) if last_job is not None else None,
            measurements=[
                BrakeMeasurementResponse.model_validate(m)
                for m in _newest_first(corner.measurements)
            ],
            jobs=[BrakeJobResponse.model_validate(j) for j in _newest_first(corner.jobs)],
        )

    async def _respond(self, vin: str, axes: VehicleAxes) -> BrakeOverviewResponse:
        setups, corners = await self._corners(vin, axes)
        return BrakeOverviewResponse(
            usage_axis=axes.primary.kind,
            tracks_distance=axes.tracks("distance"),
            tracks_hours=axes.tracks("hours"),
            axles=[
                BrakeAxleResponse(
                    axle=setup.axle,
                    brake_type=setup.brake_type,
                    min_thickness_mm=setup.min_thickness_mm,
                    new_thickness_mm=setup.new_thickness_mm,
                    rotor_min_mm=setup.rotor_min_mm,
                    drum_max_mm=setup.drum_max_mm,
                    configured=setup.configured,
                    due_soon_mm=setup.due_soon_mm,
                )
                for setup in setups.values()
            ],
            corners=[self._corner_response(c) for c in corners],
        )

    async def _finish(
        self, vin: str, axes: VehicleAxes, *, may_complete: bool = True
    ) -> BrakeOverviewResponse:
        """Sync both axle reminders from what this write left, commit once, and answer."""
        await self.db.flush()
        setups, corners = await self._corners(vin, axes)
        await self._sync_axle_reminders(vin, setups, corners, may_complete=may_complete)
        await self.db.commit()
        return await self._respond(vin, axes)

    async def _sync_axle_reminders(
        self,
        vin: str,
        setups: dict[Axle, AxleSetup],
        corners: Sequence[_Corner],
        *,
        may_complete: bool,
    ) -> None:
        """Raise, keep current, or complete each axle's "brake pads low" reminder.

        A corner is LOW (due soon or replace now), OK (measured above the
        band, or its pads replaced since), or unknown. Any LOW corner raises
        the axle's reminder; it completes only when none is LOW and at least
        one is OK. An axle with nothing known leaves it alone: not knowing is
        not a measurement of healthy pads.

        A delete never completes one (`may_complete=False`). Taking away the
        low figure is not news that the pads are fine, and deleting one to
        re-enter it would otherwise close the reminder and open a new one,
        losing its snooze and notifying again.
        """
        for axle in AXLES:
            source = REMINDER_SOURCE[axle]
            setup = setups[axle]
            on_axle = [c for c in corners if AXLE_OF[c.position] == axle]
            low = [c for c in on_axle if c.condition in _LOW]
            ok = [c for c in on_axle if c.condition is BrakeCondition.OK]

            owned = (
                (
                    await self.db.execute(
                        select(Reminder)
                        .where(
                            Reminder.vin == vin,
                            Reminder.source == source,
                            Reminder.status == "pending",
                        )
                        .order_by(Reminder.id)
                    )
                )
                .scalars()
                .all()
            )
            existing = owned[0] if owned else None
            for duplicate in owned[1:]:
                duplicate.status = "done"

            if low:
                due = min(reminder_due(c.wear, c.condition) or household_today() for c in low)
                title = _reminder_title(setup)
                if existing is None:
                    start_km, start_hours = await start_readings(self.db, vin)
                    self.db.add(
                        Reminder(
                            vin=vin,
                            source=source,
                            title=title,
                            # A date: the wear estimate is distance REMAINING,
                            # not an odometer to be due at.
                            reminder_type="date",
                            due_date=due,
                            status="pending",
                            start_odometer_km=start_km,
                            start_hours=start_hours,
                        )
                    )
                else:
                    existing.title = title
                    existing.due_date = due
            elif ok and existing is not None and may_complete:
                existing.status = "done"
            elif existing is not None:
                # Left pending: still name the axle's brakes as they're set up now.
                existing.title = _reminder_title(setup)

    async def overview(self, vin: str, current_user: User | None) -> BrakeOverviewResponse:
        """Both axles and the four corners, with their estimates and history."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)
        axes = await TireService(self.db).request_axes(current_user, vin)
        return await self._respond(vin, axes)

    async def update_axle(
        self, vin: str, axle: Axle, data: BrakeAxleUpdate, current_user: User | None
    ) -> BrakeOverviewResponse:
        """Save an axle's setup. Measurements of the other brake type stay in history."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        row = (
            await self.db.execute(
                select(BrakeAxle).where(BrakeAxle.vin == vin, BrakeAxle.axle == axle)
            )
        ).scalar_one_or_none()
        if row is None:
            row = BrakeAxle(vin=vin, axle=axle)
            self.db.add(row)
        for name, value in data.model_dump().items():
            setattr(row, name, value)
        return await self._finish(vin, axes)

    async def log_measurements(
        self, vin: str, data: BrakeMeasurementBatchCreate, current_user: User | None
    ) -> BrakeOverviewResponse:
        """Record one to four corners measured on one day."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        _refuse_untracked(axes, data.odometer_km, data.engine_hours)
        setups = await self._setups(vin)
        for corner in data.corners:
            figures = corner.model_dump(include=set(MEASURES))
            _refuse_other_type(corner.position, setups[AXLE_OF[corner.position]], figures)
            self.db.add(
                BrakeMeasurement(
                    vin=vin,
                    position=corner.position,
                    recorded_at=data.recorded_at,
                    odometer_km=data.odometer_km,
                    engine_hours=data.engine_hours,
                    notes=corner.notes,
                    **figures,
                )
            )
        return await self._finish(vin, axes)

    async def update_measurement(
        self,
        vin: str,
        measurement_id: int,
        data: BrakeMeasurementUpdate,
        current_user: User | None,
    ) -> BrakeOverviewResponse:
        """Correct one measurement, judged on the merged row."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        changes = data.model_dump(exclude_unset=True)
        _refuse_untracked(axes, changes.get("odometer_km"), changes.get("engine_hours"))
        row = await self._measurement(vin, measurement_id)
        if row.brake_job_id is not None:
            moved = sorted(
                {"recorded_at", "odometer_km", "engine_hours"} & changes.keys(),
            )
            if moved:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "This measurement was recorded with a brake job; change the job's "
                        f"date, odometer or hours instead ({', '.join(moved)})"
                    ),
                )
        setups = await self._setups(vin)
        _refuse_other_type(row.position, setups[AXLE_OF[row.position]], changes)
        if all(changes.get(name, getattr(row, name)) is None for name in MEASURES):
            raise HTTPException(status_code=422, detail="A measurement needs at least one figure")
        for name, value in changes.items():
            setattr(row, name, value)
        return await self._finish(vin, axes)

    async def delete_measurement(
        self, vin: str, measurement_id: int, current_user: User | None
    ) -> None:
        """Delete one measurement. A brake job it came with stays."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        row = await self._measurement(vin, measurement_id)
        await self.db.delete(row)
        await self._finish(vin, axes, may_complete=False)

    async def create_job(
        self, vin: str, data: BrakeJobCreate, current_user: User | None
    ) -> BrakeOverviewResponse:
        """Record a brake job on one to four corners, with the new pads' figures."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        _refuse_untracked(axes, data.odometer_km, data.engine_hours)
        setups = await self._setups(vin)
        for corner in data.corners:
            setup = setups[AXLE_OF[corner.position]]
            job = BrakeJob(
                vin=vin,
                position=corner.position,
                brake_type=setup.brake_type,
                performed_on=data.performed_on,
                odometer_km=data.odometer_km,
                engine_hours=data.engine_hours,
                friction_replaced=data.friction_replaced,
                surface=data.surface,
                notes=data.notes,
            )
            self.db.add(job)
            if corner.new_thickness_mm is None:
                continue
            await self.db.flush()
            fresh = corner.new_thickness_mm
            pads = (
                {"shoe_mm": fresh}
                if setup.brake_type == "drum"
                else {"inner_pad_mm": fresh, "outer_pad_mm": fresh}
            )
            self.db.add(
                BrakeMeasurement(
                    vin=vin,
                    position=corner.position,
                    recorded_at=data.performed_on,
                    odometer_km=data.odometer_km,
                    engine_hours=data.engine_hours,
                    brake_job_id=job.id,
                    **pads,
                )
            )
        return await self._finish(vin, axes)

    async def update_job(
        self, vin: str, job_id: int, data: BrakeJobUpdate, current_user: User | None
    ) -> BrakeOverviewResponse:
        """Correct one corner's brake job; the measurement it wrote follows it."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        changes = data.model_dump(exclude_unset=True)
        _refuse_untracked(axes, changes.get("odometer_km"), changes.get("engine_hours"))
        job = await self._job(vin, job_id)
        if not changes.get("friction_replaced", job.friction_replaced) and (
            changes.get("surface", job.surface) is None
        ):
            raise HTTPException(
                status_code=422,
                detail="A brake job replaces the pads or shoes, or does the rotor or drum",
            )
        for name, value in changes.items():
            setattr(job, name, value)
        if not job.friction_replaced:
            await self.db.execute(
                delete(BrakeMeasurement).where(
                    BrakeMeasurement.vin == vin, BrakeMeasurement.brake_job_id == job.id
                )
            )
        else:
            moved = {name: changes[name] for name in _JOB_CONTEXT if name in changes}
            if moved:
                linked = (
                    (
                        await self.db.execute(
                            select(BrakeMeasurement).where(
                                BrakeMeasurement.vin == vin,
                                BrakeMeasurement.brake_job_id == job.id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in linked:
                    if "performed_on" in moved:
                        row.recorded_at = moved["performed_on"]
                    if "odometer_km" in moved:
                        row.odometer_km = moved["odometer_km"]
                    if "engine_hours" in moved:
                        row.engine_hours = moved["engine_hours"]
        return await self._finish(vin, axes)

    async def delete_job(self, vin: str, job_id: int, current_user: User | None) -> None:
        """Delete one corner's brake job and the measurement it wrote."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        axes = await self._lock(vin, current_user)
        job = await self._job(vin, job_id)
        await self.db.execute(
            delete(BrakeMeasurement).where(
                BrakeMeasurement.vin == vin, BrakeMeasurement.brake_job_id == job.id
            )
        )
        await self.db.delete(job)
        await self._finish(vin, axes, may_complete=False)

    async def _setups(self, vin: str) -> dict[Axle, AxleSetup]:
        rows = (
            (await self.db.execute(select(BrakeAxle).where(BrakeAxle.vin == vin))).scalars().all()
        )
        by_axle = {row.axle: row for row in rows}
        return {axle: axle_setup(axle, by_axle.get(axle)) for axle in AXLES}

    async def _measurement(self, vin: str, measurement_id: int) -> BrakeMeasurement:
        row = (
            await self.db.execute(
                select(BrakeMeasurement).where(
                    BrakeMeasurement.id == measurement_id, BrakeMeasurement.vin == vin
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Brake measurement not found")
        return row

    async def _job(self, vin: str, job_id: int) -> BrakeJob:
        row = (
            await self.db.execute(
                select(BrakeJob).where(BrakeJob.id == job_id, BrakeJob.vin == vin)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Brake job not found")
        return row
