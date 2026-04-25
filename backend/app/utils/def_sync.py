"""Utility for auto-syncing DEF observation records from fuel records."""

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord

logger = logging.getLogger(__name__)


async def sync_def_from_fuel_record(
    db: AsyncSession,
    vin: str,
    date: date_type,
    odometer_km: Decimal | None,
    fill_level: Decimal,
    fuel_record_id: int,
) -> DEFRecord | None:
    """Create or update a DEF observation record linked to a fuel record.

    Metric-canonical since v2.26.2: odometer_km (Decimal km).
    """
    result = await db.execute(
        select(DEFRecord).where(DEFRecord.origin_fuel_record_id == fuel_record_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.fill_level = fill_level
        existing.date = date
        existing.odometer_km = odometer_km
        await db.commit()
        await db.refresh(existing)
        logger.info(
            "Updated auto-synced DEF record %d for fuel record %d", existing.id, fuel_record_id
        )
        return existing

    def_record = DEFRecord(
        vin=vin,
        date=date,
        odometer_km=odometer_km,
        fill_level=fill_level,
        entry_type="auto_fuel_sync",
        origin_fuel_record_id=fuel_record_id,
    )
    db.add(def_record)
    await db.commit()
    await db.refresh(def_record)
    logger.info(
        "Created auto-synced DEF record %d for fuel record %d", def_record.id, fuel_record_id
    )
    return def_record


async def delete_def_for_fuel_record(
    db: AsyncSession,
    fuel_record_id: int,
) -> int:
    """Delete DEF records linked to a fuel record.

    Does NOT commit — caller manages the transaction for atomicity
    with the fuel record delete.

    Args:
        db: Database session
        fuel_record_id: ID of the fuel record being deleted

    Returns:
        Number of DEF records deleted
    """
    result = await db.execute(
        delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == fuel_record_id)
    )
    count: int = result.rowcount  # type: ignore[attr-defined]  # CursorResult has rowcount at runtime
    if count:
        logger.info(
            "Deleted %d auto-synced DEF record(s) for fuel record %d", count, fuel_record_id
        )
    return count
