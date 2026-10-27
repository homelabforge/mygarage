"""Reminder business logic service layer."""

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol, cast

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.schemas.reminder import (
    DueStatus,
    ProgressBasis,
    ReminderCreate,
    ReminderResponse,
    ReminderUpdate,
)
from app.services.hours_service import latest_engine_hours_and_date, nearest_hours
from app.services.maintenance_recurrence import project_usage_date
from app.services.odometer_service import nearest_odometer
from app.utils.hours_formatting import format_hours
from app.utils.household_time import household_date, household_today
from app.utils.logging_utils import sanitize_for_log
from app.utils.maintenance_types import classify
from app.utils.notification_cooldown import in_cooldown
from app.utils.render_context import RenderContext, render_context_for_vehicle
from app.utils.unit_formatting import format_quantity

logger = logging.getLogger(__name__)

# A pending reminder expected within this window is "due soon" (card/hero badge, fleet strip).
DUE_SOON_WINDOW = timedelta(days=30)
# A usage target the rates can't project is due soon this far along its span (#192 D2).
DUE_SOON_PROGRESS = 0.9


def validate_reminder_state(
    reminder_type: str,
    due_date: date | None,
    due_mileage_km: Decimal | None,
    due_hours: Decimal | None,
) -> None:
    """Shared validation for both create and the final merged state on update.

    Raises ValueError if the combination is invalid for reminder_type.

    - ``'date'`` requires ``due_date``.
    - ``'mileage'`` requires ``due_mileage_km``.
    - ``'hours'`` requires ``due_hours`` (mirrors ``'mileage'`` — no date
      requirement).
    - ``'both'`` requires ``due_date`` AND ``due_mileage_km`` (unchanged —
      stays date+mileage, never date+hours).
    - ``'smart'`` requires ``due_date`` AND *exactly one* of
      ``{due_mileage_km, due_hours}``. This accepts today's existing
      date+mileage smart reminders (hours null) as well as the new
      date+hours variant (mileage null) for hour-tracked vehicles, but
      rejects specifying both or neither.
    """
    if reminder_type in ("date", "both", "smart") and not due_date:
        raise ValueError("due_date required for this reminder type")
    if reminder_type in ("mileage", "both") and not due_mileage_km:
        raise ValueError("due_mileage_km required for this reminder type")
    if reminder_type == "hours" and not due_hours:
        raise ValueError("due_hours required for this reminder type")
    if reminder_type == "smart":
        has_mileage = due_mileage_km is not None
        has_hours = due_hours is not None
        if has_mileage == has_hours:
            raise ValueError("smart reminders require exactly one of due_mileage_km or due_hours")


async def calculate_driving_rate(vin: str, db: AsyncSession) -> float | None:
    """Calculate average km/day from last 90 days of OdometerRecord.

    Returns None if fewer than 2 records in the window.
    """
    cutoff = household_today() - timedelta(days=90)
    result = await db.execute(
        select(
            func.min(OdometerRecord.odometer_km),
            func.max(OdometerRecord.odometer_km),
            func.min(OdometerRecord.date),
            func.max(OdometerRecord.date),
            func.count(OdometerRecord.id),
        )
        .where(OdometerRecord.vin == vin)
        .where(OdometerRecord.date >= cutoff)
    )
    row = result.one()
    min_km, max_km, min_date, max_date, count = row

    if count < 2 or min_date == max_date:
        return None

    days_span = (max_date - min_date).days
    if days_span <= 0:
        return None

    return float(max_km - min_km) / days_span


