"""Insurance schemas: household policies, the vehicles on them, named fields."""

import re
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.constants.insurance import NO_CLAIMS_CLASS_PATTERN
from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null
from app.utils.insurance_coverages import COVERAGE_BY_KEY

#: Spelled out rather than built from `POLICY_TYPE_VALUES` so pyright and the
#: generated TypeScript union both see real literals;
#: `test_the_policy_type_literal_matches_the_constant` keeps the two in step.
#: The last two are the European formulas (#211).
PolicyType = Literal[
    "Liability",
    "Comprehensive",
    "Collision",
    "Full Coverage",
    "Minimum",
    "Other",
    "Third Party",
    "Third Party Extended",
]
PremiumFrequency = Literal["Monthly", "Quarterly", "Semi-Annual", "Annual"]
PolicyStatus = Literal["upcoming", "active", "expired"]
ShareStrategy = Literal["rescale", "reset_even"]
#: The standard coverage catalogue. Spelled out rather than built from
#: `COVERAGE_KEYS` so pyright and the generated TypeScript union both see real
#: literals; `test_the_literal_matches_the_catalogue` keeps the two in step.
#: The last nine are the European coverages (#211).
CoverageKey = Literal[
    "bodily_injury",
    "property_damage",
    "uninsured_bodily_injury",
    "uninsured_property_damage",
    "personal_injury_protection",
    "medical_payments",
    "comprehensive",
    "collision",
    "glass",
    "rental_reimbursement",
    "roadside_assistance",
    "loan_lease_gap",
    "custom_equipment",
    "third_party_liability",
    "driver_protection",
    "theft",
    "fire",
    "natural_disasters",
    "all_accidents_damage",
    "legal_protection",
    "assistance",
    "replacement_vehicle",
]

_NO_CLAIMS_DESCRIPTION = (
    "The no-claims class the vehicle is rated at: a bonus-malus coefficient (0.50), "
    "an SF-Klasse (SF 12), a classe di merito (1)… Ten characters of plain text"
)


def _blank_is_none(value: object) -> object:
    """A form sends '' for an untouched text field; the column wants NULL. A
    French coefficient typed with its comma (« 0,50 ») is stored with a point,
    the way the parsers and the profile's example write it."""
    if isinstance(value, str):
        stripped = " ".join(value.split())
        if re.fullmatch(r"[0-3],\d{2}", stripped):
            stripped = stripped.replace(",", ".")
        return stripped or None
    return value


class NamedField(BaseModel):
    """A user-named field: a suggested label or anything the user typed."""

    label: str = Field(..., min_length=1, max_length=60)
    value: str = Field(..., min_length=1, max_length=255)

    model_config = ConfigDict(from_attributes=True)


class NamedFieldResponse(BaseModel):
    """A user-named field, as stored.

    `NamedField`'s shape without its length rules, so a stored field those
    rules would refuse today (an imported empty label, say) still reads
    instead of taking the whole policy read down with it.
    """

    label: str
    value: str

    model_config = ConfigDict(from_attributes=True)


#: The catalogue's SHAPE, published on both coverage models so the frontend's
#: copy of it can be checked rather than trusted. Without this the two can
#: disagree silently and destructively: a slot the backend has and the frontend
#: lacks renders no input, and saving the form then clears the stored amount.
#: `frontend/src/constants/__tests__/insuranceCoverages.test.ts` compares
#: against it.
_COVERAGE_SLOTS_SCHEMA = {
    "x-coverage-slots": {
        key: {name: slot.kind for name, slot in coverage.slots()}
        for key, coverage in COVERAGE_BY_KEY.items()
    },
    # Which market lists each coverage (#211); the frontend's catalogue is
    # checked against it the same way.
    "x-coverage-regions": {
        key: list(coverage.regions) for key, coverage in COVERAGE_BY_KEY.items()
    },
}


