"""Post-create side effects for fuel records written outside FuelRecordService.

Two ingest paths build FuelRecord rows directly rather than going through
FuelRecordService.create_fuel_record: the token-authenticated webhook and the
third-party CSV importers. Both are already authorized by their own mechanism
(a shared ingest token, and get_vehicle_or_403 respectively), so they must not
be rerouted through the service's user-authorization gate -- doing so would
grant an unowned-vehicle bypass and would also reject the odometer-less charge
sessions the webhook contract deliberately allows.

What they do need is the bookkeeping the service performs after the insert.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


async def apply_fuel_record_side_effects(
    db: AsyncSession,
    record: FuelRecord,
    *,
    commit: bool = False,
) -> None:
    """Sync the odometer log for one freshly-flushed fuel record.

    ``record.id`` must already be populated, so call this after ``flush()``.
    Cache invalidation is NOT done here: it is per-vehicle and belongs after the
    whole batch, so callers invoke ``invalidate_cache_for_vehicle`` once.

    Errors are logged and re-raised, matching FuelRecordService. Swallowing them
    would commit a fuel record with no odometer entry. Callers that must survive
    a sync failure are responsible for catching it themselves.
    """
    # `is None`, not truthiness: bool(Decimal("0")) is False, and 0 km is a
    # legitimate odometer reading that the create schema explicitly allows.
    if record.date is None or record.odometer_km is None:
        return
    try:
        await sync_odometer_from_record(
            db=db,
            vin=record.vin,
            date=record.date,
            odometer_km=record.odometer_km,
            source_type="fuel",
            source_id=record.id,
            commit=commit,
        )
    except Exception as e:
        logger.warning(
            "Failed to auto-sync odometer for fuel record %s (rolling back): %s",
            record.id,
            e,
        )
        raise


__all__ = ["apply_fuel_record_side_effects", "invalidate_cache_for_vehicle"]
