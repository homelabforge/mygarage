"""Inbound webhook endpoints for fuel, odometer, reminders, and Telegram.

Authenticated with the shared ``webhook_ingest_token`` setting via the
``X-Webhook-Token`` header. Used by the Home Assistant integration, n8n, and
the structured Telegram bot.

The token is deliberately NOT accepted as a query parameter: it would be
written verbatim into granian, Traefik, and Cloudflare access logs, none of
which this application controls.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.vehicle import Vehicle
from app.services.fuel_side_effects import (
    apply_fuel_record_side_effects,
    invalidate_cache_for_vehicle,
)
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

# Shared-secret auth with no account lockout, so cap guess rate per source IP.
# Local Limiter instance matching the established pattern in routes/auth.py.
limiter = Limiter(key_func=get_remote_address)

# fuel <vin|nickname> <odometer> <volume> [price_per_unit] [cost]
# volume may end with L, gal, or kWh; odometer may end with km/mi
_FUEL_CMD = re.compile(
    r"""^fuel\s+
        (?P<vehicle>\S+)\s+
        (?P<odo>[\d.]+)(?P<odo_unit>km|mi)?\s+
        (?P<vol>[\d.]+)(?P<vol_unit>L|l|gal|kWh|kwh|KWH)?
        (?:\s+(?P<price>[\d.]+))?
        (?:\s+(?P<cost>[\d.]+))?
        \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


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


class WebhookFuelPayload(BaseModel):
    vin: str = Field(..., max_length=17)
    date: date_type | None = None
    odometer_km: Decimal | None = None
    liters: Decimal | None = None
    kwh: Decimal | None = None
    cost: Decimal | None = None
    price_per_unit: Decimal | None = None
    price_basis: str | None = None
    is_full_tank: bool = True
    notes: str | None = None
    soc_start_pct: Decimal | None = None
    soc_end_pct: Decimal | None = None
    charge_level: str | None = None
    charge_location: str | None = None
    battery_soh_pct: Decimal | None = None
    fuel_type_used: str | None = None


class WebhookOdometerPayload(BaseModel):
    vin: str = Field(..., max_length=17)
    odometer_km: Decimal
    date: date_type | None = None
    notes: str | None = None


class WebhookCompleteReminderPayload(BaseModel):
    vin: str = Field(..., max_length=17)
    reminder_id: int


async def _resolve_vehicle(db: AsyncSession, vin_or_nick: str) -> Vehicle:
    from sqlalchemy import func

    key = vin_or_nick.strip()
    result = await db.execute(select(Vehicle).where(Vehicle.vin == key.upper()))
    vehicle = result.scalar_one_or_none()
    if vehicle:
        return vehicle
    result = await db.execute(
        select(Vehicle).where(func.lower(Vehicle.nickname) == key.lower()).limit(2)
    )
    matches = result.scalars().all()
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ambiguous nickname '{vin_or_nick}' matches multiple vehicles; use VIN instead",
        )
    if not matches:
        raise HTTPException(status_code=404, detail=f"Vehicle not found: {vin_or_nick}")
    return matches[0]


async def _create_fuel_record(db: AsyncSession, payload: WebhookFuelPayload) -> dict[str, Any]:
    vehicle = await _resolve_vehicle(db, payload.vin)
    fill_date = payload.date or date_type.today()
    price_basis = payload.price_basis
    if price_basis is None and payload.kwh is not None:
        price_basis = "per_kwh"
    elif price_basis is None and payload.liters is not None:
        price_basis = "per_volume"

    record = FuelRecord(
        vin=vehicle.vin,
        date=fill_date,
        odometer_km=payload.odometer_km,
        liters=payload.liters,
        kwh=payload.kwh,
        cost=payload.cost,
        price_per_unit=payload.price_per_unit,
        price_basis=price_basis,
        is_full_tank=payload.is_full_tank,
        notes=payload.notes,
        soc_start_pct=payload.soc_start_pct,
        soc_end_pct=payload.soc_end_pct,
        charge_level=payload.charge_level,
        charge_location=payload.charge_location,
        battery_soh_pct=payload.battery_soh_pct,
        fuel_type_used=payload.fuel_type_used or ("electric" if payload.kwh is not None else None),
    )
    db.add(record)
    await db.flush()  # populate record.id without committing
    await apply_fuel_record_side_effects(db, record)
    await db.commit()
    await db.refresh(record)
    await invalidate_cache_for_vehicle(vehicle.vin)
    return {"id": record.id, "vin": record.vin, "date": str(record.date)}


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
    return await _create_fuel_record(db, payload)


