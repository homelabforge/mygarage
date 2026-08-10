"""Global search across vehicles and reminders."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.reminder import Reminder
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.services.auth import require_auth

router = APIRouter(prefix="/api/search", tags=["Search"])


class SearchHit(BaseModel):
    """A single search result."""

    type: Literal["vehicle", "reminder"]
    id: str
    title: str
    subtitle: str | None = None
    vin: str | None = None
    href: str


class SearchResponse(BaseModel):
    """Global search response."""

    query: str
    results: list[SearchHit] = Field(default_factory=list)


async def _accessible_vehicles(
    db: AsyncSession,
    current_user: User | None,
) -> list[Vehicle]:
    """Owned + shared (or all when auth is disabled), non-archived."""
    if current_user is None:
        result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
        return list(result.scalars().all())

    owned_result = await db.execute(
        select(Vehicle).where(
            Vehicle.user_id == current_user.id,
            Vehicle.archived_at.is_(None),
        )
    )
    owned = list(owned_result.scalars().all())
    owned_vins = {v.vin for v in owned}

    shared_query = (
        select(Vehicle)
        .join(VehicleShare, VehicleShare.vehicle_vin == Vehicle.vin)
        .where(
            VehicleShare.user_id == current_user.id,
            Vehicle.archived_at.is_(None),
        )
    )
    if owned_vins:
        shared_query = shared_query.where(Vehicle.vin.not_in(owned_vins))
    shared_result = await db.execute(shared_query)
    return owned + list(shared_result.scalars().all())


@router.get("", response_model=SearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, max_length=100, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> SearchResponse:
    """Search vehicles (nickname/VIN/plate/make/model) and pending reminders."""
    query = q.strip()
    if not query:
        return SearchResponse(query=q, results=[])

    vehicles = await _accessible_vehicles(db, current_user)
    vins = [v.vin for v in vehicles]
    vin_lookup = {v.vin: v for v in vehicles}
    needle = query.lower()

    results: list[SearchHit] = []

    for vehicle in vehicles:
        haystacks = [
            vehicle.nickname or "",
            vehicle.vin or "",
            vehicle.license_plate or "",
            vehicle.make or "",
            vehicle.model or "",
            f"{vehicle.year or ''} {vehicle.make or ''} {vehicle.model or ''}".strip(),
        ]
        if any(needle in (h or "").lower() for h in haystacks):
            label = vehicle.nickname or vehicle.vin
            subtitle_parts = [
                str(vehicle.year) if vehicle.year else None,
                vehicle.make,
                vehicle.model,
            ]
            results.append(
                SearchHit(
                    type="vehicle",
                    id=vehicle.vin,
                    title=label,
                    subtitle=" ".join(p for p in subtitle_parts if p) or None,
                    vin=vehicle.vin,
                    href=f"/vehicles/{vehicle.vin}",
                )
            )
        if len(results) >= limit:
            return SearchResponse(query=query, results=results[:limit])

    if vins:
        reminder_result = await db.execute(
            select(Reminder)
            .where(Reminder.vin.in_(vins), Reminder.status == "pending")
            .order_by(Reminder.created_at.desc())
            .limit(limit)
        )
        for reminder in reminder_result.scalars().all():
            if needle not in (reminder.title or "").lower():
                if reminder.notes and needle in reminder.notes.lower():
                    pass
                else:
                    continue
            vehicle = vin_lookup.get(reminder.vin)
            results.append(
                SearchHit(
                    type="reminder",
                    id=str(reminder.id),
                    title=reminder.title,
                    subtitle=vehicle.nickname if vehicle else reminder.vin,
                    vin=reminder.vin,
                    href=f"/vehicles/{reminder.vin}?tab=reminders",
                )
            )
            if len(results) >= limit:
                break

    return SearchResponse(query=query, results=results[:limit])