async def get_current_mileage(vin: str, db: AsyncSession) -> Decimal | None:
    """The vehicle's current odometer (km): the highest reading of its latest day."""
    result = await db.execute(
        select(OdometerRecord.odometer_km)
        .where(OdometerRecord.vin == vin)
        .order_by(
            OdometerRecord.date.desc(),
            OdometerRecord.odometer_km.desc(),
            OdometerRecord.id.desc(),
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


async def calculate_hours_driving_rate(vin: str, db: AsyncSession) -> float | None:
    """Calculate average engine-hours/day from last 90 days of HoursRecord.

    Mirrors ``calculate_driving_rate`` (same 90-day window/approach),
    substituting ``engine_hours`` for ``odometer_km``.

    Returns None if fewer than 2 records in the window.
    """
    cutoff = household_today() - timedelta(days=90)
    result = await db.execute(
        select(
            func.min(HoursRecord.engine_hours),
            func.max(HoursRecord.engine_hours),
            func.min(HoursRecord.date),
            func.max(HoursRecord.date),
            func.count(HoursRecord.id),
        )
        .where(HoursRecord.vin == vin)
        .where(HoursRecord.date >= cutoff)
    )
    row = result.one()
    min_hours, max_hours, min_date, max_date, count = row

    if count < 2 or min_date == max_date:
        return None

    days_span = (max_date - min_date).days
    if days_span <= 0:
        return None

    return float(max_hours - min_hours) / days_span


async def get_current_hours(vin: str, db: AsyncSession) -> Decimal | None:
    """Get the canonical current engine-hours reading for a vehicle.

    Mirrors ``get_current_mileage``, but delegates to the ONE canonical
    "latest hours" helper (``latest_engine_hours_and_date`` — see the
    hours-usage-model plan §1) rather than re-deriving it, so reminders
    agree with every other surface (detail-stats, hero/card, widget).
    """
    engine_hours, _ = await latest_engine_hours_and_date(db, vin)
    return engine_hours


async def start_readings(db: AsyncSession, vin: str) -> tuple[Decimal | None, Decimal | None]:
    """The odometer and hours an unanchored reminder made now counts from: the
    vehicle's current readings, both, whatever targets it has (R5)."""
    return await get_current_mileage(vin, db), await get_current_hours(vin, db)


def is_reminder_overdue(
    reminder: Reminder,
    current_km: Decimal | None,
    current_hours: Decimal | None,
    today: date | None = None,
) -> bool:
    """Whether a pending reminder is overdue right now (Phase 6b).

    The single boolean overdue check shared by ``routes/dashboard.py`` and
    ``services/family_dashboard_service.py`` — both duplicated this inline
    (date + mileage only) before this helper existed, which is exactly why a
    pure ``hours`` reminder never showed up as overdue on either surface
    despite ``check_due_reminders`` already firing notifications for it
    (Phase 5). Extracted here rather than in a route/service module so both
    call sites (and any future one) share ONE definition.

    Field-presence gated, not ``reminder_type`` gated: a reminder is overdue
    if ANY of its set due-fields (date / mileage / hours) has been reached.
    This is equivalent to gating on ``reminder_type`` since
    ``validate_reminder_state`` only ever lets compatible fields be set for
    a given type (e.g. a ``'mileage'`` reminder never has ``due_hours`` set).

    Args:
        reminder: The pending reminder to evaluate.
        current_km: The vehicle's current odometer reading (km), or
            ``None`` if no reading exists yet.
        current_hours: The vehicle's current engine-hours reading, or
            ``None`` if no reading exists yet.
        today: Override for "today" (tests only); defaults to
            ``household_today()``.

    Returns:
        ``True`` if the reminder is overdue by date, mileage, or hours.
    """
    if today is None:
        today = household_today()
    if is_reminder_snoozed(reminder, today):
        # A snooze silences every trigger alike, date, mileage and hours:
        # "not now" is about the nagging, not about which threshold fired.
        return False
    if reminder.due_date and reminder.due_date <= today:
        return True
    if reminder.due_mileage_km and current_km and current_km >= reminder.due_mileage_km:
        return True
    if reminder.due_hours and current_hours and current_hours >= reminder.due_hours:
        return True
    return False


def is_reminder_snoozed(reminder: Reminder, today: date | None = None) -> bool:
    """Whether the reminder's snooze is active right now.

    Strictly before: a snooze until the 20th means "leave me alone UNTIL
    the 20th", and on the 20th the reminder is back. Inert on non-pending
    reminders only by virtue of every consumer filtering status first; the
    field itself needs no clearing to expire.
    """
    if today is None:
        today = household_today()
    return reminder.snoozed_until is not None and today < reminder.snoozed_until


def projected_usage_date(
    reminder: Reminder,
    current_km: Decimal | None,
    current_hours: Decimal | None,
    km_per_day: float | None,
    hours_per_day: float | None,
    today: date,
) -> date | None:
    """When the reminder's usage target is reached at the vehicle's rate.

    Mileage first, else hours (a rule never sets both; legacy ``both`` rows
    carry only mileage). ``None`` without a target, a reading or a rate.
    """
    if reminder.due_mileage_km is not None:
        if current_km is None or not km_per_day:
            return None
        return project_usage_date(current_km, reminder.due_mileage_km, km_per_day, today)
    if reminder.due_hours is not None:
        if current_hours is None or not hours_per_day:
            return None
        return project_usage_date(current_hours, reminder.due_hours, hours_per_day, today)
    return None


def expected_due_date(
    reminder: Reminder,
    current_km: Decimal | None,
    current_hours: Decimal | None,
    km_per_day: float | None,
    hours_per_day: float | None,
    today: date,
) -> date | None:
    """The date a pending reminder is expected: the earlier of its calendar
    ``due_date`` and its usage projection, whichever exist; ``None`` with
    neither. The reminders list shows it as ``estimated_due_date`` (once a
    projection exists) and the due-soon count compares it to ``DUE_SOON_WINDOW``.
    """
    projected = projected_usage_date(
        reminder, current_km, current_hours, km_per_day, hours_per_day, today
    )
    if reminder.due_date and projected:
        return min(reminder.due_date, projected)
    return reminder.due_date or projected


#: Ties between dimensions go to the first: a distance or hours figure tells a
#: row more than a day count does.
_BASIS_ORDER: tuple[ProgressBasis, ...] = ("distance", "hours", "date")


@dataclass(frozen=True)
class ReminderStart:
    """What a pending reminder counts from (#192 D4): its anchor, or for an
    unanchored one the day it was made and the readings stored then (or,
    without them, the readings nearest that day)."""

    day: date | None
    km: Decimal | None
    hours: Decimal | None


@dataclass(frozen=True)
class DueContext:
    """One vehicle's readings and rates on one day, plus the starts of its
    unanchored reminders by id. Built once per list or count, so every row
    reads the same values the badges count with."""

    today: date
    current_km: Decimal | None
    current_hours: Decimal | None
    km_per_day: float | None
    hours_per_day: float | None
    starts: Mapping[int, ReminderStart] = field(default_factory=dict[int, ReminderStart])


def anchor_start(reminder: Reminder) -> ReminderStart | None:
    """The reminder's anchor as its start, or ``None`` when it has none on record.

    Read through ``maintenance_service.anchor_of``, so "unanchored" here is
    exactly what rule adoption and reconciliation treat as unanchored: a
    hand-made one-off, or a legacy reminder from before anchors.
    """
    # Imported here: maintenance_service imports this module.
    from app.services.maintenance_service import anchor_of

    anchor = anchor_of(reminder)
    if anchor is None:
        return None
    return ReminderStart(day=anchor.date, km=anchor.odometer_km, hours=anchor.hours)


def reminder_start(reminder: Reminder, ctx: DueContext) -> ReminderStart | None:
    """The reminder's anchor, else the start ``ctx`` holds for it."""
    return anchor_start(reminder) or ctx.starts.get(reminder.id)


def progress_fractions(reminder: Reminder, ctx: DueContext) -> dict[ProgressBasis, float]:
    """Elapsed over span for each dimension the reminder has (#192 D3), counted
    from ``reminder_start``.

    A dimension is left out when its start, its current reading or a positive
    span is missing. Unclamped both ways: past due reads above 1, and a reading
    below the start (a typo, or a nearest reading taken after creation when
    there's no stored start to use) reads below 0. The bar clamps; the sort
    doesn't need to.
    """
    start = reminder_start(reminder, ctx)
    if start is None:
        return {}
    fractions: dict[ProgressBasis, float] = {}
    if reminder.due_date is not None and start.day is not None:
        span_days = (reminder.due_date - start.day).days
        if span_days > 0:
            fractions["date"] = (ctx.today - start.day).days / span_days
    if reminder.due_mileage_km is not None and start.km is not None and ctx.current_km is not None:
        span_km = reminder.due_mileage_km - start.km
        if span_km > 0:
            fractions["distance"] = float((ctx.current_km - start.km) / span_km)
    if reminder.due_hours is not None and start.hours is not None and ctx.current_hours is not None:
        span_hours = reminder.due_hours - start.hours
        if span_hours > 0:
            fractions["hours"] = float((ctx.current_hours - start.hours) / span_hours)
    return fractions


def leading_progress(
    fractions: Mapping[ProgressBasis, float],
) -> tuple[ProgressBasis, float] | None:
    """The dimension closest to due and its fraction, or ``None`` with none."""
    leading: tuple[ProgressBasis, float] | None = None
    for basis in _BASIS_ORDER:
        value = fractions.get(basis)
        if value is not None and (leading is None or value > leading[1]):
            leading = (basis, value)
    return leading


def _projected(reminder: Reminder, ctx: DueContext) -> date | None:
    """``projected_usage_date`` on the context's readings and rates."""
    return projected_usage_date(
        reminder, ctx.current_km, ctx.current_hours, ctx.km_per_day, ctx.hours_per_day, ctx.today
    )


def expected_for(reminder: Reminder, ctx: DueContext) -> date | None:
    """``expected_due_date`` on the context's readings and rates."""
    return expected_due_date(
        reminder, ctx.current_km, ctx.current_hours, ctx.km_per_day, ctx.hours_per_day, ctx.today
    )


def _usage_basis(reminder: Reminder) -> ProgressBasis | None:
    """The usage dimension ``projected_usage_date`` projects: mileage first, else hours."""
    if reminder.due_mileage_km is not None:
        return "distance"
    if reminder.due_hours is not None:
        return "hours"
    return None


def reminder_due_status(reminder: Reminder, ctx: DueContext) -> DueStatus:
    """Where a pending reminder stands (#192 D1).

    The hero, dashboard-card and fleet-strip counts tally these, so a row's
    colour and the badge beside it agree. Snoozed wins, then overdue, then due
    soon: expected within ``DUE_SOON_WINDOW``, or, for a usage target the rates
    can't project, ``DUE_SOON_PROGRESS`` of the way there (D2). The fallback
    reads the usage dimension's own fraction, never the date's, and never fires
    when a projection exists, so it can't contradict one.
    """
    if is_reminder_snoozed(reminder, ctx.today):
        return "snoozed"
    if is_reminder_overdue(reminder, ctx.current_km, ctx.current_hours, ctx.today):
        return "overdue"
    expected = expected_for(reminder, ctx)
    if expected is not None and expected <= ctx.today + DUE_SOON_WINDOW:
        return "due_soon"
    basis = _usage_basis(reminder)
    if basis is not None and _projected(reminder, ctx) is None:
        share = progress_fractions(reminder, ctx).get(basis)
        if share is not None and share >= DUE_SOON_PROGRESS:
            return "due_soon"
    return "on_track"


@dataclass(frozen=True)
class ReminderCounts:
    """Per-vehicle counts; ``due_soon`` is the subset of ``upcoming`` that ``reminder_due_status`` calls due soon: expected within ``DUE_SOON_WINDOW``, or the D2 progress fallback."""

    overdue: int
    upcoming: int
    due_soon: int


def tally_due_statuses(pending: Sequence[Reminder], ctx: DueContext) -> ReminderCounts:
    """Count a vehicle's pending reminders by ``reminder_due_status``.

    Upcoming is pending and not overdue; due soon is its subset. A snoozed
    reminder is in no count until its date passes.
    """
    overdue = upcoming = due_soon = 0
    for reminder in pending:
        status = reminder_due_status(reminder, ctx)
        if status == "snoozed":
            continue
        if status == "overdue":
            overdue += 1
            continue
        upcoming += 1
        if status == "due_soon":
            due_soon += 1
    return ReminderCounts(overdue=overdue, upcoming=upcoming, due_soon=due_soon)


def classify_pending_reminders(
    pending: Sequence[Reminder],
    current_km: Decimal | None,
    current_hours: Decimal | None,
    km_per_day: float | None,
    hours_per_day: float | None,
    today: date,
) -> ReminderCounts:
    """``tally_due_statuses`` from loose readings, for callers that hold them.

    ``None`` rates skip the usage projection, and an unanchored reminder gets no
    start here, so a usage reminder is then due soon only through its
    anchor (D2). The widget and the family dashboard call this without rates and
    read only overdue and upcoming, which D2 never moves.
    """
    ctx = DueContext(
        today=today,
        current_km=current_km,
        current_hours=current_hours,
        km_per_day=km_per_day,
        hours_per_day=hours_per_day,
    )
    return tally_due_statuses(pending, ctx)


def created_on(reminder: Reminder) -> date | None:
    """The household day the reminder was created.

    ``None`` for a reminder not yet flushed, whose server default hasn't run.
    """
    # The column is NOT NULL but an unflushed object's attribute is still None.
    # A cast, not an annotation: pyright narrows an annotated assignment to the
    # mapped type and would call the check below always false.
    created = cast("datetime | None", reminder.created_at)
    if created is None:
        return None
    return household_date(created)


def _usable_start(stored: Decimal | None, current: Decimal | None) -> Decimal | None:
    """The stored start, unless it's missing or above the current reading (R2)."""
    if stored is None or (current is not None and stored > current):
        return None
    return stored


async def load_reminder_starts(
    db: AsyncSession,
    vin: str,
    reminders: Sequence[Reminder],
    *,
    current_km: Decimal | None,
    current_hours: Decimal | None,
) -> dict[int, ReminderStart]:
    """Starts for the unanchored reminders among ``reminders``, by id (#192 D4).

    Each counts from the day it was made and the readings it stored then; a
    missing stored reading, or one above the current reading (a typo since
    fixed), falls back to the reading nearest that day, looked up once per day.
    These are stored starts, not anchors: adoption (``_pick_keeper``) and
    ``reconcile_rule`` read anchors only, so a loose reminder stays an adoption
    candidate.
    """
    km_on: dict[date, Decimal | None] = {}
    hours_on: dict[date, Decimal | None] = {}
    starts: dict[int, ReminderStart] = {}
    for reminder in reminders:
        if anchor_start(reminder) is not None:
            continue
        day = created_on(reminder)
        if day is None:
            continue
        km: Decimal | None = None
        if reminder.due_mileage_km is not None:
            km = _usable_start(reminder.start_odometer_km, current_km)
            if km is None:
                if day not in km_on:
                    record = await nearest_odometer(db, vin, day)
                    km_on[day] = record.odometer_km if record is not None else None
                km = km_on[day]
        hours: Decimal | None = None
        if reminder.due_hours is not None:
            hours = _usable_start(reminder.start_hours, current_hours)
            if hours is None:
                if day not in hours_on:
                    hours_on[day] = await nearest_hours(db, vin, day)
                hours = hours_on[day]
        starts[reminder.id] = ReminderStart(day=day, km=km, hours=hours)
    return starts


async def due_context_for_readings(
    db: AsyncSession,
    vin: str,
    pending: Sequence[Reminder],
    current_km: Decimal | None,
    current_hours: Decimal | None,
    today: date,
) -> DueContext:
    """The rates and starts for ``pending``, around readings the caller holds.

    A rate is fetched only when a reminder can use it (a usage target and a
    reading to project from), the gating ``count_pending_reminders`` always had.
    """
    km_per_day = (
        await calculate_driving_rate(vin, db)
        if current_km is not None and any(r.due_mileage_km is not None for r in pending)
        else None
    )
    hours_per_day = (
        await calculate_hours_driving_rate(vin, db)
        if current_hours is not None and any(r.due_hours is not None for r in pending)
        else None
    )
    return DueContext(
        today=today,
        current_km=current_km,
        current_hours=current_hours,
        km_per_day=km_per_day,
        hours_per_day=hours_per_day,
        starts=await load_reminder_starts(
            db, vin, pending, current_km=current_km, current_hours=current_hours
        ),
    )


async def load_due_context(
    db: AsyncSession, vin: str, pending: Sequence[Reminder], today: date
) -> DueContext:
    """``due_context_for_readings`` with the current readings fetched here.

    Each reading is fetched only when a reminder has that target. They are the
    readings the hero shows (``get_current_mileage`` orders like
    ``latest_odometer_km_and_date``; ``get_current_hours`` delegates to the
    canonical hours helper), so the list and the badges see the same numbers.
    """
    current_km = (
        await get_current_mileage(vin, db)
        if any(r.due_mileage_km is not None for r in pending)
        else None
    )
    current_hours = (
        await get_current_hours(vin, db) if any(r.due_hours is not None for r in pending) else None
    )
    return await due_context_for_readings(db, vin, pending, current_km, current_hours, today)


async def count_pending_reminders(
    db: AsyncSession,
    vin: str,
    current_km: Decimal | None,
    current_hours: Decimal | None,
    today: date | None = None,
) -> ReminderCounts:
    """``classify_pending_reminders`` over the vehicle's pending reminders.

    The usage rates are fetched only when a reminder can use one (a usage
    target and a reading to project from). The dashboard card, the fleet
    strip and the detail hero all count through here, so their badges agree;
    callers pass the readings they display, so a reading and the counts
    beside it never disagree. Unanchored reminders get their starts, so the
    D2 fallback counts here exactly as the list row shows it.
    """
    if today is None:
        today = household_today()
    pending = (
        (
            await db.execute(
                select(Reminder).where(Reminder.vin == vin, Reminder.status == "pending")
            )
        )
        .scalars()
        .all()
    )
    ctx = await due_context_for_readings(db, vin, pending, current_km, current_hours, today)
    return tally_due_statuses(pending, ctx)


async def _validate_line_item_vin(line_item_id: int, vin: str, db: AsyncSession) -> None:
    """Verify a line_item belongs to a service visit for this VIN."""
    result = await db.execute(
        select(ServiceLineItem.id)
        .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
        .where(ServiceLineItem.id == line_item_id)
        .where(ServiceVisit.vin == vin)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Line item {line_item_id} does not belong to vehicle {vin}",
        )


async def _get_reminder_or_404(reminder_id: int, vin: str, db: AsyncSession) -> Reminder:
    """Fetch a reminder scoped by vin, or 404."""
    result = await db.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.vin == vin)
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


async def create_reminder(
    vin: str,
    data: ReminderCreate,
    db: AsyncSession,
    line_item_id: int | None = None,
) -> Reminder:
    """Create a ONE-OFF reminder from the client's thresholds.

    A reminder with a ``recurrence`` goes through
    ``maintenance_service.create_recurring_reminder`` instead (the route
    branches); a line item's reminder through
    ``maintenance_service.create_reminder_for_line_item``, which anchors it
    on the visit. The type is stored so duplicates of the same maintenance
    are detectable even for a hand-made reminder. It stores both current
    readings as its start, so a reading added or corrected later can't move it.
    """
    if data.recurrence is not None:
        raise HTTPException(
            status_code=400, detail="A recurring reminder is created through the maintenance flow"
        )
    effective_line_item_id = line_item_id or data.line_item_id
    if effective_line_item_id:
        await _validate_line_item_vin(effective_line_item_id, vin, db)

    assert data.reminder_type is not None  # the schema requires it without a recurrence
    validate_reminder_state(data.reminder_type, data.due_date, data.due_mileage_km, data.due_hours)
    start_km, start_hours = await start_readings(db, vin)

    reminder = Reminder(
        vin=vin,
        line_item_id=effective_line_item_id,
        title=data.title,
        reminder_type=data.reminder_type,
        due_date=data.due_date,
        due_mileage_km=data.due_mileage_km,
        due_hours=data.due_hours,
        notes=data.notes,
        maintenance_type=data.maintenance_type or classify(data.title),
        start_odometer_km=start_km,
        start_hours=start_hours,
    )
    db.add(reminder)
    return reminder


async def update_reminder(reminder: Reminder, data: ReminderUpdate, db: AsyncSession) -> Reminder:
    """Merge patch onto existing reminder using model_fields_set.

    Validates the final merged state before persisting. A reminder with an
    ACTIVE rule derives its thresholds from the rule and its anchor, so the
    ``due_*`` fields are a 422 for it; the recurrence and type parts of the
    patch are applied by ``maintenance_service.update_reminder_recurrence``.
    """
    from app.services.maintenance_service import update_reminder_recurrence

    set_fields = data.model_fields_set
    rule = reminder.rule
    rule_active = rule is not None and rule.is_active
    stops_recurring = "recurrence" in set_fields and data.recurrence is None
    if rule_active and not stops_recurring:
        derived = {"due_date", "due_mileage_km", "due_hours", "reminder_type"} & set_fields
        if derived:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This reminder's due values are derived from its maintenance rule; "
                    "edit the recurrence intervals instead of " + ", ".join(sorted(derived))
                ),
            )

    final_type = (
        str(data.reminder_type)
        if "reminder_type" in set_fields and data.reminder_type
        else reminder.reminder_type
    )
    final_date = data.due_date if "due_date" in set_fields else reminder.due_date
    final_km = data.due_mileage_km if "due_mileage_km" in set_fields else reminder.due_mileage_km
    final_hours = data.due_hours if "due_hours" in set_fields else reminder.due_hours

    try:
        validate_reminder_state(final_type, final_date, final_km, final_hours)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if "title" in set_fields:
        reminder.title = data.title  # type: ignore[assignment]
    if "reminder_type" in set_fields:
        reminder.reminder_type = final_type  # type: ignore[assignment]
    if "due_date" in set_fields:
        reminder.due_date = final_date
    if "due_mileage_km" in set_fields:
        reminder.due_mileage_km = final_km
    if "due_hours" in set_fields:
        reminder.due_hours = final_hours
    if "notes" in set_fields:
        reminder.notes = data.notes

    await update_reminder_recurrence(db, reminder, data)
    return reminder


