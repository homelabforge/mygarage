"""Reminder business logic service layer."""

import logging
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.schemas.reminder import ReminderCreate, ReminderResponse, ReminderUpdate
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

# Notification dedup cooldown (24 hours)
NOTIFICATION_COOLDOWN = timedelta(hours=24)


def validate_reminder_state(
    reminder_type: str, due_date: date | None, due_mileage: int | None
) -> None:
    """Shared validation for both create and the final merged state on update.

    Raises ValueError if the combination is invalid for reminder_type.
    """
    if reminder_type in ("date", "both", "smart") and not due_date:
        raise ValueError("due_date required for this reminder type")
    if reminder_type in ("mileage", "both", "smart") and not due_mileage:
        raise ValueError("due_mileage required for this reminder type")


async def calculate_driving_rate(vin: str, db: AsyncSession) -> float | None:
    """Calculate average miles/day from last 90 days of OdometerRecord.

    Returns None if fewer than 2 records in the window.
    """
    cutoff = date.today() - timedelta(days=90)
    result = await db.execute(
        select(
            func.min(OdometerRecord.mileage),
            func.max(OdometerRecord.mileage),
            func.min(OdometerRecord.date),
            func.max(OdometerRecord.date),
            func.count(OdometerRecord.id),
        )
        .where(OdometerRecord.vin == vin)
        .where(OdometerRecord.date >= cutoff)
    )
    row = result.one()
    min_miles, max_miles, min_date, max_date, count = row

    if count < 2 or min_date == max_date:
        return None

    days_span = (max_date - min_date).days
    if days_span <= 0:
        return None

    return (max_miles - min_miles) / days_span


async def get_current_mileage(vin: str, db: AsyncSession) -> int | None:
    """Get the most recent odometer reading for a vehicle."""
    result = await db.execute(
        select(OdometerRecord.mileage)
        .where(OdometerRecord.vin == vin)
        .order_by(OdometerRecord.date.desc(), OdometerRecord.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


def calculate_smart_estimated_date(
    current_mileage: int,
    target_mileage: int,
    avg_miles_per_day: float,
    hard_date: date,
) -> date:
    """Estimate when mileage target will be hit. Never later than hard_date."""
    if target_mileage <= current_mileage:
        return date.today()
    days = (target_mileage - current_mileage) / avg_miles_per_day
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

    validate_reminder_state(data.reminder_type, data.due_date, data.due_mileage)

    reminder = Reminder(
        vin=vin,
        line_item_id=effective_line_item_id,
        title=data.title,
        reminder_type=data.reminder_type,
        due_date=data.due_date,
        due_mileage=data.due_mileage,
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
    final_miles = data.due_mileage if "due_mileage" in set_fields else reminder.due_mileage

    try:
        validate_reminder_state(final_type, final_date, final_miles)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if "title" in set_fields:
        reminder.title = data.title  # type: ignore[assignment]
    if "reminder_type" in set_fields:
        reminder.reminder_type = final_type  # type: ignore[assignment]
    if "due_date" in set_fields:
        reminder.due_date = final_date
    if "due_mileage" in set_fields:
        reminder.due_mileage = final_miles
    if "notes" in set_fields:
        reminder.notes = data.notes

    return reminder


async def enrich_with_estimate(reminder: Reminder, db: AsyncSession) -> ReminderResponse:
    """Build ReminderResponse, computing estimated_due_date for smart type."""
    response = ReminderResponse.model_validate(reminder)
    if reminder.reminder_type == "smart" and reminder.status == "pending":
        rate = await calculate_driving_rate(reminder.vin, db)
        current = await get_current_mileage(reminder.vin, db)
        if rate and current and reminder.due_mileage and reminder.due_date:
            response.estimated_due_date = calculate_smart_estimated_date(
                current, reminder.due_mileage, rate, reminder.due_date
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
        # Dedup check
        if reminder.last_notified_at and (now - reminder.last_notified_at) < NOTIFICATION_COOLDOWN:
            continue

        should_notify = False

        # Date-based check
        if reminder.reminder_type in ("date", "both") and reminder.due_date:
            if reminder.due_date <= today:
                should_notify = True

        # Mileage-based check
        if reminder.reminder_type in ("mileage", "both") and reminder.due_mileage:
            current = await get_current_mileage(reminder.vin, db)
            if current and current >= reminder.due_mileage:
                should_notify = True

        # Smart: check estimated date or mileage
        if reminder.reminder_type == "smart":
            # Check mileage
            if reminder.due_mileage:
                current = await get_current_mileage(reminder.vin, db)
                if current and current >= reminder.due_mileage:
                    should_notify = True

            # Check date (hard cap)
            if reminder.due_date and reminder.due_date <= today:
                should_notify = True

            # Check estimated date (within 7 days)
            if not should_notify and reminder.due_mileage and reminder.due_date:
                rate = await calculate_driving_rate(reminder.vin, db)
                current = await get_current_mileage(reminder.vin, db)
                if rate and current:
                    est = calculate_smart_estimated_date(
                        current, reminder.due_mileage, rate, reminder.due_date
                    )
                    if (est - today).days <= 7:
                        should_notify = True

        if should_notify:
            try:
                await dispatcher.dispatch(
                    event_type="reminder_due",
                    title=f"Reminder Due: {reminder.title}",
                    message=_build_reminder_message(reminder),
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


def _build_reminder_message(reminder: Reminder) -> str:
    """Build notification message for a due reminder."""
    parts = [f"Service reminder: {reminder.title}"]
    if reminder.due_date:
        parts.append(f"Due date: {reminder.due_date.isoformat()}")
    if reminder.due_mileage:
        parts.append(f"Due mileage: {reminder.due_mileage:,} mi")
    if reminder.notes:
        parts.append(f"Notes: {reminder.notes}")
    return "\n".join(parts)
