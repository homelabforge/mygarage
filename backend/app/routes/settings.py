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
from app.services.auth import get_current_admin_user
from app.services.settings_service import SettingsService
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
        total=len(settings),
    )


@router.get("", response_model=SettingsListResponse)
async def list_settings(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
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
        total=len(settings),
    )


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
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
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Create a new setting (admin only)."""
    # Check if setting already exists
    result = await db.execute(select(Setting).where(Setting.key == setting.key))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=400, detail=f"Setting '{setting.key}' already exists"
        )

    # Create new setting
    db_setting = Setting(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=dt.datetime.now(),
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
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Update a setting (admin only)."""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()

    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    # Update fields
    update_data = setting_update.model_dump(exclude_unset=True)

    # Security: Log warning when disabling authentication
    if key == "auth_mode" and "value" in update_data:
        new_auth_mode = update_data["value"]
        if new_auth_mode == "none":
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
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Batch update or create multiple settings (admin only)."""
    updated_settings = []

    # Security: Log warning when disabling authentication
    if "auth_mode" in batch.settings and batch.settings["auth_mode"] == "none":
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
            setting = Setting(key=key, value=value, updated_at=dt.datetime.now())
            db.add(setting)

        updated_settings.append(setting)

    await db.commit()

    # Refresh all settings
    for setting in updated_settings:
        await db.refresh(setting)

    logger.info("Batch updated %s settings", len(updated_settings))

    return SettingsListResponse(
        settings=[SettingResponse.model_validate(s) for s in updated_settings],
        total=len(updated_settings),
    )


@router.delete("/{key}", status_code=204)
async def delete_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
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
    current_user: Optional[User] = Depends(get_current_admin_user),
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
        uptime_seconds=round(uptime_seconds, 0),
    )


# POI Provider Management Endpoints


@router.get("/poi-providers")
async def get_poi_providers(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Get configured POI search providers (admin only).

    Returns list of all configured providers with their status, API limits,
    and configuration. API keys are masked for security.

    Returns:
        List of provider configurations
    """
    # Load provider configurations from settings
    providers = []

    # Check TomTom
    tomtom_enabled_setting = await SettingsService.get(db, "tomtom_enabled")
    tomtom_enabled = (
        tomtom_enabled_setting.value.lower() == "true"
        if tomtom_enabled_setting
        else False
    )

    tomtom_key_setting = await SettingsService.get(db, "tomtom_api_key")
    tomtom_api_key = tomtom_key_setting.value if tomtom_key_setting else ""

    providers.append(
        {
            "name": "tomtom",
            "display_name": "TomTom Places API",
            "enabled": tomtom_enabled and bool(tomtom_api_key),
            "is_default": False,
            "api_key_configured": bool(tomtom_api_key),
            "api_key_masked": (
                f"{tomtom_api_key[:8]}***" if len(tomtom_api_key) > 8 else "***"
            )
            if tomtom_api_key
            else None,
            "api_usage": 0,  # TODO: Implement usage tracking
            "api_limit": 2500,  # TomTom free tier
            "priority": 1,
        }
    )

    # OSM is always available (default fallback)
    providers.append(
        {
            "name": "osm",
            "display_name": "OpenStreetMap (OSM)",
            "enabled": True,
            "is_default": True,
            "api_key_configured": True,  # No API key needed
            "api_key_masked": None,
            "api_usage": 0,
            "api_limit": None,  # Unlimited
            "priority": 99,  # Lowest priority (fallback)
        }
    )

    # Sort by priority
    providers.sort(key=lambda x: x["priority"])

    return {"providers": providers}


