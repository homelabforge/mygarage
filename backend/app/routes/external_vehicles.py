"""CRUD routes for lightweight external vehicles (customer / reference)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
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

_KIND_SETTING_KEY = {
    "reference": "family_friends_enabled",
    "customer": "customers_enabled",
}


async def _kind_enabled(db: AsyncSession, kind: str) -> bool:
    """Return True when the garage section for this external kind is enabled."""
    key = _KIND_SETTING_KEY.get(kind)
    if key is None:
        return False
    setting = await SettingsService.get(db, key)
    value = (setting.value if setting and setting.value is not None else "false").lower()
    return value in ("true", "1", "yes")


async def _require_kind_enabled(db: AsyncSession, kind: str) -> None:
    if not await _kind_enabled(db, kind):
        label = "Family & Friends" if kind == "reference" else "Customers"
        raise HTTPException(
            status_code=403,
            detail=f"{label} vehicles are disabled in Settings",
        )


async def _resolve_owner(db: AsyncSession, current_user: User | None) -> User | None:
    """Return the acting user, or None when auth is disabled (auth_mode=none).

    With auth disabled there is no session user; list/mutate all external
    vehicles (matching how the garage treats owned vehicles in none mode).
    """
    return current_user


@router.get("", response_model=ExternalVehicleListResponse)
async def list_external_vehicles(
    kind: str | None = Query(None, pattern="^(customer|reference)$"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleListResponse:
    """List external vehicles for the current user (or all when auth is off)."""
    if kind is not None:
        if not await _kind_enabled(db, kind):
            return ExternalVehicleListResponse(vehicles=[], total=0)
        allowed_kinds = {kind}
    else:
        allowed_kinds = {
            k for k in ("customer", "reference") if await _kind_enabled(db, k)
        }
        if not allowed_kinds:
            return ExternalVehicleListResponse(vehicles=[], total=0)

    owner = await _resolve_owner(db, current_user)
    stmt = select(ExternalVehicle)
    if owner is not None:
        stmt = stmt.where(ExternalVehicle.user_id == owner.id)
    if len(allowed_kinds) == 1:
        stmt = stmt.where(ExternalVehicle.kind == next(iter(allowed_kinds)))
    else:
        stmt = stmt.where(ExternalVehicle.kind.in_(allowed_kinds))
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
    """Create a customer or family reference vehicle."""
    await _require_kind_enabled(db, payload.kind)
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
    owner = await _resolve_owner(db, current_user)
    row = await _get_owned(db, vehicle_id, owner.id if owner else None)
    await _require_kind_enabled(db, row.kind)
    return ExternalVehicleResponse.model_validate(row)


@router.put("/{vehicle_id}", response_model=ExternalVehicleResponse)
async def update_external_vehicle(
    vehicle_id: int,
    payload: ExternalVehicleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> ExternalVehicleResponse:
    owner = await _resolve_owner(db, current_user)
    row = await _get_owned(db, vehicle_id, owner.id if owner else None)
    await _require_kind_enabled(db, row.kind)
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
    owner = await _resolve_owner(db, current_user)
    row = await _get_owned(db, vehicle_id, owner.id if owner else None)
    await _require_kind_enabled(db, row.kind)
    await db.delete(row)
    await db.commit()


async def _get_owned(
    db: AsyncSession, vehicle_id: int, user_id: int | None
) -> ExternalVehicle:
    stmt = select(ExternalVehicle).where(ExternalVehicle.id == vehicle_id)
    if user_id is not None:
        stmt = stmt.where(ExternalVehicle.user_id == user_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="External vehicle not found")
    return row
