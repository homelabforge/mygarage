"""Reminder routes for MyGarage API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Reminder, Vehicle
from app.models.user import User
from app.schemas.reminder import (
    ReminderCreate,
    ReminderListResponse,
    ReminderResponse,
    ReminderUpdate,
)
from app.services.auth import require_auth
from app.utils.datetime_utils import utc_now

router = APIRouter(prefix="/api/vehicles", tags=["reminders"])


@router.get("/{vin}/reminders", response_model=ReminderListResponse)
async def list_reminders(
    vin: str,
    include_completed: bool = False,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ReminderListResponse:
    """List all reminders for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Build query
    query = select(Reminder).where(Reminder.vin == vin)

    if not include_completed:
        query = query.where(Reminder.is_completed.is_(False))

    query = query.order_by(
        Reminder.due_date.asc().nullslast(), Reminder.due_mileage.asc().nullslast()
    )

    # Get reminders
    result = await db.execute(query)
    reminders = result.scalars().all()

    # Get counts
    total_result = await db.execute(
        select(func.count()).select_from(Reminder).where(Reminder.vin == vin)
    )
    total = total_result.scalar_one()

    active_result = await db.execute(
        select(func.count())
        .select_from(Reminder)
        .where(Reminder.vin == vin, Reminder.is_completed.is_(False))
    )
    active = active_result.scalar_one()

    completed = total - active

    return ReminderListResponse(
        reminders=[ReminderResponse.model_validate(r) for r in reminders],
        total=total,
        active=active,
        completed=completed,
    )


@router.post("/{vin}/reminders", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    vin: str,
    reminder_data: ReminderCreate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ReminderResponse:
    """Create a new reminder for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate that at least one due condition is set
    if not reminder_data.due_date and not reminder_data.due_mileage:
        raise HTTPException(
            status_code=400,
            detail="At least one due condition (date or mileage) must be set",
        )

    # Validate recurring settings
    if reminder_data.is_recurring:
        if not reminder_data.recurrence_days and not reminder_data.recurrence_miles:
            raise HTTPException(
                status_code=400,
                detail="Recurring reminders must have recurrence_days or recurrence_miles set",
            )

    # Create reminder
    reminder = Reminder(
        vin=vin,
        description=reminder_data.description,
        due_date=reminder_data.due_date,
        due_mileage=reminder_data.due_mileage,
        is_recurring=reminder_data.is_recurring,
        recurrence_days=reminder_data.recurrence_days,
        recurrence_miles=reminder_data.recurrence_miles,
        notes=reminder_data.notes,
    )

    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)

    return ReminderResponse.model_validate(reminder)


@router.get("/{vin}/reminders/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(
    vin: str,
    reminder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ReminderResponse:
    """Get a specific reminder."""
    result = await db.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.vin == vin)
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    return ReminderResponse.model_validate(reminder)


@router.put("/{vin}/reminders/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    vin: str,
    reminder_id: int,
    update_data: ReminderUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ReminderResponse:
    """Update a reminder."""
    # Get reminder
    result = await db.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.vin == vin)
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    # Update fields
    if update_data.description is not None:
        reminder.description = update_data.description
    if update_data.due_date is not None:
        reminder.due_date = update_data.due_date
    if update_data.due_mileage is not None:
        reminder.due_mileage = update_data.due_mileage
    if update_data.is_recurring is not None:
        reminder.is_recurring = update_data.is_recurring
    if update_data.recurrence_days is not None:
        reminder.recurrence_days = update_data.recurrence_days
    if update_data.recurrence_miles is not None:
        reminder.recurrence_miles = update_data.recurrence_miles
    if update_data.notes is not None:
        reminder.notes = update_data.notes

    # Handle completion status change
    if update_data.is_completed is not None:
        reminder.is_completed = update_data.is_completed
        if update_data.is_completed and not reminder.completed_at:
            reminder.completed_at = utc_now()
        elif not update_data.is_completed:
            reminder.completed_at = None

    await db.commit()
    await db.refresh(reminder)

    return ReminderResponse.model_validate(reminder)


@router.delete("/{vin}/reminders/{reminder_id}", status_code=204)
async def delete_reminder(
    vin: str,
    reminder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete a reminder."""
    # Get reminder
    result = await db.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.vin == vin)
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    await db.delete(reminder)
    await db.commit()


@router.post("/{vin}/reminders/{reminder_id}/complete", response_model=ReminderResponse)
async def complete_reminder(
    vin: str,
    reminder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ReminderResponse:
    """Mark a reminder as completed."""
    # Get reminder
    result = await db.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.vin == vin)
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    if reminder.is_completed:
        raise HTTPException(status_code=400, detail="Reminder already completed")

    reminder.is_completed = True
    reminder.completed_at = utc_now()

    await db.commit()
    await db.refresh(reminder)

    return ReminderResponse.model_validate(reminder)


@router.post("/{vin}/reminders/{reminder_id}/uncomplete", response_model=ReminderResponse)
async def uncomplete_reminder(
    vin: str,
    reminder_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ReminderResponse:
    """Mark a reminder as not completed."""
    # Get reminder
    result = await db.execute(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.vin == vin)
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    if not reminder.is_completed:
        raise HTTPException(status_code=400, detail="Reminder not completed")

    reminder.is_completed = False
    reminder.completed_at = None

    await db.commit()
    await db.refresh(reminder)

    return ReminderResponse.model_validate(reminder)
