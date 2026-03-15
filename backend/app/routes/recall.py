"""Recall CRUD API endpoints and NHTSA integration."""

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.recall import (
    RecallCreate,
    RecallListResponse,
    RecallResponse,
    RecallUpdate,
)
from app.services.auth import require_auth
from app.services.recall_service import RecallService

logger = logging.getLogger(__name__)

recalls_router = APIRouter(prefix="/api/vehicles/{vin}/recalls", tags=["Recalls"])


@recalls_router.get("", response_model=RecallListResponse)
async def list_recalls(
    vin: str,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get all recalls for a vehicle with optional status filtering."""
    service = RecallService(db)
    return await service.list_recalls(vin, current_user, status=status)


@recalls_router.post("/check-nhtsa", response_model=RecallListResponse)
async def check_nhtsa_recalls(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Fetch recalls from NHTSA API and store new ones in database."""
    service = RecallService(db)
    return await service.check_nhtsa(vin, current_user)


@recalls_router.post("", response_model=RecallResponse, status_code=201)
async def create_recall(
    vin: str,
    recall: RecallCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Create a new recall manually."""
    service = RecallService(db)
    return await service.create_recall(vin, recall, current_user)


@recalls_router.get("/{recall_id}", response_model=RecallResponse)
async def get_recall(
    vin: str,
    recall_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get a specific recall."""
    service = RecallService(db)
    return await service.get_recall(vin, recall_id, current_user)


@recalls_router.put("/{recall_id}", response_model=RecallResponse)
async def update_recall(
    vin: str,
    recall_id: int,
    recall_update: RecallUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Update a recall."""
    service = RecallService(db)
    return await service.update_recall(vin, recall_id, recall_update, current_user)


@recalls_router.delete("/{recall_id}", status_code=204)
async def delete_recall(
    vin: str,
    recall_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Delete a recall."""
    service = RecallService(db)
    await service.delete_recall(vin, recall_id, current_user)
    return Response(status_code=204)
