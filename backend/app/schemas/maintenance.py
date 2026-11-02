"""Pydantic schemas for the maintenance lifecycle: rules, anchors, completion,
pack preview and duplicate reconciliation.

Canonical units throughout: kilometres (Decimal NUMERIC(10,2)), engine hours
(dimensionless NUMERIC(10,1)), calendar months and days.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null
from app.utils.lenient_vocab import LenientVocab, lenient_reader
from app.utils.maintenance_types import is_valid_code

AnchorKind = Literal["service", "completion", "baseline"]
# `vehicle_reminders.anchor_kind` has no CHECK, so a kind we don't know reads as
# null on the way out instead of 500ing the reminder list or the pack preview.
LenientAnchorKind = Annotated[
    AnchorKind | None, BeforeValidator(lenient_reader(AnchorKind)), LenientVocab(None)
]


def validate_maintenance_type(value: str | None) -> str | None:
    """A stored code is lowercase snake_case; anything else is a 422, not a guess."""
    if value is None:
        return None
    if not is_valid_code(value):
        raise ValueError("maintenance_type must be a lowercase snake_case code (2-50 chars)")
    return value


class RecurrenceSpec(BaseModel):
    """The intervals of a rule. At least one; km and hours never together."""

    interval_km: Decimal | None = Field(None, gt=0, le=99999999.99)
    interval_months: int | None = Field(None, gt=0, le=600)
    interval_days: int | None = Field(None, gt=0, le=36500)
    interval_hours: Decimal | None = Field(None, gt=0, le=999999999.9)

    @model_validator(mode="after")
    def validate_intervals(self) -> RecurrenceSpec:
        """Reject an empty rule and a rule that mixes the two usage dimensions."""
        if (
            self.interval_km is None
            and self.interval_months is None
            and self.interval_days is None
            and self.interval_hours is None
        ):
            raise ValueError("recurrence needs at least one interval")
        if self.interval_km is not None and self.interval_hours is not None:
            raise ValueError("recurrence may use a distance or an hours interval, not both")
        return self


class IntervalOverride(RecurrenceSpec):
    """Intervals the caller typed while applying a pack, for one item.

    Subclasses `RecurrenceSpec` so the rules a rule obeys (at least one
    interval, never distance and hours together) are enforced from one place
    rather than restated here.

    An override is not the pack's value, it is a number the caller typed just
    now, so it wins over BOTH the pack's own interval and the destination
    vehicle's existing rule. See `maintenance_service._plan_item`: without that
    second part the override is planned, previewed, and then dropped on a reuse.
    """


class AnchorSpec(BaseModel):
    """A hand-entered anchor: when and at what reading the work was last done."""

    date: date_type | None = None
    odometer_km: Decimal | None = Field(None, ge=0, le=99999999.99)
    hours: Decimal | None = Field(None, ge=0, le=9999999.9)


class MaintenanceTypeResponse(BaseModel):
    """One registry entry for pickers."""

    code: str
    label: str
    category: str


class MaintenanceRuleSummary(BaseModel):
    """The rule a reminder is derived from, embedded in the reminder response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    maintenance_type: str | None
    interval_km: Decimal | None
    interval_months: int | None
    interval_days: int | None
    interval_hours: Decimal | None
    #: Days before the due date from which the work may be done (#211); the
    #: inspection engine sets it from the country profile. Null: no window.
    lead_days: int | None = None
    source: str
    source_pack_id: str | None
    is_active: bool


class MaintenanceRuleResponse(MaintenanceRuleSummary):
    """A rule on its own."""

    vin: str
    source_pack_key: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime | None


class MaintenanceRuleCreate(RecurrenceSpec):
    """The explicit path: creates a rule even when one of the type exists."""

    title: str = Field(..., min_length=1, max_length=200)
    maintenance_type: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=2000)

    _validate_type = field_validator("maintenance_type")(validate_maintenance_type)


class MaintenanceRuleUpdate(BaseModel):
    """Patch a rule. Omitted fields keep their values."""

    title: str | None = Field(None, min_length=1, max_length=200)
    maintenance_type: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=2000)
    recurrence: RecurrenceSpec | None = None
    is_active: bool | None = None

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("title", "is_active", "recurrence")

    _validate_type = field_validator("maintenance_type")(validate_maintenance_type)