async def enrich_with_estimate(
    reminder: Reminder, db: AsyncSession, ctx: DueContext | None = None
) -> ReminderResponse:
    """Build ReminderResponse with the projection and due status of a pending reminder.

    Any pending reminder with a mileage or hours target and a usage rate gets
    ``projected_usage_date``, the uncapped date the target is reached at the
    current rate, and ``estimated_due_date``, the earlier of that projection
    and the calendar threshold. The two are separate fields on purpose: a
    slow driver's projection may sit months past the calendar threshold, and
    the threshold is the one that fires.

    A reminder with both targets (legacy ``both``-typed rows can only carry
    mileage; a rule never produces both) projects from the mileage.

    #192 adds where it stands: ``due_status``, ``progress`` and its basis, and
    what is left by date, distance and hours. ``list_reminders`` passes one
    ``ctx`` for the whole vehicle. Any other caller leaves it out, and the
    readings, rates and start are fetched for this reminder alone, so a row a
    write returns keeps its colour until the list refetches.
    """
    response = ReminderResponse.model_validate(reminder)
    if reminder.status != "pending":
        return response
    if ctx is None:
        ctx = await load_due_context(db, reminder.vin, [reminder], household_today())
    projected = _projected(reminder, ctx)
    if projected is not None:
        response.projected_usage_date = projected
        response.estimated_due_date = expected_for(reminder, ctx)
    response.due_status = reminder_due_status(reminder, ctx)
    leading = leading_progress(progress_fractions(reminder, ctx))
    if leading is not None:
        response.progress_basis, response.progress = leading
    if reminder.due_date is not None:
        response.days_until_due = (reminder.due_date - ctx.today).days
    if reminder.due_mileage_km is not None and ctx.current_km is not None:
        response.km_until_due = reminder.due_mileage_km - ctx.current_km
    if reminder.due_hours is not None and ctx.current_hours is not None:
        response.hours_until_due = reminder.due_hours - ctx.current_hours
    return response


