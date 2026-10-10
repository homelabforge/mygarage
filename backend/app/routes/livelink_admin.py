"""LiveLink admin endpoints for settings, devices, and parameters."""

import logging
from datetime import datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.user import User
from app.models.vehicle_telemetry import VehicleTelemetry
from app.schemas.dtc import DTCDefinitionResponse, DTCSearchResponse
from app.schemas.livelink import (
    BackfillResultResponse,
    DeviceCommandRequest,
    DeviceCommandResponse,
    DeviceFirmwareStatus,
    DeviceReading,
    DeviceReadingsResponse,
    FirmwareInfoResponse,
    FirmwareSkipRequest,
    IntegrationListResponse,
    IntegrationTab,
    LiveLinkDeviceListResponse,
    LiveLinkDeviceManualCreate,
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
    SdConfigResponse,
    SdConfigUpdate,
    TokenGenerateResponse,
    TokenInfoResponse,
)
from app.schemas.livelink_topic_map import (
    PresetApplyRequest,
    PresetInfo,
    PresetReadingInfo,
    TopicDiscoveryRequest,
    TopicMapCreate,
    TopicMapResponse,
    TopicMapUpdate,
)
from app.services.auth import (
    get_current_admin_user,
    get_vehicle_for_owner_or_403,
    require_auth,
)
from app.services.dtc_service import DTCService
from app.services.firmware_service import FirmwareService
from app.services.livelink_integrations import (
    derive_broker_status,
    derive_group_status,
    device_is_linked,
    device_is_online,
    firmware_is_pending,
)
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.presets import PRESETS
from app.services.livelink_sources.presets.sensors import (
    create_sensor,
    reading_of,
    reject_foreign_preset_key,
    rename_sensor_parameters,
)
from app.services.livelink_sources.registry import default_registry
from app.services.mqtt_subscriber import mqtt_subscriber
from app.services.sd_backfill_service import SdBackfillService
from app.services.settings_service import SettingsService
from app.services.telemetry_service import TelemetryService
from app.tasks.livelink_tasks import get_mqtt_status as get_subscriber_status
from app.utils.datetime_utils import utc_now
from app.utils.request_scheme import get_external_base_url

logger = logging.getLogger(__name__)


class FirmwareTrack(StrEnum):
    """Firmware track selector for WiCAN device families."""

    obd = "obd"
    pro = "pro"


router = APIRouter(prefix="/api/livelink", tags=["LiveLink Admin"])


# =============================================================================
# Settings Endpoints
# =============================================================================