CompletionMode = Literal["create_visit", "link_visit", "mark_only"]


class ReminderCompleteRequest(BaseModel):
    """Close a reminder with the real completion date and readings.

    With `link_visit` the linked visit is the service record: its date,
    odometer and engine hours are the completion, and `completed_date`,
    `odometer_km` and `engine_hours` in the request are not used.
    """

    completed_date: date_type
    odometer_km: Decimal | None = Field(None, ge=0, le=99999999.99)
    engine_hours: Decimal | None = Field(None, ge=0, le=9999999.9)
    mode: CompletionMode = "create_visit"
    service_visit_id: int | None = None
    vendor_id: int | None = None
    cost: OptionalMoney = None
    notes: str | None = Field(None, max_length=5000)

    @model_validator(mode="after")
    def validate_mode(self) -> ReminderCompleteRequest:
        """`link_visit` names the visit; the other modes must not."""
        if self.mode == "link_visit" and self.service_visit_id is None:
            raise ValueError("service_visit_id is required to link an existing visit")
        if self.mode != "link_visit" and self.service_visit_id is not None:
            raise ValueError("service_visit_id is only used with mode 'link_visit'")
        return self


class AnchorCandidate(BaseModel):
    """A line item the preview can point at."""

    line_item_id: int
    visit_id: int
    date: date_type
    odometer_km: Decimal | None
    engine_hours: Decimal | None
    description: str
    maintenance_type: str | None


class AnchorProposal(BaseModel):
    """What a reminder would count from, and why."""

    kind: LenientAnchorKind
    date: date_type
    odometer_km: Decimal | None
    hours: Decimal | None
    line_item_id: int | None = None
    #: 'reminder' = the rule's pending reminder already carries this anchor;
    #: 'history' = the newest typed service; 'baseline' = nothing on record.
    origin: Literal["reminder", "history", "baseline"]
    note: str | None = None


class AnchorChoice(BaseModel):
    """The caller's pick for one pack item: a line item to type, or done today."""

    line_item_id: int | None = None
    done_today: bool = False

    @model_validator(mode="after")
    def validate_choice(self) -> AnchorChoice:
        """Exactly one of the two."""
        if (self.line_item_id is None) == (not self.done_today):
            raise ValueError("choose either line_item_id or done_today")
        return self


class PackItemPlan(BaseModel):
    """Everything apply-pack would do for one item, computed before any write."""

    key: str
    maintenance_type: str
    title: str
    interval_km: Decimal | None
    interval_months: int | None
    interval_days: int | None
    interval_hours: Decimal | None
    rule_action: Literal["create", "reuse", "reactivate", "skip"]
    rule_id: int | None = None
    skip_reason: str | None = None
    keep_reminder_id: int | None = None
    adopted: bool = False
    supersede_reminder_ids: list[int] = Field(default_factory=list)
    anchor: AnchorProposal | None = None
    #: A typed service newer than the pending reminder's anchor: applying
    #: completes the reminder from it and creates the successor.
    newer_service: AnchorCandidate | None = None
    typed_history: list[AnchorCandidate] = Field(default_factory=list)
    untyped_candidates: list[AnchorCandidate] = Field(default_factory=list)
    due_date: date_type | None = None
    due_mileage_km: Decimal | None = None
    due_hours: Decimal | None = None
    reminder_type: str | None = None
    note: str | None = None


class ApplyPackPreview(BaseModel):
    """The plan for one pack on one vehicle."""

    pack_id: str
    pack_name: str
    items: list[PackItemPlan]


class DuplicateGroup(BaseModel):
    """Pending reminders that share a maintenance type."""

    maintenance_type: str
    label: str
    reminder_ids: list[int]
    suggested_keep_id: int


class ReconcileDuplicatesRequest(BaseModel):
    """Keep one reminder of a group and supersede the rest."""

    keep_id: int
    supersede_ids: list[int] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_ids(self) -> ReconcileDuplicatesRequest:
        """The keeper is never in the list it supersedes."""
        if self.keep_id in self.supersede_ids:
            raise ValueError("keep_id cannot also be superseded")
        if len(set(self.supersede_ids)) != len(self.supersede_ids):
            raise ValueError("supersede_ids must be unique")
        return self
