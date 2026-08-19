"""CRUD routes for lightweight external vehicles (family/friend reference)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.external_vehicle import ExternalVehicle
from app.models.user import User
from app.schemas.external_vehicle import (
    ExternalVehicleCreate,
    ExternalVehicleListResponse,
    ExternalVehicleResponse,
    ExternalVehicleUpdate,
)
from app.services.auth import require_auth
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/external-vehicles", tags=["external-vehicles"])


async def _family_friends_enabled(db: AsyncSession) -> bool:
    """Return True when Family & Friends reference vehicles are enabled."""
    setting = await SettingsService.get(db, "family_friends_enabled")
    value = (setting.value if setting and setting.value is not None else "false").lower()
    return value in ("true", "1", "yes")


async def _require_family_friends_enabled(db: AsyncSession) -> None:
    if not await _family_friends_enabled(db):
        raise HTTPException(
            status_code=403,
            detail="Family & Friends vehicles are disabled in Settings",
        )


async def _owner_for_create(db: AsyncSession, current_user: User | None) -> User:
    """Resolve the owner for a new external vehicle.

    auth_mode=none has no session user. Attach to the first existing user if
    one exists; do not invent an account (that row would block later
    registration when switching to auth_mode=local).
    """
    if current_user is not None:
        return current_user
    result = await db.execute(select(User).order_by(User.id.asc()).limit(1))
    owner = result.scalar_one_or_none()
    if owner is None:
        raise HTTPException(
            status_code=400,
            detail="Create a user before adding Family & Friends vehicles",
        )
    return owner


@router.get("", response_model=ExternalVehicleListResponse)
async def list_external_vehicles(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleListResponse:
    """List external vehicles for the current user (or all when auth is off)."""
    if not await _family_friends_enabled(db):
        return ExternalVehicleListResponse(vehicles=[], total=0)

    stmt = select(ExternalVehicle)
    if current_user is not None:
        stmt = stmt.where(ExternalVehicle.user_id == current_user.id)
    stmt = stmt.order_by(ExternalVehicle.nickname.asc())
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return ExternalVehicleListResponse(
        vehicles=[ExternalVehicleResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.post("", response_model=ExternalVehicleResponse, status_code=201)
async def create_external_vehicle(
    payload: ExternalVehicleCreate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleResponse:
    """Create a family/friend reference vehicle."""
    await _require_family_friends_enabled(db)
    owner = await _owner_for_create(db, current_user)
    row = ExternalVehicle(user_id=owner.id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ExternalVehicleResponse.model_validate(row)


@router.get("/{vehicle_id}", response_model=ExternalVehicleResponse)
async def get_external_vehicle(
    vehicle_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleResponse:
    await _require_family_friends_enabled(db)
    row = await _get_owned(db, vehicle_id, current_user.id if current_user else None)
    return ExternalVehicleResponse.model_validate(row)


@router.put("/{vehicle_id}", response_model=ExternalVehicleResponse)
async def update_external_vehicle(
    vehicle_id: int,
    payload: ExternalVehicleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleResponse:
    await _require_family_friends_enabled(db)
    row = await _get_owned(db, vehicle_id, current_user.id if current_user else None)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return ExternalVehicleResponse.model_validate(row)


@router.delete("/{vehicle_id}", status_code=204)
async def delete_external_vehicle(
    vehicle_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> None:
    await _require_family_friends_enabled(db)
    row = await _get_owned(db, vehicle_id, current_user.id if current_user else None)
    await db.delete(row)
    await db.commit()


async def _get_owned(db: AsyncSession, vehicle_id: int, user_id: int | None) -> ExternalVehicle:
    stmt = select(ExternalVehicle).where(ExternalVehicle.id == vehicle_id)
    if user_id is not None:
        stmt = stmt.where(ExternalVehicle.user_id == user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="External vehicle not found")
    return row
