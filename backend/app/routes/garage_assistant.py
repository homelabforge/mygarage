"""Ask My Garage assistant routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.garage_assistant import GarageAssistantChatRequest, GarageAssistantChatResponse
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.garage_assistant_service import ask_garage

router = APIRouter(prefix="/api/vehicles/{vin}/assistant", tags=["Garage Assistant"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/chat", response_model=GarageAssistantChatResponse)
@limiter.limit(settings.rate_limit_uploads)
async def garage_assistant_chat(
    request: Request,
    vin: str,
    body: GarageAssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> GarageAssistantChatResponse:
    """Ask a grounded question about this vehicle (specs, history, diagnostics).

    Requires ``llm_garage_assistant_enabled``. Answers use garage records and
    curated DTC enrichment only — never persists chat history.
    """
    vin = vin.upper().strip()
    # POST for payload size / rate limits only — no garage writes.
    await get_vehicle_or_403(vin, current_user, db)  # tripwire: read-only

    return await ask_garage(
        db,
        vin=vin,
        message=body.message,
        history=body.history,
    )
