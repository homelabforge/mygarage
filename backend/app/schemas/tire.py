"""Pydantic schemas for tire position / tread tracking."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.schemas._nullability import reject_null
from app.utils.household_time import household_today
from app.utils.lenient_vocab import LenientVocab, lenient_reader

TirePosition = Literal["FL", "FR", "RL", "RR", "SPARE"]
# For TireResponse: `tires.position` has no CHECK, so a corner we don't know
# reads as null (like a stored tire) instead of 500ing the tire list.
LenientTirePosition = Annotated[
    TirePosition | None, BeforeValidator(lenient_reader(TirePosition)), LenientVocab(None)
]

#: The `hours_records.engine_hours` bounds, so a tire takes any figure the hours log does.
_HOURS_MAX = Decimal("999999999.9")


def _to_stored_tenth(value: Decimal) -> Decimal:
    """Round to the tenth NUMERIC(10, 1) keeps, so what's checked is what's saved (#217)."""
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


#: An hour meter figure on a tire write. Rounded as it's parsed: unrounded,
#: 100.15 then 100.10 passed the history check and stored as 100.2 then 100.1.
HoursFigure = Annotated[Decimal, Field(ge=0, le=_HOURS_MAX), AfterValidator(_to_stored_tenth)]


class TireBase(BaseModel):
    """Shared tire fields.

    **`position` is not here, and neither is `installed_date`.**

    `position` left because a tire is no longer identified by a corner (D2c):
    it is a thing you own, which is sometimes mounted somewhere. Mounting is a
    separate operation with its own conflict semantics, so `POST /api/tires`
    no longer upserts by position.

    `installed_date` left because it is now DERIVED from the earliest mount
    period (D12). Keeping it writable would need synchronisation on every
    period create, edit and delete, and would give the same fact two sources.

    `extra="forbid"` is deliberate and is what makes the break loud (D13). A
    stale v3.2 browser tab POSTing a payload with `position` gets a 422 naming
    the field. Pydantic's default is to IGNORE unknown fields, which here would
    mean silently creating a second, unmounted tire instead of updating the one
    at that corner -- a duplicate the user did not ask for and cannot see the
    cause of.
    """

    model_config = ConfigDict(extra="forbid")

    brand: str | None = Field(None, max_length=80)
    model_name: str | None = Field(None, max_length=80)
    size: str | None = Field(None, max_length=40)
    dot_code: str | None = Field(None, max_length=20)
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    min_tread_mm: Decimal | None = Field(
        Decimal("2.0"),
        ge=0,
        le=10,
        description="Wear-out threshold in mm; drives reminder hooks",
    )
    notes: str | None = None
    storage_location: str | None = Field(
        None, max_length=120
    )  #: Where the tire is kept while it is off the vehicle. Free text (migration 100).


class TireCreate(TireBase):
    """Create / upsert a tire at a position."""

    vin: str = Field(..., max_length=17)


class TireUpdate(BaseModel):
    """Partial tire update.

    Neither `position` nor `installed_date` is writable here: position changes
    through mount/dismount (D14), and `installed_date` is derived (D12).
    """

    model_config = ConfigDict(extra="forbid")

    brand: str | None = Field(None, max_length=80)
    model_name: str | None = Field(None, max_length=80)
    size: str | None = Field(None, max_length=40)
    dot_code: str | None = Field(None, max_length=20)
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    min_tread_mm: Decimal | None = Field(None, ge=0, le=10)
    notes: str | None = None
    #: The set this tire belongs to, or null for ungrouped. Writable HERE and
    #: nowhere else: `TireCreate` deliberately does not take one, because a set
    #: is a label applied to a tire you already own rather than part of its
    #: identity. `update_tire` uses `exclude_unset`, so omitting the key leaves
    #: membership alone and sending null clears it -- two different intents that
    #: a plain optional field would collapse into one.
    set_id: int | None = None
    storage_location: str | None = Field(
        None, max_length=120
    )  #: Where the tire is kept while it is off the vehicle. Free text (migration 100).


class TireMountRequest(BaseModel):
    """Mount a tire at a position."""

    model_config = ConfigDict(extra="forbid")

    position: TirePosition
    mounted_on: date_type | None = None
    mounted_odometer_km: Decimal | None = Field(None, ge=0)
    mounted_hours: HoursFigure | None = None
    notes: str | None = None


class TireDismountRequest(BaseModel):
    """Take a tire off the vehicle."""

    model_config = ConfigDict(extra="forbid")

    dismounted_on: date_type | None = None
    dismounted_odometer_km: Decimal | None = Field(None, ge=0)
    dismounted_hours: HoursFigure | None = None
    notes: str | None = None
    storage_location: str | None = Field(
        None, max_length=120
    )  #: Where the tire is kept while it is off the vehicle. Free text (migration 100).


class TireCreateAndMountRequest(TireCreate):
    """Create a tire and mount it in one atomic operation.

    Offered because create-then-mount is two calls for the common case, and
    the conflict semantics are the MOUNT's: if that corner is occupied the
    whole operation fails and no tire is created. A caller that did the two
    steps itself and got a conflict on the second would be left with an
    orphan tire it did not ask for.
    """

    position: TirePosition
    mounted_on: date_type | None = None
    mounted_odometer_km: Decimal | None = Field(None, ge=0)
    mounted_hours: HoursFigure | None = None


class TireRotationMove(BaseModel):
    """One tire's destination in a rotation."""

    model_config = ConfigDict(extra="forbid")

    tire_id: int
    position: TirePosition


class TireRotationRequest(BaseModel):
    """Move several tires at once.

    All or nothing. A partial rotation would leave the vehicle in an
    arrangement the user did not ask for and cannot easily read back, which
    for something done four tires at a time is worse than a refusal.
    """

    model_config = ConfigDict(extra="forbid")

    moves: list[TireRotationMove] = Field(..., min_length=1)
    odometer_km: Decimal | None = Field(None, ge=0)
    engine_hours: HoursFigure | None = None
    rotated_on: date_type | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _no_duplicate_targets(self) -> TireRotationRequest:
        """Two tires cannot be sent to one corner.

        Caught here rather than by the unique index, because the index fires
        mid-write and the resulting IntegrityError cannot say which pair of
        moves conflicted.
        """
        positions = [m.position for m in self.moves]
        if len(set(positions)) != len(positions):
            raise ValueError("Two tires cannot be rotated to the same position")
        tire_ids = [m.tire_id for m in self.moves]
        if len(set(tire_ids)) != len(tire_ids):
            raise ValueError("A tire cannot be rotated to two positions")
        return self


class TireReadingCreate(BaseModel):
    """Record a tread/pressure reading (updates the parent tire's latest depth).

    Tread is OPTIONAL (#152): the reporter tracks a slow pressure leak and owns
    no tread gauge, and a required tread beside an optional odometer meant they
    could not record a pressure at all. What is required is that a reading carry
    at least one measurement (see ``_at_least_one_measurement``).

    Forbids extras like every other tire write schema, so a misspelt field is
    a 422 and not a silent drop.
    """

    model_config = ConfigDict(extra="forbid")

    recorded_at: date_type
    odometer_km: Decimal | None = Field(None, ge=0)
    engine_hours: HoursFigure | None = None
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    notes: str | None = None

    @model_validator(mode="after")
    def _at_least_one_measurement(self) -> TireReadingCreate:
        """Reject a reading that measures nothing.

        ``odometer_km`` and ``engine_hours`` deliberately do not count. It is
        context for the wear projection, not an observation of the tire, so a
        date-plus-odometer row would add a history entry that says nothing
        about the tire and would still be picked up by ``_project_wear`` as
        the newest reading.

        :raises ValueError: when both tread and pressure are absent.
        """
        if self.tread_depth_mm is None and self.pressure_kpa is None:
            raise ValueError("A reading needs a tread depth, a pressure, or both")
        return self


class TireReadingResponse(BaseModel):
    """Tire reading response."""

    id: int
    tire_id: int
    vin: str
    # Nullable since 097: a reading can be taken on a stored tire.
    position: str | None = None
    mount_period_id: int | None = None
    recorded_at: date_type
    odometer_km: Decimal | None
    engine_hours: Decimal | None = None
    tread_depth_mm: Decimal | None
    pressure_kpa: Decimal | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MountPeriodResponse(BaseModel):
    """One interval a tire spent mounted at one position."""

    id: int
    position: str
    mounted_on: date_type | None
    dismounted_on: date_type | None
    mounted_odometer_km: Decimal | None
    dismounted_odometer_km: Decimal | None
    mounted_hours: Decimal | None = None
    dismounted_hours: Decimal | None = None
    is_assumed: bool
    observed_active_on: date_type | None
    notes: str | None

    model_config = {"from_attributes": True}


class MountPeriodUpdate(BaseModel):
    """Correct one mount period's bounds or notes.

    Every field optional, `exclude_unset` semantics: a key absent from the
    body is untouched, a key sent as null is cleared to unknown. `position`
    is deliberately not here (D14: only mount, dismount and rotate write it),
    and forbid-extra makes sending it a 422 rather than a silent ignore.
    """

    model_config = ConfigDict(extra="forbid")

    mounted_on: date_type | None = None
    mounted_odometer_km: Decimal | None = Field(None, ge=0)
    mounted_hours: HoursFigure | None = None
    dismounted_on: date_type | None = None
    dismounted_odometer_km: Decimal | None = Field(None, ge=0)
    dismounted_hours: HoursFigure | None = None
    notes: str | None = None


class MountPeriodCreate(BaseModel):
    """A closed period the tire spent on a corner, recorded after the fact.

    Closed only: an open period is what Mount creates, and it is the one whose
    corner `tires.position` holds. Odometers optional, dates required, the
    dismount no later than tomorrow (a day of slack for a user whose calendar
    is ahead of the server's).
    """

    model_config = ConfigDict(extra="forbid")

    position: TirePosition
    mounted_on: date_type
    mounted_odometer_km: Decimal | None = Field(None, ge=0)
    mounted_hours: HoursFigure | None = None
    dismounted_on: date_type
    dismounted_odometer_km: Decimal | None = Field(None, ge=0)
    dismounted_hours: HoursFigure | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _a_closed_period_in_the_past(self) -> MountPeriodCreate:
        if self.dismounted_on < self.mounted_on:
            raise ValueError("dismounted_on cannot be before mounted_on")
        if self.dismounted_on > household_today() + timedelta(days=1):
            raise ValueError("dismounted_on cannot be in the future")
        return self


class HistoryFaultResponse(BaseModel):
    """One contradiction in a tire's mount history.

    The same validator that refuses a contradictory write, run over the
    stored history, so a contradiction that blocks writes always has a period
    to badge even when no distance or projection figure is blocked by it.
    `message` is in the requesting user's distance unit.
    """

    period_id: int
    code: str
    counterpart_id: int | None = None
    message: str


class TireResponse(TireBase):
    """A tire, with where it is now and what is known about its wear.

    `position` is RE-DECLARED here as nullable rather than inherited: it left
    the write schema (D2c) but is still part of every read. Declaring it only
    on the base would have made it required on writes; omitting it entirely
    would have dropped it from responses. Neither is what a reader wants.

    `installed_date` is DERIVED, not stored (D12): the `mounted_on` of the
    earliest period **that has one**. When the earliest period is the migrated
    assumed one with a null start, this is null -- NOT the next known remount
    date. A plain MIN(mounted_on) would skip the unknown and report a later
    date as the installation date, which is worse than reporting nothing.
    """

    # Numbers without the input bounds, so a stored reading past today's rules
    # still reads instead of 500ing (test_response_contract).
    tread_depth_mm: Decimal | None = None
    pressure_kpa: Decimal | None = None
    min_tread_mm: Decimal | None = Field(
        Decimal("2.0"), description="Wear-out threshold in mm; drives reminder hooks"
    )
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    brand: str | None = None
    model_name: str | None = None
    size: str | None = None
    dot_code: str | None = None
    storage_location: str | None = None
    id: int
    vin: str
    # None means in storage, not mounted, or a stored corner we don't know.
    position: LenientTirePosition = None
    set_id: int | None = None
    retired_on: date_type | None = None
    installed_date: date_type | None = None
    created_at: datetime
    updated_at: datetime | None = None
    # Estimated km remaining until min_tread_mm based on the last two readings.
    projected_km_remaining: Decimal | None = None
    # Estimated calendar date of wear-out. Null even on a successful projection
    # when the two readings are same-day, so it is not a proxy for "projected".
    projected_wear_date: date_type | None = None
    # Why a projection is or is not available. See WearStatus.
    wear_status: str | None = None
    # Distance driven ON THIS TIRE, summed over its mount periods.
    distance_km: Decimal | None = None
    # The measurable part when the full history is not known, and the date it
    # runs from. Non-null for `incomplete`.
    known_distance_km: Decimal | None = None
    known_distance_since: date_type | None = None
    # Why the distance is or is not available. See DistanceStatus.
    distance_status: str | None = None
    # The periods a user must supply a number for, so the UI can link to the
    # exact one instead of saying "record a mount".
    blocking_period_ids: list[int] = Field(default_factory=list)
    # Every contradiction the history validator finds, including ones no
    # figure is blocked by, so the history drawer can badge and explain them.
    history_faults: list[HistoryFaultResponse] = Field(default_factory=list)
    below_threshold: bool = False
    mount_periods: list[MountPeriodResponse] = Field(default_factory=list)
    readings: list[TireReadingResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TireListResponse(BaseModel):
    """All tires for a vehicle."""

    tires: list[TireResponse]
    total: int


class TireSetCreate(BaseModel):
    """Name a group of tires.

    No `tire_ids` here. Membership is set from the TIRE side
    (`PUT /tires/{id}` with a `set_id`), so there is exactly one writer for it
    and no way for the two ends to disagree about who is in what.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=60)
    notes: str | None = None


class TireSetUpdate(BaseModel):
    """Rename a set, or change its notes."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=60)
    notes: str | None = None

    # NOT NULL column: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("name")


class TireSetResponse(BaseModel):
    """A set, with enough about its members to render it without a second call."""

    id: int
    vin: str
    name: str
    notes: str | None = None
    created_at: datetime
    #: Members, retired tires excluded: a retired tire is history rather than
    #: inventory, and a set that still counted it would offer to fit a tire the
    #: user has thrown away.
    tire_ids: list[int] = Field(default_factory=list)
    #: How many members are on the vehicle right now. 0 means the whole set is
    #: in storage, which is what makes "currently fitted" renderable without
    #: the caller joining the tire list itself.
    mounted_count: int = 0

    model_config = {"from_attributes": True}


class TireSetListResponse(BaseModel):
    """All sets for a vehicle."""

    sets: list[TireSetResponse]
    total: int


class TireSetMountRequest(BaseModel):
    """Fit every tire in a set, each at the corner it was last on.

    The odometer is a reading of the VEHICLE and applies to the whole swap: it
    closes the periods of everything coming off and opens the periods of
    everything going on. One number, because that is what the user reads off
    the dash once.
    """

    model_config = ConfigDict(extra="forbid")

    odometer_km: Decimal | None = Field(None, ge=0)
    engine_hours: HoursFigure | None = None
    mounted_on: date_type | None = None
    notes: str | None = None
