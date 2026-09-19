"""Insurance schemas: household policies, the vehicles on them, named fields."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PolicyType = Literal["Liability", "Comprehensive", "Collision", "Full Coverage", "Minimum", "Other"]
PremiumFrequency = Literal["Monthly", "Quarterly", "Semi-Annual", "Annual"]
PolicyStatus = Literal["upcoming", "active", "expired"]
ShareStrategy = Literal["rescale", "reset_even"]


class NamedField(BaseModel):
    """A user-named field: a suggested label or anything the user typed."""

    label: str = Field(..., min_length=1, max_length=60)
    value: str = Field(..., min_length=1, max_length=255)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Vehicle links
# ---------------------------------------------------------------------------


class PolicyVehicleCreate(BaseModel):
    """Attach one vehicle to a policy."""

    vin: str = Field(..., min_length=17, max_length=17)
    policy_type: PolicyType
    premium_share: Decimal | None = Field(
        None, ge=0, decimal_places=2, description="Per-period share; omit for an even split"
    )
    deductible: Decimal | None = Field(None, ge=0, decimal_places=2)
    coverage_limits: str | None = None
    notes: str | None = None
    fields: list[NamedField] = Field(default_factory=list)


class PolicyVehicleUpdate(BaseModel):
    """Edit one vehicle's place on a policy.

    `fields` omitted leaves the named fields alone; present (even empty)
    replaces them. `premium_share` and `effective_to` move money between
    vehicles, so the route demands write access to the whole policy for them.
    """

    policy_type: PolicyType | None = None
    premium_share: Decimal | None = Field(None, ge=0, decimal_places=2)
    deductible: Decimal | None = Field(None, ge=0, decimal_places=2)
    coverage_limits: str | None = None
    notes: str | None = None
    effective_to: date_type | None = None
    fields: list[NamedField] | None = None


class PolicyVehicleUpsert(BaseModel):
    """One vehicle in the policy form's FULL vehicle list (see
    `InsurancePolicyUpdate.vehicles`). Matched to an existing link by VIN."""

    vin: str = Field(..., min_length=17, max_length=17)
    policy_type: PolicyType
    premium_share: Decimal | None = Field(None, ge=0, decimal_places=2)
    deductible: Decimal | None = Field(None, ge=0, decimal_places=2)
    coverage_limits: str | None = None
    notes: str | None = None
    effective_to: date_type | None = None
    fields: list[NamedField] | None = Field(
        None, description="Omit to leave an existing vehicle's named fields alone"
    )


class PolicyVehicleResponse(BaseModel):
    """One vehicle beneath a policy."""

    id: int
    vin: str
    vehicle_name: str
    policy_type: str
    premium_share: Decimal | None = Field(None, description="Explicit share, if the user set one")
    effective_share: Decimal | None = Field(
        None, description="What this vehicle costs per period: explicit, or the even split"
    )
    deductible: Decimal | None = None
    coverage_limits: str | None = None
    notes: str | None = None
    effective_to: date_type | None = None
    fields: list[NamedField] = Field(default_factory=list)
    can_edit: bool = False


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class _PolicyDates(BaseModel):
    @model_validator(mode="after")
    def _end_not_before_start(self):
        start = getattr(self, "start_date", None)
        end = getattr(self, "end_date", None)
        if start is not None and end is not None and end < start:
            raise ValueError("end_date must not be before start_date")
        return self


class InsurancePolicyCreate(_PolicyDates):
    """Create a household policy, optionally with its vehicles."""

    provider: str = Field(..., min_length=1, max_length=100)
    policy_number: str = Field(..., min_length=1, max_length=50)
    start_date: date_type
    end_date: date_type
    premium_amount: Decimal | None = Field(
        None,
        ge=0,
        decimal_places=2,
        description="Whole-policy amount per premium_frequency period",
    )
    premium_frequency: PremiumFrequency | None = None
    notes: str | None = None
    fields: list[NamedField] = Field(default_factory=list)
    vehicles: list[PolicyVehicleCreate] = Field(default_factory=list)


class InsurancePolicyUpdate(_PolicyDates):
    """Edit the policy-level details. Vehicles are edited through their links."""

    provider: str | None = Field(None, min_length=1, max_length=100)
    policy_number: str | None = Field(None, min_length=1, max_length=50)
    start_date: date_type | None = None
    end_date: date_type | None = None
    premium_amount: Decimal | None = Field(None, ge=0, decimal_places=2)
    premium_frequency: PremiumFrequency | None = None
    notes: str | None = None
    fields: list[NamedField] | None = None
    vehicles: list[PolicyVehicleUpsert] | None = Field(
        None,
        description="The policy's COMPLETE vehicle list. Omit to leave the vehicles alone; "
        "when present, vehicles not listed are removed. Sending the premium and every share "
        "together is how a vehicle is added and the premium raised in one valid step",
    )
    share_strategy: ShareStrategy | None = Field(
        None,
        description="Required when the premium changes on a policy whose vehicle shares "
        "are all explicit: rescale them proportionally, or reset to an even split",
    )


class InsurancePolicyRenew(_PolicyDates):
    """Enter the next term. Allowed any time, so a renewal notice can be
    recorded the day it arrives; the new term reads `upcoming` until it starts."""

    start_date: date_type | None = Field(None, description="Default: the current end_date")
    end_date: date_type | None = Field(None, description="Default: the same term length")
    premium_amount: Decimal | None = Field(None, ge=0, decimal_places=2)
    premium_frequency: PremiumFrequency | None = None
    notes: str | None = None


class InsurancePolicyReplace(_PolicyDates):
    """Switch insurers: a new policy succeeds this one and takes its vehicles."""

    provider: str = Field(..., min_length=1, max_length=100)
    policy_number: str = Field(..., min_length=1, max_length=50)
    start_date: date_type
    end_date: date_type
    premium_amount: Decimal | None = Field(None, ge=0, decimal_places=2)
    premium_frequency: PremiumFrequency | None = None
    notes: str | None = None
    vins: list[str] | None = Field(
        None, description="Vehicles to carry over; omit to carry every vehicle"
    )
    vehicles: list[PolicyVehicleCreate] | None = Field(
        None,
        description="The new policy's vehicles WITH the new insurer's coverages. When "
        "present it replaces `vins`; omit both to carry every vehicle over by type only",
    )
    end_old_on: date_type | None = Field(
        None, description="Shorten the old policy to this date for a mid-term switch"
    )


class InsurancePolicyResponse(BaseModel):
    """A policy with the vehicles the caller may see beneath it."""

    id: int
    provider: str
    policy_number: str
    start_date: date_type
    end_date: date_type
    premium_amount: Decimal | None = None
    premium_frequency: str | None = None
    notes: str | None = None
    status: PolicyStatus
    previous_policy_id: int | None = None
    has_successor: bool = False
    created_by_user_id: int | None = None
    created_at: datetime | None = None
    fields: list[NamedField] = Field(default_factory=list)
    vehicles: list[PolicyVehicleResponse] = Field(default_factory=list)
    other_vehicle_count: int = Field(
        0, description="Covered vehicles the caller has no access to see"
    )
    can_edit: bool = False


class PolicyHistoryEntry(BaseModel):
    """One term in a policy's chain, for review."""

    id: int
    provider: str
    policy_number: str
    start_date: date_type
    end_date: date_type
    premium_amount: Decimal | None = None
    premium_frequency: str | None = None
    status: PolicyStatus
    premium_change: Decimal | None = Field(
        None, description="This term's premium minus the prior term's, same frequency only"
    )
    vehicles: list[PolicyVehicleResponse] = Field(default_factory=list)
    is_current: bool = Field(False, description="The policy the history was requested for")
