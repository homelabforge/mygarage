"""Vehicle Reminder CRUD API endpoints, plus the maintenance lifecycle around them:
completion with a real date and reading, pack preview and apply, duplicate
reconciliation and an idempotent reconcile."""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.maintenance import (
    ApplyPackPreview,
    DuplicateGroup,
    ReconcileDuplicatesRequest,
    ReminderCompleteRequest,
)
from app.schemas.reminder import (
    ReminderCompleteResponse,
    ReminderCreate,
    ReminderResponse,
    ReminderSnoozeRequest,
    ReminderUpdate,
)
from app.schemas.reminder_pack import (
    ApplyReminderPackRequest,
    ReminderPackDetail,
    ReminderPackSummary,
    RenameReminderPackRequest,
    SaveReminderPackRequest,
)
from app.services import maintenance_service, reminder_pack_service, reminder_service
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.household_time import household_today

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/reminders", tags=["Reminders"])
packs_router = APIRouter(prefix="/api/reminder-packs", tags=["Reminders"])


@packs_router.get("", response_model=list[ReminderPackSummary])
async def list_reminder_packs(
    vehicle_type: str | None = Query(
        None, description="Filter packs applicable to this vehicle type"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """List the reminder packs available to apply to a vehicle.

    Built-in and saved packs in one list. A saved pack is marked `is_custom`, and
    `can_edit` says whether this caller may change it.
    """
    return await reminder_pack_service.list_packs(
        db, vehicle_type=vehicle_type, current_user=current_user
    )


@packs_router.post("", response_model=ReminderPackDetail, status_code=201)
async def save_reminder_pack(
    body: SaveReminderPackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Save one vehicle's chosen maintenance rules as a reusable pack.

    Needs WRITE access to the source vehicle, not read: the pack is visible to
    every user of the instance, so this publishes that vehicle's schedule.
    """
    return await reminder_pack_service.save_pack_from_vehicle(db, body, current_user)


@packs_router.put("/{pack_id}", response_model=ReminderPackDetail)
async def overwrite_reminder_pack(
    pack_id: str,
    body: SaveReminderPackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Replace a saved pack's contents from a vehicle, keeping its id."""
    return await reminder_pack_service.overwrite_pack(db, pack_id, body, current_user)


@packs_router.patch("/{pack_id}", response_model=ReminderPackDetail)
async def rename_reminder_pack(
    pack_id: str,
    body: RenameReminderPackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Rename a saved pack. Its id does not change, so rules it created keep
    pointing at it."""
    return await reminder_pack_service.rename_pack(db, pack_id, body.name, current_user)


@packs_router.delete("/{pack_id}", status_code=204)
async def delete_reminder_pack(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Delete a saved pack. Rules it already created are left alone."""
    await reminder_pack_service.delete_pack(db, pack_id, current_user)


@router.get("", response_model=list[ReminderResponse])
async def list_reminders(
    vin: str,
    status: str = Query("pending", description="Filter: pending|done|dismissed|all"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """List reminders for a vehicle, optionally filtered by status."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)
    return await reminder_service.list_reminders(vin, db, status)


@router.get("/duplicates", response_model=list[DuplicateGroup])
async def list_duplicates(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Pending reminders that share a maintenance type, with a suggested keeper."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)
    return await maintenance_service.duplicate_groups(db, vin)


@router.post("", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    vin: str,
    data: ReminderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Create a new reminder for a vehicle.

    With ``recurrence`` the reminder gets a maintenance rule and its
    thresholds are derived from the anchor and the intervals; the vehicle's
    existing rule of the type is reused, so this may return that rule's
    existing pending reminder rather than a new row.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    if data.recurrence is not None:
        reminder = await maintenance_service.create_recurring_reminder(db, vin, data)
    else:
        reminder = await reminder_service.create_reminder(vin, data, db)
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.post("/apply-pack/preview", response_model=ApplyPackPreview)
async def preview_reminder_pack(
    vin: str,
    body: ApplyReminderPackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """What applying the pack would do: rules, anchors, adoptions, thresholds. No writes."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)  # tripwire: read-only
    return await reminder_pack_service.preview_pack(
        vin, body.pack_id, db, body.anchors, body.overrides
    )


@router.post("/apply-pack", response_model=list[ReminderResponse], status_code=201)
async def apply_reminder_pack(
    vin: str,
    body: ApplyReminderPackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Apply a built-in reminder pack to a vehicle.

    Returns the pending reminder of every rule the pack touched: created,
    reused or adopted, never a duplicate of one already tracking the type.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    return await reminder_pack_service.apply_pack(
        vin, body.pack_id, db, body.anchors, body.overrides
    )


@router.post("/reconcile", response_model=list[ReminderResponse])
async def reconcile_reminders(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Recompute every active rule's pending reminder from the history. Idempotent."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await maintenance_service.reconcile_vehicle(db, vin)
    return await reminder_service.list_reminders(vin, db, "pending")


@router.post("/reconcile-duplicates", response_model=list[ReminderResponse])
async def reconcile_duplicates(
    vin: str,
    body: ReconcileDuplicatesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Keep one reminder of a duplicate group and supersede the others."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminders = await maintenance_service.reconcile_duplicates(db, vin, body)
    return await reminder_service.enrich_reminders(reminders, db)


@router.put("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder(
    vin: str,
    reminder_id: int,
    data: ReminderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Update a reminder (content only — use /done, /dismiss or /complete for status)."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    # An update may create, reuse or retype a rule: serialise with every other
    # rule writer before reading anything.
    await lock_vehicle_for_write(db, vin)
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
    current_user: User | None = Depends(require_auth),
):
    """Delete a reminder."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    # Deleting the reminder a rule produced stops the repeat, or the next
    # reconcile would recreate it.
    await maintenance_service.stop_repeating(db, reminder)
    await db.delete(reminder)
    await db.commit()
    return None


@router.post("/{reminder_id}/complete", response_model=ReminderCompleteResponse)
async def complete_reminder(
    vin: str,
    reminder_id: int,
    body: ReminderCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Complete a reminder with the actual date and readings.

    Logs a service visit (default), links an existing one, or just records
    the completion; a recurring reminder's successor is created from it.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    return await maintenance_service.complete_reminder(db, vin, reminder_id, body)


@router.post("/{reminder_id}/done", response_model=ReminderResponse)
async def mark_done(
    vin: str,
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Mark a reminder as done today, without a service record.

    The fallback: a recurring reminder still advances, anchored on today's
    date and the nearest readings. ``/complete`` records the real ones.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    if reminder.status == "pending":
        result = await maintenance_service.complete_reminder(
            db,
            vin,
            reminder_id,
            ReminderCompleteRequest(completed_date=household_today(), mode="mark_only"),
        )
        return result.reminder
    reminder.status = "done"
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.post("/{reminder_id}/dismiss", response_model=ReminderResponse)
async def dismiss(
    vin: str,
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Mark a reminder as dismissed; a recurring one stops repeating."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    await maintenance_service.stop_repeating(db, reminder)
    reminder.status = "dismissed"
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.post("/{reminder_id}/snooze", response_model=ReminderResponse)
async def snooze(
    vin: str,
    reminder_id: int,
    data: ReminderSnoozeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Hide a pending reminder from every nag surface until a date.

    The due fields stay untouched: on `until` the reminder is back, with
    whatever overdue state reality gives it. Dismiss is "stop repeating";
    this is "not now".
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    if reminder.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending reminder can be snoozed")
    today = household_today()
    if data.until <= today:
        raise HTTPException(status_code=422, detail="Snooze until must be a future date")
    if data.until > today + timedelta(days=3653):
        raise HTTPException(status_code=422, detail="Snooze until is more than ten years out")
    reminder.snoozed_until = data.until
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)


@router.post("/{reminder_id}/unsnooze", response_model=ReminderResponse)
async def unsnooze(
    vin: str,
    reminder_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Clear a pending reminder's snooze; it counts again immediately."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)
    await lock_vehicle_for_write(db, vin)
    reminder = await reminder_service._get_reminder_or_404(reminder_id, vin, db)
    if reminder.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending reminder can be unsnoozed")
    reminder.snoozed_until = None
    await db.commit()
    await db.refresh(reminder)
    return await reminder_service.enrich_with_estimate(reminder, db)
