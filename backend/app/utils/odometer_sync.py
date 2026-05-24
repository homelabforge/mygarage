"""Utility for auto-syncing odometer records from service and fuel records.

Metric-canonical since v2.26.2: `odometer_km` (Decimal kilometers).

Since v2.27.0 the helper supports a `commit` flag so callers (e.g. the
extended fuel-tracking flow) can compose this into a single outer
transaction with other side effects.
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
    *,
    commit: bool = True,
) -> OdometerRecord | None:
    """Create or update an odometer record from a service/fuel record.

    Behavior:
        - Skips sync if odometer_km is None
        - Checks for existing odometer record on same (vin, date)
        - If exists and was auto-synced or from livelink: updates odometer_km
          (user-entered fuel/service data is more authoritative than LiveLink)
        - If exists and was manual: does not overwrite
        - If not exists: creates new odometer record with source marker

    Args:
        commit: When True (default) the helper commits and refreshes within
            its own unit of work. When False the caller is responsible for
            committing — the helper still flushes so the row gets an id and
            any FK side effects are visible to subsequent queries inside the
            same transaction.
    """
    if odometer_km is None:
        return None

    result = await db.execute(
        select(OdometerRecord).where(OdometerRecord.vin == vin).where(OdometerRecord.date == date)
    )
    existing = result.scalar_one_or_none()

    auto_sync_marker = f"[AUTO-SYNC from {source_type} #{source_id}]"

    # Migration 055 added odometer_records.fuel_record_id with ON DELETE
    # CASCADE for fuel-sourced rows. Set it when source is 'fuel' so the
    # database can clean orphans when a fuel record is deleted; for
    # service/livelink the FK stays NULL (no fuel parent to cascade from).
    fk_value = source_id if source_type == "fuel" else None

    if existing:
        is_auto_synced = existing.notes and "[AUTO-SYNC from" in existing.notes
        is_livelink = existing.source == "livelink"

        if is_auto_synced or is_livelink:
            existing.odometer_km = odometer_km
            existing.notes = auto_sync_marker
            existing.source = source_type
            existing.fuel_record_id = fk_value
            if commit:
                await db.commit()
                await db.refresh(existing)
            else:
                await db.flush()
            return existing
        return None

    odometer_record = OdometerRecord(
        vin=vin,
        date=date,
        odometer_km=odometer_km,
        notes=auto_sync_marker,
        source=source_type,
        fuel_record_id=fk_value,
    )
    db.add(odometer_record)
    if commit:
        await db.commit()
        await db.refresh(odometer_record)
    else:
        await db.flush()
    return odometer_record
