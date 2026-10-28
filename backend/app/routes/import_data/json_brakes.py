"""The brake family of a JSON backup: axle setups, jobs and measurements (J1).

Read whole before anything is written, so a bad row refuses the family and
leaves the vehicle as it was. A measurement names the job that wrote it by
the job's place in the file's `brake_jobs`. The reminder marks never travel:
they key on measurement ids (N-5).
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_args

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement
from app.routes.import_data._common import (
    _blank_to_none,
    _in_vocabulary,
    _json_bool,
    _json_decimal,
    _json_row_date,
    _json_text,
    _RowError,
)
from app.routes.import_data._families import (
    as_object,
    file_index,
    required_word,
    within_figure_bounds,
)
from app.schemas.brake import (
    MEASURES,
    Axle,
    BrakeAxleUpdate,
    BrakePosition,
    BrakeType,
    DrumFigure,
    OdometerFigure,
    RotorFigure,
    Surface,
    Thickness,
)
from app.schemas.tire import HoursFigure

logger = logging.getLogger(__name__)

_AXLES: tuple[str, ...] = get_args(Axle)
_TYPES: tuple[str, ...] = get_args(BrakeType)
_POSITIONS: tuple[str, ...] = get_args(BrakePosition)
_SURFACES: tuple[str, ...] = get_args(Surface)


@dataclass(frozen=True)
class BrakePlan:
    """Everything the file's brake family writes, checked and ready.

    Each measurement comes with the index of its job in `jobs`, or None.
    """

    axles: list[BrakeAxle]
    jobs: list[BrakeJob]
    measurements: list[tuple[BrakeMeasurement, int | None]]


def _axle_from_json(vin: str, index: int, raw: Any) -> BrakeAxle:
    """One axle setup as an unsaved row, held to the API's whole-setup rule."""
    try:
        row = as_object(raw)
        axle = required_word(row, "axle", _AXLES)
        brake_type = required_word(row, "brake_type", _TYPES)
        min_thickness_mm = _json_decimal(row, "min_thickness_mm")
        new_thickness_mm = _json_decimal(row, "new_thickness_mm")
        rotor_min_mm = _json_decimal(row, "rotor_min_mm")
        drum_max_mm = _json_decimal(row, "drum_max_mm")
        within_figure_bounds(
            Thickness, min_thickness_mm=min_thickness_mm, new_thickness_mm=new_thickness_mm
        )
        within_figure_bounds(RotorFigure, rotor_min_mm=rotor_min_mm)
        within_figure_bounds(DrumFigure, drum_max_mm=drum_max_mm)
        # Both are NOT NULL, and the setup rule would only say "Field required".
        if min_thickness_mm is None:
            raise _RowError("min_thickness_mm is missing")
        if new_thickness_mm is None:
            raise _RowError("new_thickness_mm is missing")
        figures = {
            "brake_type": brake_type,
            "min_thickness_mm": min_thickness_mm,
            "new_thickness_mm": new_thickness_mm,
            "rotor_min_mm": rotor_min_mm,
            "drum_max_mm": drum_max_mm,
        }
        # Every stored setup passed this on its way in (S4), so a file's must too.
        try:
            BrakeAxleUpdate.model_validate(figures)
        except ValidationError as e:
            reason = str(e.errors()[0]["msg"]).removeprefix("Value error, ")
            raise _RowError(reason) from e
        return BrakeAxle(vin=vin, axle=axle, **figures)
    except _RowError as e:
        raise _RowError(f"Brake axle {index}: {e.reason}") from e


