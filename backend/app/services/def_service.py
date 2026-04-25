"""DEF (Diesel Exhaust Fluid) record business logic service layer."""

import logging
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.def_record import (
    DEFAnalytics,
    DEFRecordCreate,
    DEFRecordResponse,
    DEFRecordUpdate,
)
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


class DEFRecordService:
    """Service for managing DEF record business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_def_records(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[DEFRecordResponse], int]:
        """Get all DEF records for a vehicle.

        Returns:
            Tuple of (DEF record responses, total count)
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(DEFRecord)
                .where(DEFRecord.vin == vin)
                .order_by(DEFRecord.date.desc())
                .offset(skip)
                .limit(limit)
            )
            records = result.scalars().all()

            responses = [DEFRecordResponse.model_validate(r) for r in records]

            count_result = await self.db.execute(
                select(func.count()).select_from(DEFRecord).where(DEFRecord.vin == vin)
            )
            total = count_result.scalar() or 0

            return responses, total

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing DEF records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_def_record(self, vin: str, record_id: int, current_user: User) -> DEFRecord:
        """Get a specific DEF record by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(DEFRecord).where(DEFRecord.id == record_id).where(DEFRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"DEF record {record_id} not found")

        return record

    async def create_def_record(
        self, vin: str, record_data: DEFRecordCreate, current_user: User
    ) -> DEFRecord:
        """Create a new DEF record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            _ = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            record_dict = record_data.model_dump()
            record_dict["vin"] = vin

            record = DEFRecord(**record_dict)
            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)

            logger.info(
                "Created DEF record %s for %s",
                record.id,
                sanitize_for_log(vin),
            )

            # Auto-sync odometer if odometer_km provided
            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="def",
                        source_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for DEF record %s: %s",
                        record.id,
                        sanitize_for_log(e),
                    )

            await invalidate_cache_for_vehicle(vin)

            return record

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating DEF record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid DEF record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating DEF record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_def_record(
        self,
        vin: str,
        record_id: int,
        record_data: DEFRecordUpdate,
        current_user: User,
    ) -> DEFRecord:
        """Update an existing DEF record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(DEFRecord).where(DEFRecord.id == record_id).where(DEFRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"DEF record {record_id} not found")

            update_data = record_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)

            logger.info("Updated DEF record %s for %s", record_id, sanitize_for_log(vin))

            # Auto-sync odometer if odometer_km and date are present
            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="def",
                        source_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for DEF record %s: %s",
                        record_id,
                        sanitize_for_log(e),
                    )

            await invalidate_cache_for_vehicle(vin)

            return record

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating DEF record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating DEF record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_def_record(self, vin: str, record_id: int, current_user: User) -> None:
        """Delete a DEF record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(DEFRecord).where(DEFRecord.id == record_id).where(DEFRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"DEF record {record_id} not found")

            await self.db.execute(
                delete(DEFRecord).where(DEFRecord.id == record_id).where(DEFRecord.vin == vin)
            )
            await self.db.commit()

            logger.info("Deleted DEF record %s for %s", record_id, sanitize_for_log(vin))

            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting DEF record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting DEF record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_def_analytics(self, vin: str, current_user: User) -> DEFAnalytics:
        """Calculate DEF analytics and consumption predictions.

        Conservative approach: returns None when data is insufficient.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        # Get all DEF records ordered by date
        result = await self.db.execute(
            select(DEFRecord).where(DEFRecord.vin == vin).order_by(DEFRecord.date.asc())
        )
        records = list(result.scalars().all())

        record_count = len(records)
        if record_count == 0:
            return DEFAnalytics(record_count=0, data_confidence="insufficient")

        # Basic aggregates
        total_liters = sum((r.liters for r in records if r.liters is not None), Decimal("0"))
        total_cost = sum((r.cost for r in records if r.cost is not None), Decimal("0"))

        avg_cost_per_liter: Decimal | None = None
        if total_liters > 0 and total_cost > 0:
            avg_cost_per_liter = round(total_cost / total_liters, 3)

        # Last known fill level
        last_fill_level: Decimal | None = None
        for r in reversed(records):
            if r.fill_level is not None:
                last_fill_level = r.fill_level
                break

        # Average purchase frequency (only count actual purchases, not auto-synced observations)
        avg_purchase_frequency_days: int | None = None
        purchase_records = [r for r in records if r.date is not None and r.entry_type == "purchase"]
        if len(purchase_records) >= 2:
            total_days = (purchase_records[-1].date - purchase_records[0].date).days
            if total_days > 0:
                avg_purchase_frequency_days = total_days // (len(purchase_records) - 1)

        # Consumption rate: liters per 1000 km
        # Requires minimum 3 records with odometer_km, and span > ~800 km
        odometer_records = [
            r for r in records if r.odometer_km is not None and r.liters is not None
        ]
        liters_per_1000_km: Decimal | None = None
        data_confidence = "insufficient"

        if len(odometer_records) >= 3:
            odometers = [r.odometer_km for r in odometer_records if r.odometer_km is not None]
            min_km = min(odometers)
            max_km = max(odometers)
            km_span = max_km - min_km

            if km_span >= Decimal("800"):
                total_liters_with_odometer = sum(
                    (r.liters for r in odometer_records if r.liters is not None),
                    Decimal("0"),
                )
                if total_liters_with_odometer > 0:
                    liters_per_1000_km = round(
                        total_liters_with_odometer / Decimal(str(km_span)) * 1000, 2
                    )

            if len(odometer_records) >= 5 and km_span >= Decimal("3200"):
                data_confidence = "high"
            elif len(odometer_records) >= 3:
                data_confidence = "low"

        # Estimated remaining liters (requires fill_level and tank capacity)
        estimated_remaining_liters: Decimal | None = None
        estimated_km_remaining: int | None = None
        estimated_days_remaining: int | None = None

        if last_fill_level is not None:
            # Get vehicle tank capacity (liters)
            vehicle_result = await self.db.execute(
                select(Vehicle.def_tank_capacity_liters).where(Vehicle.vin == vin)
            )
            tank_capacity = vehicle_result.scalar_one_or_none()

            if tank_capacity is not None and tank_capacity > 0:
                estimated_remaining_liters = round(last_fill_level * tank_capacity, 2)

                # Estimated km remaining
                if liters_per_1000_km is not None and liters_per_1000_km > 0:
                    km_remaining = estimated_remaining_liters / (liters_per_1000_km / 1000)
                    estimated_km_remaining = int(km_remaining)

                    # Estimated days remaining (from average daily km)
                    if len(odometer_records) >= 2:
                        odometers_sorted = sorted(odometer_records, key=lambda r: r.date)
                        total_km = (
                            odometers_sorted[-1].odometer_km - odometers_sorted[0].odometer_km  # type: ignore[operator]
                        )
                        total_days = (odometers_sorted[-1].date - odometers_sorted[0].date).days
                        if total_days > 0 and total_km > 0:
                            avg_daily_km = Decimal(str(total_km)) / Decimal(str(total_days))
                            if avg_daily_km > 0:
                                estimated_days_remaining = int(
                                    Decimal(str(estimated_km_remaining)) / avg_daily_km
                                )

        return DEFAnalytics(
            total_liters=total_liters if total_liters > 0 else None,
            total_cost=total_cost if total_cost > 0 else None,
            avg_cost_per_liter=avg_cost_per_liter,
            liters_per_1000_km=liters_per_1000_km,
            avg_purchase_frequency_days=avg_purchase_frequency_days,
            estimated_remaining_liters=estimated_remaining_liters,
            estimated_km_remaining=estimated_km_remaining,
            estimated_days_remaining=estimated_days_remaining,
            last_fill_level=last_fill_level,
            record_count=record_count,
            data_confidence=data_confidence,
        )
