"""Global search across vehicles and reminders."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.reminder import Reminder
from app.models.user import User
from app.services.auth import accessible_vehicles, require_auth

router = APIRouter(prefix="/api/search", tags=["Search"])


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so a literal % or _ in the query stays literal.

    Without this, searching "50%" matches every reminder and "a_b" matches "axb".
    The backslash escape is declared on the ilike() call below.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    vehicles = await accessible_vehicles(db, current_user)
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
        # Match in SQL, not in Python after the fact. Filtering a LIMITed page
        # meant a reminder outside the newest `limit` rows could never be found,
        # so a real match reported "no results".
        pattern = f"%{_escape_like(needle)}%"
        reminder_result = await db.execute(
            select(Reminder)
            .where(
                Reminder.vin.in_(vins),
                Reminder.status == "pending",
                or_(
                    Reminder.title.ilike(pattern, escape="\\"),
                    Reminder.notes.ilike(pattern, escape="\\"),
                ),
            )
            .order_by(Reminder.created_at.desc())
            .limit(limit)
        )
        for reminder in reminder_result.scalars().all():
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