def _job_from_json(vin: str, index: int, raw: Any) -> BrakeJob:
    """One corner's brake job as an unsaved row.

    Not the create path's "does something" rule (S4): a job that did neither
    is odd, but it's history the app kept.
    """
    try:
        row = as_object(raw)
        position = required_word(row, "position", _POSITIONS)
        brake_type = required_word(row, "brake_type", _TYPES)
        performed_on = _json_row_date(row, "performed_on")
        odometer_km = _json_decimal(row, "odometer_km")
        engine_hours = _json_decimal(row, "engine_hours")
        within_figure_bounds(OdometerFigure, odometer_km=odometer_km)
        within_figure_bounds(HoursFigure, engine_hours=engine_hours)
        return BrakeJob(
            vin=vin,
            position=position,
            brake_type=brake_type,
            performed_on=performed_on,
            odometer_km=odometer_km,
            engine_hours=engine_hours,
            friction_replaced=_json_bool(row, "friction_replaced", default=False),
            surface=_in_vocabulary(_blank_to_none(row.get("surface")), "surface", _SURFACES),
            notes=_json_text(row, "notes"),
        )
    except _RowError as e:
        raise _RowError(f"Brake job {index}: {e.reason}") from e


def _measurement_from_json(
    vin: str, index: int, raw: Any, job_count: int
) -> tuple[BrakeMeasurement, int | None]:
    """One corner's measurement as an unsaved row, with its job's index in the file."""
    try:
        row = as_object(raw)
        position = required_word(row, "position", _POSITIONS)
        recorded_at = _json_row_date(row, "recorded_at")
        odometer_km = _json_decimal(row, "odometer_km")
        engine_hours = _json_decimal(row, "engine_hours")
        within_figure_bounds(OdometerFigure, odometer_km=odometer_km)
        within_figure_bounds(HoursFigure, engine_hours=engine_hours)
        figures = {name: _json_decimal(row, name) for name in MEASURES}
        within_figure_bounds(
            Thickness,
            inner_pad_mm=figures["inner_pad_mm"],
            outer_pad_mm=figures["outer_pad_mm"],
            shoe_mm=figures["shoe_mm"],
        )
        within_figure_bounds(RotorFigure, rotor_mm=figures["rotor_mm"])
        within_figure_bounds(DrumFigure, drum_mm=figures["drum_mm"])
        if all(value is None for value in figures.values()):
            raise _RowError("has nothing measured")
        job_index = file_index(row, "brake_job_index", job_count, what="a brake job in this file")
        measurement = BrakeMeasurement(
            vin=vin,
            position=position,
            recorded_at=recorded_at,
            odometer_km=odometer_km,
            engine_hours=engine_hours,
            notes=_json_text(row, "notes"),
            **figures,
        )
        return measurement, job_index
    except _RowError as e:
        raise _RowError(f"Brake measurement {index}: {e.reason}") from e


def parse_brakes(vin: str, sections: Mapping[str, list[Any]]) -> BrakePlan:
    """The file's brake family, every row checked, nothing touching the session.

    No future-date, untracked-axis or other-type check (N-7): a check taken
    before the axle changed type is history the app keeps, so a backup
    restores it whole.
    """
    axles: list[BrakeAxle] = []
    # One setup per axle, as `uq_brake_axles_vin_axle` will insist anyway.
    set_up: dict[str, int] = {}
    for i, row in enumerate(sections["brake_axles"]):
        axle = _axle_from_json(vin, i, row)
        if axle.axle in set_up:
            raise _RowError(
                f"Brake axle {i}: {axle.axle} is already set up by brake axle {set_up[axle.axle]}"
            )
        set_up[axle.axle] = i
        axles.append(axle)
    jobs = [_job_from_json(vin, i, row) for i, row in enumerate(sections["brake_jobs"])]
    measurements = [
        _measurement_from_json(vin, i, row, len(jobs))
        for i, row in enumerate(sections["brake_measurements"])
    ]
    return BrakePlan(axles=axles, jobs=jobs, measurements=measurements)


async def write_brakes(db: AsyncSession, plan: BrakePlan) -> None:
    """Write the plan, the jobs first so each measurement gets its job's id."""
    db.add_all(plan.axles)
    db.add_all(plan.jobs)
    await db.flush()
    for measurement, job_index in plan.measurements:
        measurement.brake_job_id = plan.jobs[job_index].id if job_index is not None else None
    db.add_all([measurement for measurement, _ in plan.measurements])
    await db.flush()
