"""Vendor business logic service layer."""

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import Vendor
from app.models.vendor_price_history import VendorPriceHistory
from app.models.maintenance_schedule_item import MaintenanceScheduleItem
from app.models.user import User
from app.schemas.vendor import (
    VendorCreate,
    VendorUpdate,
    VendorResponse,
    VendorPriceHistoryEntry,
    VendorPriceHistoryResponse,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class VendorService:
    """Service for managing vendor business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize vendor service with database session."""
        self.db = db

    async def list_vendors(
        self,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
    ) -> tuple[list[VendorResponse], int]:
        """
        Get all vendors with optional search.

        Args:
            current_user: The authenticated user
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return
            search: Optional search term for vendor name

        Returns:
            Tuple of (vendor responses, total count)
        """
        try:
            query = select(Vendor)

            if search:
                search_pattern = f"%{search}%"
                query = query.where(Vendor.name.ilike(search_pattern))

            # Get total count
            count_query = select(func.count()).select_from(Vendor)
            if search:
                count_query = count_query.where(Vendor.name.ilike(search_pattern))
            count_result = await self.db.execute(count_query)
            total = count_result.scalar() or 0

            # Get vendors
            query = query.order_by(Vendor.name).offset(skip).limit(limit)
            result = await self.db.execute(query)
            vendors = result.scalars().all()

            vendor_responses = [
                VendorResponse(
                    id=v.id,
                    name=v.name,
                    address=v.address,
                    city=v.city,
                    state=v.state,
                    zip_code=v.zip_code,
                    phone=v.phone,
                    created_at=v.created_at,
                    updated_at=v.updated_at,
                    full_address=v.full_address,
                )
                for v in vendors
            ]

            return vendor_responses, total

        except OperationalError as e:
            logger.error(
                "Database connection error listing vendors: %s", sanitize_for_log(e)
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def get_vendor(self, vendor_id: int, current_user: User) -> Vendor:
        """
        Get a specific vendor by ID.

        Args:
            vendor_id: Vendor ID
            current_user: The authenticated user

        Returns:
            Vendor object

        Raises:
            HTTPException: 404 if not found
        """
        result = await self.db.execute(select(Vendor).where(Vendor.id == vendor_id))
        vendor = result.scalar_one_or_none()

        if not vendor:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        return vendor

    async def create_vendor(
        self, vendor_data: VendorCreate, current_user: User
    ) -> Vendor:
        """
        Create a new vendor.

        Args:
            vendor_data: Vendor creation data
            current_user: The authenticated user

        Returns:
            Created Vendor object

        Raises:
            HTTPException: 409 if vendor already exists
        """
        try:
            vendor_dict = vendor_data.model_dump()
            vendor = Vendor(**vendor_dict)

            self.db.add(vendor)
            await self.db.commit()
            await self.db.refresh(vendor)

            logger.info(
                "Created vendor %s: %s", vendor.id, sanitize_for_log(vendor.name)
            )
            return vendor

        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating vendor: %s", sanitize_for_log(e)
            )
            raise HTTPException(
                status_code=409, detail="Vendor with this name already exists"
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating vendor: %s", sanitize_for_log(e)
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def update_vendor(
        self, vendor_id: int, vendor_data: VendorUpdate, current_user: User
    ) -> Vendor:
        """
        Update an existing vendor.

        Args:
            vendor_id: Vendor ID
            vendor_data: Vendor update data
            current_user: The authenticated user

        Returns:
            Updated Vendor object

        Raises:
            HTTPException: 404 if not found, 409 on constraint violation
        """
        try:
            vendor = await self.get_vendor(vendor_id, current_user)

            update_data = vendor_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(vendor, field, value)

            await self.db.commit()
            await self.db.refresh(vendor)

            logger.info(
                "Updated vendor %s: %s", vendor_id, sanitize_for_log(vendor.name)
            )
            return vendor

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating vendor %s: %s",
                vendor_id,
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409, detail="Vendor with this name already exists"
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating vendor %s: %s",
                vendor_id,
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def delete_vendor(self, vendor_id: int, current_user: User) -> None:
        """
        Delete a vendor.

        Args:
            vendor_id: Vendor ID
            current_user: The authenticated user

        Raises:
            HTTPException: 404 if not found, 409 if has dependent records
        """
        try:
            vendor = await self.get_vendor(vendor_id, current_user)

            await self.db.delete(vendor)
            await self.db.commit()

            logger.info("Deleted vendor %s", vendor_id)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting vendor %s: %s",
                vendor_id,
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409,
                detail="Cannot delete vendor with existing service visits",
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting vendor %s: %s",
                vendor_id,
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def get_price_history(
        self,
        vendor_id: int,
        current_user: User,
        schedule_item_id: Optional[int] = None,
    ) -> VendorPriceHistoryResponse:
        """
        Get price history for a vendor.

        Args:
            vendor_id: Vendor ID
            current_user: The authenticated user
            schedule_item_id: Optional filter by schedule item

        Returns:
            Price history response with statistics
        """
        vendor = await self.get_vendor(vendor_id, current_user)

        query = (
            select(VendorPriceHistory, MaintenanceScheduleItem.name)
            .join(
                MaintenanceScheduleItem,
                VendorPriceHistory.schedule_item_id == MaintenanceScheduleItem.id,
            )
            .where(VendorPriceHistory.vendor_id == vendor_id)
        )

        if schedule_item_id:
            query = query.where(VendorPriceHistory.schedule_item_id == schedule_item_id)

        query = query.order_by(VendorPriceHistory.date.desc())

        result = await self.db.execute(query)
        rows = result.all()

        history = [
            VendorPriceHistoryEntry(
                date=str(row[0].date),
                cost=float(row[0].cost),
                service_name=row[1],
                service_line_item_id=row[0].service_line_item_id,
            )
            for row in rows
        ]

        # Calculate statistics
        costs = [h.cost for h in history]
        avg_cost = sum(costs) / len(costs) if costs else None
        min_cost = min(costs) if costs else None
        max_cost = max(costs) if costs else None

        return VendorPriceHistoryResponse(
            vendor_id=vendor_id,
            vendor_name=vendor.name,
            history=history,
            average_cost=avg_cost,
            min_cost=min_cost,
            max_cost=max_cost,
        )
