"""Load and apply built-in reminder packs."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.reminder import ReminderCreate, ReminderResponse
from app.schemas.reminder_pack import ReminderPackDetail, ReminderPackSummary
from app.services import reminder_service
from app.services.reminder_service import get_current_hours, get_current_mileage

logger = logging.getLogger(__name__)

PACKS_DIR = Path(__file__).resolve().parent.parent / "data" / "reminder_packs"


def _load_pack_file(path: Path) -> ReminderPackDetail:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return ReminderPackDetail.model_validate(data)


def list_packs(vehicle_type: str | None = None) -> list[ReminderPackSummary]:
    """List built-in reminder packs (sorted by name).

    When ``vehicle_type`` is provided, packs that declare a non-empty
    ``vehicle_types`` list are included only if that type is listed.
    Packs with an empty ``vehicle_types`` list apply to every vehicle.
    """
    packs: list[ReminderPackSummary] = []
    if not PACKS_DIR.is_dir():
        logger.warning("Reminder packs directory missing: %s", PACKS_DIR)
        return packs

    for path in sorted(PACKS_DIR.glob("*.json")):
        try:
            detail = _load_pack_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to load reminder pack %s: %s", path.name, exc)
            continue
        if vehicle_type and detail.vehicle_types and vehicle_type not in detail.vehicle_types:
            continue
        packs.append(
            ReminderPackSummary(
                id=detail.id,
                name=detail.name,
                description=detail.description,
                reminder_count=len(detail.reminders),
                vehicle_types=list(detail.vehicle_types),
            )
        )
    packs.sort(key=lambda p: p.name.lower())
    return packs


def get_pack(pack_id: str) -> ReminderPackDetail:
    """Load a single pack by id, or raise 404."""
    path = PACKS_DIR / f"{pack_id}.json"
    if not path.is_file():
        # Allow id mismatch with filename by scanning
        for candidate in PACKS_DIR.glob("*.json"):
            try:
                detail = _load_pack_file(candidate)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if detail.id == pack_id:
                return detail
        raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")

    try:
        detail = _load_pack_file(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to load reminder pack %s: %s", pack_id, exc)
        raise HTTPException(status_code=500, detail="Failed to load reminder pack") from exc

    if detail.id != pack_id:
        raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")
    return detail


async def apply_pack(
    vin: str,
    pack_id: str,
    db: AsyncSession,
) -> list[ReminderResponse]:
    """Apply a reminder pack to a vehicle.

    - ``due_date`` is resolved from today + ``due_date_offset_days`` when set.
    - ``due_mileage_km`` / ``due_hours`` in packs are treated as *intervals*
      when a current reading exists (current + interval); otherwise used as-is.
    """
    pack = get_pack(pack_id)
    today = date.today()
    current_km = await get_current_mileage(vin, db)
    current_hours = await get_current_hours(vin, db)

    created: list[ReminderResponse] = []
    for item in pack.reminders:
        due_date: date | None = None
        if item.due_date_offset_days is not None:
            due_date = today + timedelta(days=item.due_date_offset_days)

        due_mileage_km: Decimal | None = None
        if item.due_mileage_km is not None:
            interval = Decimal(str(item.due_mileage_km))
            if current_km is not None:
                due_mileage_km = current_km + interval
            else:
                due_mileage_km = interval

        due_hours: Decimal | None = None
        if item.due_hours is not None:
            interval_h = Decimal(str(item.due_hours))
            if current_hours is not None:
                due_hours = current_hours + interval_h
            else:
                due_hours = interval_h

        try:
            data = ReminderCreate(
                title=item.title,
                reminder_type=item.reminder_type,  # type: ignore[arg-type]
                due_date=due_date,
                due_mileage_km=due_mileage_km,
                due_hours=due_hours,
                notes=item.notes,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reminder in pack '{pack_id}': {exc.errors()}",
            ) from exc

        reminder = await reminder_service.create_reminder(vin, data, db)
        await db.flush()
        created.append(await reminder_service.enrich_with_estimate(reminder, db))

    return created
