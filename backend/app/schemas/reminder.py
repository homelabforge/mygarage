"""Pydantic schemas for Vehicle Reminder operations.

Canonical units (since v2.26.2): kilometers (Decimal NUMERIC(10,2)).
Engine-hours (since the hours-usage-model feature): dimensionless Decimal
NUMERIC(10,1) — no unit conversion, mirrors the mileage fields.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas._nullability import reject_null
from app.schemas.maintenance import (
    AnchorSpec,
    LenientAnchorKind,
    MaintenanceRuleSummary,
    RecurrenceSpec,
    validate_maintenance_type,
)

ReminderType = Literal["date", "mileage", "both", "smart", "hours"]
#: Where a pending reminder stands (#192 D1). Computed, never stored.
DueStatus = Literal["overdue", "due_soon", "on_track", "snoozed"]
#: The dimension a reminder's progress is measured along (#192 D3).
ProgressBasis = Literal["date", "distance", "hours"]


class ReminderCreate(BaseModel):
    """Schema for creating a vehicle reminder.

    With ``recurrence`` the server derives ``reminder_type`` and the ``due_*``
    thresholds from the anchor (``anchor``, the linked line item's visit, or
    a baseline) plus the intervals, and creates a maintenance rule. Without
    it the reminder is a one-off and the ``due_*`` rules below apply.
    """

    title: str = Field(..., min_length=1, max_length=200)
    reminder_type: ReminderType | None = None
    due_date: date | None = None
    due_mileage_km: Decimal | None = Field(None, gt=0, le=99999999.99)
    due_hours: Decimal | None = Field(None, gt=0, le=999999999.9)
    notes: str | None = None
    line_item_id: int | None = None
    maintenance_type: str | None = Field(None, max_length=50)
    recurrence: RecurrenceSpec | None = None
    anchor: AnchorSpec | None = None

    _validate_type = field_validator("maintenance_type")(validate_maintenance_type)

    @model_validator(mode="after")
    def validate_fields_for_type(self) -> ReminderCreate:
        """Ensure required fields are present based on reminder type.

        ``smart`` requires ``due_date`` and exactly one of
        ``{due_mileage_km, due_hours}`` — accepts both today's existing
        date+mileage smart reminders (hours null) and the new date+hours
        variant (mileage null), but rejects specifying both or neither.

        A recurring reminder skips these: its thresholds are derived.
        """
        if self.recurrence is not None:
            return self
        if self.reminder_type is None:
            raise ValueError("reminder_type is required unless recurrence is given")
        if self.reminder_type in ("date", "both", "smart") and not self.due_date:
            raise ValueError("due_date required for this reminder type")
        if self.reminder_type in ("mileage", "both") and not self.due_mileage_km:
            raise ValueError("due_mileage_km required for this reminder type")
        if self.reminder_type == "hours" and not self.due_hours:
            raise ValueError("due_hours required for this reminder type")
        if self.reminder_type == "smart":
            has_mileage = self.due_mileage_km is not None
            has_hours = self.due_hours is not None
            if has_mileage == has_hours:
                raise ValueError(
                    "smart reminders require exactly one of due_mileage_km or due_hours"
                )
        return self


class ReminderUpdate(BaseModel):
    """Schema for updating a vehicle reminder.

    Status is NOT here — use /done, /dismiss or /complete endpoints.
    Validation is lenient (fields may be absent). The route handler merges
    this patch onto the existing reminder and validates the final state.

    ``recurrence`` edits the reminder's rule (or creates one); an explicit
    ``null`` deactivates the rule and leaves the reminder as a one-off. For a
    reminder with an active rule the ``due_*`` fields are derived and
    rejected with 422 if sent.
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    reminder_type: ReminderType | None = None
    due_date: date | None = None
    due_mileage_km: Decimal | None = Field(None, gt=0, le=99999999.99)
    due_hours: Decimal | None = Field(None, gt=0, le=999999999.9)
    notes: str | None = None
    maintenance_type: str | None = Field(None, max_length=50)
    recurrence: RecurrenceSpec | None = None

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("title", "reminder_type")

    _validate_type = field_validator("maintenance_type")(validate_maintenance_type)


class ReminderSnoozeRequest(BaseModel):
    """Body of POST /{reminder_id}/snooze.

    The range check (strictly after household "today", at most ten years
    out) lives in the route: it needs ``household_today()``, which is
    request-scoped state a schema validator cannot see.
    """

    until: date


class ReminderResponse(BaseModel):
    """Schema for reminder response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vin: str
    line_item_id: int | None
    title: str
    reminder_type: str
    due_date: date | None
    due_mileage_km: Decimal | None
    due_hours: Decimal | None
    status: str
    notes: str | None
    #: Hide-until-date snooze. The due fields above stay real; while
    #: household "today" is before this date the reminder is out of every
    #: overdue/due-soon count and notification. The frontend derives
    #: "snoozed now" by comparing against todayInHousehold().
    snoozed_until: date | None = None
    estimated_due_date: date | None = None
    #: When the usage target (mileage or hours) is reached at the current
    #: rate, uncapped. ``estimated_due_date`` is the earlier of this and
    #: ``due_date``; the two are shown apart so a slow driver still sees the
    #: calendar threshold.
    projected_usage_date: date | None = None
    # --- Where it stands (#192). Pending only; null on done and dismissed. ----
    #: reminder_service.reminder_due_status: the row's colour, and what the
    #: hero, card and fleet-strip counts tally.
    due_status: DueStatus | None = None
    #: Share of the way from the start (the anchor, else creation) to due, along
    #: the dimension closest to due. Unclamped: 1.25 is a quarter past due.
    progress: float | None = None
    progress_basis: ProgressBasis | None = None
    #: due_date minus household today; negative once past.
    days_until_due: int | None = None
    #: due_mileage_km minus the current odometer, canonical km; negative once over.
    km_until_due: Decimal | None = None
    #: due_hours minus the current engine hours; negative once over.
    hours_until_due: Decimal | None = None
    last_notified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # --- Maintenance lifecycle ---------------------------------------------
    maintenance_type: str | None = None
    rule_id: int | None = None
    rule: MaintenanceRuleSummary | None = None
    anchor_kind: LenientAnchorKind = None
    anchor_date: date | None = None
    anchor_odometer_km: Decimal | None = None
    anchor_hours: Decimal | None = None
    completed_at: datetime | None = None
    completed_date: date | None = None
    completed_odometer_km: Decimal | None = None
    completed_hours: Decimal | None = None
    completed_line_item_id: int | None = None
    superseded_by_id: int | None = None
    #: Other PENDING reminders on the vehicle with the same maintenance type.
    duplicate_of: list[int] = Field(default_factory=list)


class ReminderCompleteResponse(BaseModel):
    """What completing a reminder produced: the closed one, its successor,
    and the service record it created or linked."""

    reminder: ReminderResponse
    next_reminder: ReminderResponse | None = None
    service_visit_id: int | None = None
    line_item_id: int | None = None
