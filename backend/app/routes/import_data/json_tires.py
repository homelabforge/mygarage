"""The tire family of a JSON backup: sets, tires, mount periods and readings (J1).

Read whole before anything is written, so a bad row refuses the family and
leaves the vehicle as it was (N-4). Links travel as places in the file: a
tire's `set_index`, a reading's `mount_period_index`.
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast, get_args

from sqlalchemy import null, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tire import Tire, TireMountPeriod, TireReading, TireSet
from app.routes.import_data._common import (
    _blank_to_none,
    _in_vocabulary,
    _is_blank,
    _json_bool,
    _json_decimal,
    _json_optional_date,
    _json_row_date,
    _json_text,
    _RowError,
    _within_api_bounds,
)
from app.routes.import_data._families import file_index, nested_list, within_figure_bounds
from app.schemas.tire import (
    HoursFigure,
    MountPeriodUpdate,
    TirePosition,
    TireReadingCreate,
    TireUpdate,
)
from app.services.tire_service import sync_low_tread_reminder

logger = logging.getLogger(__name__)

_POSITIONS: tuple[str, ...] = get_args(TirePosition)


@dataclass(frozen=True)
class ParsedTire:
    """One tire as unsaved rows, each reading with its period's index in `periods`."""

    tire: Tire
    set_index: int | None
    periods: list[TireMountPeriod]
    readings: list[tuple[TireReading, int | None]]


@dataclass(frozen=True)
class TirePlan:
    """Everything the file's tire family writes, checked and ready."""

    sets: list[TireSet]
    tires: list[ParsedTire]


def _as_object(row: Any) -> Mapping[str, Any]:
    """The row as a mapping, or a row error when it isn't an object."""
    if not isinstance(row, Mapping):
        raise _RowError("must be an object")
    return cast(Mapping[str, Any], row)


def _optional_position(row: Mapping[str, Any]) -> str | None:
    """A tire's or a reading's corner: blank is none, anything else one the API takes."""
    return _in_vocabulary(_blank_to_none(row.get("position")), "position", _POSITIONS)


def _set_from_json(vin: str, index: int, raw: Any) -> TireSet:
    """One tire set as an unsaved row."""
    try:
        row = _as_object(raw)
        name = _json_text(row, "name")
        if name is None:
            raise _RowError("name is missing")
        return TireSet(vin=vin, name=name, notes=_json_text(row, "notes"))
    except _RowError as e:
        raise _RowError(f"Tire set {index}: {e.reason}") from e


def _period_from_json(tire_index: int, index: int, raw: Any) -> TireMountPeriod:
    """One mount period as an unsaved row; the caller sets its tire once that has an id.

    No closed-period or future-date rule (N-7): a backup restores what it holds.
    """
    try:
        row = _as_object(raw)
        if _is_blank(row.get("position")):
            raise _RowError("position is missing")
        position = _in_vocabulary(row.get("position"), "position", _POSITIONS)
        mounted_odometer_km = _json_decimal(row, "mounted_odometer_km")
        dismounted_odometer_km = _json_decimal(row, "dismounted_odometer_km")
        _within_api_bounds(
            MountPeriodUpdate,
            mounted_odometer_km=mounted_odometer_km,
            dismounted_odometer_km=dismounted_odometer_km,
        )
        mounted_hours = _json_decimal(row, "mounted_hours")
        dismounted_hours = _json_decimal(row, "dismounted_hours")
        within_figure_bounds(
            HoursFigure, mounted_hours=mounted_hours, dismounted_hours=dismounted_hours
        )
        return TireMountPeriod(
            position=position,
            mounted_on=_json_optional_date(row, "mounted_on"),
            dismounted_on=_json_optional_date(row, "dismounted_on"),
            mounted_odometer_km=mounted_odometer_km,
            dismounted_odometer_km=dismounted_odometer_km,
            mounted_hours=mounted_hours,
            dismounted_hours=dismounted_hours,
            is_assumed=_json_bool(row, "is_assumed", default=False),
            observed_active_on=_json_optional_date(row, "observed_active_on"),
            notes=_json_text(row, "notes"),
        )
    except _RowError as e:
        raise _RowError(f"Tire {tire_index}, mount period {index}: {e.reason}") from e


def _reading_from_json(
    vin: str, tire_index: int, index: int, raw: Any, period_count: int
) -> tuple[TireReading, int | None]:
    """One reading as an unsaved row, with the index of the period it falls in."""
    try:
        row = _as_object(raw)
        recorded_at = _json_row_date(row, "recorded_at")
        # A snapshot of where the tire was, so it keeps its own corner.
        position = _optional_position(row)
        odometer_km = _json_decimal(row, "odometer_km")
        tread_depth_mm = _json_decimal(row, "tread_depth_mm")
        pressure_kpa = _json_decimal(row, "pressure_kpa")
        _within_api_bounds(
            TireReadingCreate,
            odometer_km=odometer_km,
            tread_depth_mm=tread_depth_mm,
            pressure_kpa=pressure_kpa,
        )
        engine_hours = _json_decimal(row, "engine_hours")
        within_figure_bounds(HoursFigure, engine_hours=engine_hours)
        if tread_depth_mm is None and pressure_kpa is None:
            raise _RowError("a reading needs a tread depth, a pressure, or both")
        period_index = file_index(
            row, "mount_period_index", period_count, what="a mount period of this tire"
        )
        reading = TireReading(
            vin=vin,
            position=position,
            recorded_at=recorded_at,
            odometer_km=odometer_km,
            engine_hours=engine_hours,
            tread_depth_mm=tread_depth_mm,
            pressure_kpa=pressure_kpa,
            notes=_json_text(row, "notes"),
        )
        return reading, period_index
    except _RowError as e:
        raise _RowError(f"Tire {tire_index}, reading {index}: {e.reason}") from e