@router.get("/settings", response_model=LiveLinkSettingsResponse)
async def get_livelink_settings(
    request: Request,
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

    # Build ingestion URL. Absolute — a dongle is configured with this by
    # copy-paste and cannot resolve a relative path (#129).
    configured = await SettingsService.get(db, "app_base_url")
    base_url = (
        configured.value.strip().rstrip("/")
        if configured and configured.value and configured.value.strip()
        else get_external_base_url(request)
    )
    ingestion_url = f"{base_url}/api/v1/livelink/ingest"

    return LiveLinkSettingsResponse(
        enabled=await service.is_enabled(),
        has_global_token=has_global_token,
        ingestion_url=ingestion_url,
        telemetry_retention_days=await service.get_retention_days(),
        session_timeout_minutes=await service.get_session_timeout_minutes(),
        device_offline_timeout_minutes=await service.get_device_offline_timeout_minutes(),
        daily_aggregation_enabled=await SettingsService.get_bool(
            db, "livelink_daily_aggregation_enabled", default=True
        ),
        firmware_check_enabled=await SettingsService.get_bool(
            db, "livelink_firmware_check_enabled", default=True
        ),
        alert_cooldown_minutes=await service.get_alert_cooldown_minutes(),
        session_grace_period_seconds=await service.get_session_grace_period_seconds(),
        session_gap_minutes=await service.get_session_gap_minutes(),
        session_boundary_mode=await service.get_session_boundary_mode(),
        notify_device_offline=await SettingsService.get_bool(
            db, "livelink_notify_device_offline", default=True
        ),
        notify_threshold_alerts=await SettingsService.get_bool(
            db, "livelink_notify_threshold_alerts", default=True
        ),
        notify_firmware_update=await SettingsService.get_bool(
            db, "livelink_notify_firmware_update", default=True
        ),
        notify_new_device=await SettingsService.get_bool(
            db, "livelink_notify_new_device", default=True
        ),
    )


@router.put("/settings", response_model=LiveLinkSettingsResponse)
async def update_livelink_settings(
    updates: LiveLinkSettingsUpdate,
    request: Request,
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
    if updates.session_gap_minutes is not None:
        await SettingsService.set(
            db, "livelink_session_gap_minutes", str(updates.session_gap_minutes)
        )
    if updates.session_boundary_mode is not None:
        await SettingsService.set(
            db, "livelink_session_boundary_mode", updates.session_boundary_mode
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
    return await get_livelink_settings(request=request, db=db, current_user=current_user)


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


async def _device_response(db: AsyncSession, device) -> LiveLinkDeviceResponse:
    """One device, with `movement_unreadable` actually answered.

    The field defaults to False on the schema, so a handler that skips this
    reports "this device's movement reads fine" about a device nobody asked
    about. That is the silent zero this whole feature exists to remove, one
    layer up from where it was removed.
    """
    unreadable = await LiveLinkService(db).movement_unreadable_device_ids([device])
    return LiveLinkDeviceResponse.model_validate(device).model_copy(
        update={"movement_unreadable": device.device_id in unreadable}
    )


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
    unreadable = await service.movement_unreadable_device_ids(devices)

    online_count = sum(1 for d in devices if d.device_status == "online")

    return LiveLinkDeviceListResponse(
        devices=[
            LiveLinkDeviceResponse.model_validate(d).model_copy(
                update={"movement_unreadable": d.device_id in unreadable}
            )
            for d in devices
        ],
        total=len(devices),
        online_count=online_count,
    )


@router.get("/devices/{device_id}", response_model=LiveLinkDeviceResponse)
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get a specific device.

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    device = await _get_device_for_owner_or_404(db, device_id, current_user)
    return await _device_response(db, device)


@router.put("/devices/{device_id}", response_model=LiveLinkDeviceResponse)
async def update_device(
    device_id: str,
    updates: LiveLinkDeviceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Update a device (label, VIN link, enabled status).

    **Security:**
    - Owner of the device's CURRENT linked vehicle, and -- when relinking -- of
      the TARGET vehicle too (D-5 both-VIN check). Unlinked devices are admin-only.
    """
    # Authorise against the current link first.
    device = await _get_device_for_owner_or_404(db, device_id, current_user)
    # Read before `service.update_device`, which commits.
    old_label = device.label

    # Relink: the target VIN must also be owned by the caller, else a user could
    # attach a device to a vehicle they don't own (cross-tenant telemetry).
    # The schema has already uppercased it. An empty VIN is an unlink, which
    # the current-link check above already authorised.
    if updates.vin and updates.vin != (device.vin or "").upper():
        await get_vehicle_for_owner_or_403(updates.vin, current_user, db)

    service = LiveLinkService(db)
    try:
        device = await service.update_device(device_id, updates.model_dump(exclude_unset=True))
    except ValueError as exc:
        # Changing the odometer unit once readings depend on it would split the
        # device's history across two units. 409: the request is well formed,
        # the stored data is what conflicts with it.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    # A preset sensor's readings are named after it ("Front tank level").
    preset = PRESETS.get(device.preset_key or "")
    if preset is not None and old_label and device.label != old_label:
        await rename_sensor_parameters(db, preset, device, old_label)
        await db.commit()

    return await _device_response(db, device)


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Delete a device.

    Historical telemetry and sessions are retained (keyed on vehicle), except a
    preset sensor's readings, which are deleted with it.

    **Security:**
    - Owner of the device's linked vehicle (admin for unlinked devices).
    """
    await _get_device_for_owner_or_404(db, device_id, current_user)

    service = LiveLinkService(db)
    deleted = await service.delete_device(device_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    # delete_device also dropped this device's topic maps. Without a resubscribe
    # the broker keeps delivering topics that now resolve to no module, one
    # debug line per message, indefinitely.
    await mqtt_subscriber.reload()


@router.post("/devices/{device_id}/token", response_model=TokenGenerateResponse)
async def generate_device_token(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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


def _check_alert_lines(param: LiveLinkParameter, lines: dict[str, float | None]) -> None:
    """Refuse lines no value could sensibly cross. Raises 422.

    A percentage's lines stay within 0 to 100, and the critical line sits
    below the low one, taking whichever of the two this update leaves stored.
    """
    if param.unit == "%":
        for name, line in lines.items():
            if line is not None and not 0 <= line <= 100:
                raise HTTPException(status_code=422, detail=f"{name} must be between 0 and 100")
    low = lines.get("warning_min", param.warning_min)
    critical = lines.get("critical_min", param.critical_min)
    if low is not None and critical is not None and critical >= low:
        raise HTTPException(status_code=422, detail="critical_min must be below warning_min")


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

    # Omitted keeps, null clears.
    sent = updates.model_fields_set
    if "display_name" in sent:
        param.display_name = updates.display_name
    if "category" in sent:
        param.category = updates.category
    if "icon" in sent:
        param.icon = updates.icon
    # An explicit null switches a line off; an omitted one stays as it is.
    lines = {
        name: getattr(updates, name)
        for name in ("warning_min", "critical_min", "warning_max")
        if name in updates.model_fields_set
    }
    _check_alert_lines(param, lines)
    for name, line in lines.items():
        setattr(param, name, line)
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
                skipped_version=status.get("skipped_version"),
            )
        )

    return results


async def _get_device_or_404(db: AsyncSession, device_id: str):
    """Fetch a device for the firmware-skip endpoints; 404 when unknown."""
    device = await LiveLinkService(db).get_device_by_id(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.post("/devices/{device_id}/firmware/skip", response_model=DeviceFirmwareStatus)
async def skip_firmware_version(
    device_id: str,
    body: FirmwareSkipRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Skip firmware-update notifications for one release on one device.

    The next (newer) release notifies again. Note the interplay with
    notify-once: a release that was already notified stays silenced even
    after an unskip, because ``firmware_notified_version`` still matches —
    that is the notify-once rule working, not a bug.

    **Security:**
    - Requires admin authentication
    """
    device = await _get_device_or_404(db, device_id)
    device.firmware_skipped_version = body.version
    await db.commit()
    status = await FirmwareService(db).check_device_firmware(device_id)
    return DeviceFirmwareStatus(
        device_id=device_id,
        current_version=status.get("current_version"),
        latest_version=status.get("latest_version"),
        update_available=status.get("update_available") or False,
        release_url=status.get("release_url") if status.get("update_available") else None,
        firmware_track=status.get("firmware_track"),
        skipped_version=status.get("skipped_version"),
    )


@router.delete("/devices/{device_id}/firmware/skip", response_model=DeviceFirmwareStatus)
async def unskip_firmware_version(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Clear a device's skipped firmware version.

    Because ``firmware_notified_version`` is only stamped on actual sends,
    an unskipped device that was never notified gets its notification at
    the next daily run.

    **Security:**
    - Requires admin authentication
    """
    device = await _get_device_or_404(db, device_id)
    device.firmware_skipped_version = None
    await db.commit()
    status = await FirmwareService(db).check_device_firmware(device_id)
    return DeviceFirmwareStatus(
        device_id=device_id,
        current_version=status.get("current_version"),
        latest_version=status.get("latest_version"),
        update_available=status.get("update_available") or False,
        release_url=status.get("release_url") if status.get("update_available") else None,
        firmware_track=status.get("firmware_track"),
        skipped_version=status.get("skipped_version"),
    )


# =============================================================================
# DTC Definition Lookup Endpoints
# =============================================================================


@router.get("/dtc-definitions/{code}", response_model=DTCDefinitionResponse)
async def lookup_dtc_definition(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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
    enabled = await SettingsService.get_bool(db, "livelink_mqtt_enabled", default=False)
    broker_host = await SettingsService.get(db, "livelink_mqtt_broker_host")
    broker_port = await SettingsService.get(db, "livelink_mqtt_broker_port")
    username = await SettingsService.get(db, "livelink_mqtt_username")
    password = await SettingsService.get(db, "livelink_mqtt_password")
    topic_prefix = await SettingsService.get(db, "livelink_mqtt_topic_prefix")
    use_tls = await SettingsService.get_bool(db, "livelink_mqtt_use_tls", default=False)

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
    use_tls = await SettingsService.get_bool(db, "livelink_mqtt_use_tls", default=False)

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
# SD-Card Backfill Endpoints (admin-only)
# =============================================================================


@router.put("/devices/{device_id}/sd-config", response_model=SdConfigResponse)
async def set_sd_config(
    device_id: str,
    body: SdConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Configure the SD-pull address and enable flag for a device.

    **Security:**
    - Requires admin authentication
    - device_address must be a private/LAN address (SSRF guard)
    """
    svc = LiveLinkService(db)
    if body.device_address and not svc.is_private_address(body.device_address):
        raise HTTPException(
            status_code=422,
            detail="device_address must be a private/LAN address (public IPs are rejected)",
        )
    await svc.update_device_address(device_id, body.device_address, body.sd_backfill_enabled)
    return SdConfigResponse()


@router.post("/devices/{device_id}/backfill", response_model=BackfillResultResponse)
async def trigger_backfill(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
):
    """Pull and backfill the device's SD logs immediately.

    409 while LiveLink is switched off: the service would quietly do nothing
    (it checks the master switch too, for queued backfills), and an operator
    who pressed "pull now" deserves to be told why nothing arrived.

    **Security:**
    - Requires admin authentication
    """
    if not await LiveLinkService(db).is_enabled():
        raise HTTPException(status_code=409, detail="LiveLink is switched off")
    result = await SdBackfillService(db).backfill_device(device_id)
    return BackfillResultResponse(
        files_seen=result.files_seen,
        rows_ingested=result.rows_ingested,
        rows_skipped=result.rows_skipped,
        errors=result.errors,
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


# =========================================================================
# Source modules and topic maps
# =========================================================================


@router.get("/sources")
async def list_sources(
    current_user: User | None = Depends(get_current_admin_user),
) -> list[dict[str, Any]]:
    """Every registered source kind and what it produces."""
    return [
        {
            "kind": m.kind,
            "capabilities": sorted(c.value for c in m.capabilities),
            # The frontend hides the odometer-parameter picker for kinds whose
            # storage policy already syncs odometer; a declaration on those is
            # silently ignored today.
            "syncs_odometer": m.storage_policy.sync_odometer,
        }
        for m in default_registry().all_modules()
    ]


#: Display names for the built-in source modules. A kind that is not here gets
#: its bare `kind` as a label rather than raising: a missing entry that 500s
#: would take the whole strip down, and the strip is one of six cards.
_SOURCE_LABELS = {"wican": "WiCAN", "torque": "Torque"}

#: generic_mqtt has no tab of its own: its preset sensors are grouped by
#: preset, and every other device is its own tab. Nothing on the module says
#: which behaviour it wants, so this is a rule of the endpoint rather than a
#: property of the registry.
_PER_DEVICE_KINDS = frozenset({"generic_mqtt"})


@router.get("/integrations", response_model=IntegrationListResponse)
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> IntegrationListResponse:
    """The integrations card's tab strip, with each tab's status.

    One request replaces the card's previous four. The status rules live in
    `app.services.livelink_integrations` so they can be unit-tested without a
    database, a broker or an HTTP client.

    **Security:**
    - Requires admin
    """
    livelink = LiveLinkService(db)
    enabled = await livelink.is_enabled()
    timeout = await livelink.get_device_offline_timeout_minutes()
    now = utc_now()

    devices = await livelink.list_devices()
    firmware_by_id: dict[str, DeviceFirmwareStatus] = {}
    if enabled:
        firmware_service = FirmwareService(db)
        for device in devices:
            status = await firmware_service.check_device_firmware(device.device_id)
            firmware_by_id[device.device_id] = DeviceFirmwareStatus(
                device_id=device.device_id,
                current_version=status.get("current_version"),
                latest_version=status.get("latest_version"),
                update_available=status.get("update_available") or False,
                skipped_version=status.get("skipped_version"),
            )

    def _tab(
        tab_id: str,
        label: str,
        kind: str | None,
        group: list[LiveLinkDevice],
        description: str | None = None,
    ) -> IntegrationTab:
        state = derive_group_status(group, firmware_by_id, timeout, now, livelink_enabled=enabled)
        return IntegrationTab(
            id=tab_id,
            label=label,
            kind=kind,
            status=state.status,
            reason=state.reason,
            description=description,
            device_count=len(group),
            online_count=sum(1 for d in group if device_is_online(d, timeout, now)),
            linked_count=sum(1 for d in group if device_is_linked(d)),
            firmware_updates=sum(
                1 for d in group if firmware_is_pending(firmware_by_id.get(d.device_id))
            ),
        )

    tabs: list[IntegrationTab] = []
    for module in default_registry().all_modules():
        if module.kind in _PER_DEVICE_KINDS:
            continue
        group = [d for d in devices if d.kind == module.kind]
        tabs.append(
            _tab(module.kind, _SOURCE_LABELS.get(module.kind, module.kind), module.kind, group)
        )

    # The broker is not a source module. It is the transport the MQTT sources
    # share, and "is my broker up" is exactly the kind of thing a status dot
    # is for.
    try:
        connection_status = get_subscriber_status().get("connection_status", "disconnected")
    except Exception:  # noqa: BLE001 - a broker we cannot read is not healthy
        logger.warning("Could not read MQTT subscriber status", exc_info=True)
        connection_status = "error"
    broker = derive_broker_status(connection_status, livelink_enabled=enabled)
    tabs.append(
        IntegrationTab(
            id="broker",
            label="Mosquitto",
            kind=None,
            status=broker.status,
            reason=broker.reason,
        )
    )

    # A preset's sensors share one tab, the way WiCAN's dongles do: two tanks
    # are "2 devices linked", not two tabs.
    generic = [d for d in devices if d.kind in _PER_DEVICE_KINDS]
    for preset in PRESETS.values():
        group = [d for d in generic if d.preset_key == preset.name]
        if group:
            tabs.append(
                _tab(
                    f"preset:{preset.name}",
                    preset.title,
                    preset.kind,
                    group,
                    description=preset.description,
                )
            )

    # Every other device is its own tab, including one whose preset no longer
    # exists: it stays reachable to be edited or deleted.
    for device in generic:
        if device.preset_key in PRESETS:
            continue
        tabs.append(
            _tab(
                f"device:{device.device_id}",
                device.label or device.device_id,
                device.kind,
                [device],
            )
        )

    return IntegrationListResponse(tabs=tabs)


@router.get("/devices/{device_id}/readings", response_model=DeviceReadingsResponse)
async def get_device_readings(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> DeviceReadingsResponse:
    """Every parameter this device is mapped to, with its current value.

    Which keys comes from `livelink_topic_maps`: those rows are what route a
    topic to a parameter, so a device's mapped key set IS its parameter list.

    Whose value cannot come from `vehicle_telemetry_latest`. That table is
    UNIQUE(vin, param_key) with no device_id, so two devices on one vehicle
    mapping the same key means the last writer owns the row and the other
    device's sidecar would display a reading that is not its own. Values come
    from `vehicle_telemetry`, which carries device_id.

    The cost is recency: `vehicle_telemetry` is written subject to
    `storage_interval_seconds`. The timestamp is returned so the UI can show
    how old the value actually is rather than implying it is live.

    Values are the device's under its CURRENT vehicle. A device relinked to
    another vehicle starts again rather than showing the old one's readings.

    **Security:**
    - Requires admin
    """
    device = await _get_device_or_404(db, device_id)
    livelink = LiveLinkService(db)
    online = device_is_online(
        device, await livelink.get_device_offline_timeout_minutes(), utc_now()
    )

    # In the order they were first mapped, which for a preset is the preset's
    # own order (a tank's level first). GROUP BY rather than DISTINCT: one key
    # may be mapped from two topics, and it is listed once, at its first row.
    keys_result = await db.execute(
        select(LiveLinkTopicMap.param_key)
        .where(
            LiveLinkTopicMap.device_id == device_id,
            LiveLinkTopicMap.role == "telemetry",
            LiveLinkTopicMap.param_key.is_not(None),
        )
        .group_by(LiveLinkTopicMap.param_key)
        .order_by(func.min(LiveLinkTopicMap.id))
    )
    param_keys = [key for (key,) in keys_result.all() if key]

    if not param_keys:
        return DeviceReadingsResponse(
            device_id=device_id, vin=device.vin, online=online, readings=[]
        )

    parameters = await TelemetryService(db).get_all_parameters()

    values: dict[str, tuple[float, datetime]] = {}
    if device.vin:
        # Newest row per (device_id, param_key) under the current vehicle.
        # Expressed as a grouped subquery rather than a window function so it
        # runs unchanged on SQLite (production) and PostgreSQL (CI). The VIN
        # filter lives here only: rows are UNIQUE(device_id, param_key,
        # timestamp), so the one row at the newest current-vehicle timestamp
        # is already this vehicle's.
        newest = (
            select(
                VehicleTelemetry.param_key.label("param_key"),
                func.max(VehicleTelemetry.timestamp).label("ts"),
            )
            .where(
                VehicleTelemetry.device_id == device_id,
                VehicleTelemetry.vin == device.vin,
                VehicleTelemetry.param_key.in_(param_keys),
            )
            .group_by(VehicleTelemetry.param_key)
            .subquery()
        )
        rows = await db.execute(
            select(VehicleTelemetry.param_key, VehicleTelemetry.value, VehicleTelemetry.timestamp)
            .join(
                newest,
                (VehicleTelemetry.param_key == newest.c.param_key)
                & (VehicleTelemetry.timestamp == newest.c.ts),
            )
            .where(VehicleTelemetry.device_id == device_id)
        )
        for param_key, value, timestamp in rows.all():
            values[param_key] = (value, timestamp)

    preset = PRESETS.get(device.preset_key or "")
    readings: list[DeviceReading] = []
    for key in param_keys:
        parameter = parameters.get(key)
        value, timestamp = values.get(key, (None, None))
        reading = reading_of(key, preset)
        readings.append(
            DeviceReading(
                param_key=key,
                display_name=parameter.display_name if parameter else key,
                unit=parameter.unit if parameter else None,
                value=value,
                timestamp=timestamp,
                show_on_dashboard=bool(parameter.show_on_dashboard) if parameter else True,
                format=reading.format if reading else "value",
                max_value=reading.max_value if reading else None,
                warning_min=parameter.warning_min if parameter else None,
                critical_min=parameter.critical_min if parameter else None,
                alert_lines=list(reading.alert_lines) if reading else [],
            )
        )

    return DeviceReadingsResponse(
        device_id=device_id, vin=device.vin, online=online, readings=readings
    )


async def _resolve_new_device_vin(
    db: AsyncSession, vin: str | None, current_user: User | None
) -> str | None:
    """The VIN a newly created device should be linked to, or None.

    Mirrors what `update_device` does when it LINKS a device: uppercase, then
    resolve through `get_vehicle_for_owner_or_403`. Without this the body's VIN
    went straight into `livelink_devices.vin`, a foreign key to `vehicles.vin`,
    so an unknown VIN, or a lowercase one (VINs are stored uppercase), was an
    IntegrityError at commit: a 500 instead of a 404.

    Called before anything is added to the session, so a bad VIN leaves no
    device and no topic maps behind.
    """
    if not vin:
        return None
    normalised = vin.upper().strip()
    await get_vehicle_for_owner_or_403(normalised, current_user, db)
    return normalised


@router.post("/devices", response_model=LiveLinkDeviceResponse, status_code=201)
async def create_device(
    body: LiveLinkDeviceManualCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> LiveLinkDevice:
    """Create a device by hand.

    Auto-discovery covers WiCAN and a token flow covers Torque; a generic MQTT
    device has neither, so without this an admin can save topic maps against a
    device id that does not exist and every reading is silently discarded.
    """
    existing = await LiveLinkService(db).get_device_by_id(body.device_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Device {body.device_id} already exists")
    vin = await _resolve_new_device_vin(db, body.vin, current_user)

    device = LiveLinkDevice(
        device_id=body.device_id,
        kind=body.kind,
        label=body.label,
        vin=vin,
        enabled=True,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


@router.get("/devices/{device_id}/param-keys", response_model=list[str])
async def list_device_param_keys(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> list[str]:
    """Distinct parameter keys THIS device has reported.

    Per-device on purpose. `vehicle_telemetry_latest` has no device_id column
    and is keyed (vin, param_key), so a per-vehicle list would offer a Torque
    phone the co-located WiCAN's A6-ODOMETER, which it never emits.
    """
    return await LiveLinkService(db).device_reported_param_keys(device_id)


@router.get("/topic-maps", response_model=list[TopicMapResponse])
async def list_topic_maps(
    device_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> list[LiveLinkTopicMap]:
    """All topic maps, optionally for one device."""
    stmt = select(LiveLinkTopicMap).order_by(LiveLinkTopicMap.topic)
    if device_id:
        stmt = stmt.where(LiveLinkTopicMap.device_id == device_id)
    return list((await db.execute(stmt)).scalars().all())


async def _reject_foreign_topic_claim(
    db: AsyncSession, topic: str, device_id: str, exclude_id: int | None = None
) -> None:
    """One topic belongs to exactly ONE device.

    The unique key is (topic, param_key), which does not stop two devices
    mapping the same topic under different param keys. `GenericMqttModule.parse`
    attributes a whole batch to its first entry, so that configuration would
    write one device's readings against another device's vehicle.
    """
    stmt = select(LiveLinkTopicMap).where(
        LiveLinkTopicMap.topic == topic, LiveLinkTopicMap.device_id != device_id
    )
    if exclude_id is not None:
        stmt = stmt.where(LiveLinkTopicMap.id != exclude_id)
    clash = (await db.execute(stmt)).scalars().first()
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Topic {topic} is already mapped to device {clash.device_id}",
        )


async def _register_mapped_parameter(db: AsyncSession, row: LiveLinkTopicMap) -> None:
    """Give a mapped telemetry key a `livelink_parameters` row.

    `apply_preset` registers a parameter per reading; these two write paths must
    too, or the integrations sidecar renders a show-on-dashboard switch whose
    `PUT /parameters/{key}` returns 404. Parameters are otherwise registered
    only at first ingest, and a freshly mapped topic has not ingested yet.

    Called before the caller's commit, so the parameter and the mapping land
    in one transaction: `get_or_create_parameter` only flushes.

    `get_or_create`, never create-or-clobber. A repointed mapping must not
    reset an operator's display name or dashboard choice.
    """
    if row.role == "telemetry" and row.param_key:
        await TelemetryService(db).get_or_create_parameter(
            row.param_key, unit=row.unit, param_class=row.param_class
        )


@router.post("/topic-maps", response_model=TopicMapResponse, status_code=201)
async def create_topic_map(
    body: TopicMapCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> LiveLinkTopicMap:
    """Add a mapping and resubscribe."""
    await _reject_foreign_topic_claim(db, body.topic, body.device_id)
    reject_foreign_preset_key(body.param_key, body.device_id)
    row = LiveLinkTopicMap(**body.model_dump())
    db.add(row)
    await _register_mapped_parameter(db, row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "That topic already maps to that parameter") from None
    await db.refresh(row)
    await mqtt_subscriber.reload()
    return row


@router.patch("/topic-maps/{map_id}", response_model=TopicMapResponse)
async def update_topic_map(
    map_id: int,
    body: TopicMapUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> LiveLinkTopicMap:
    """Change a mapping and resubscribe.

    Re-validates the MERGED row through TopicMapCreate rather than assigning
    the patch fields directly: otherwise a PATCH could null `param_key` on a
    telemetry row, set a wildcard topic, or skip param-key canonicalisation,
    all of which create rejects.
    """
    row = await db.get(LiveLinkTopicMap, map_id)
    if row is None:
        raise HTTPException(404, "Topic map not found")

    merged = {
        "device_id": row.device_id,
        "topic": row.topic,
        "role": row.role,
        "param_key": row.param_key,
        "value_path": row.value_path,
        "unit": row.unit,
        "param_class": row.param_class,
        "scale": row.scale,
        "value_offset": row.value_offset,
        "enabled": row.enabled,
    }
    merged.update(body.model_dump(exclude_unset=True))
    try:
        validated = TopicMapCreate(**merged)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    await _reject_foreign_topic_claim(db, validated.topic, validated.device_id, exclude_id=map_id)
    # Only a new claim: a mapping made before the rule (dev's two-tank
    # `rvgateway`) must still be editable, or it can never be switched off.
    if validated.param_key != row.param_key:
        reject_foreign_preset_key(validated.param_key, validated.device_id)
    for field, value in validated.model_dump().items():
        setattr(row, field, value)
    await _register_mapped_parameter(db, row)
    await db.commit()
    await db.refresh(row)
    await mqtt_subscriber.reload()
    return row


@router.delete("/topic-maps/{map_id}", status_code=204)
async def delete_topic_map(
    map_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> None:
    """Remove a mapping and resubscribe."""
    row = await db.get(LiveLinkTopicMap, map_id)
    if row is None:
        raise HTTPException(404, "Topic map not found")
    await db.delete(row)
    await db.commit()
    await mqtt_subscriber.reload()


@router.post("/topic-discovery", response_model=list[dict])
async def discover_topics(
    body: TopicDiscoveryRequest,
    current_user: User | None = Depends(get_current_admin_user),
) -> list[dict[str, str]]:
    """Listen briefly and report what the broker is publishing."""
    try:
        return await mqtt_subscriber.discover_topics(
            prefix=body.prefix, seconds=min(body.seconds, 60)
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/presets", response_model=list[PresetInfo])
async def list_presets(
    current_user: User | None = Depends(get_current_admin_user),
) -> list[PresetInfo]:
    """Sensor templates, with the readings each sensor publishes."""
    return [
        PresetInfo(
            name=p.name,
            title=p.title,
            description=p.description,
            kind=p.kind,
            readings=[
                PresetReadingInfo(
                    suffix=r.suffix,
                    name=r.name,
                    unit=r.unit,
                    default_topic=r.default_topic,
                    keywords=list(r.keywords),
                    required=r.required,
                )
                for r in p.readings
            ],
        )
        for p in PRESETS.values()
    ]


@router.post("/presets/{name}/apply", response_model=LiveLinkDeviceResponse, status_code=201)
async def apply_preset(
    name: str,
    body: PresetApplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> LiveLinkDevice:
    """Add one sensor: its own device, and a topic map per reading given.

    Which readings a preset has, and which it requires, is the preset's, so
    `topics` is checked against it here rather than on the schema.

    Each reading's parameter gets the preset's `storage_interval_seconds`.
    REQUIRED, not tuning: retained messages replay on every resubscribe and
    the storage path stamps server time, so without it each reconnect writes a
    fresh row.
    """
    preset = PRESETS.get(name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Unknown preset {name!r}")

    known = {reading.suffix for reading in preset.readings}
    unknown = sorted(set(body.topics) - known)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"{preset.title} has no reading {', '.join(unknown)}",
        )
    missing = [r.name for r in preset.readings if r.required and r.suffix not in body.topics]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"A topic is required for: {', '.join(missing)}"
        )

    vin = await _resolve_new_device_vin(db, body.vin, current_user)
    device = await create_sensor(db, preset, body.label, vin, body.topics)
    await db.commit()
    await db.refresh(device)
    await mqtt_subscriber.reload()
    return device