async def enrich_reminders(
    reminders: Sequence[Reminder], db: AsyncSession
) -> list[ReminderResponse]:
    """``enrich_with_estimate`` over several reminders, in their order, on one
    context per vehicle (#192 D6).

    The readings, rates and starts are fetched once for each vehicle's pending
    reminders, not once per row, and every row reads the same ``today``.
    """
    today = household_today()
    contexts: dict[str, DueContext] = {}
    for vin in dict.fromkeys(r.vin for r in reminders):
        pending = [r for r in reminders if r.vin == vin and r.status == "pending"]
        contexts[vin] = await load_due_context(db, vin, pending, today)
    return [await enrich_with_estimate(r, db, contexts[r.vin]) for r in reminders]


#: Pending rows sort by this rank first (#192 D5).
_STATUS_RANK: dict[DueStatus, int] = {"overdue": 0, "due_soon": 1, "on_track": 2, "snoozed": 3}


def _due_order_key(response: ReminderResponse) -> tuple[int, date, float, int]:
    """Status rank, then the expected date (undated last), then progress (most
    first, none last), then id. ``estimated_due_date`` is set only when a
    projection exists, and is then the earlier of it and ``due_date``, so this
    pair is exactly ``expected_due_date``."""
    expected = response.estimated_due_date or response.due_date
    progress = response.progress
    return (
        _STATUS_RANK[response.due_status or "on_track"],
        expected or date.max,
        -progress if progress is not None else math.inf,
        response.id,
    )


