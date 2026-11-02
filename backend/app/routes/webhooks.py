"""Inbound webhook endpoints for fuel, odometer and reminders.

Authenticated with the shared ``webhook_ingest_token`` setting via the
``X-Webhook-Token`` header. Used by the Home Assistant integration and n8n.
Telegram fuel commands are fetched by ``services/telegram_poller.py``, not
posted here.

The token is deliberately NOT accepted as a query parameter: it would be
written verbatim into granian, Traefik, and Cloudflare access logs, none of
which this application controls.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date as date_type
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.services.fuel_ingest import (
    WebhookFuelPayload,
    WebhookVehicleRef,
    create_fuel_record,
    resolve_vehicle,
)
from app.services.settings_service import SettingsService
from app.utils.household_time import household_today

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Shared-secret auth with no account lockout, so cap guess rate per source IP.
# Local Limiter instance matching the established pattern in routes/auth.py.
limiter = Limiter(key_func=get_remote_address)


async def require_webhook_token(db: AsyncSession, provided_token: str | None) -> str:
    """Validate the ingest token. Empty/unset configured token -> 503.

    Deliberately NOT a FastAPI dependency: dependencies resolve before slowapi's
    endpoint wrapper runs, so a 401 raised from here would bypass the rate limit
    and leave the shared secret brute-forceable at full request rate.
    """
    setting = await SettingsService.get(db, "webhook_ingest_token")
    expected = (setting.value or "").strip() if setting else ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook ingest token is not configured",
        )
    provided = (provided_token or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token"
        )
    return provided


class WebhookOdometerPayload(WebhookVehicleRef):
    odometer_km: Decimal
    date: date_type | None = None
    notes: str | None = None


class WebhookCompleteReminderPayload(WebhookVehicleRef):
    reminder_id: int


@router.post("/fuel")
@limiter.limit(settings.rate_limit_webhooks)
async def webhook_fuel(
    request: Request,
    payload: WebhookFuelPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a fuel / charge record (metric canonical)."""
    # In-body, not Depends: see require_webhook_token's docstring.
    await require_webhook_token(db, request.headers.get("X-Webhook-Token"))
    return await create_fuel_record(db, payload)


@router.post("/odometer")
@limiter.limit(settings.rate_limit_webhooks)
async def webhook_odometer(
    request: Request,
    payload: WebhookOdometerPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # In-body, not Depends: see require_webhook_token's docstring.
    await require_webhook_token(db, request.headers.get("X-Webhook-Token"))
    vehicle = await resolve_vehicle(db, payload.vehicle_ref)
    reading = OdometerRecord(
        vin=vehicle.vin,
        date=payload.date or household_today(),
        odometer_km=payload.odometer_km,
        notes=payload.notes,
        source="webhook",
    )
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    return {"id": reading.id, "vin": reading.vin, "odometer_km": str(reading.odometer_km)}


@router.post("/reminders/complete")
@limiter.limit(settings.rate_limit_webhooks)
async def webhook_complete_reminder(
    request: Request,
    payload: WebhookCompleteReminderPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # In-body, not Depends: see require_webhook_token's docstring.
    await require_webhook_token(db, request.headers.get("X-Webhook-Token"))
    vehicle = await resolve_vehicle(db, payload.vehicle_ref)
    result = await db.execute(
        select(Reminder).where(
            Reminder.id == payload.reminder_id,
            Reminder.vin == vehicle.vin,
        )
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    # "done" is the app's completion status. reminders.py filters on
    # pending|done|dismissed and the UI renders exactly those three tabs, so any
    # other value makes the reminder invisible and unrecoverable. Routed through
    # the legacy completion so a recurring reminder still gets its successor,
    # anchored on today and the nearest readings.
    if reminder.status == "pending":
        from app.schemas.maintenance import ReminderCompleteRequest
        from app.services.maintenance_service import complete_reminder

        result = await complete_reminder(
            db,
            vehicle.vin,
            reminder.id,
            ReminderCompleteRequest(completed_date=household_today(), mode="mark_only"),
        )
        return {"id": result.reminder.id, "status": result.reminder.status}
    reminder.status = "done"
    await db.commit()
    return {"id": reminder.id, "status": reminder.status}
