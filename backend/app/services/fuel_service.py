"""Fuel record business logic service layer with L/100km calculation.

Canonical units (since v2.26.2): SI metric. Fuel economy surfaces as
L/100 km (lower is better). Imperial display is done client-side via the
frontend UnitFormatter.
"""

# pyright: reportReturnType=false, reportOptionalOperand=false

import logging
from datetime import date as date_type
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.user import User
from app.schemas.fuel import FuelRecordCreate, FuelRecordResponse, FuelRecordUpdate
from app.utils.cache import cached, invalidate_cache_for_vehicle
from app.utils.def_sync import sync_def_from_fuel_record
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


# Propane-by-weight → liters conversion factor.
# Derived from: gal = lb/4.24 (old imperial formula, 4.24 lb/gal density of propane)
#   L_per_kg = (1/0.45359237) / 4.24 * 3.78541  ≈  1.96850 L/kg
PROPANE_LITERS_PER_KG = Decimal("1.9685")


def calculate_l_per_100km(
    current_record: FuelRecord, previous_record: FuelRecord | None
) -> Decimal | None:
    """Calculate L/100km for a fuel record.

    Logic:
    - Only calculate for full tank fill-ups
    - Skip if no previous full tank fill-up
    - Skip if no odometer recorded
    - L/100km = current_liters / (distance_km / 100)

    Lower values are better fuel economy.
    """
    # Only calculate for full tank fill-ups
    if not current_record.is_full_tank:
        return None

    # Need odometer_km and liters on current record
    if not current_record.odometer_km or not current_record.liters:
        return None

    # Need a previous record to calculate distance
    if not previous_record or not previous_record.odometer_km:
        return None

    distance_km = current_record.odometer_km - previous_record.odometer_km

    # Sanity check
    if distance_km <= 0 or current_record.liters <= 0:
        return None

    l_per_100km = (current_record.liters / distance_km) * Decimal("100")
    return round(l_per_100km, 2)


async def get_previous_full_tank(
    db: AsyncSession,
    vin: str,
    current_date: date_type,
    current_odometer_km: Decimal | None,
) -> FuelRecord | None:
    """Get the most recent previous full tank fill-up."""
    query = (
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.is_full_tank.is_(True))
        .where(FuelRecord.date < current_date)
    )

    if current_odometer_km:
        query = query.where(FuelRecord.odometer_km < current_odometer_km)

    query = query.order_by(FuelRecord.date.desc()).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


@cached(ttl_seconds=300)  # Cache for 5 minutes
async def calculate_average_l_per_100km(
    db: AsyncSession, vin: str, exclude_hauling: bool = True
) -> Decimal | None:
    """Calculate average L/100km across all full-tank fuel records.

    Args:
        db: Database session
        vin: Vehicle VIN
        exclude_hauling: If True (default), exclude is_hauling=True records
            for more representative daily-driving economy
    """
    query = (
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.is_full_tank.is_(True))
        .where(FuelRecord.odometer_km.isnot(None))
        .where(FuelRecord.liters.isnot(None))
    )

    if exclude_hauling:
        query = query.where(FuelRecord.is_hauling.is_(False))

    query = query.order_by(FuelRecord.date)

    result = await db.execute(query)
    records = result.scalars().all()

    if len(records) < 2:
        return None

    values = []
    for i in range(1, len(records)):
        value = calculate_l_per_100km(records[i], records[i - 1])
        if value:
            values.append(value)

    if not values:
        return None

    return round(sum(values) / len(values), 2)


