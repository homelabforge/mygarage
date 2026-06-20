"""LiveLink admin endpoints for settings, devices, and parameters."""

import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession


class FirmwareTrack(str, Enum):
    """Firmware track selector for WiCAN device families."""

    obd = "obd"
    pro = "pro"


from app.database import get_db
from app.models.user import User
from app.schemas.dtc import DTCDefinitionResponse, DTCSearchResponse
from app.schemas.livelink import (
    DeviceCommandRequest,
    DeviceCommandResponse,
    DeviceFirmwareStatus,
    FirmwareInfoResponse,
    LiveLinkDeviceListResponse,
    LiveLinkDeviceResponse,
    LiveLinkDeviceUpdate,
    LiveLinkParameterListResponse,
    LiveLinkParameterResponse,
    LiveLinkParameterUpdate,
    LiveLinkSettingsResponse,
    LiveLinkSettingsUpdate,
    MQTTSettingsResponse,
    MQTTSettingsUpdate,
    MQTTStatusResponse,
    MQTTTestResult,
    TokenGenerateResponse,
    TokenInfoResponse,
)
from app.services.auth import (
    get_current_admin_user,
    get_vehicle_for_owner_or_403,
    require_auth,
)
from app.services.dtc_service import DTCService
from app.services.firmware_service import FirmwareService
from app.services.livelink_service import LiveLinkService
from app.services.settings_service import SettingsService
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/livelink", tags=["LiveLink Admin"])


# =============================================================================
# Settings Endpoints
# =============================================================================


@router.get("/settings", response_model=LiveLinkSettingsResponse)
async def get_livelink_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Get LiveLink settings.

    **Security:**
    - Requires authentication
    """
    service = LiveLinkService(db)

    # Check if global token exists
    token_hash = await SettingsService.get(db, "livelink_global_token_hash")
    has_global_token = bool(token_hash and token_hash.value)

    # Build ingestion URL
    base_url = await SettingsService.get(db, "app_base_url")
    ingestion_url = f"{base_url.value if base_url else ''}/api/v1/livelink/ingest"

    return LiveLinkSettingsResponse(
        enabled=await service.is_enabled(),
        has_global_token=has_global_token,
        ingestion_url=ingestion_url,
        telemetry_retention_days=await service.get_retention_days(),
        session_timeout_minutes=await service.get_session_timeout_minutes(),
        device_offline_timeout_minutes=await service.get_device_offline_timeout_minutes(),
        daily_aggregation_enabled=await _get_bool_setting(
            db, "livelink_daily_aggregation_enabled", True
        ),
        firmware_check_enabled=await _get_bool_setting(db, "livelink_firmware_check_enabled", True),
        alert_cooldown_minutes=await service.get_alert_cooldown_minutes(),
        session_grace_period_seconds=await service.get_session_grace_period_seconds(),
        notify_device_offline=await _get_bool_setting(db, "livelink_notify_device_offline", True),
        notify_threshold_alerts=await _get_bool_setting(
            db, "livelink_notify_threshold_alerts", True
        ),
        notify_firmware_update=await _get_bool_setting(db, "livelink_notify_firmware_update", True),
        notify_new_device=await _get_bool_setting(db, "livelink_notify_new_device", True),
    )


@router.put("/settings", response_model=LiveLinkSettingsResponse)
async def update_livelink_settings(
    updates: LiveLinkSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Update LiveLink settings.

    **Security:**
    - Requires authentication
    """
    # Update each provided setting
    if updates.enabled is not None:
        await SettingsService.set(db, "livelink_enabled", str(updates.enabled).lower())
    if updates.telemetry_retention_days is not None:
        await SettingsService.set(
            db, "livelink_telemetry_retention_days", str(updates.telemetry_retention_days)
        )
    if updates.session_timeout_minutes is not None:
        await SettingsService.set(
            db, "livelink_session_timeout_minutes", str(updates.session_timeout_minutes)
        )
    if updates.device_offline_timeout_minutes is not None:
        await SettingsService.set(
            db,
            "livelink_device_offline_timeout_minutes",
            str(updates.device_offline_timeout_minutes),
        )
    if updates.daily_aggregation_enabled is not None:
        await SettingsService.set(
            db, "livelink_daily_aggregation_enabled", str(updates.daily_aggregation_enabled).lower()
        )
    if updates.firmware_check_enabled is not None:
        await SettingsService.set(
            db, "livelink_firmware_check_enabled", str(updates.firmware_check_enabled).lower()
        )
    if updates.alert_cooldown_minutes is not None:
        await SettingsService.set(
            db, "livelink_alert_cooldown_minutes", str(updates.alert_cooldown_minutes)
        )
    if updates.session_grace_period_seconds is not None:
        await SettingsService.set(
            db,
            "livelink_session_grace_period_seconds",
            str(updates.session_grace_period_seconds),
        )
    if updates.notify_device_offline is not None:
        await SettingsService.set(
            db, "livelink_notify_device_offline", str(updates.notify_device_offline).lower()
        )
    if updates.notify_threshold_alerts is not None:
        await SettingsService.set(
            db, "livelink_notify_threshold_alerts", str(updates.notify_threshold_alerts).lower()
        )
    if updates.notify_firmware_update is not None:
        await SettingsService.set(
            db, "livelink_notify_firmware_update", str(updates.notify_firmware_update).lower()
        )
    if updates.notify_new_device is not None:
        await SettingsService.set(
            db, "livelink_notify_new_device", str(updates.notify_new_device).lower()
        )

    await db.commit()

    # Return updated settings
    return await get_livelink_settings(db=db, current_user=current_user)


