"""Recall business logic service layer."""

import datetime as dt
import logging

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from app.models.user import User
from app.schemas.recall import (
    RecallCreate,
    RecallListResponse,
    RecallResponse,
    RecallUpdate,
)
from app.services.nhtsa import NHTSAService
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class RecallService:
    """Service for managing recall business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_recalls(
        self,
        vin: str,
        current_user: User,
        status: str | None = None,
    ) -> RecallListResponse:
        """Get all recalls for a vehicle with optional status filtering.

        Args:
            vin: Vehicle identification number.
            current_user: Authenticated user.
            status: Optional filter - 'active', 'resolved', or None for all.

        Returns:
            RecallListResponse with recalls, total, active_count, resolved_count.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            query = select(Recall).where(Recall.vin == vin)

            if status == "active":
                query = query.where(Recall.is_resolved.is_(False))
            elif status == "resolved":
                query = query.where(Recall.is_resolved.is_(True))

            query = query.order_by(Recall.is_resolved.asc(), Recall.date_announced.desc())

            result = await self.db.execute(query)
            recalls = result.scalars().all()

            active_count = sum(1 for r in recalls if not r.is_resolved)
            resolved_count = sum(1 for r in recalls if r.is_resolved)

            return RecallListResponse(
                recalls=[RecallResponse.model_validate(r) for r in recalls],
                total=len(recalls),
                active_count=active_count,
                resolved_count=resolved_count,
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing recalls for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def check_nhtsa(
        self,
        vin: str,
        current_user: User,
    ) -> RecallListResponse:
        """Fetch recalls from NHTSA API, store new ones, and return updated list.

        Args:
            vin: Vehicle identification number.
            current_user: Authenticated user.

        Returns:
            RecallListResponse with all recalls including newly fetched ones.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            # Fetch recalls from NHTSA
            nhtsa_service = NHTSAService()
            nhtsa_recalls = await nhtsa_service.get_vehicle_recalls(vin, self.db)

            # Get existing recalls
            result = await self.db.execute(select(Recall).where(Recall.vin == vin))
            existing_recalls = result.scalars().all()
            existing_campaign_numbers = {
                r.nhtsa_campaign_number for r in existing_recalls if r.nhtsa_campaign_number
            }

            # Add new recalls
            new_recalls_added = 0
            for nhtsa_recall in nhtsa_recalls:
                campaign_number = nhtsa_recall.get("NHTSACampaignNumber")

                if campaign_number and campaign_number in existing_campaign_numbers:
                    continue

                db_recall = Recall(
                    vin=vin,
                    nhtsa_campaign_number=campaign_number,
                    component=nhtsa_recall.get("Component", "Unknown Component")[:200],
                    summary=nhtsa_recall.get("Summary", "No summary available"),
                    consequence=nhtsa_recall.get("Consequence"),
                    remedy=nhtsa_recall.get("Remedy"),
                    date_announced=None,
                    is_resolved=False,
                )
                self.db.add(db_recall)
                new_recalls_added += 1

            await self.db.commit()

            logger.info(
                "Added %s new recalls for vehicle %s from NHTSA",
                new_recalls_added,
                sanitize_for_log(vin),
            )

            # Return updated list
            result = await self.db.execute(
                select(Recall)
                .where(Recall.vin == vin)
                .order_by(Recall.is_resolved.asc(), Recall.created_at.desc())
            )
            recalls = result.scalars().all()

            active_count = sum(1 for r in recalls if not r.is_resolved)
            resolved_count = sum(1 for r in recalls if r.is_resolved)

            return RecallListResponse(
                recalls=[RecallResponse.model_validate(r) for r in recalls],
                total=len(recalls),
                active_count=active_count,
                resolved_count=resolved_count,
            )

        except HTTPException:
            raise
        except ValueError as e:
            logger.warning(
                "VIN decode failure for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(
                status_code=422,
                detail=f"Could not decode VIN to fetch recalls: {e!s}",
            )
        except httpx.TimeoutException:
            logger.error(
                "NHTSA API timeout fetching recalls for VIN %s",
                sanitize_for_log(vin),
            )
            raise HTTPException(status_code=504, detail="NHTSA API request timed out")
        except httpx.ConnectError:
            logger.error(
                "Cannot connect to NHTSA API for VIN %s",
                sanitize_for_log(vin),
            )
            raise HTTPException(status_code=503, detail="Cannot connect to NHTSA API")
        except httpx.HTTPStatusError as e:
            logger.error(
                "NHTSA API error fetching recalls for VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(status_code=e.response.status_code, detail="NHTSA API error")
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation storing NHTSA recalls for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate recall data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database error fetching recalls for VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(str(e)),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_recall(
        self,
        vin: str,
        data: RecallCreate,
        current_user: User,
    ) -> RecallResponse:
        """Create a new recall manually.

        Args:
            vin: Vehicle identification number.
            data: Recall creation data.
            current_user: Authenticated user.

        Returns:
            RecallResponse for the newly created recall.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            db_recall = Recall(
                vin=vin,
                nhtsa_campaign_number=data.nhtsa_campaign_number,
                component=data.component,
                summary=data.summary,
                consequence=data.consequence,
                remedy=data.remedy,
                date_announced=data.date_announced,
                is_resolved=data.is_resolved,
                notes=data.notes,
            )

            if data.is_resolved:
                db_recall.resolved_at = dt.datetime.now()

            self.db.add(db_recall)
            await self.db.commit()
            await self.db.refresh(db_recall)

            logger.info(
                "Created recall %s for vehicle %s",
                db_recall.id,
                sanitize_for_log(vin),
            )

            return RecallResponse.model_validate(db_recall)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating recall for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid recall")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating recall for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_recall(
        self,
        vin: str,
        recall_id: int,
        current_user: User,
    ) -> RecallResponse:
        """Get a specific recall by ID.

        Args:
            vin: Vehicle identification number.
            recall_id: Recall record ID.
            current_user: Authenticated user.

        Returns:
            RecallResponse for the requested recall.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
            )
            recall = result.scalar_one_or_none()

            if not recall:
                raise HTTPException(status_code=404, detail="Recall not found")

            return RecallResponse.model_validate(recall)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting recall %s for %s: %s",
                recall_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_recall(
        self,
        vin: str,
        recall_id: int,
        data: RecallUpdate,
        current_user: User,
    ) -> RecallResponse:
        """Update an existing recall.

        Args:
            vin: Vehicle identification number.
            recall_id: Recall record ID.
            data: Recall update data.
            current_user: Authenticated user.

        Returns:
            RecallResponse for the updated recall.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
            )
            recall = result.scalar_one_or_none()

            if not recall:
                raise HTTPException(status_code=404, detail="Recall not found")

            update_data = data.model_dump(exclude_unset=True)

            # Handle is_resolved field specially
            if "is_resolved" in update_data:
                new_resolved_status = update_data["is_resolved"]
                old_resolved_status = recall.is_resolved

                if new_resolved_status and not old_resolved_status:
                    recall.resolved_at = dt.datetime.now()
                elif not new_resolved_status and old_resolved_status:
                    recall.resolved_at = None

            for field, value in update_data.items():
                setattr(recall, field, value)

            await self.db.commit()
            await self.db.refresh(recall)

            logger.info(
                "Updated recall %s for vehicle %s",
                recall_id,
                sanitize_for_log(vin),
            )

            return RecallResponse.model_validate(recall)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating recall %s for %s: %s",
                recall_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating recall %s for %s: %s",
                recall_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_recall(
        self,
        vin: str,
        recall_id: int,
        current_user: User,
    ) -> None:
        """Delete a recall.

        Args:
            vin: Vehicle identification number.
            recall_id: Recall record ID.
            current_user: Authenticated user.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
            )
            recall = result.scalar_one_or_none()

            if not recall:
                raise HTTPException(status_code=404, detail="Recall not found")

            await self.db.execute(delete(Recall).where(Recall.id == recall_id))
            await self.db.commit()

            logger.info(
                "Deleted recall %s for vehicle %s",
                recall_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting recall %s for %s: %s",
                recall_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete recall with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting recall %s for %s: %s",
                recall_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")