def _history_key(response: ReminderResponse) -> tuple[date, datetime, int]:
    """When a closed reminder was closed: its completion date, else its last update.

    ``completed_date`` is a household day, so the fallback is converted to one
    too; a raw UTC date would put a row updated late in the evening west of UTC
    on the next day (Codex R1-M1).
    """
    return (
        response.completed_date or household_date(response.updated_at),
        response.updated_at,
        response.id,
    )


def order_reminders(responses: Sequence[ReminderResponse]) -> list[ReminderResponse]:
    """Pending first, by how soon each is due; then done and dismissed, newest first (#192 D5)."""
    pending = sorted((r for r in responses if r.status == "pending"), key=_due_order_key)
    closed = sorted((r for r in responses if r.status != "pending"), key=_history_key, reverse=True)
    return [*pending, *closed]


async def list_reminders(
    vin: str, db: AsyncSession, status: str | None = None
) -> list[ReminderResponse]:
    """List a vehicle's reminders, optionally filtered by status, in ``order_reminders`` order.

    The readings, rates and starts are fetched once for the vehicle's pending
    reminders (#192 D6), not once per row.
    """
    query = select(Reminder).where(Reminder.vin == vin)
    if status and status != "all":
        query = query.where(Reminder.status == status)
    reminders = list((await db.execute(query)).scalars().all())
    return order_reminders(await enrich_reminders(reminders, db))


