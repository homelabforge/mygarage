"""Utility for auto-syncing odometer records from service and fuel records."""

from datetime import date as date_type
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OdometerRecord


async def sync_odometer_from_record(
    db: AsyncSession,
    vin: str,
    date: date_type,
    mileage: Optional[int],
    source_type: str,
    source_id: int,
) -> Optional[OdometerRecord]:
    """
    Create or update odometer record from service/fuel record.

    Args:
        db: Database session
        vin: Vehicle VIN
        date: Date of the reading
        mileage: Mileage value (if None, no sync occurs)
        source_type: "service" or "fuel"
        source_id: ID of the source record

    Returns:
        OdometerRecord if created/updated, None if skipped

    Behavior:
        - Skips sync if mileage is None
        - Checks for existing odometer record on same (vin, date)
        - If exists and was auto-synced: updates mileage
        - If exists and was manual: does not overwrite
        - If not exists: creates new odometer record with auto-sync marker
    """
    # Skip if no mileage provided
    if mileage is None:
        return None

    # Check for existing odometer record on same date
    result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.vin == vin)
        .where(OdometerRecord.date == date)
    )
    existing = result.scalar_one_or_none()

    auto_sync_marker = f"[AUTO-SYNC from {source_type} #{source_id}]"

    if existing:
        # Check if this was auto-synced (has marker in notes)
        if existing.notes and "[AUTO-SYNC from" in existing.notes:
            # Update the mileage and notes
            existing.mileage = mileage
            existing.notes = auto_sync_marker
            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            # Manual entry - don't overwrite
            return None
    else:
        # Create new odometer record
        odometer_record = OdometerRecord(
            vin=vin, date=date, mileage=mileage, notes=auto_sync_marker
        )
        db.add(odometer_record)
        await db.commit()
        await db.refresh(odometer_record)
        return odometer_record
