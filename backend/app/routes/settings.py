"""Settings API endpoints."""

import logging
import sys
import time
import datetime as dt
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db, engine
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.config import settings as app_settings
from app.services.auth import get_optional_user, get_current_admin_user
from app.schemas.settings import (
    SettingCreate,
    SettingUpdate,
    SettingResponse,
    SettingsListResponse,
    SettingsBatchUpdate,
    SystemInfoResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["Settings"])

# Track application start time for uptime calculation
START_TIME = time.time()


@router.get("/public", response_model=SettingsListResponse)
async def get_public_settings(db: AsyncSession = Depends(get_db)):
    """Get public settings (no authentication required).

    Returns only non-sensitive settings required for frontend initialization:
    - auth_mode: Authentication mode (local/oidc)
    - app_name: Application name
    - theme: UI theme preference

    Security: This endpoint is intentionally public to allow frontend
    initialization before login. All sensitive settings are excluded.
    """
    # Whitelist of public settings safe for unauthenticated access
    public_keys = {"auth_mode", "app_name", "theme"}

    result = await db.execute(
        select(Setting).where(Setting.key.in_(public_keys)).order_by(Setting.key)
    )
    settings = result.scalars().all()

    return SettingsListResponse(
        settings=[SettingResponse.model_validate(s) for s in settings],
        total=len(settings)
    )


@router.get("", response_model=SettingsListResponse)
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Get all settings (admin only).

    Security Enhancement v2.10.0: Restricted to admin users only.
    Prevents unauthorized access to sensitive configuration including:
    - OIDC secrets
    - SMTP credentials
    - API keys
    - Authentication settings
    """
    result = await db.execute(select(Setting).order_by(Setting.key))
    settings = result.scalars().all()

    return SettingsListResponse(
        settings=[SettingResponse.model_validate(s) for s in settings],
        total=len(settings)
    )


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Get a specific setting by key (admin only)."""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return SettingResponse.model_validate(setting)


@router.post("", response_model=SettingResponse, status_code=201)
async def create_setting(
    setting: SettingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Create a new setting (admin only)."""
    # Check if setting already exists
    result = await db.execute(select(Setting).where(Setting.key == setting.key))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail=f"Setting '{setting.key}' already exists")

    # Create new setting
    db_setting = Setting(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=dt.datetime.now()
    )

    db.add(db_setting)
    await db.commit()
    await db.refresh(db_setting)

    logger.info("Created setting: %s", setting.key)
    return SettingResponse.model_validate(db_setting)


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    key: str,
    setting_update: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Update a setting (admin only)."""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Update fields
    update_data = setting_update.model_dump(exclude_unset=True)

    # Security: Log warning when disabling authentication
    if key == 'auth_mode' and 'value' in update_data:
        new_auth_mode = update_data['value']
        if new_auth_mode == 'none':
            logger.warning(
                "⚠️  SECURITY WARNING: Authentication is being disabled (auth_mode='none'). "
                "This exposes your application to unauthorized access. Use with caution!"
            )

    for field, value in update_data.items():
        setattr(setting, field, value)

    setting.updated_at = dt.datetime.now()

    await db.commit()
    await db.refresh(setting)

    logger.info("Updated setting: %s", key)
    return SettingResponse.model_validate(setting)


@router.post("/batch", response_model=SettingsListResponse)
async def batch_update_settings(
    batch: SettingsBatchUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Batch update or create multiple settings (admin only)."""
    updated_settings = []

    # Security: Log warning when disabling authentication
    if 'auth_mode' in batch.settings and batch.settings['auth_mode'] == 'none':
        logger.warning(
            "⚠️  SECURITY WARNING: Authentication is being disabled (auth_mode='none'). "
            "This exposes your application to unauthorized access. Use with caution!"
        )

    for key, value in batch.settings.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()

        if setting:
            # Update existing
            setting.value = value
            setting.updated_at = dt.datetime.now()
        else:
            # Create new
            setting = Setting(
                key=key,
                value=value,
                updated_at=dt.datetime.now()
            )
            db.add(setting)

        updated_settings.append(setting)

    await db.commit()

    # Refresh all settings
    for setting in updated_settings:
        await db.refresh(setting)

    logger.info("Batch updated %s settings", len(updated_settings))

    return SettingsListResponse(
        settings=[SettingResponse.model_validate(s) for s in updated_settings],
        total=len(updated_settings)
    )


@router.delete("/{key}", status_code=204)
async def delete_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Delete a setting (admin only)."""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    await db.delete(setting)
    await db.commit()

    logger.info("Deleted setting: %s", key)
    return Response(status_code=204)


@router.get("/system/info", response_model=SystemInfoResponse)
async def get_system_info(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user)
):
    """Get system information and statistics (admin only)."""
    # Count total vehicles
    result = await db.execute(select(func.count(Vehicle.vin)))
    total_vehicles = result.scalar() or 0

    # Get database size
    database_path = Path(str(engine.url).replace("sqlite+aiosqlite:///", ""))
    database_size_mb = 0.0
    if database_path.exists():
        database_size_mb = database_path.stat().st_size / (1024 * 1024)

    # Calculate uptime
    uptime_seconds = time.time() - START_TIME

    return SystemInfoResponse(
        app_name=app_settings.app_name,
        app_version=app_settings.app_version,
        python_version=sys.version.split()[0],
        database_url=str(engine.url).replace(str(database_path), "***"),
        data_directory=str(app_settings.data_dir),
        total_vehicles=total_vehicles,
        database_size_mb=round(database_size_mb, 2),
        uptime_seconds=round(uptime_seconds, 0)
    )
