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
    """Return True when the Family & Friends garage section is enabled."""
    setting = await SettingsService.get(db, "family_friends_enabled")
    value = (setting.value if setting and setting.value is not None else "false").lower()
    return value in ("true", "1", "yes")


async def _require_family_friends_enabled(db: AsyncSession) -> None:
    if not await _family_friends_enabled(db):
        raise HTTPException(
            status_code=403,
            detail="Family & Friends vehicles are disabled in Settings",
        )


async def _resolve_owner(db: AsyncSession, current_user: User | None) -> User | None:
    """Return the acting user, or None when auth is disabled (auth_mode=none).

    With auth disabled there is no session user; list/mutate all external
    vehicles (matching how the garage treats owned vehicles in none mode).
    """
    return current_user


@router.get("", response_model=ExternalVehicleListResponse)
async def list_external_vehicles(
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleListResponse:
    """List external vehicles for the current user (or all when auth is off)."""
    if not await _family_friends_enabled(db):
        return ExternalVehicleListResponse(vehicles=[], total=0)

    owner = await _resolve_owner(db, current_user)
    stmt = select(ExternalVehicle)
    if owner is not None:
        stmt = stmt.where(ExternalVehicle.user_id == owner.id)
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
    owner = await _resolve_owner(db, current_user)
    if owner is None:
        # auth_mode=none: attach to the first user if one exists, else invent a
        # lightweight owner row so the NOT NULL FK is satisfied.
        result = await db.execute(select(User).order_by(User.id.asc()).limit(1))
        owner = result.scalar_one_or_none()
        if owner is None:
            owner = User(
                username="local",
                email="local@localhost",
                hashed_password="!",
                is_active=True,
                is_admin=True,
            )
            db.add(owner)
            await db.flush()
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
    owner = await _resolve_owner(db, current_user)
    row = await _get_owned(db, vehicle_id, owner.id if owner else None)
    return ExternalVehicleResponse.model_validate(row)


@router.put("/{vehicle_id}", response_model=ExternalVehicleResponse)
async def update_external_vehicle(
    vehicle_id: int,
    payload: ExternalVehicleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleResponse:
    await _require_family_friends_enabled(db)
    owner = await _resolve_owner(db, current_user)
    row = await _get_owned(db, vehicle_id, owner.id if owner else None)
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
    owner = await _resolve_owner(db, current_user)
    row = await _get_owned(db, vehicle_id, owner.id if owner else None)
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
