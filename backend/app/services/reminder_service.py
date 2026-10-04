"""Reminder business logic service layer."""

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
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
from app.utils.render_context import RenderContext, render_context_for_vehicle
from app.utils.unit_formatting import format_quantity

logger = logging.getLogger(__name__)

# Notification dedup cooldown (24 hours)
NOTIFICATION_COOLDOWN = timedelta(hours=24)

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
    unanchored reminder the household day it was created and the readings
    nearest that day."""

    day: date | None
    km: Decimal | None
    hours: Decimal | None


@dataclass(frozen=True)
class DueContext:
    """One vehicle's readings and rates on one day, plus the derived starts of
    its unanchored reminders by id. Built once per list or count, so every row
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
    """The reminder's anchor, else the start ``ctx`` derived for it."""
    return anchor_start(reminder) or ctx.starts.get(reminder.id)


def progress_fractions(reminder: Reminder, ctx: DueContext) -> dict[ProgressBasis, float]:
    """Elapsed over span for each dimension the reminder has (#192 D3), counted
    from ``reminder_start``.

    A dimension is left out when its start, its current reading or a positive
    span is missing. Unclamped both ways: past due reads above 1, and a reading
    below the start (a typo, or a nearest reading taken after creation) reads
    below 0. The bar clamps; the sort doesn't need to.
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


def _expected(reminder: Reminder, ctx: DueContext) -> date | None:
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
    expected = _expected(reminder, ctx)
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
    derived start here, so a usage reminder is then due soon only through its
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


async def load_reminder_starts(
    db: AsyncSession, vin: str, reminders: Sequence[Reminder]
) -> dict[int, ReminderStart]:
    """Derived starts for the unanchored reminders among ``reminders``, by id (#192 D4).

    Such a reminder counts from the household day it was created, with the
    odometer and hours readings nearest that day. Each reading is looked up
    only for a target the reminder has, and once per day, so these lookups
    (two queries each) grow with the number of distinct creation days, not
    with the rows; the rates and current readings are once per list. Nothing is stored:
    loose pending reminders are adoption candidates, and a stored anchor would
    change what rule adoption (``_pick_keeper``) and ``reconcile_rule`` do.
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
            if day not in km_on:
                record = await nearest_odometer(db, vin, day)
                km_on[day] = record.odometer_km if record is not None else None
            km = km_on[day]
        hours: Decimal | None = None
        if reminder.due_hours is not None:
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
        starts=await load_reminder_starts(db, vin, pending),
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
    beside it never disagree. Unanchored reminders get derived starts, so the
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


def calculate_smart_estimated_date(
    current_odometer_km: Decimal,
    target_odometer_km: Decimal,
    avg_km_per_day: float,
    hard_date: date,
) -> date:
    """Estimate when km target will be hit. Never later than hard_date."""
    if target_odometer_km <= current_odometer_km:
        return household_today()
    days = float(target_odometer_km - current_odometer_km) / avg_km_per_day
    estimated = household_today() + timedelta(days=days)
    return min(estimated, hard_date)


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
    are detectable even for a hand-made reminder.
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
    and the calendar threshold (which is what ``calculate_smart_estimated_date``
    always computed for ``smart``). The two are separate fields on purpose: a
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
        response.estimated_due_date = _expected(reminder, ctx)
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
    # The response order is order_reminders'. This one is for duplicate_map, which
    # lists each row's siblings in the order it meets them.
    query = query.order_by(Reminder.created_at.desc())
    reminders = list((await db.execute(query)).scalars().all())

    # Duplicates are judged over PENDING reminders only, so a done-tab listing
    # carries no flags and a pending-tab listing sees every sibling.
    from app.services.maintenance_service import duplicate_map

    duplicates = duplicate_map([r for r in reminders if r.status == "pending"])
    responses = await enrich_reminders(reminders, db)
    for response in responses:
        response.duplicate_of = duplicates.get(response.id, [])
    return order_reminders(responses)


async def check_due_reminders(db: AsyncSession) -> None:
    """Scheduler entry point. Check pending reminders and send notifications.

    Dedup: skip if last_notified_at < 24h ago.
    """
    from app.services.notifications.dispatcher import NotificationDispatcher

    now = datetime.now(UTC)
    today = household_today()

    # Get all pending reminders
    result = await db.execute(select(Reminder).where(Reminder.status == "pending"))
    reminders = result.scalars().all()

    dispatcher = NotificationDispatcher(db)

    for reminder in reminders:
        if is_reminder_snoozed(reminder, today):
            # Snoozed: no notification whatever the thresholds say, and no
            # cooldown stamp either, so the day the snooze expires the very
            # next run notifies (plan 2026-09-18, feature A).
            continue

        # Dedup check. Reminder.last_notified_at is a plain (non-tz-aware)
        # DateTime column — SQLite's bind processor silently drops tzinfo on
        # write, so a value round-tripped through the DB comes back naive
        # even though it was always written as UTC. Re-attach UTC before
        # comparing against the aware `now`, or a naive/aware subtraction
        # raises TypeError on the very next scheduler tick after a reminder
        # has ever been notified once.
        last_notified_at = reminder.last_notified_at
        if last_notified_at is not None and last_notified_at.tzinfo is None:
            last_notified_at = last_notified_at.replace(tzinfo=UTC)
        if last_notified_at and (now - last_notified_at) < NOTIFICATION_COOLDOWN:
            continue

        should_notify = False

        # Date-based check
        if reminder.reminder_type in ("date", "both") and reminder.due_date:
            if reminder.due_date <= today:
                should_notify = True

        # Mileage-based check
        if reminder.reminder_type in ("mileage", "both") and reminder.due_mileage_km:
            latest_odometer_km = await get_current_mileage(reminder.vin, db)
            if latest_odometer_km and latest_odometer_km >= reminder.due_mileage_km:
                should_notify = True

        # Hours-based check
        if reminder.reminder_type == "hours" and reminder.due_hours:
            current_hours = await get_current_hours(reminder.vin, db)
            if current_hours and current_hours >= reminder.due_hours:
                should_notify = True

        # Smart: check estimated date or the tracked usage target (exactly
        # one of due_mileage_km/due_hours is set — validate_reminder_state).
        if reminder.reminder_type == "smart":
            # Check mileage
            if reminder.due_mileage_km:
                latest_odometer_km = await get_current_mileage(reminder.vin, db)
                if latest_odometer_km and latest_odometer_km >= reminder.due_mileage_km:
                    should_notify = True

            # Check hours
            if reminder.due_hours:
                current_hours = await get_current_hours(reminder.vin, db)
                if current_hours and current_hours >= reminder.due_hours:
                    should_notify = True

            # Check date (hard cap)
            if reminder.due_date and reminder.due_date <= today:
                should_notify = True

            # Check estimated date (within 7 days), branching on whichever
            # target is set.
            if not should_notify and reminder.due_date:
                rate: float | None = None
                current: Decimal | None = None
                target: Decimal | None = None
                if reminder.due_mileage_km:
                    rate = await calculate_driving_rate(reminder.vin, db)
                    current = await get_current_mileage(reminder.vin, db)
                    target = reminder.due_mileage_km
                elif reminder.due_hours:
                    rate = await calculate_hours_driving_rate(reminder.vin, db)
                    current = await get_current_hours(reminder.vin, db)
                    target = reminder.due_hours
                if rate and current and target:
                    est = calculate_smart_estimated_date(current, target, rate, reminder.due_date)
                    if (est - today).days <= 7:
                        should_notify = True

        if should_notify:
            try:
                # No caller: a scheduled job renders in the VEHICLE OWNER's
                # units (render_context_for_vehicle), which falls back to the
                # instance default for an ownerless vehicle. Resolved here,
                # inside the notify branch, so a sweep over pending reminders
                # that sends nothing costs no extra queries.
                ctx = await render_context_for_vehicle(db, reminder.vin)
                await dispatcher.dispatch(
                    event_type="reminder_due",
                    title=f"Reminder Due: {reminder.title}",
                    message=_build_reminder_message(reminder, ctx),
                )
                # `last_notified_at` is DateTime with no timezone
                # (models/reminder.py:40). PostgreSQL rejects an aware value
                # for a naive column with asyncpg DataError; SQLite accepts it
                # and strips the offset on the way back out, which is why this
                # never showed on a dev instance. `now` itself stays aware
                # because the cooldown comparison above needs it.
                reminder.last_notified_at = now.replace(tzinfo=None)
                logger.info(
                    "Sent reminder notification for reminder %s (vin=%s)",
                    reminder.id,
                    sanitize_for_log(reminder.vin),
                )
            except Exception as e:
                logger.error(
                    "Failed to send reminder notification %s: %s",
                    reminder.id,
                    sanitize_for_log(e),
                )

    await db.commit()


def _build_reminder_message(reminder: Reminder, ctx: RenderContext) -> str:
    """Build the notification message for a due reminder, rendered in ``ctx``.

    Three kinds of content, three deliberately different treatments:

    - ``due_mileage_km`` is canonical km and renders in ``ctx``'s distance
      unit, gaining a parenthetical counterpart when ``ctx.show_both``.
    - ``due_hours`` is dimensionless (R6): ``"hours"`` is not a ``UnitSet``
      quantity, so it keeps ``format_hours``'s fixed ``hr`` label, the same
      helper the vehicle PDF renders this field with.
    - ``notes`` is stored prose, passed through byte-identically (see below).

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
    if reminder.notes:
        # Byte-identical passthrough, deliberate and NOT an oversight.
        #
        # An auto-generated low-tread reminder (TireService._sync_low_tread_
        # reminder) stores due_mileage_km=None and puts its tread depth and
        # projected remaining distance ONLY in this prose, so there is nothing
        # in such a message for the conversion above to reach. Rewriting the
        # stored text here instead would persist display units: it would go
        # stale the moment the reader changed preferences and would never
        # refresh, because notes are written once at creation and the reminder
        # is completed only when tread recovers.
        #
        # Correct low-tread units are therefore a hard PREREQUISITE on the
        # tire workstream: migration A gains structured tread and distance
        # columns on vehicle_reminders (with an explicit legacy-row policy),
        # after which these values are rendered at read time from those
        # columns. Recorded in 2026-08-25-tire-mount-periods-design.md under
        # "Low-tread reminder units".
        parts.append(f"Notes: {reminder.notes}")
    return "\n".join(parts)
