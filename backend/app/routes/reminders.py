"""Vehicle Reminder CRUD API endpoints."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.reminder import ReminderCreate, ReminderResponse, ReminderUpdate
from app.services import reminder_service
from app.services.auth import get_vehicle_or_403, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/reminders", tags=["Reminders"])


@router.get("", response_model=list[ReminderResponse])
async def list_reminders(
    vin: str,
    status: str = Query("pending", description="Filter: pending|done|dismissed|all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """List reminders for a vehicle, optionally filtered by status."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)
    return await reminder_service.list_reminders(vin, db, status)


@router.post("", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    vin: str,
    data: ReminderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Create a new reminder for a vehicle."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminder = await reminder_service.create_reminder(vin, data, db)
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.put("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    vin: str,
    reminder_id: int,
    data: ReminderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Update a reminder (content only — use /done or /dismiss for status)."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    await reminder_service.update_reminder(reminder, data, db)
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.delete("/{reminder_id}", status_code=204)
async def delete_reminder(
    vin: str,
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Delete a reminder."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    await db.delete(reminder)
    await db.commit()
    return None


@router.post("/{reminder_id}/done", response_model=ReminderResponse)
async def mark_done(
    vin: str,
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Mark a reminder as done."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    reminder.status = "done"
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.post("/{reminder_id}/dismiss", response_model=ReminderResponse)
async def dismiss(
    vin: str,
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Mark a reminder as dismissed."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    reminder.status = "dismissed"
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)
