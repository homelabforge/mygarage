"""Reminder business logic service layer."""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.schemas.reminder import ReminderCreate, ReminderResponse, ReminderUpdate
from app.services.hours_service import latest_engine_hours_and_date
from app.utils.hours_formatting import format_hours
from app.utils.logging_utils import sanitize_for_log
from app.utils.render_context import RenderContext, render_context_for_vehicle
from app.utils.unit_formatting import format_quantity

logger = logging.getLogger(__name__)

# Notification dedup cooldown (24 hours)
NOTIFICATION_COOLDOWN = timedelta(hours=24)


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
    cutoff = date.today() - timedelta(days=90)
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
    """Get the most recent odometer reading (km) for a vehicle."""
    result = await db.execute(
        select(OdometerRecord.odometer_km)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
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
    cutoff = date.today() - timedelta(days=90)
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
            ``date.today()``.

    Returns:
        ``True`` if the reminder is overdue by date, mileage, or hours.
    """
    if today is None:
        today = date.today()
    if reminder.due_date and reminder.due_date <= today:
        return True
    if reminder.due_mileage_km and current_km and current_km >= reminder.due_mileage_km:
        return True
    if reminder.due_hours and current_hours and current_hours >= reminder.due_hours:
        return True
    return False


def calculate_smart_estimated_date(
    current_odometer_km: Decimal,
    target_odometer_km: Decimal,
    avg_km_per_day: float,
    hard_date: date,
) -> date:
    """Estimate when km target will be hit. Never later than hard_date."""
    if target_odometer_km <= current_odometer_km:
        return date.today()
    days = float(target_odometer_km - current_odometer_km) / avg_km_per_day
    estimated = date.today() + timedelta(days=days)
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
    """Create a reminder. Used both from routes and inline from service_visit_service."""
    effective_line_item_id = line_item_id or data.line_item_id
    if effective_line_item_id:
        await _validate_line_item_vin(effective_line_item_id, vin, db)

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
    )
    db.add(reminder)
    return reminder


async def update_reminder(reminder: Reminder, data: ReminderUpdate, db: AsyncSession) -> Reminder:
    """Merge patch onto existing reminder using model_fields_set.

    Validates the final merged state before persisting.
    """
    set_fields = data.model_fields_set

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

    return reminder


async def enrich_with_estimate(reminder: Reminder, db: AsyncSession) -> ReminderResponse:
    """Build ReminderResponse, computing estimated_due_date for smart type.

    A smart reminder targets exactly one of ``due_mileage_km``/``due_hours``
    (enforced by ``validate_reminder_state``); branch on which is set and
    project from the matching accumulation rate (km/day or hours/day), both
    fed through the same ``calculate_smart_estimated_date`` formula.
    """
    response = ReminderResponse.model_validate(reminder)
    if reminder.reminder_type == "smart" and reminder.status == "pending":
        rate: float | None = None
        current: Decimal | None = None
        target: Decimal | None = None
        if reminder.due_mileage_km is not None:
            rate = await calculate_driving_rate(reminder.vin, db)
            current = await get_current_mileage(reminder.vin, db)
            target = reminder.due_mileage_km
        elif reminder.due_hours is not None:
            rate = await calculate_hours_driving_rate(reminder.vin, db)
            current = await get_current_hours(reminder.vin, db)
            target = reminder.due_hours
        if rate and current and target and reminder.due_date:
            response.estimated_due_date = calculate_smart_estimated_date(
                current, target, rate, reminder.due_date
            )
    return response


async def list_reminders(
    vin: str, db: AsyncSession, status: str | None = None
) -> list[ReminderResponse]:
    """List reminders for a vehicle, optionally filtered by status."""
    query = select(Reminder).where(Reminder.vin == vin)
    if status and status != "all":
        query = query.where(Reminder.status == status)
    query = query.order_by(Reminder.created_at.desc())

    result = await db.execute(query)
    reminders = result.scalars().all()

    responses = []
    for r in reminders:
        responses.append(await enrich_with_estimate(r, db))
    return responses


async def check_due_reminders(db: AsyncSession) -> None:
    """Scheduler entry point. Check pending reminders and send notifications.

    Dedup: skip if last_notified_at < 24h ago.
    """
    from app.services.notifications.dispatcher import NotificationDispatcher

    now = datetime.now(UTC)
    today = date.today()

    # Get all pending reminders
    result = await db.execute(select(Reminder).where(Reminder.status == "pending"))
    reminders = result.scalars().all()

    dispatcher = NotificationDispatcher(db)

    for reminder in reminders:
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
                reminder.last_notified_at = now
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
