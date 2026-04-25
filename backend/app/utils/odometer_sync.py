"""Utility for auto-syncing odometer records from service and fuel records.

Metric-canonical since v2.26.2: `odometer_km` (Decimal kilometers).
"""

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OdometerRecord


async def sync_odometer_from_record(
    db: AsyncSession,
    vin: str,
    date: date_type,
    odometer_km: Decimal | None,
    source_type: str,
    source_id: int,
) -> OdometerRecord | None:
    """Create or update an odometer record from a service/fuel record.

    Behavior:
        - Skips sync if odometer_km is None
        - Checks for existing odometer record on same (vin, date)
        - If exists and was auto-synced or from livelink: updates odometer_km
          (user-entered fuel/service data is more authoritative than LiveLink)
        - If exists and was manual: does not overwrite
        - If not exists: creates new odometer record with source marker
    """
    if odometer_km is None:
        return None

    result = await db.execute(
        select(OdometerRecord).where(OdometerRecord.vin == vin).where(OdometerRecord.date == date)
    )
    existing = result.scalar_one_or_none()

    auto_sync_marker = f"[AUTO-SYNC from {source_type} #{source_id}]"

    if existing:
        is_auto_synced = existing.notes and "[AUTO-SYNC from" in existing.notes
        is_livelink = existing.source == "livelink"

        if is_auto_synced or is_livelink:
            existing.odometer_km = odometer_km
            existing.notes = auto_sync_marker
            existing.source = source_type
            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            return None
    else:
        odometer_record = OdometerRecord(
            vin=vin,
            date=date,
            odometer_km=odometer_km,
            notes=auto_sync_marker,
            source=source_type,
        )
        db.add(odometer_record)
        await db.commit()
        await db.refresh(odometer_record)
        return odometer_record