@router.post("/token", response_model=TokenGenerateResponse)
async def regenerate_global_token(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Generate a new global API token.

    **Important:** The token is only shown once. Store it securely.

    **Security:**
    - Requires authentication
    """
    service = LiveLinkService(db)
    token = await service.generate_global_token()

    return TokenGenerateResponse(
        token=token,
        expires_at=None,  # Global tokens don't expire
    )


# =============================================================================
# Device Endpoints
# =============================================================================


@router.get("/devices", response_model=LiveLinkDeviceListResponse)
async def list_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    List all discovered LiveLink devices.

    **Security:**
    - Requires authentication
    """
    service = LiveLinkService(db)
    devices = await service.list_devices()

    online_count = sum(1 for d in devices if d.device_status == "online")

    return LiveLinkDeviceListResponse(
        devices=[LiveLinkDeviceResponse.model_validate(d) for d in devices],
        total=len(devices),
        online_count=online_count,
    )


@router.get("/devices/{device_id}", response_model=LiveLinkDeviceResponse)
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific device.

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    device = await _get_device_for_owner_or_404(db, device_id, current_user)
    return LiveLinkDeviceResponse.model_validate(device)


@router.put("/devices/{device_id}", response_model=LiveLinkDeviceResponse)
async def update_device(
    device_id: str,
    updates: LiveLinkDeviceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update a device (label, VIN link, enabled status).

    **Security:**
    - Owner of the device's CURRENT linked vehicle, and -- when relinking -- of
      the TARGET vehicle too (D-5 both-VIN check). Unlinked devices are admin-only.
    """
    # Authorise against the current link first.
    device = await _get_device_for_owner_or_404(db, device_id, current_user)

    # Relink: the target VIN must also be owned by the caller, else a user could
    # attach a device to a vehicle they don't own (cross-tenant telemetry).
    if updates.vin:
        target_vin = updates.vin.upper().strip()
        if target_vin != (device.vin or "").upper():
            await get_vehicle_for_owner_or_403(target_vin, current_user, db)

    service = LiveLinkService(db)
    device = await service.update_device(
        device_id=device_id,
        label=updates.label,
        vin=updates.vin,
        enabled=updates.enabled,
    )

    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    return LiveLinkDeviceResponse.model_validate(device)


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a device.

    Historical telemetry and sessions are retained (keyed on vehicle).

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    await _get_device_for_owner_or_404(db, device_id, current_user)

    service = LiveLinkService(db)
    deleted = await service.delete_device(device_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")


@router.post("/devices/{device_id}/token", response_model=TokenGenerateResponse)
async def generate_device_token(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Generate a per-device API token.

    Per-device tokens take precedence over the global token.
    **Important:** The token is only shown once.

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    await _get_device_for_owner_or_404(db, device_id, current_user)

    service = LiveLinkService(db)
    token = await service.generate_device_token(device_id)

    if not token:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    return TokenGenerateResponse(
        token=token,
        expires_at=None,
    )


@router.delete("/devices/{device_id}/token", status_code=204)
async def revoke_device_token(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Revoke a per-device token (device falls back to global token).

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    await _get_device_for_owner_or_404(db, device_id, current_user)

    service = LiveLinkService(db)
    revoked = await service.revoke_device_token(device_id)

    if not revoked:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")


@router.get("/devices/{device_id}/token", response_model=TokenInfoResponse)
async def get_device_token_info(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get info about a device's token (masked).

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    device = await _get_device_for_owner_or_404(db, device_id, current_user)

    if not device.device_token_hash:
        raise HTTPException(status_code=404, detail="Device has no per-device token")

    # We can't show the actual token, just metadata
    return TokenInfoResponse(
        masked_token="***" + device.device_token_hash[-4:],
        created_at=device.updated_at or device.created_at,
        last_used=device.last_seen,
    )


@router.post("/devices/{device_id}/command", response_model=DeviceCommandResponse)
async def send_device_command(
    device_id: str,
    request: DeviceCommandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Send a command to a WiCAN device via MQTT.

    Supported commands:
    - **get_vbatt**: Request battery voltage
    - **get_autopid_data**: Trigger one-shot AutoPID data poll (requires ECU online)
    - **reboot**: Reboot the WiCAN device

    Commands are fire-and-forget. Responses arrive via normal MQTT telemetry topics.

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    - Device must be online
    - MQTT subscriber must be connected
    """
    await _get_device_for_owner_or_404(db, device_id, current_user)

    from app.services.device_command_service import send_command

    try:
        result = await send_command(db, device_id, request.command)
        return DeviceCommandResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


# =============================================================================
# Parameter Endpoints
# =============================================================================


@router.get("/parameters", response_model=LiveLinkParameterListResponse)
async def list_parameters(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    List all registered parameters.

    **Security:**
    - Requires authentication
    """
    service = TelemetryService(db)
    parameters = await service.get_all_parameters()

    return LiveLinkParameterListResponse(
        parameters=[LiveLinkParameterResponse.model_validate(p) for p in parameters.values()],
        total=len(parameters),
    )


@router.get("/parameters/{param_key}", response_model=LiveLinkParameterResponse)
async def get_parameter(
    param_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Get a specific parameter.

    **Security:**
    - Requires authentication
    """
    service = TelemetryService(db)
    param = await service.get_parameter(param_key)

    if not param:
        raise HTTPException(status_code=404, detail=f"Parameter {param_key} not found")

    return LiveLinkParameterResponse.model_validate(param)


@router.put("/parameters/{param_key}", response_model=LiveLinkParameterResponse)
async def update_parameter(
    param_key: str,
    updates: LiveLinkParameterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Update parameter settings (thresholds, display options).

    **Security:**
    - Requires authentication
    """
    service = TelemetryService(db)
    param = await service.get_parameter(param_key)

    if not param:
        raise HTTPException(status_code=404, detail=f"Parameter {param_key} not found")

    # Update fields
    if updates.display_name is not None:
        param.display_name = updates.display_name
    if updates.category is not None:
        param.category = updates.category
    if updates.icon is not None:
        param.icon = updates.icon
    if updates.warning_min is not None:
        param.warning_min = updates.warning_min
    if updates.warning_max is not None:
        param.warning_max = updates.warning_max
    if updates.display_order is not None:
        param.display_order = updates.display_order
    if updates.show_on_dashboard is not None:
        param.show_on_dashboard = updates.show_on_dashboard
    if updates.archive_only is not None:
        param.archive_only = updates.archive_only
    if updates.storage_interval_seconds is not None:
        param.storage_interval_seconds = updates.storage_interval_seconds

    await db.commit()
    await db.refresh(param)

    return LiveLinkParameterResponse.model_validate(param)


# =============================================================================
# Firmware Endpoints
# =============================================================================


@router.get("/firmware/latest", response_model=FirmwareInfoResponse)
async def get_latest_firmware(
    track: FirmwareTrack = Query(FirmwareTrack.pro, description="Firmware track"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Get the latest WiCAN firmware version for a track (from cache).

    **Security:**
    - Requires authentication
    """
    service = FirmwareService(db)
    info = await service.get_cached_firmware_info(track.value)

    return FirmwareInfoResponse(
        latest_version=info.get("latest_version") if info else None,
        latest_tag=info.get("latest_tag") if info else None,
        release_url=info.get("release_url") if info else None,
        release_notes=info.get("release_notes") if info else None,
        checked_at=info.get("checked_at") if info else None,
        firmware_track=info.get("firmware_track") if info else track.value,
    )


@router.post("/firmware/check", response_model=FirmwareInfoResponse)
async def trigger_firmware_check(
    track: FirmwareTrack = Query(FirmwareTrack.pro, description="Track to return after refresh"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Check GitHub for new firmware (refreshes ALL tracks); return one track.

    **Security:**
    - Requires authentication
    """
    service = FirmwareService(db)
    await service.check_firmware_updates()  # refreshes obd + pro
    info = await service.get_cached_firmware_info(track.value)

    return FirmwareInfoResponse(
        latest_version=info.get("latest_version") if info else None,
        latest_tag=info.get("latest_tag") if info else None,
        release_url=info.get("release_url") if info else None,
        release_notes=info.get("release_notes") if info else None,
        checked_at=info.get("checked_at") if info else None,
        firmware_track=info.get("firmware_track") if info else track.value,
    )


@router.get("/firmware/devices", response_model=list[DeviceFirmwareStatus])
async def get_device_firmware_status(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Get firmware status for all devices (current vs latest, per track).

    **Security:**
    - Requires authentication
    """
    livelink_service = LiveLinkService(db)
    firmware_service = FirmwareService(db)

    devices = await livelink_service.list_devices()
    results = []
    for device in devices:
        status = await firmware_service.check_device_firmware(device.device_id)
        results.append(
            DeviceFirmwareStatus(
                device_id=device.device_id,
                current_version=status.get("current_version"),
                latest_version=status.get("latest_version"),
                update_available=status.get("update_available") or False,
                release_url=status.get("release_url") if status.get("update_available") else None,
                firmware_track=status.get("firmware_track"),
            )
        )

    return results


# =============================================================================
# DTC Definition Lookup Endpoints
# =============================================================================


@router.get("/dtc-definitions/{code}", response_model=DTCDefinitionResponse)
async def lookup_dtc_definition(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Look up a DTC code definition.

    **Security:**
    - Requires authentication
    """
    service = DTCService(db)
    definition = await service.lookup_dtc(code)

    if not definition:
        raise HTTPException(status_code=404, detail=f"DTC code {code} not found in database")

    return DTCDefinitionResponse.model_validate(definition)


@router.get("/dtc-definitions", response_model=DTCSearchResponse)
async def search_dtc_definitions(
    q: str,
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Search DTC definitions by code prefix or description.

    **Query Parameters:**
    - **q**: Search query (code prefix like "P06" or description keywords)
    - **limit**: Maximum results (default 50)

    **Security:**
    - Requires authentication
    """
    service = DTCService(db)
    results = await service.search_dtc_definitions(q, limit=limit)

    return DTCSearchResponse(
        results=[DTCDefinitionResponse.model_validate(d) for d in results],
        total=len(results),
        query=q,
    )


# =============================================================================
# MQTT Endpoints
# =============================================================================


@router.get("/mqtt/settings", response_model=MQTTSettingsResponse)
async def get_mqtt_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Get MQTT subscriber settings.

    **Security:**
    - Requires authentication
    """
    enabled = await _get_bool_setting(db, "livelink_mqtt_enabled", False)
    broker_host = await SettingsService.get(db, "livelink_mqtt_broker_host")
    broker_port = await SettingsService.get(db, "livelink_mqtt_broker_port")
    username = await SettingsService.get(db, "livelink_mqtt_username")
    password = await SettingsService.get(db, "livelink_mqtt_password")
    topic_prefix = await SettingsService.get(db, "livelink_mqtt_topic_prefix")
    use_tls = await _get_bool_setting(db, "livelink_mqtt_use_tls", False)

    return MQTTSettingsResponse(
        enabled=enabled,
        broker_host=broker_host.value if broker_host else "",
        broker_port=int(broker_port.value) if broker_port and broker_port.value else 1883,
        username=username.value if username else "",
        has_password=bool(password and password.value),
        topic_prefix=topic_prefix.value if topic_prefix and topic_prefix.value else "wican",
        use_tls=use_tls,
    )


@router.put("/mqtt/settings", response_model=MQTTSettingsResponse)
async def update_mqtt_settings(
    updates: MQTTSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Update MQTT subscriber settings.

    After updating settings, restart the MQTT subscriber for changes to take effect.

    **Security:**
    - Requires authentication
    """
    if updates.enabled is not None:
        await SettingsService.set(db, "livelink_mqtt_enabled", str(updates.enabled).lower())
    if updates.broker_host is not None:
        await SettingsService.set(db, "livelink_mqtt_broker_host", updates.broker_host)
    if updates.broker_port is not None:
        await SettingsService.set(db, "livelink_mqtt_broker_port", str(updates.broker_port))
    if updates.username is not None:
        await SettingsService.set(db, "livelink_mqtt_username", updates.username)
    if updates.password is not None:
        await SettingsService.set(
            db,
            "livelink_mqtt_password",
            updates.password,
            encrypted=True,
        )
    if updates.topic_prefix is not None:
        await SettingsService.set(db, "livelink_mqtt_topic_prefix", updates.topic_prefix)
    if updates.use_tls is not None:
        await SettingsService.set(db, "livelink_mqtt_use_tls", str(updates.use_tls).lower())

    await db.commit()

    # Return updated settings
    return await get_mqtt_settings(db=db, current_user=current_user)


@router.get("/mqtt/status", response_model=MQTTStatusResponse)
async def get_mqtt_status(
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Get MQTT subscriber status.

    **Security:**
    - Requires authentication
    """
    from app.tasks.livelink_tasks import get_mqtt_status as get_status

    status = get_status()
    return MQTTStatusResponse(**status)


@router.post("/mqtt/restart", response_model=MQTTStatusResponse)
async def restart_mqtt_subscriber(
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Restart the MQTT subscriber.

    Use this after updating MQTT settings to apply changes.

    **Security:**
    - Requires authentication
    """
    from app.tasks.livelink_tasks import get_mqtt_status as get_status
    from app.tasks.livelink_tasks import restart_mqtt_subscriber as restart

    await restart()

    status = get_status()
    return MQTTStatusResponse(**status)


@router.post("/mqtt/test", response_model=MQTTTestResult)
async def test_mqtt_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """
    Test MQTT broker connection.

    Attempts to connect to the configured MQTT broker and subscribe to the topic.

    **Security:**
    - Requires authentication
    """
    # Get current config
    broker_host = await SettingsService.get(db, "livelink_mqtt_broker_host")
    broker_port = await SettingsService.get(db, "livelink_mqtt_broker_port")
    username = await SettingsService.get(db, "livelink_mqtt_username")
    password = await SettingsService.get(db, "livelink_mqtt_password")
    use_tls = await _get_bool_setting(db, "livelink_mqtt_use_tls", False)

    if not broker_host or not broker_host.value:
        return MQTTTestResult(
            success=False,
            message="No MQTT broker host configured",
            broker=None,
        )

    host = broker_host.value
    port = int(broker_port.value) if broker_port and broker_port.value else 1883
    broker = f"{host}:{port}"

    try:
        import asyncio
        import ssl

        import aiomqtt

        # Build TLS context if needed
        tls_context = None
        if use_tls:
            tls_context = ssl.create_default_context()

        # Try to connect with a short timeout
        async with asyncio.timeout(10):
            async with aiomqtt.Client(
                hostname=host,
                port=port,
                username=username.value if username and username.value else None,
                password=password.value if password and password.value else None,
                tls_context=tls_context,
            ):
                pass  # Connection successful

        return MQTTTestResult(
            success=True,
            message="Successfully connected to MQTT broker",
            broker=broker,
        )

    except ImportError:
        return MQTTTestResult(
            success=False,
            message="aiomqtt library not installed",
            broker=broker,
        )
    except TimeoutError:
        return MQTTTestResult(
            success=False,
            message="Connection timed out (10s)",
            broker=broker,
        )
    except Exception as e:
        return MQTTTestResult(
            success=False,
            message=f"Connection failed: {e!s}",
            broker=broker,
        )


# =============================================================================
# Helpers
# =============================================================================


async def _get_device_for_owner_or_404(db: AsyncSession, device_id: str, current_user: User | None):
    """Resolve a device and require the caller owns its linked vehicle (D-5).

    Per-device ops (view/relink/command/token/delete a single device) are scoped
    to the owner of the device's linked vehicle. An unlinked device (no vin) has
    no vehicle owner, so it is admin-only. Returns the device on success.
    """
    service = LiveLinkService(db)
    device = await service.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    if device.vin:
        # Raises 403 unless caller owns the linked vehicle (or is admin / none-mode).
        await get_vehicle_for_owner_or_403(device.vin, current_user, db)
    elif current_user is not None and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can manage an unlinked device")
    return device


async def _get_bool_setting(db: AsyncSession, key: str, default: bool = False) -> bool:
    """Get a boolean setting value."""
    setting = await SettingsService.get(db, key)
    if not setting or not setting.value:
        return default
    return setting.value.lower() in ("true", "1", "yes")
