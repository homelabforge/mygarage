"""Maintenance schedule business logic service layer."""

import logging
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance_schedule_item import MaintenanceScheduleItem
from app.models.odometer import OdometerRecord
from app.models.user import User
from app.schemas.maintenance_schedule import (
    MaintenanceScheduleItemCreate,
    MaintenanceScheduleItemResponse,
    MaintenanceScheduleItemUpdate,
    MaintenanceScheduleListResponse,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class MaintenanceScheduleService:
    """Service for managing maintenance schedule business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize maintenance schedule service with database session."""
        self.db = db

    async def list_schedule_items(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
        status_filter: str | None = None,
    ) -> MaintenanceScheduleListResponse:
        """
        Get all maintenance schedule items for a vehicle with status.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return
            status_filter: Optional filter by status

        Returns:
            MaintenanceScheduleListResponse with items and counts
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            # Get current mileage for status calculation
            current_mileage = await self._get_current_mileage(vin)
            current_date = date.today()

            # Get schedule items
            query = (
                select(MaintenanceScheduleItem)
                .where(MaintenanceScheduleItem.vin == vin)
                .order_by(MaintenanceScheduleItem.name)
            )
            result = await self.db.execute(query)
            items = result.scalars().all()

            # Calculate status for each item and build responses
            item_responses = []
            status_counts = {
                "due_soon": 0,
                "overdue": 0,
                "on_track": 0,
                "never_performed": 0,
            }

            for item in items:
                status = item.calculate_status(current_date, current_mileage)
                status_counts[status] += 1

                # Skip if filtering by status
                if status_filter and status != status_filter:
                    continue

                # Calculate days/miles until due
                days_until = None
                miles_until = None
                next_due_date = item.next_due_date
                next_due_mileage = item.next_due_mileage

                if next_due_date:
                    days_until = (next_due_date - current_date).days
                if next_due_mileage and current_mileage:
                    miles_until = next_due_mileage - current_mileage

                item_responses.append(
                    MaintenanceScheduleItemResponse(
                        id=item.id,
                        vin=item.vin,
                        name=item.name,
                        component_category=item.component_category,
                        item_type=item.item_type,
                        interval_months=item.interval_months,
                        interval_miles=item.interval_miles,
                        source=item.source,
                        template_item_id=item.template_item_id,
                        last_performed_date=item.last_performed_date,
                        last_performed_mileage=item.last_performed_mileage,
                        last_service_line_item_id=item.last_service_line_item_id,
                        next_due_date=next_due_date,
                        next_due_mileage=next_due_mileage,
                        status=status,
                        days_until_due=days_until,
                        miles_until_due=miles_until,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                    )
                )

            # Apply pagination
            paginated_items = item_responses[skip : skip + limit]

            return MaintenanceScheduleListResponse(
                items=paginated_items,
                total=len(item_responses),
                due_soon_count=status_counts["due_soon"],
                overdue_count=status_counts["overdue"],
                on_track_count=status_counts["on_track"],
                never_performed_count=status_counts["never_performed"],
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing schedule items for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_schedule_item(
        self, vin: str, item_id: int, current_user: User
    ) -> MaintenanceScheduleItem:
        """
        Get a specific schedule item by ID.

        Args:
            vin: Vehicle VIN
            item_id: Schedule item ID
            current_user: The authenticated user

        Returns:
            MaintenanceScheduleItem object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(MaintenanceScheduleItem)
            .where(MaintenanceScheduleItem.id == item_id)
            .where(MaintenanceScheduleItem.vin == vin)
        )
        item = result.scalar_one_or_none()

        if not item:
            raise HTTPException(status_code=404, detail=f"Schedule item {item_id} not found")

        return item

    async def create_schedule_item(
        self, vin: str, item_data: MaintenanceScheduleItemCreate, current_user: User
    ) -> MaintenanceScheduleItem:
        """
        Create a new maintenance schedule item.

        Args:
            vin: Vehicle VIN
            item_data: Schedule item creation data
            current_user: The authenticated user

        Returns:
            Created MaintenanceScheduleItem object
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            item = MaintenanceScheduleItem(
                vin=vin,
                name=item_data.name,
                component_category=item_data.component_category,
                item_type=item_data.item_type,
                interval_months=item_data.interval_months,
                interval_miles=item_data.interval_miles,
                source=item_data.source,
                template_item_id=item_data.template_item_id,
            )

            self.db.add(item)
            await self.db.commit()
            await self.db.refresh(item)

            logger.info(
                "Created schedule item %s for %s: %s",
                item.id,
                sanitize_for_log(vin),
                sanitize_for_log(item.name),
            )
            return item

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating schedule item for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Invalid schedule item data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating schedule item for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_schedule_item(
        self,
        vin: str,
        item_id: int,
        item_data: MaintenanceScheduleItemUpdate,
        current_user: User,
    ) -> MaintenanceScheduleItem:
        """
        Update an existing schedule item.

        Args:
            vin: Vehicle VIN
            item_id: Schedule item ID
            item_data: Schedule item update data
            current_user: The authenticated user

        Returns:
            Updated MaintenanceScheduleItem object
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            item = await self.get_schedule_item(vin, item_id, current_user)

            update_data = item_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(item, field, value)

            await self.db.commit()
            await self.db.refresh(item)

            logger.info("Updated schedule item %s for %s", item_id, sanitize_for_log(vin))
            return item

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating schedule item %s: %s",
                item_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Invalid schedule item data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating schedule item %s: %s",
                item_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_schedule_item(self, vin: str, item_id: int, current_user: User) -> None:
        """
        Delete a schedule item.

        Args:
            vin: Vehicle VIN
            item_id: Schedule item ID
            current_user: The authenticated user
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            item = await self.get_schedule_item(vin, item_id, current_user)

            await self.db.delete(item)
            await self.db.commit()

            logger.info("Deleted schedule item %s for %s", item_id, sanitize_for_log(vin))

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting schedule item %s: %s",
                item_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete item with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting schedule item %s: %s",
                item_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def _get_current_mileage(self, vin: str) -> int | None:
        """Get the most recent mileage reading for a vehicle."""
        result = await self.db.execute(
            select(OdometerRecord.mileage)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc())
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None
