"""Pydantic schemas for brake tracking (#202).

Requests are canonical: millimetres, kilometres, hours. Every write model
forbids extras, like the tire schemas, so a misspelt field is a 422 and not a
silent drop. Responses carry no bounds (see test_response_contract.py).
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas._nullability import reject_null
from app.schemas.tire import HoursFigure, UsageAxisName
from app.utils.household_time import household_today

BrakePosition = Literal["FL", "FR", "RL", "RR"]
Axle = Literal["front", "rear"]
BrakeType = Literal["disc", "drum"]
Surface = Literal["replaced", "resurfaced"]
BrakeConditionName = Literal["ok", "due_soon", "replace_now", "unknown"]
BrakeWearStatusName = Literal[
    "projected",
    "at_or_below_minimum",
    "no_measurements",
    "replaced_not_measured",
    "insufficient_measurements",
    "no_usage_figures",
    "no_usage_between",
    "not_decreasing",
]


def _to_stored_hundredth(value: Decimal) -> Decimal:
    """Round to the hundredth the NUMERIC columns keep, so what's checked is what's saved."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


#: A pad or shoe lining, in mm. NUMERIC(4, 2).
Thickness = Annotated[Decimal, Field(ge=0, le=50), AfterValidator(_to_stored_hundredth)]
#: A rotor's thickness, in mm. NUMERIC(5, 2).
RotorFigure = Annotated[Decimal, Field(ge=0, le=100), AfterValidator(_to_stored_hundredth)]
#: A drum's inside diameter, in mm. NUMERIC(6, 2).
DrumFigure = Annotated[Decimal, Field(ge=0, le=1000), AfterValidator(_to_stored_hundredth)]
#: An odometer, in km. NUMERIC(10, 2).
OdometerFigure = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"))]


def _not_in_the_future(value: date_type | None) -> date_type | None:
    """Refuse a date past tomorrow, with a day's slack for a browser ahead of the household.

    A mistyped year would otherwise outrank every real record for years: a
    brake job dated 2062 starts the pads over, and the reminder for pads that
    are still worn out completes.
    """
    if value is not None and value > household_today() + timedelta(days=1):
        raise ValueError("cannot be in the future")
    return value


#: The measures each brake type takes. A write carrying one of the other
#: type's is refused, naming the corner.
DISC_MEASURES = ("inner_pad_mm", "outer_pad_mm", "rotor_mm")
DRUM_MEASURES = ("shoe_mm", "drum_mm")
MEASURES = DISC_MEASURES + DRUM_MEASURES


class BrakeAxleUpdate(BaseModel):
    """An axle's whole setup. PUT replaces it."""

    model_config = ConfigDict(extra="forbid")

    brake_type: BrakeType
    min_thickness_mm: Thickness
    new_thickness_mm: Thickness
    rotor_min_mm: RotorFigure | None = None
    drum_max_mm: DrumFigure | None = None

    @model_validator(mode="after")
    def _limits_fit_the_type(self) -> BrakeAxleUpdate:
        """New must be thicker than the minimum, and each limit belongs to one type."""
        if self.new_thickness_mm <= self.min_thickness_mm:
            raise ValueError("New thickness must be more than the minimum")
        if self.brake_type == "disc" and self.drum_max_mm is not None:
            raise ValueError("A disc axle has no drum maximum")
        if self.brake_type == "drum" and self.rotor_min_mm is not None:
            raise ValueError("A drum axle has no rotor minimum")
        return self


class BrakeMeasurementCorner(BaseModel):
    """One corner's figures in a measurement batch."""

    model_config = ConfigDict(extra="forbid")

    position: BrakePosition
    inner_pad_mm: Thickness | None = None
    outer_pad_mm: Thickness | None = None
    rotor_mm: RotorFigure | None = None
    shoe_mm: Thickness | None = None
    drum_mm: DrumFigure | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _measures_something(self) -> BrakeMeasurementCorner:
        """A corner in the batch must carry at least one figure. Leave a corner out to skip it."""
        if all(getattr(self, name) is None for name in MEASURES):
            raise ValueError(f"{self.position} has nothing measured; leave it out to skip it")
        return self


class BrakeMeasurementBatchCreate(BaseModel):
    """Measurements for one to four corners, taken on one day at one odometer."""

    model_config = ConfigDict(extra="forbid")

    recorded_at: date_type
    odometer_km: OdometerFigure | None = None
    engine_hours: HoursFigure | None = None
    corners: list[BrakeMeasurementCorner] = Field(min_length=1, max_length=4)

    _past = field_validator("recorded_at")(_not_in_the_future)

    @model_validator(mode="after")
    def _one_entry_per_corner(self) -> BrakeMeasurementBatchCreate:
        positions = [c.position for c in self.corners]
        if len(set(positions)) != len(positions):
            raise ValueError("Each corner can appear once")
        return self


class BrakeMeasurementUpdate(BaseModel):
    """Correct one measurement. Omitted keeps, null clears.

    The result must still measure something, and a changed figure must fit the
    corner's brake type; `BrakeService.update_measurement` judges both on the
    merged row. A measurement a brake job wrote takes figure and note edits
    only: its date, odometer and hours are the job's.
    """

    model_config = ConfigDict(extra="forbid")

    recorded_at: date_type | None = None
    odometer_km: OdometerFigure | None = None
    engine_hours: HoursFigure | None = None
    inner_pad_mm: Thickness | None = None
    outer_pad_mm: Thickness | None = None
    rotor_mm: RotorFigure | None = None
    shoe_mm: Thickness | None = None
    drum_mm: DrumFigure | None = None
    notes: str | None = None

    _no_null = reject_null("recorded_at")
    _past = field_validator("recorded_at")(_not_in_the_future)