class ReminderMessageSource(Protocol):
    """What `_build_reminder_message` reads. The ORM `Reminder` satisfies it,
    and so does the sweep's plain-value `_DueNotification`."""

    @property
    def title(self) -> str: ...
    @property
    def due_date(self) -> date | None: ...
    @property
    def due_mileage_km(self) -> Decimal | None: ...
    @property
    def due_hours(self) -> Decimal | None: ...
    @property
    def notes(self) -> str | None: ...
    @property
    def tread_depth_mm(self) -> Decimal | None: ...
    @property
    def tread_threshold_mm(self) -> Decimal | None: ...


#: The two events the sweep sends, each behind its own switch in Settings.
DueEvent = Literal["service_due", "service_overdue"]

_DUE_TITLES: dict[DueEvent, str] = {
    "service_due": "Reminder due soon: {title}",
    "service_overdue": "Reminder overdue: {title}",
}


@dataclass(frozen=True)
class _DueNotification:
    """A reminder the sweep decided to send, copied out as plain values.

    The send phase may have to roll the session back, which expires every
    loaded ORM object, so nothing after the checks reads a `Reminder`. The due
    values and `last_notified_at` double as the snapshot the stamp is
    conditional on.
    """

    id: int
    vin: str
    event: DueEvent
    title: str
    due_date: date | None
    due_mileage_km: Decimal | None
    due_hours: Decimal | None
    notes: str | None
    tread_depth_mm: Decimal | None
    tread_threshold_mm: Decimal | None
    last_notified_at: datetime | None

    @classmethod
    def of(cls, reminder: Reminder, event: DueEvent) -> _DueNotification:
        """Copy what the send, its log lines and its stamp need from a loaded reminder."""
        return cls(
            id=reminder.id,
            vin=reminder.vin,
            event=event,
            title=reminder.title,
            due_date=reminder.due_date,
            due_mileage_km=reminder.due_mileage_km,
            due_hours=reminder.due_hours,
            notes=reminder.notes,
            tread_depth_mm=reminder.tread_depth_mm,
            tread_threshold_mm=reminder.tread_threshold_mm,
            last_notified_at=reminder.last_notified_at,
        )