class CoverageEntry(BaseModel):
    """One standard coverage on one vehicle.

    Sending the entry at all is what says the coverage is carried, so every
    amount may be omitted (roadside assistance usually has none). A slot the
    catalogue does not give this coverage is REJECTED rather than ignored: a
    stored "each accident" limit on a coverage whose card has no such line
    would be money no screen ever shows.

    `premium` is what the declarations page charges for this coverage alone.
    It is a record of the bill, NOT part of the allocation: the policy premium
    and the per-vehicle shares are what analytics and the even split work from,
    so editing it moves no money between vehicles and needs only write access
    to the vehicle it is on.
    """

    coverage_key: CoverageKey
    limit_primary: OptionalMoney = Field(None, decimal_places=2)
    limit_secondary: OptionalMoney = Field(None, decimal_places=2)
    deductible: OptionalMoney = Field(None, decimal_places=2)
    premium: OptionalMoney = Field(None, decimal_places=2)

    model_config = ConfigDict(from_attributes=True, json_schema_extra=_COVERAGE_SLOTS_SCHEMA)

    @model_validator(mode="after")
    def _only_the_slots_this_coverage_has(self):
        slots = dict(COVERAGE_BY_KEY[self.coverage_key].slots())
        for name in ("limit_primary", "limit_secondary", "deductible", "premium"):
            value = getattr(self, name)
            if value is None:
                continue
            slot = slots.get(name)
            if slot is None:
                raise ValueError(f"{self.coverage_key} has no {name}")
            # A count slot is a number of days, not money. Accepting 30.5 here
            # would store what the flat exports, which write counts whole,
            # cannot render back.
            if slot.kind == "count" and value != value.to_integral_value():
                raise ValueError(f"{self.coverage_key} {name} must be a whole number")
        return self


class CoverageEntryResponse(BaseModel):
    """One standard coverage on one vehicle, as stored.

    `CoverageEntry`'s shape without its input rules: no bounds and no slot
    check, so a stored amount those rules would refuse today still reads
    instead of taking the whole policy read down with it.
    """

    coverage_key: CoverageKey
    limit_primary: Decimal | None = None
    limit_secondary: Decimal | None = None
    deductible: Decimal | None = None
    premium: Decimal | None = None

    model_config = ConfigDict(from_attributes=True, json_schema_extra=_COVERAGE_SLOTS_SCHEMA)


def no_repeated_coverage(entries: list[CoverageEntry] | None) -> list[CoverageEntry] | None:
    """Reject a vehicle carrying the same coverage twice.

    The database's UNIQUE would catch it as a 409 at commit time, after the
    premium arithmetic has already run; this says which key, before anything
    is written. A plain function attached per schema, the way the reminder and
    maintenance schemas share their validators, so the check names the field it
    guards instead of riding on a base class a schema can forget to inherit.
    """
    seen = set()
    for entry in entries or []:
        if entry.coverage_key in seen:
            raise ValueError(f"{entry.coverage_key} is listed more than once")
        seen.add(entry.coverage_key)
    return entries


# ---------------------------------------------------------------------------
# Vehicle links
# ---------------------------------------------------------------------------


class PolicyVehicleCreate(BaseModel):
    """Attach one vehicle to a policy."""

    vin: str = Field(..., min_length=17, max_length=17)
    policy_type: PolicyType
    premium_share: OptionalMoney = Field(
        None, decimal_places=2, description="Per-period share; omit for an even split"
    )
    deductible: OptionalMoney = Field(None, decimal_places=2)
    no_claims_class: str | None = Field(
        None, max_length=10, pattern=NO_CLAIMS_CLASS_PATTERN, description=_NO_CLAIMS_DESCRIPTION
    )
    notes: str | None = None
    coverages: list[CoverageEntry] = Field(default_factory=list)
    fields: list[NamedField] = Field(default_factory=list)

    _check_coverages = field_validator("coverages")(no_repeated_coverage)
    _blank_class = field_validator("no_claims_class", mode="before")(_blank_is_none)


