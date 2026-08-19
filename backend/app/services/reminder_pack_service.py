"""Load and apply built-in reminder packs."""

from __future__ import annotations

import json
import logging
import re
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
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

PACKS_DIR = Path(__file__).resolve().parent.parent / "data" / "reminder_packs"
# Pack ids are filenames (minus .json). Reject anything that could traverse.
_PACK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _path_within_packs(path: Path) -> Path | None:
    """Return the resolved path if it stays inside PACKS_DIR, else None."""
    try:
        resolved = path.resolve()
        resolved.relative_to(PACKS_DIR.resolve())
    except ValueError, OSError:
        return None
    return resolved


def _load_pack_file(path: Path) -> ReminderPackDetail:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return ReminderPackDetail.model_validate(data)


def _pack_paths() -> dict[str, Path]:
    """Map filename stem -> resolved path for every readable pack in PACKS_DIR.

    Every path here comes from directory enumeration, never from caller input,
    so a caller-supplied id is only ever used as a dict *key*. That keeps user
    data out of path expressions entirely instead of relying on a
    validate-then-join round trip to make it safe after the fact.
    """
    index: dict[str, Path] = {}
    if not PACKS_DIR.is_dir():
        return index
    for candidate in sorted(PACKS_DIR.glob("*.json")):
        resolved = _path_within_packs(candidate)
        if resolved is None or not resolved.is_file():
            continue
        index[candidate.stem] = resolved
    return index


def list_packs() -> list[ReminderPackSummary]:
    """List all built-in reminder packs (sorted by name)."""
    packs: list[ReminderPackSummary] = []
    if not PACKS_DIR.is_dir():
        logger.warning("Reminder packs directory missing: %s", PACKS_DIR)
        return packs

    for path in _pack_paths().values():
        try:
            detail = _load_pack_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to load reminder pack %s: %s", path.name, sanitize_for_log(exc))
            continue
        packs.append(
            ReminderPackSummary(
                id=detail.id,
                name=detail.name,
                description=detail.description,
                reminder_count=len(detail.reminders),
            )
        )
    packs.sort(key=lambda p: p.name.lower())
    return packs


def get_pack(pack_id: str) -> ReminderPackDetail:
    """Load a single pack by id, or raise 404.

    ``pack_id`` is checked against a conservative identifier pattern and then
    used only as a key into the enumerated pack index, so it never becomes a
    path component. ``../`` and absolute paths 404.
    """
    if not _PACK_ID_RE.fullmatch(pack_id):
        raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")

    index = _pack_paths()
    path = index.get(pack_id)
    if path is not None:
        try:
            detail = _load_pack_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Failed to load reminder pack %s: %s",
                sanitize_for_log(pack_id),
                sanitize_for_log(exc),
            )
            raise HTTPException(status_code=500, detail="Failed to load reminder pack") from exc
        if detail.id != pack_id:
            raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")
        return detail

    # A pack's filename may differ from the id it declares, so fall back to
    # reading the declared id out of each enumerated pack.
    for resolved in index.values():
        try:
            detail = _load_pack_file(resolved)
        except OSError, json.JSONDecodeError, ValueError:
            continue
        if detail.id == pack_id:
            return detail

    raise HTTPException(status_code=404, detail=f"Reminder pack '{pack_id}' not found")


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