def _due_event(reminder: Reminder, status: DueStatus, now: datetime) -> DueEvent | None:
    """What the sweep sends for a reminder in ``status``, if anything (D2a).

    Overdue goes daily: the next sweep after a stamp at least 23 h old (the
    cooldown less its slack). Due soon goes once: any stamp holds it back, and
    a due-value change clears the stamp (`Reminder._rearm_heads_up`). Snoozed
    and on track send nothing and leave the stamp alone, so an overdue
    reminder whose snooze ends notifies the next morning. One that comes back
    still due soon stays quiet if it already had its heads-up.
    """
    if status == "overdue":
        # The column is naive (SQLite drops tzinfo on write), so re-attach UTC
        # before comparing with the aware `now`, or the subtraction raises.
        last = reminder.last_notified_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if in_cooldown(last, now):
            return None
        return "service_overdue"
    if status == "due_soon" and reminder.last_notified_at is None:
        return "service_due"
    return None


async def check_due_reminders(db: AsyncSession) -> None:
    """Scheduler entry point: notify for the pending reminders that are due.

    Each vehicle's reminders are judged by `reminder_due_status` on one
    `DueContext`, the rule the reminders list and the badges use. Archived
    vehicles are skipped. Overdue sends `service_overdue`, due soon sends
    `service_due`, each behind its own switch (`EVENT_SETTINGS_MAP`).

    Three phases: check, commit, send. Then a stamp for each delivered
    notification, only while the row still holds the values it was sent for.
    """
    from app.services.notifications.dispatcher import NotificationDispatcher

    now = datetime.now(UTC)
    today = household_today()

    pending = (
        (
            await db.execute(
                select(Reminder)
                .join(Vehicle, Vehicle.vin == Reminder.vin)
                .where(Reminder.status == "pending", Vehicle.archived_at.is_(None))
                .order_by(Reminder.vin, Reminder.id)
            )
        )
        .scalars()
        .all()
    )
    by_vin: dict[str, list[Reminder]] = {}
    for reminder in pending:
        by_vin.setdefault(reminder.vin, []).append(reminder)

    dispatcher = NotificationDispatcher(db)
    due: list[_DueNotification] = []

    for vin, reminders in by_vin.items():
        # Read before the savepoint: if it rolls back, whatever it changed comes
        # back expired, and reading that in async raises MissingGreenlet.
        reminder_ids = [r.id for r in reminders]
        found: list[_DueNotification] = []
        try:
            # Its own savepoint, so a vehicle whose readings fail to load rolls
            # back alone. Without it PostgreSQL keeps the transaction aborted
            # and every vehicle after it fails too.
            async with db.begin_nested():
                due_ctx = await load_due_context(db, vin, reminders, today)
                for reminder, reminder_id in zip(reminders, reminder_ids, strict=True):
                    # No savepoint here: judging a reminder runs no SQL.
                    try:
                        event = _due_event(reminder, reminder_due_status(reminder, due_ctx), now)
                    except Exception:
                        logger.exception("Reminder %s check failed", reminder_id)
                        continue
                    if event is not None:
                        found.append(_DueNotification.of(reminder, event))
        except Exception:
            logger.exception("Reminder check failed for vehicle %s", sanitize_for_log(vin))
            continue
        due.extend(found)

    # End the checking transaction before anything goes out. On SQLite a
    # rolled-back savepoint is never released, so the transaction would stay
    # open on its old read snapshot, and the stamps written in it fail with
    # "database is locked" once anyone else has committed in the meantime.
    await db.commit()

    sent: list[_DueNotification] = []
    for item in due:
        try:
            # No caller: a scheduled job renders in the VEHICLE OWNER's units
            # (render_context_for_vehicle), which falls back to the instance
            # default for an ownerless vehicle. Resolved here, for the ones
            # going out, so a sweep that sends nothing costs no extra queries.
            render_ctx = await render_context_for_vehicle(db, item.vin)
            results = await dispatcher.dispatch(
                event_type=item.event,
                title=_DUE_TITLES[item.event].format(title=item.title),
                message=_build_reminder_message(item, render_ctx),
            )
        except Exception as e:
            logger.error(
                "Failed to send reminder notification %s: %s",
                item.id,
                sanitize_for_log(e),
            )
            if isinstance(e, SQLAlchemyError):
                # A failed statement leaves PostgreSQL's transaction aborted.
                # Start clean so the rest still send and get stamped.
                await db.rollback()
            continue
        # Stamped only when something got it. `{}` is the switch off or no
        # provider set up, and all False is every provider failing: left
        # unstamped, the next sweep tries again. One provider is enough.
        if not results:
            logger.info(
                "Reminder notification %s (%s) not delivered: switched off or no provider configured",
                item.id,
                item.event,
            )
            continue
        if not any(results.values()):
            logger.info(
                "Reminder notification %s (%s) not delivered: every provider failed: %s",
                item.id,
                item.event,
                sorted(results),
            )
            continue
        sent.append(item)
        logger.info(
            "Sent %s notification for reminder %s (vin=%s)",
            item.event,
            item.id,
            sanitize_for_log(item.vin),
        )

    # Stamped once every send is done: a write any earlier would hold SQLite's
    # write lock through the remaining backend calls. By id, because nothing
    # after the checks touches a loaded reminder (see `_DueNotification`), and
    # only while the row is as it was sent: an edit committed meanwhile has
    # cleared the stamp for its new target and keeps it clear.
    #
    # `last_notified_at` is DateTime with no timezone (models/reminder.py).
    # PostgreSQL rejects an aware value for a naive column with asyncpg
    # DataError; SQLite accepts it and strips the offset on the way back out,
    # which is why this never showed on a dev instance. `now` itself stays
    # aware because the cooldown comparison above needs it. The snapshot is
    # compared as it was loaded, naive.
    stamp = now.replace(tzinfo=None)
    for item in sent:
        try:
            # Its own savepoint, so one failed stamp leaves PostgreSQL's
            # transaction usable for the rest and for the commit.
            async with db.begin_nested():
                result = await db.execute(
                    update(Reminder)
                    .where(
                        Reminder.id == item.id,
                        Reminder.status == "pending",
                        Reminder.due_date.is_not_distinct_from(item.due_date),
                        Reminder.due_mileage_km.is_not_distinct_from(item.due_mileage_km),
                        Reminder.due_hours.is_not_distinct_from(item.due_hours),
                        Reminder.last_notified_at.is_not_distinct_from(item.last_notified_at),
                    )
                    .values(last_notified_at=stamp)
                )
        except SQLAlchemyError as e:
            logger.error("Failed to stamp reminder %s: %s", item.id, sanitize_for_log(e))
            continue
        if not cast(CursorResult[Any], result).rowcount:
            # An edit or a close during the send is expected now and then. The
            # same id here every day means the snapshot never matches.
            logger.warning(
                "Reminder %s not stamped: row no longer matches the sent values", item.id
            )
    await db.commit()