@router.post("/odometer")
@limiter.limit(settings.rate_limit_webhooks)
async def webhook_odometer(
    request: Request,
    payload: WebhookOdometerPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # In-body, not Depends: see require_webhook_token's docstring.
    await require_webhook_token(db, request.headers.get("X-Webhook-Token"))
    vehicle = await _resolve_vehicle(db, payload.vin)
    reading = OdometerRecord(
        vin=vehicle.vin,
        date=payload.date or date_type.today(),
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
    vehicle = await _resolve_vehicle(db, payload.vin)
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
    # other value makes the reminder invisible and unrecoverable.
    reminder.status = "done"
    await db.commit()
    return {"id": reminder.id, "status": reminder.status}


class TelegramUpdate(BaseModel):
    """Minimal Telegram Bot API Update subset."""

    update_id: int | None = None
    message: dict[str, Any] | None = None


def _parse_fuel_command(text: str) -> WebhookFuelPayload:
    match = _FUEL_CMD.match(text.strip())
    if not match:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unrecognized command. Use: "
                "fuel <vin|nickname> <odometer>[km|mi] <volume>[L|gal|kWh] [price] [cost]"
            ),
        )
    try:
        odo = Decimal(match.group("odo"))
        vol = Decimal(match.group("vol"))
    except (InvalidOperation, TypeError) as err:
        raise HTTPException(status_code=400, detail="Invalid numeric values") from err

    odo_unit = (match.group("odo_unit") or "km").lower()
    vol_unit = (match.group("vol_unit") or "L").lower()
    odometer_km = odo * Decimal("1.609344") if odo_unit == "mi" else odo

    liters = None
    kwh = None
    price_basis = None
    if vol_unit in ("kwh",):
        kwh = vol
        price_basis = "per_kwh"
    elif vol_unit == "gal":
        liters = vol * Decimal("3.785411784")
        price_basis = "per_volume"
    else:
        liters = vol
        price_basis = "per_volume"

    price = None
    cost = None
    if match.group("price"):
        price = Decimal(match.group("price"))
        if vol_unit == "gal" and price_basis == "per_volume":
            # Convert $/gal → $/L
            price = price / Decimal("3.785411784")
    if match.group("cost"):
        cost = Decimal(match.group("cost"))

    return WebhookFuelPayload(
        vin=match.group("vehicle"),
        odometer_km=odometer_km,
        liters=liters,
        kwh=kwh,
        price_per_unit=price,
        price_basis=price_basis,
        cost=cost,
        notes="via telegram",
    )


@router.post("/telegram")
@limiter.limit(settings.rate_limit_webhooks)
async def webhook_telegram(
    request: Request,
    update: TelegramUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Telegram bot webhook — structured text fuel commands only (no OCR).

    Enable with ``telegram_inbound_enabled=true``. Auth: same webhook ingest
    token via the ``X-Webhook-Token`` header.
    """
    # Authenticate BEFORE reporting whether Telegram ingest is enabled, so an
    # unauthenticated caller cannot probe the instance's configuration.
    await require_webhook_token(db, request.headers.get("X-Webhook-Token"))

    inbound = await SettingsService.get(db, "telegram_inbound_enabled")
    if not inbound or (inbound.value or "").lower() != "true":
        raise HTTPException(status_code=403, detail="Telegram inbound is disabled")

    message = update.message or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    # Restrict to the configured notification chat when set.
    chat_setting = await SettingsService.get(db, "telegram_chat_id")
    configured_chat = (chat_setting.value or "").strip() if chat_setting else ""
    if configured_chat and str(chat_id) != configured_chat:
        raise HTTPException(status_code=403, detail="Chat not authorized")

    if not text:
        return {"ok": True, "ignored": True}

    if text.lower() in ("help", "/help", "start", "/start"):
        return {
            "ok": True,
            "reply": (
                "MyGarage fuel bot\n"
                "fuel <vin|nickname> <odometer>[km|mi] <volume>[L|gal|kWh] [price] [cost]"
            ),
        }

    payload = _parse_fuel_command(text)
    # Resolve nickname → VIN before create
    vehicle = await _resolve_vehicle(db, payload.vin)
    payload.vin = vehicle.vin
    result = await _create_fuel_record(db, payload)
    return {"ok": True, "created": result}