class PolicyVehicleUpdate(BaseModel):
    """Edit one vehicle's place on a policy.

    `fields` omitted leaves the named fields alone; present (even empty)
    replaces them. `premium_share` and `effective_to` move money between
    vehicles, so the route demands write access to the whole policy for them.
    """

    policy_type: PolicyType | None = None
    premium_share: OptionalMoney = Field(None, decimal_places=2)
    deductible: OptionalMoney = Field(None, decimal_places=2)
    no_claims_class: str | None = Field(
        None, max_length=10, pattern=NO_CLAIMS_CLASS_PATTERN, description=_NO_CLAIMS_DESCRIPTION
    )
    notes: str | None = None
    effective_to: date_type | None = None
    coverages: list[CoverageEntry] | None = None
    fields: list[NamedField] | None = None

    # NOT NULL column: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("policy_type")

    _check_coverages = field_validator("coverages")(no_repeated_coverage)
    _blank_class = field_validator("no_claims_class", mode="before")(_blank_is_none)


class PolicyVehicleUpsert(BaseModel):
    """One vehicle in the policy form's FULL vehicle list (see
    `InsurancePolicyUpdate.vehicles`). Matched to an existing link by VIN."""

    vin: str = Field(..., min_length=17, max_length=17)
    policy_type: PolicyType
    premium_share: OptionalMoney = Field(None, decimal_places=2)
    deductible: OptionalMoney = Field(None, decimal_places=2)
    no_claims_class: str | None = Field(
        None, max_length=10, pattern=NO_CLAIMS_CLASS_PATTERN, description=_NO_CLAIMS_DESCRIPTION
    )
    notes: str | None = None
    effective_to: date_type | None = None
    coverages: list[CoverageEntry] | None = Field(
        None, description="Omit to leave an existing vehicle's coverages alone"
    )
    fields: list[NamedField] | None = Field(
        None, description="Omit to leave an existing vehicle's named fields alone"
    )

    _check_coverages = field_validator("coverages")(no_repeated_coverage)
    _blank_class = field_validator("no_claims_class", mode="before")(_blank_is_none)


class PolicyVehicleResponse(BaseModel):
    """One vehicle beneath a policy."""

    id: int
    vin: str
    vehicle_name: str
    #: As stored: the inputs hold the vocabulary (`PolicyType`), a row written
    #: before this release or by an import reads whatever it holds.
    policy_type: str
    premium_share: Decimal | None = Field(None, description="Explicit share, if the user set one")
    effective_share: Decimal | None = Field(
        None, description="What this vehicle costs per period: explicit, or the even split"
    )
    deductible: Decimal | None = None
    # The same field as the inputs', read without its length and pattern rules.
    no_claims_class: str | None = Field(None, description=_NO_CLAIMS_DESCRIPTION)
    notes: str | None = None
    effective_to: date_type | None = None
    #: In catalogue order, which IS the display order.
    coverages: list[CoverageEntryResponse] = Field(default_factory=list)
    fields: list[NamedFieldResponse] = Field(default_factory=list)
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
    premium_amount: OptionalMoney = Field(
        None,
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
    premium_amount: OptionalMoney = Field(None, decimal_places=2)
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

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("start_date", "end_date", "provider", "policy_number")


class InsurancePolicyRenew(_PolicyDates):
    """Enter the next term. Allowed any time, so a renewal notice can be
    recorded the day it arrives; the new term reads `upcoming` until it starts."""

    start_date: date_type | None = Field(None, description="Default: the current end_date")
    end_date: date_type | None = Field(None, description="Default: the same term length")
    premium_amount: OptionalMoney = Field(None, decimal_places=2)
    premium_frequency: PremiumFrequency | None = None
    notes: str | None = None


class InsurancePolicyReplace(_PolicyDates):
    """Switch insurers: a new policy succeeds this one and takes its vehicles."""

    provider: str = Field(..., min_length=1, max_length=100)
    policy_number: str = Field(..., min_length=1, max_length=50)
    start_date: date_type
    end_date: date_type
    premium_amount: OptionalMoney = Field(None, decimal_places=2)
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
    fields: list[NamedFieldResponse] = Field(default_factory=list)
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
