"""Utility for auto-syncing DEF observation records from fuel records.

Since v2.27.0 the helper supports a `commit` flag so callers (e.g. the
extended fuel-tracking flow) can compose this into a single outer
transaction with other side effects.
"""

import logging
from datetime import date as date_type
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.fuel import is_diesel_vehicle
from app.models.def_record import DEFRecord
from app.models.vehicle import Vehicle
from app.utils.odometer_sync import remove_synced_odometer

logger = logging.getLogger(__name__)


def ensure_def_capable(vehicle: Vehicle) -> None:
    """Raise 400 unless the vehicle can use DEF (diesel primary or secondary)."""
    if not is_diesel_vehicle(vehicle.fuel_type, vehicle.fuel_type_secondary):
        raise HTTPException(status_code=400, detail="DEF tracking applies only to diesel vehicles")


async def sync_def_from_fuel_record(
    db: AsyncSession,
    vin: str,
    date: date_type,
    odometer_km: Decimal | None,
    fill_level: Decimal,
    fuel_record_id: int,
    *,
    commit: bool = True,
) -> DEFRecord | None:
    """Create or update a DEF observation record linked to a fuel record.

    Metric-canonical since v2.26.2: odometer_km (Decimal km).

    Args:
        commit: When True (default) commits the change. When False the
            caller is responsible for committing; the helper still flushes
            so the row id is available within the same transaction.
    """
    result = await db.execute(
        select(DEFRecord).where(DEFRecord.origin_fuel_record_id == fuel_record_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.fill_level = fill_level
        existing.date = date
        existing.odometer_km = odometer_km
        if commit:
            await db.commit()
            await db.refresh(existing)
        else:
            await db.flush()
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
    if commit:
        await db.commit()
        await db.refresh(def_record)
    else:
        await db.flush()
    logger.info(
        "Created auto-synced DEF record %d for fuel record %d", def_record.id, fuel_record_id
    )
    return def_record


async def delete_def_for_fuel_record(
    db: AsyncSession,
    vin: str,
    fuel_record_id: int,
) -> int:
    """Delete the DEF records a fuel record wrote, and the odometer readings they synced.

    One edited through the DEF page syncs its own reading, which has no FK to
    cascade from, so it goes by marker here. Does NOT commit: the caller owns
    the transaction, for atomicity with the fuel record write.

    Returns:
        Number of DEF records deleted
    """
    linked = await db.execute(
        select(DEFRecord.id).where(DEFRecord.origin_fuel_record_id == fuel_record_id)
    )
    for def_id in linked.scalars().all():
        await remove_synced_odometer(db, vin, "def", def_id)
    result = await db.execute(
        delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == fuel_record_id)
    )
    count: int = result.rowcount  # pyright: ignore[reportAttributeAccessIssue]  # DML execute returns CursorResult
    if count:
        logger.info(
            "Deleted %d auto-synced DEF record(s) for fuel record %d", count, fuel_record_id
        )
    return count