class FuelRecordService:
    """Service for managing fuel record business logic with L/100km calculations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_fuel_records(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
        include_hauling: bool = False,
    ) -> tuple[list[FuelRecordResponse], int, Decimal | None]:
        """List fuel records with per-record L/100km + vehicle-wide average."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .order_by(FuelRecord.date.desc())
                .offset(skip)
                .limit(limit)
            )
            records = result.scalars().all()

            full_tank_result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .where(FuelRecord.is_full_tank.is_(True))
                .where(FuelRecord.odometer_km.isnot(None))
                .order_by(FuelRecord.date.asc())
            )
            full_tank_records = full_tank_result.scalars().all()

            responses = []
            for record in records:
                value = None
                if record.is_full_tank and record.odometer_km:
                    prev_record = None
                    for ft_record in reversed(full_tank_records):
                        if ft_record.date < record.date and (
                            not record.odometer_km or ft_record.odometer_km < record.odometer_km
                        ):
                            prev_record = ft_record
                            break

                    if prev_record:
                        value = calculate_l_per_100km(record, prev_record)

                record_dict = record.__dict__.copy()
                record_dict["l_per_100km"] = value
                responses.append(FuelRecordResponse(**record_dict))

            count_result = await self.db.execute(
                select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
            )
            total = count_result.scalar()

            avg_value = await calculate_average_l_per_100km(
                self.db, vin, exclude_hauling=not include_hauling
            )

            return responses, total, avg_value

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing fuel records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_fuel_record(
        self, vin: str, record_id: int, current_user: User
    ) -> tuple[FuelRecord, Decimal | None]:
        """Get a specific fuel record with L/100km."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

        value = None
        if record.is_full_tank:
            prev_record = await get_previous_full_tank(
                self.db, vin, record.date, record.odometer_km
            )
            value = calculate_l_per_100km(record, prev_record)

        return record, value

    async def create_fuel_record(
        self, vin: str, record_data: FuelRecordCreate, current_user: User
    ) -> tuple[FuelRecord, Decimal | None]:
        """Create a new fuel record with L/100km calc."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            _ = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            record_dict = record_data.model_dump()
            record_dict["vin"] = vin

            # Pop DEF fill level before creating FuelRecord (not a fuel table column)
            def_fill_level = record_dict.pop("def_fill_level", None)

            # Auto-calculate propane_liters if tank-by-weight data provided
            if (
                record_dict.get("tank_size_kg") is not None
                and record_dict.get("tank_quantity") is not None
                and record_dict.get("propane_liters") is None
            ):
                tank_kg = Decimal(str(record_dict["tank_size_kg"]))
                qty = Decimal(str(record_dict["tank_quantity"]))
                calculated = tank_kg * PROPANE_LITERS_PER_KG * qty
                record_dict["propane_liters"] = calculated.quantize(Decimal("0.001"))

            record = FuelRecord(**record_dict)

            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)

            value = None
            if record.is_full_tank:
                prev_record = await get_previous_full_tank(
                    self.db, vin, record.date, record.odometer_km
                )
                value = calculate_l_per_100km(record, prev_record)

            logger.info(
                "Created fuel record %s for %s (L/100km: %s)",
                record.id,
                sanitize_for_log(vin),
                value,
            )

            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="fuel",
                        source_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record %s: %s",
                        record.id,
                        sanitize_for_log(e),
                    )

            if def_fill_level is not None:
                try:
                    await sync_def_from_fuel_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        fill_level=def_fill_level,
                        fuel_record_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync DEF for fuel record %s: %s",
                        record.id,
                        sanitize_for_log(e),
                    )

            await invalidate_cache_for_vehicle(vin)

            return record, value

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid fuel record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_fuel_record(
        self,
        vin: str,
        record_id: int,
        record_data: FuelRecordUpdate,
        current_user: User,
    ) -> tuple[FuelRecord, Decimal | None]:
        """Update a fuel record; recompute L/100km."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            update_data = record_data.model_dump(exclude_unset=True)
            def_fill_level = update_data.pop("def_fill_level", None)
            def_fill_level_was_sent = "def_fill_level" in record_data.model_fields_set

            # Auto-calculate propane_liters if tank-by-weight data provided/updated
            if (
                update_data.get("tank_size_kg") is not None
                and update_data.get("tank_quantity") is not None
                and update_data.get("propane_liters") is None
            ):
                tank_size = update_data.get("tank_size_kg", record.tank_size_kg)
                tank_qty = update_data.get("tank_quantity", record.tank_quantity)
                if tank_size is not None and tank_qty is not None:
                    calculated = (
                        Decimal(str(tank_size)) * PROPANE_LITERS_PER_KG * Decimal(str(tank_qty))
                    )
                    update_data["propane_liters"] = calculated.quantize(Decimal("0.001"))

            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)

            value = None
            if record.is_full_tank:
                prev_record = await get_previous_full_tank(
                    self.db, vin, record.date, record.odometer_km
                )
                value = calculate_l_per_100km(record, prev_record)

            logger.info("Updated fuel record %s for %s", record_id, sanitize_for_log(vin))

            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="fuel",
                        source_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record %s: %s",
                        record_id,
                        sanitize_for_log(e),
                    )

            if def_fill_level_was_sent:
                try:
                    if def_fill_level is not None:
                        await sync_def_from_fuel_record(
                            db=self.db,
                            vin=vin,
                            date=record.date,
                            odometer_km=record.odometer_km,
                            fill_level=def_fill_level,
                            fuel_record_id=record.id,
                        )
                    else:
                        from app.models.def_record import DEFRecord

                        await self.db.execute(
                            delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
                        )
                        await self.db.commit()
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync DEF for fuel record %s: %s",
                        record_id,
                        sanitize_for_log(e),
                    )

            await invalidate_cache_for_vehicle(vin)

            return record, value

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_fuel_record(self, vin: str, record_id: int, current_user: User) -> None:
        """Delete a fuel record and any linked DEF auto-synced record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            from app.models.def_record import DEFRecord

            await self.db.execute(
                delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
            )
            await self.db.execute(
                delete(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            await self.db.commit()

            logger.info("Deleted fuel record %s for %s", record_id, sanitize_for_log(vin))

            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")


# Back-compat aliases for v1 widget endpoints (kept until v3.2.0).
calculate_mpg = calculate_l_per_100km
calculate_average_mpg = calculate_average_l_per_100km