class BrakeJobCorner(BaseModel):
    """One corner of a brake job, with the new pads' thickness if it was measured."""

    model_config = ConfigDict(extra="forbid")

    position: BrakePosition
    #: Writes a measurement of the new pads (or shoes), linked to the job.
    new_thickness_mm: Thickness | None = None


class BrakeJobCreate(BaseModel):
    """Work done on one to four corners on one day."""

    model_config = ConfigDict(extra="forbid")

    performed_on: date_type
    odometer_km: OdometerFigure | None = None
    engine_hours: HoursFigure | None = None
    #: Pads on a disc corner, shoes on a drum one.
    friction_replaced: bool = False
    #: The rotor or the drum: replaced, resurfaced, or left alone (null).
    surface: Surface | None = None
    notes: str | None = None
    corners: list[BrakeJobCorner] = Field(min_length=1, max_length=4)

    _past = field_validator("performed_on")(_not_in_the_future)

    @model_validator(mode="after")
    def _does_something(self) -> BrakeJobCreate:
        if not self.friction_replaced and self.surface is None:
            raise ValueError("A brake job replaces the pads or shoes, or does the rotor or drum")
        positions = [c.position for c in self.corners]
        if len(set(positions)) != len(positions):
            raise ValueError("Each corner can appear once")
        if not self.friction_replaced and any(c.new_thickness_mm is not None for c in self.corners):
            raise ValueError("A new thickness needs the pads or shoes replaced")
        return self


class BrakeJobUpdate(BaseModel):
    """Correct one corner's brake job. Omitted keeps, null clears.

    Its date, odometer and hours carry over to the measurement it wrote, and
    turning `friction_replaced` off deletes that measurement.
    """

    model_config = ConfigDict(extra="forbid")

    performed_on: date_type | None = None
    odometer_km: OdometerFigure | None = None
    engine_hours: HoursFigure | None = None
    friction_replaced: bool | None = None
    surface: Surface | None = None
    notes: str | None = None

    _no_null = reject_null("performed_on", "friction_replaced")
    _past = field_validator("performed_on")(_not_in_the_future)


class BrakeAxleResponse(BaseModel):
    """An axle's setup, saved or the defaults."""

    axle: Axle
    brake_type: BrakeType
    min_thickness_mm: Decimal
    new_thickness_mm: Decimal
    rotor_min_mm: Decimal | None = None
    drum_max_mm: Decimal | None = None
    #: False when nobody has saved Axle setup yet and these are the defaults.
    configured: bool
    #: The thickness at or below which a corner on this axle is due soon.
    due_soon_mm: Decimal


class BrakeMeasurementResponse(BaseModel):
    """One corner's measurement."""

    id: int
    position: BrakePosition
    recorded_at: date_type
    odometer_km: Decimal | None = None
    engine_hours: Decimal | None = None
    inner_pad_mm: Decimal | None = None
    outer_pad_mm: Decimal | None = None
    rotor_mm: Decimal | None = None
    shoe_mm: Decimal | None = None
    drum_mm: Decimal | None = None
    #: The brake job that wrote this one, for the new pads' figure.
    brake_job_id: int | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class BrakeJobResponse(BaseModel):
    """One corner's brake job."""

    id: int
    position: BrakePosition
    brake_type: BrakeType
    performed_on: date_type
    odometer_km: Decimal | None = None
    engine_hours: Decimal | None = None
    friction_replaced: bool
    surface: Surface | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}


class BrakeCornerResponse(BaseModel):
    """One corner: its condition, wear estimate, newest figures and history."""

    position: BrakePosition
    axle: Axle
    brake_type: BrakeType
    condition: BrakeConditionName
    wear_status: BrakeWearStatusName
    #: The thinner pad (or the shoe) at the newest measurement since the pads went on.
    thinnest_mm: Decimal | None = None
    inner_pad_mm: Decimal | None = None
    outer_pad_mm: Decimal | None = None
    shoe_mm: Decimal | None = None
    #: When each pad was last measured. A one-pad check keeps the other pad's
    #: figure, so either can be older than `measured_on`.
    inner_pad_measured_on: date_type | None = None
    outer_pad_measured_on: date_type | None = None
    measured_on: date_type | None = None
    measured_odometer_km: Decimal | None = None
    measured_hours: Decimal | None = None
    #: The newest rotor thickness or drum diameter since the rotor or drum changed.
    surface_mm: Decimal | None = None
    surface_measured_on: date_type | None = None
    surface_past_limit: bool = False
    #: Distance in km, or hours when `usage_axis` is hours.
    projected_usage_remaining: Decimal | None = None
    projected_wear_date: date_type | None = None
    last_job: BrakeJobResponse | None = None
    #: Newest first.
    measurements: list[BrakeMeasurementResponse] = Field(default_factory=list)
    jobs: list[BrakeJobResponse] = Field(default_factory=list)


class BrakeOverviewResponse(BaseModel):
    """A vehicle's brakes: both axles and the four corners, FL, FR, RL, RR."""

    usage_axis: UsageAxisName = "distance"
    tracks_distance: bool = True
    tracks_hours: bool = False
    axles: list[BrakeAxleResponse]
    corners: list[BrakeCornerResponse]
