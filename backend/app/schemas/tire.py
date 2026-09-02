"""Pydantic schemas for tire position / tread tracking."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TirePosition = Literal["FL", "FR", "RL", "RR", "SPARE"]
TIRE_POSITIONS: tuple[str, ...] = ("FL", "FR", "RL", "RR", "SPARE")


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


class TireMountRequest(BaseModel):
    """Mount a tire at a position."""

    model_config = ConfigDict(extra="forbid")

    position: TirePosition
    mounted_on: date_type | None = None
    mounted_odometer_km: Decimal | None = Field(None, ge=0)
    notes: str | None = None


class TireDismountRequest(BaseModel):
    """Take a tire off the vehicle."""

    model_config = ConfigDict(extra="forbid")

    dismounted_on: date_type | None = None
    dismounted_odometer_km: Decimal | None = Field(None, ge=0)
    notes: str | None = None


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
    """

    recorded_at: date_type
    odometer_km: Decimal | None = Field(None, ge=0)
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    notes: str | None = None

    @model_validator(mode="after")
    def _at_least_one_measurement(self) -> TireReadingCreate:
        """Reject a reading that measures nothing.

        ``odometer_km`` deliberately does not count. It is context for the wear
        projection, not an observation of the tire, so a date-plus-odometer row
        would add a history entry that says nothing about the tire and would
        still be picked up by ``_project_wear`` as the newest reading.

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
    is_assumed: bool
    observed_active_on: date_type | None
    notes: str | None

    model_config = {"from_attributes": True}


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

    id: int
    vin: str
    position: TirePosition | None = None
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
    below_threshold: bool = False
    mount_periods: list[MountPeriodResponse] = Field(default_factory=list)
    readings: list[TireReadingResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_validator("position")
    @classmethod
    def _position_ok(cls, v: str | None) -> str | None:
        """None is valid: it means the tire is in storage, not mounted."""
        if v is not None and v not in TIRE_POSITIONS:
            raise ValueError(f"position must be one of {TIRE_POSITIONS} or null")
        return v


class TireListResponse(BaseModel):
    """All tires for a vehicle."""

    tires: list[TireResponse]
    total: int