def _build_reminder_message(reminder: ReminderMessageSource, ctx: RenderContext) -> str:
    """Build the notification message for a due reminder, rendered in ``ctx``.

    Four kinds of content, four deliberately different treatments:

    - ``due_mileage_km`` is canonical km and renders in ``ctx``'s distance
      unit, gaining a parenthetical counterpart when ``ctx.show_both``.
    - ``due_hours`` is dimensionless (R6): ``"hours"`` is not a ``UnitSet``
      quantity, so it keeps ``format_hours``'s fixed ``hr`` label, the same
      helper the vehicle PDF renders this field with.
    - ``notes`` is stored prose, passed through byte-identically (see below).
      A low-tread reminder's tread is a fourth kind: its own columns, rendered
      in ``ctx``'s tread unit.

    ``ctx`` is supplied by the caller rather than resolved here, so this stays
    pure and synchronous and can be unit-tested against any unit set.
    """
    parts = [f"Service reminder: {reminder.title}"]
    if reminder.due_date:
        parts.append(f"Due date: {reminder.due_date.isoformat()}")
    if reminder.due_mileage_km:
        parts.append(f"Due mileage: {format_quantity(reminder.due_mileage_km, ctx, 'distance')}")
    if reminder.due_hours:
        parts.append(f"Due hours: {format_hours(reminder.due_hours)}")
    if reminder.tread_depth_mm is not None and reminder.tread_threshold_mm is not None:
        parts.append(
            f"Tread: {format_quantity(reminder.tread_depth_mm, ctx, 'tread')}"
            f", minimum {format_quantity(reminder.tread_threshold_mm, ctx, 'tread')}"
        )
    if reminder.notes:
        # Stored prose passes through byte-identically. A low-tread reminder's
        # tread renders above from its own columns (G3a-21), never from here.
        parts.append(f"Notes: {reminder.notes}")
    return "\n".join(parts)