def _check_mount_state(tire: Tire, periods: list[TireMountPeriod]) -> None:
    """Refuse a tire whose position and open period disagree (N-4). First failure wins."""
    open_periods = [p for p in periods if p.dismounted_on is None]
    position = tire.position
    if tire.retired_on is not None and (position is not None or open_periods):
        raise _RowError("is retired but still mounted")
    if len(open_periods) > 1:
        raise _RowError("has more than one open mount period")
    if position is None and open_periods:
        raise _RowError("is off the vehicle but has an open mount period")
    if position is not None and not open_periods:
        raise _RowError(f"is mounted at {position} but has no open mount period")
    if position is not None and open_periods[0].position != position:
        raise _RowError(
            f"is mounted at {position} but its open mount period is at {open_periods[0].position}"
        )


def _tire_from_json(vin: str, index: int, raw: Any, set_count: int) -> ParsedTire:
    """One tire with its periods and readings, checked and unsaved."""
    try:
        row = _as_object(raw)
        position = _optional_position(row)
        tread_depth_mm = _json_decimal(row, "tread_depth_mm")
        pressure_kpa = _json_decimal(row, "pressure_kpa")
        min_tread_mm = _json_decimal(row, "min_tread_mm")
        _within_api_bounds(
            TireUpdate,
            tread_depth_mm=tread_depth_mm,
            pressure_kpa=pressure_kpa,
            min_tread_mm=min_tread_mm,
        )
        set_index = file_index(row, "set_index", set_count, what="a tire set in this file")
        raw_periods = nested_list(row, "mount_periods")
        raw_readings = nested_list(row, "readings")
        columns: dict[str, Any] = {
            "vin": vin,
            "position": position,
            "brand": _json_text(row, "brand"),
            "model_name": _json_text(row, "model_name"),
            "size": _json_text(row, "size"),
            "dot_code": _json_text(row, "dot_code"),
            "retired_on": _json_optional_date(row, "retired_on"),
            "tread_depth_mm": tread_depth_mm,
            "pressure_kpa": pressure_kpa,
            "notes": _json_text(row, "notes"),
            "storage_location": _json_text(row, "storage_location"),
        }
        # Absent takes the column's 2.0. A null is no threshold, and a plain None
        # would get that 2.0 on insert too, so it's written as SQL NULL (R1-F1).
        if "min_tread_mm" in row:
            columns["min_tread_mm"] = null() if min_tread_mm is None else min_tread_mm
        tire = Tire(**columns)
    except _RowError as e:
        raise _RowError(f"Tire {index}: {e.reason}") from e

    periods = [_period_from_json(index, k, p) for k, p in enumerate(raw_periods)]
    readings = [
        _reading_from_json(vin, index, m, r, len(periods)) for m, r in enumerate(raw_readings)
    ]
    try:
        _check_mount_state(tire, periods)
    except _RowError as e:
        raise _RowError(f"Tire {index}: {e.reason}") from e
    return ParsedTire(tire=tire, set_index=set_index, periods=periods, readings=readings)


def parse_tires(vin: str, sections: Mapping[str, list[Any]]) -> TirePlan:
    """The file's tire family, every row checked, nothing touching the session.

    No untracked-axis or future-date check (N-7): a backup restores whole.
    """
    sets = [_set_from_json(vin, i, row) for i, row in enumerate(sections["tire_sets"])]
    tires = [_tire_from_json(vin, i, row, len(sets)) for i, row in enumerate(sections["tires"])]
    # One tire per corner, as `uq_tires_vin_position` will insist anyway.
    taken: dict[str, int] = {}
    for i, parsed in enumerate(tires):
        position = parsed.tire.position
        if position is None:
            continue
        if position in taken:
            raise _RowError(f"Tire {i}: {position} is taken by tire {taken[position]}")
        taken[position] = i
    return TirePlan(sets=sets, tires=tires)


async def write_tires(db: AsyncSession, plan: TirePlan) -> None:
    """Write the plan, parents first so each child gets its parent's id."""
    db.add_all(plan.sets)
    await db.flush()
    for parsed in plan.tires:
        if parsed.set_index is not None:
            parsed.tire.set_id = plan.sets[parsed.set_index].id
        db.add(parsed.tire)
        await db.flush()
        for period in parsed.periods:
            period.tire_id = parsed.tire.id
        db.add_all(parsed.periods)
        await db.flush()
        for reading, period_index in parsed.readings:
            reading.tire_id = parsed.tire.id
            # A reading with no period stays without one (N-6).
            reading.mount_period_id = (
                parsed.periods[period_index].id if period_index is not None else None
            )
        db.add_all([reading for reading, _ in parsed.readings])
        await db.flush()


async def sync_imported_tires(db: AsyncSession, plan: TirePlan) -> None:
    """Raise or close the low-tread reminder for each tire this import wrote.

    Reloaded first: the sync reads the readings, and the rows written above
    never had them loaded. Nothing else raises one (N-2), and a stored or
    retired tire gets none (D3a).
    """
    ids = [parsed.tire.id for parsed in plan.tires]
    if not ids:
        return
    tires = (
        (
            await db.execute(
                select(Tire)
                .where(Tire.id.in_(ids))
                .options(selectinload(Tire.readings))
                .order_by(Tire.id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    for tire in tires:
        await sync_low_tread_reminder(db, tire)
