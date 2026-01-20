"""Recall CRUD API endpoints and NHTSA integration."""

import logging
import datetime as dt
import httpx
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import OperationalError
from typing import Optional

from app.database import get_db
from app.models.recall import Recall
from app.models.vehicle import Vehicle
from app.models.user import User
from app.schemas.recall import (
    RecallCreate,
    RecallUpdate,
    RecallResponse,
    RecallListResponse,
)
from app.services.auth import require_auth
from app.services.nhtsa import NHTSAService
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

recalls_router = APIRouter(prefix="/api/vehicles/{vin}/recalls", tags=["Recalls"])


@recalls_router.get("", response_model=RecallListResponse)
async def list_recalls(
    vin: str,
    status: Optional[str] = None,  # 'active', 'resolved', or None for all
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get all recalls for a vehicle with optional status filtering."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Build query
    query = select(Recall).where(Recall.vin == vin)

    if status == "active":
        query = query.where(Recall.is_resolved.is_(False))
    elif status == "resolved":
        query = query.where(Recall.is_resolved.is_(True))

    query = query.order_by(Recall.is_resolved.asc(), Recall.date_announced.desc())

    # Execute query
    result = await db.execute(query)
    recalls = result.scalars().all()

    # Get counts
    active_count = sum(1 for r in recalls if not r.is_resolved)
    resolved_count = sum(1 for r in recalls if r.is_resolved)

    return RecallListResponse(
        recalls=[RecallResponse.model_validate(recall) for recall in recalls],
        total=len(recalls),
        active_count=active_count,
        resolved_count=resolved_count,
    )


@recalls_router.post("/check-nhtsa", response_model=RecallListResponse)
async def check_nhtsa_recalls(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Fetch recalls from NHTSA API and store new ones in database."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    try:
        # Fetch recalls from NHTSA
        nhtsa_service = NHTSAService()
        nhtsa_recalls = await nhtsa_service.get_vehicle_recalls(vin, db)

        # Get existing recalls
        result = await db.execute(select(Recall).where(Recall.vin == vin))
        existing_recalls = result.scalars().all()
        existing_campaign_numbers = {
            r.nhtsa_campaign_number for r in existing_recalls if r.nhtsa_campaign_number
        }

        # Add new recalls
        new_recalls_added = 0
        for nhtsa_recall in nhtsa_recalls:
            campaign_number = nhtsa_recall.get("NHTSACampaignNumber")

            # Skip if we already have this recall
            if campaign_number and campaign_number in existing_campaign_numbers:
                continue

            # Create new recall
            db_recall = Recall(
                vin=vin,
                nhtsa_campaign_number=campaign_number,
                component=nhtsa_recall.get("Component", "Unknown Component")[:200],
                summary=nhtsa_recall.get("Summary", "No summary available"),
                consequence=nhtsa_recall.get("Consequence"),
                remedy=nhtsa_recall.get("Remedy"),
                date_announced=None,  # NHTSA doesn't always provide date in consistent format
                is_resolved=False,
            )
            db.add(db_recall)
            new_recalls_added += 1

        await db.commit()

        logger.info(
            "Added %s new recalls for vehicle %s from NHTSA",
            new_recalls_added,
            sanitize_for_log(vin),
        )

        # Return updated list
        result = await db.execute(
            select(Recall)
            .where(Recall.vin == vin)
            .order_by(Recall.is_resolved.asc(), Recall.created_at.desc())
        )
        recalls = result.scalars().all()

        active_count = sum(1 for r in recalls if not r.is_resolved)
        resolved_count = sum(1 for r in recalls if r.is_resolved)

        return RecallListResponse(
            recalls=[RecallResponse.model_validate(recall) for recall in recalls],
            total=len(recalls),
            active_count=active_count,
            resolved_count=resolved_count,
        )

    except httpx.TimeoutException:
        logger.error(
            "NHTSA API timeout fetching recalls for VIN %s", sanitize_for_log(vin)
        )
        raise HTTPException(status_code=504, detail="NHTSA API request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to NHTSA API for VIN %s", sanitize_for_log(vin))
        raise HTTPException(status_code=503, detail="Cannot connect to NHTSA API")
    except httpx.HTTPStatusError as e:
        logger.error(
            "NHTSA API error fetching recalls for VIN %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(
            status_code=e.response.status_code, detail="NHTSA API error"
        )
    except OperationalError as e:
        logger.error(
            "Database error fetching recalls for VIN %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@recalls_router.post("", response_model=RecallResponse, status_code=201)
async def create_recall(
    vin: str,
    recall: RecallCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Create a new recall manually."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create recall
    db_recall = Recall(
        vin=vin,
        nhtsa_campaign_number=recall.nhtsa_campaign_number,
        component=recall.component,
        summary=recall.summary,
        consequence=recall.consequence,
        remedy=recall.remedy,
        date_announced=recall.date_announced,
        is_resolved=recall.is_resolved,
        notes=recall.notes,
    )

    if recall.is_resolved:
        db_recall.resolved_at = dt.datetime.now()

    db.add(db_recall)
    await db.commit()
    await db.refresh(db_recall)

    logger.info("Created recall %s for vehicle %s", db_recall.id, sanitize_for_log(vin))
    return RecallResponse.model_validate(db_recall)


@recalls_router.get("/{recall_id}", response_model=RecallResponse)
async def get_recall(
    vin: str,
    recall_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get a specific recall."""
    result = await db.execute(
        select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
    )
    recall = result.scalar_one_or_none()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found")

    return RecallResponse.model_validate(recall)


@recalls_router.put("/{recall_id}", response_model=RecallResponse)
async def update_recall(
    vin: str,
    recall_id: int,
    recall_update: RecallUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Update a recall."""
    result = await db.execute(
        select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
    )
    recall = result.scalar_one_or_none()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found")

    # Update fields
    update_data = recall_update.model_dump(exclude_unset=True)

    # Handle is_resolved field specially
    if "is_resolved" in update_data:
        new_resolved_status = update_data["is_resolved"]
        old_resolved_status = recall.is_resolved

        # If marking as resolved for the first time
        if new_resolved_status and not old_resolved_status:
            recall.resolved_at = dt.datetime.now()
        # If marking as unresolved
        elif not new_resolved_status and old_resolved_status:
            recall.resolved_at = None

    for field, value in update_data.items():
        setattr(recall, field, value)

    await db.commit()
    await db.refresh(recall)

    logger.info("Updated recall %s for vehicle %s", recall_id, sanitize_for_log(vin))
    return RecallResponse.model_validate(recall)


@recalls_router.delete("/{recall_id}", status_code=204)
async def delete_recall(
    vin: str,
    recall_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Delete a recall."""
    result = await db.execute(
        select(Recall).where(Recall.id == recall_id, Recall.vin == vin)
    )
    recall = result.scalar_one_or_none()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found")

    await db.execute(delete(Recall).where(Recall.id == recall_id))
    await db.commit()

    logger.info("Deleted recall %s for vehicle %s", recall_id, sanitize_for_log(vin))
    return Response(status_code=204)
