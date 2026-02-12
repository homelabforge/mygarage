"""Service visit business logic service layer."""

# pyright: reportReturnType=false

import logging
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.maintenance_schedule_item import MaintenanceScheduleItem
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vendor_price_history import VendorPriceHistory
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceLineItemResponse,
    ServiceVisitCreate,
    ServiceVisitResponse,
    ServiceVisitUpdate,
    VendorSummary,
)
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


class ServiceVisitService:
    """Service for managing service visit business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize service visit service with database session."""
        self.db = db

    async def list_service_visits(
        self, vin: str, current_user: User, skip: int = 0, limit: int = 100
    ) -> tuple[list[ServiceVisitResponse], int]:
        """
        Get all service visits for a vehicle.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return

        Returns:
            Tuple of (service visit responses, total count)

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership
            await get_vehicle_or_403(vin, current_user, self.db)

            # Get visits with line items and vendor
            result = await self.db.execute(
                select(ServiceVisit)
                .options(selectinload(ServiceVisit.line_items))
                .options(selectinload(ServiceVisit.vendor))
                .where(ServiceVisit.vin == vin)
                .order_by(ServiceVisit.date.desc())
                .offset(skip)
                .limit(limit)
            )
            visits = result.scalars().all()

            # Get total count
            count_result = await self.db.execute(
                select(func.count()).select_from(ServiceVisit).where(ServiceVisit.vin == vin)
            )
            total = count_result.scalar() or 0

            visit_responses = [self._visit_to_response(v) for v in visits]
            return visit_responses, total

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing service visits for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_service_visit(self, vin: str, visit_id: int, current_user: User) -> ServiceVisit:
        """
        Get a specific service visit by ID.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            current_user: The authenticated user

        Returns:
            ServiceVisit object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(ServiceVisit)
            .options(selectinload(ServiceVisit.line_items))
            .options(selectinload(ServiceVisit.vendor))
            .where(ServiceVisit.id == visit_id)
            .where(ServiceVisit.vin == vin)
        )
        visit = result.scalar_one_or_none()

        if not visit:
            raise HTTPException(status_code=404, detail=f"Service visit {visit_id} not found")

        return visit

    async def create_service_visit(
        self, vin: str, visit_data: ServiceVisitCreate, current_user: User
    ) -> ServiceVisit:
        """
        Create a new service visit with line items.

        Args:
            vin: Vehicle VIN
            visit_data: Service visit creation data
            current_user: The authenticated user

        Returns:
            Created ServiceVisit object

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            # Create visit
            visit = ServiceVisit(
                vin=vin,
                vendor_id=visit_data.vendor_id,
                date=visit_data.date,
                mileage=visit_data.mileage,
                total_cost=visit_data.total_cost,
                tax_amount=visit_data.tax_amount,
                shop_supplies=visit_data.shop_supplies,
                misc_fees=visit_data.misc_fees,
                notes=visit_data.notes,
                service_category=visit_data.service_category,
                insurance_claim_number=visit_data.insurance_claim_number,
            )
            self.db.add(visit)
            await self.db.flush()  # Get visit ID

            # Create line items
            for item_data in visit_data.line_items:
                line_item = ServiceLineItem(
                    visit_id=visit.id,
                    schedule_item_id=item_data.schedule_item_id,
                    description=item_data.description,
                    cost=item_data.cost,
                    notes=item_data.notes,
                    is_inspection=item_data.is_inspection,
                    inspection_result=item_data.inspection_result,
                    inspection_severity=item_data.inspection_severity,
                    triggered_by_inspection_id=item_data.triggered_by_inspection_id,
                )
                self.db.add(line_item)
                await self.db.flush()

                # Update schedule item if linked
                if item_data.schedule_item_id:
                    await self._update_schedule_item(
                        item_data.schedule_item_id,
                        visit.date,
                        visit.mileage,
                        line_item.id,
                    )

                # Record price history if vendor and schedule item
                if visit_data.vendor_id and item_data.schedule_item_id and item_data.cost:
                    await self._record_price_history(
                        visit_data.vendor_id,
                        item_data.schedule_item_id,
                        line_item.id,
                        visit.date,
                        item_data.cost,
                    )

            # Always recompute total_cost from line items + fees (denormalized cache)
            await self.db.refresh(visit, attribute_names=["line_items"])
            visit.total_cost = visit.calculated_total_cost
            await self.db.flush()

            await self.db.commit()
            await self.db.refresh(visit)

            logger.info("Created service visit %s for %s", visit.id, sanitize_for_log(vin))

            # Auto-sync odometer
            if visit.date and visit.mileage:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=visit.date,
                        mileage=visit.mileage,
                        source_type="service_visit",
                        source_id=visit.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for visit %s: %s",
                        visit.id,
                        sanitize_for_log(e),
                    )

            await invalidate_cache_for_vehicle(vin)

            # Reload with relationships
            return await self.get_service_visit(vin, visit.id, current_user)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating service visit for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Invalid service visit data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating service visit for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_service_visit(
        self,
        vin: str,
        visit_id: int,
        visit_data: ServiceVisitUpdate,
        current_user: User,
    ) -> ServiceVisit:
        """
        Update an existing service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            visit_data: Service visit update data
            current_user: The authenticated user

        Returns:
            Updated ServiceVisit object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            visit = await self.get_service_visit(vin, visit_id, current_user)

            update_data = visit_data.model_dump(exclude_unset=True)

            # Handle line_items separately - replace all if provided
            new_line_items = update_data.pop("line_items", None)

            for field, value in update_data.items():
                setattr(visit, field, value)

            # If line_items provided, delete existing and create new ones
            if new_line_items is not None:
                # Delete existing line items
                for item in list(visit.line_items):
                    await self.db.delete(item)

                # Create new line items
                for item_data in new_line_items:
                    line_item = ServiceLineItem(
                        visit_id=visit.id,
                        description=item_data["description"],
                        cost=item_data.get("cost"),
                        notes=item_data.get("notes"),
                        is_inspection=item_data.get("is_inspection", False),
                        inspection_result=item_data.get("inspection_result"),
                        inspection_severity=item_data.get("inspection_severity"),
                        schedule_item_id=item_data.get("schedule_item_id"),
                        triggered_by_inspection_id=item_data.get("triggered_by_inspection_id"),
                    )
                    self.db.add(line_item)

            # Always recompute total_cost from line items + fees (denormalized cache)
            await self.db.flush()
            await self.db.refresh(visit, attribute_names=["line_items"])
            visit.total_cost = visit.calculated_total_cost

            await self.db.commit()
            await self.db.refresh(visit)

            logger.info("Updated service visit %s for %s", visit_id, sanitize_for_log(vin))

            # Auto-sync odometer
            if visit.date and visit.mileage:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=visit.date,
                        mileage=visit.mileage,
                        source_type="service_visit",
                        source_id=visit.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for visit %s: %s",
                        visit_id,
                        sanitize_for_log(e),
                    )

            await invalidate_cache_for_vehicle(vin)
            return visit

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_service_visit(self, vin: str, visit_id: int, current_user: User) -> None:
        """
        Delete a service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            current_user: The authenticated user

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            visit = await self.get_service_visit(vin, visit_id, current_user)

            await self.db.delete(visit)
            await self.db.commit()

            logger.info("Deleted service visit %s for %s", visit_id, sanitize_for_log(vin))
            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete visit with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting visit %s for %s: %s",
                visit_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def add_line_item(
        self,
        vin: str,
        visit_id: int,
        item_data: ServiceLineItemCreate,
        current_user: User,
    ) -> ServiceLineItem:
        """
        Add a line item to an existing service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            item_data: Line item creation data
            current_user: The authenticated user

        Returns:
            Created ServiceLineItem object
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            visit = await self.get_service_visit(vin, visit_id, current_user)

            line_item = ServiceLineItem(
                visit_id=visit.id,
                schedule_item_id=item_data.schedule_item_id,
                description=item_data.description,
                cost=item_data.cost,
                notes=item_data.notes,
                is_inspection=item_data.is_inspection,
                inspection_result=item_data.inspection_result,
                inspection_severity=item_data.inspection_severity,
                triggered_by_inspection_id=item_data.triggered_by_inspection_id,
            )
            self.db.add(line_item)
            await self.db.flush()

            # Update schedule item if linked
            if item_data.schedule_item_id:
                await self._update_schedule_item(
                    item_data.schedule_item_id,
                    visit.date,
                    visit.mileage,
                    line_item.id,
                )

            # Record price history
            if visit.vendor_id and item_data.schedule_item_id and item_data.cost:
                await self._record_price_history(
                    visit.vendor_id,
                    item_data.schedule_item_id,
                    line_item.id,
                    visit.date,
                    item_data.cost,
                )

            # Recompute total_cost (denormalized cache)
            await self.db.flush()
            await self.db.refresh(visit, attribute_names=["line_items"])
            visit.total_cost = visit.calculated_total_cost

            await self.db.commit()
            await self.db.refresh(line_item)

            logger.info(
                "Added line item %s to visit %s for %s",
                line_item.id,
                visit_id,
                sanitize_for_log(vin),
            )
            await invalidate_cache_for_vehicle(vin)

            return line_item

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation adding line item to visit %s: %s",
                visit_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Invalid line item data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error adding line item to visit %s: %s",
                visit_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_line_item(
        self, vin: str, visit_id: int, line_item_id: int, current_user: User
    ) -> None:
        """
        Delete a line item from a service visit.

        Args:
            vin: Vehicle VIN
            visit_id: Service visit ID
            line_item_id: Line item ID
            current_user: The authenticated user
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            await self.get_service_visit(vin, visit_id, current_user)

            result = await self.db.execute(
                select(ServiceLineItem)
                .where(ServiceLineItem.id == line_item_id)
                .where(ServiceLineItem.visit_id == visit_id)
            )
            line_item = result.scalar_one_or_none()

            if not line_item:
                raise HTTPException(status_code=404, detail=f"Line item {line_item_id} not found")

            # Get the visit before deleting line item to recompute total
            visit_result = await self.db.execute(
                select(ServiceVisit)
                .options(selectinload(ServiceVisit.line_items))
                .where(ServiceVisit.id == visit_id)
            )
            visit = visit_result.scalar_one()

            await self.db.delete(line_item)
            await self.db.flush()

            # Recompute total_cost (denormalized cache)
            await self.db.refresh(visit, attribute_names=["line_items"])
            visit.total_cost = visit.calculated_total_cost

            await self.db.commit()

            logger.info(
                "Deleted line item %s from visit %s for %s",
                line_item_id,
                visit_id,
                sanitize_for_log(vin),
            )
            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting line item %s: %s",
                line_item_id,
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def _update_schedule_item(
        self,
        schedule_item_id: int,
        service_date: date,
        mileage: int | None,
        line_item_id: int,
    ) -> None:
        """Update a maintenance schedule item with service completion."""
        result = await self.db.execute(
            select(MaintenanceScheduleItem).where(MaintenanceScheduleItem.id == schedule_item_id)
        )
        schedule_item = result.scalar_one_or_none()

        if schedule_item:
            schedule_item.update_from_service(service_date, mileage, line_item_id)

    async def _record_price_history(
        self,
        vendor_id: int,
        schedule_item_id: int,
        line_item_id: int,
        service_date: date,
        cost: Decimal,
    ) -> None:
        """Record price history for vendor comparison."""
        price_history = VendorPriceHistory(
            vendor_id=vendor_id,
            schedule_item_id=schedule_item_id,
            service_line_item_id=line_item_id,
            date=service_date,
            cost=cost,
        )
        self.db.add(price_history)

    def _visit_to_response(self, visit: ServiceVisit) -> ServiceVisitResponse:
        """Convert ServiceVisit model to response schema."""
        vendor_summary = None
        if visit.vendor:
            vendor_summary = VendorSummary(
                id=visit.vendor.id,
                name=visit.vendor.name,
                city=visit.vendor.city,
                state=visit.vendor.state,
            )

        line_item_responses = [
            ServiceLineItemResponse(
                id=item.id,
                visit_id=item.visit_id,
                description=item.description,
                cost=item.cost,
                notes=item.notes,
                is_inspection=item.is_inspection,
                inspection_result=item.inspection_result,
                inspection_severity=item.inspection_severity,
                schedule_item_id=item.schedule_item_id,
                triggered_by_inspection_id=item.triggered_by_inspection_id,
                created_at=item.created_at,
                is_failed_inspection=item.is_failed_inspection,
                needs_followup=item.needs_followup,
            )
            for item in visit.line_items
        ]

        return ServiceVisitResponse(
            id=visit.id,
            vin=visit.vin,
            vendor_id=visit.vendor_id,
            date=visit.date,
            mileage=visit.mileage,
            total_cost=visit.total_cost,
            tax_amount=visit.tax_amount,
            shop_supplies=visit.shop_supplies,
            misc_fees=visit.misc_fees,
            subtotal=visit.subtotal,
            calculated_total_cost=visit.calculated_total_cost,
            notes=visit.notes,
            service_category=visit.service_category,
            insurance_claim_number=visit.insurance_claim_number,
            line_item_count=visit.line_item_count,
            has_failed_inspections=visit.has_failed_inspections,
            created_at=visit.created_at,
            updated_at=visit.updated_at,
            line_items=line_item_responses,
            vendor=vendor_summary,
        )