@router.post("/poi-providers")
async def add_poi_provider(
    provider_config: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Add or update POI provider configuration (admin only).

    Args:
        provider_config: Provider configuration with name, api_key, enabled

    Returns:
        Updated provider configuration

    Raises:
        HTTPException: 400 if provider name invalid or API key validation fails
    """
    provider_name = provider_config.get("name")
    api_key = provider_config.get("api_key", "")
    enabled = provider_config.get("enabled", True)

    if not provider_name:
        raise HTTPException(status_code=400, detail="Provider name is required")

    # Validate provider name
    valid_providers = ["tomtom", "google", "yelp", "foursquare", "geoapify", "mapbox"]
    if provider_name not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider_name}. Must be one of: {', '.join(valid_providers)}",
        )

    # OSM cannot be configured (always available)
    if provider_name == "osm":
        raise HTTPException(
            status_code=400, detail="OSM provider cannot be configured (always available)"
        )

    # Validate API key (basic check - just ensure it's not empty if enabling)
    if enabled and not api_key:
        raise HTTPException(
            status_code=400, detail="API key is required when enabling provider"
        )

    # Save provider settings
    await SettingsService.set(db, f"{provider_name}_enabled", str(enabled).lower())
    await SettingsService.set(db, f"{provider_name}_api_key", api_key)

    logger.info("Updated POI provider %s (enabled=%s)", provider_name, enabled)

    # Return updated configuration (with masked key)
    return {
        "name": provider_name,
        "enabled": enabled,
        "api_key_masked": f"{api_key[:8]}***" if len(api_key) > 8 else "***",
    }


@router.put("/poi-providers/{provider_name}")
async def update_poi_provider(
    provider_name: str,
    provider_config: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Update POI provider configuration (admin only).

    Args:
        provider_name: Provider name (tomtom, google, etc.)
        provider_config: Updated configuration with api_key, enabled

    Returns:
        Updated provider configuration

    Raises:
        HTTPException: 400 if provider name invalid
    """
    # Validate provider name
    valid_providers = ["tomtom", "google", "yelp", "foursquare", "geoapify", "mapbox"]
    if provider_name not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider_name}. Must be one of: {', '.join(valid_providers)}",
        )

    # OSM cannot be configured
    if provider_name == "osm":
        raise HTTPException(
            status_code=400, detail="OSM provider cannot be configured (always available)"
        )

    # Update settings
    api_key = provider_config.get("api_key")
    enabled = provider_config.get("enabled")

    if enabled is not None:
        await SettingsService.set(db, f"{provider_name}_enabled", str(enabled).lower())

    if api_key is not None:
        await SettingsService.set(db, f"{provider_name}_api_key", api_key)

    logger.info("Updated POI provider %s", provider_name)

    return {
        "name": provider_name,
        "enabled": enabled if enabled is not None else True,
        "api_key_masked": f"{api_key[:8]}***" if api_key and len(api_key) > 8 else "***",
    }


@router.delete("/poi-providers/{provider_name}")
async def delete_poi_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Remove POI provider configuration (admin only).

    Args:
        provider_name: Provider name to remove

    Returns:
        None (204 No Content)

    Raises:
        HTTPException: 400 if trying to delete OSM (cannot be removed)
    """
    if provider_name == "osm":
        raise HTTPException(
            status_code=400, detail="OSM provider cannot be removed (default fallback)"
        )

    # Delete provider settings
    await SettingsService.delete(db, f"{provider_name}_enabled")
    await SettingsService.delete(db, f"{provider_name}_api_key")

    logger.info("Deleted POI provider %s", provider_name)

    return Response(status_code=204)


@router.post("/poi-providers/{provider_name}/test")
async def test_poi_provider(
    provider_name: str,
    test_config: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_admin_user),
):
    """Test POI provider API key (admin only).

    Makes a simple API call to validate the key works.

    Args:
        provider_name: Provider name to test
        test_config: Configuration with api_key to test

    Returns:
        dict with valid=True/False and error message if invalid

    Raises:
        HTTPException: 400 if provider name invalid
    """
    import httpx
    from app.utils.url_validation import validate_tomtom_url

    api_key = test_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required for testing")

    # Test different providers
    try:
        if provider_name == "tomtom":
            # Test TomTom with simple search
            url = f"{app_settings.tomtom_api_base_url}/search/auto repair.json"
            validate_tomtom_url(url)
            params = {"key": api_key, "lat": 37.7749, "lon": -122.4194, "limit": 1}

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()

            return {"valid": True, "message": "TomTom API key is valid"}

        elif provider_name == "osm":
            return {"valid": True, "message": "OSM requires no API key"}

        else:
            # TODO: Implement tests for other providers (Google, Yelp, etc.)
            raise HTTPException(
                status_code=400,
                detail=f"Testing not yet implemented for provider: {provider_name}",
            )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401 or e.response.status_code == 403:
            return {"valid": False, "message": "API key is invalid or unauthorized"}
        return {"valid": False, "message": f"API error: {e.response.status_code}"}
    except Exception as e:
        logger.error("Provider test failed for %s: %s", provider_name, str(e))
        return {"valid": False, "message": f"Test failed: {str(e)}"}
