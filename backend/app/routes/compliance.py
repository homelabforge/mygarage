"""GET /api/vehicles/{vin}/compliance: what the vehicle's country asks of it."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.compliance import ComplianceResponse
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.compliance_service import compliance_for_vehicle

router = APIRouter(prefix="/api/vehicles/{vin}/compliance", tags=["compliance"])


@router.get("", response_model=ComplianceResponse)
async def get_vehicle_compliance(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> ComplianceResponse:
    """The low-emission-zone class, the next periodic inspection and the Euro
    class of the vehicle under its country's rules. Read-only; indicative."""
    vin = vin.upper().strip()
    vehicle = await get_vehicle_or_403(vin, current_user, db)
    return await compliance_for_vehicle(db, vehicle)
