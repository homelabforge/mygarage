"""LiveLink ingestion endpoint for WiCAN device data."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.livelink_ingest import WiCANPayload
from app.services.dtc_service import DTCService
from app.services.livelink_service import LiveLinkService
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/livelink", tags=["LiveLink Ingestion"])


async def validate_livelink_token(
    db: AsyncSession,
    authorization: str | None,
    device_id: str | None,
) -> bool:
    """
    Validate the provided token against global or per-device tokens.

    Returns True if valid, raises HTTPException if invalid.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract token from "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Use 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1]
    service = LiveLinkService(db)

    # Check per-device token first if device_id provided
    if device_id:
        is_valid = await service.validate_device_token(device_id, token)
        if is_valid:
            return True

    # Fall back to global token
    is_valid = await service.validate_global_token(token)
    if is_valid:
        return True

    raise HTTPException(
        status_code=401,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/ingest", status_code=202)
async def ingest_wican_payload(
    payload: WiCANPayload,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(None),
):
    """
    Receive telemetry data from WiCAN OBD2 devices.

    This endpoint is called by WiCAN PRO devices configured for HTTPS POST.
    Authentication is via Bearer token (global or per-device).

    WiCAN sends two types of payloads:
    - Status payloads (with device_id) - used for discovery and status updates
    - Telemetry-only payloads (just autopid_data) - for high-frequency data

    **Headers:**
    - **Authorization**: Bearer token (required)

    **Request Body:**
    WiCAN payload containing:
    - **autopid_data**: Dictionary of parameter names to values (decoded OBD2 data)
    - **config**: Dictionary of parameter metadata (units, classes) - optional
    - **status**: Device status information - optional (sent periodically)

    **Returns:**
    - 202 Accepted: Payload queued for processing
    - 401 Unauthorized: Invalid or missing token
    - 422 Unprocessable Entity: Invalid payload format
    """
    livelink_service = LiveLinkService(db)

    # Get device_id from status if present, otherwise look up by token
    device_id: str | None = None
    if payload.status:
        device_id = payload.status.device_id
    else:
        # No status block - look up most recently active device for this token
        device_id = await livelink_service.get_device_id_by_token(authorization)
        if not device_id:
            # No device found - this is a telemetry-only payload from an unknown device
            # We can't process it without knowing which device sent it
            logger.warning("Received telemetry without status and no known device for token")
            return {
                "status": "rejected",
                "message": "No device_id in payload and no device associated with this token. "
                "Please send a status payload first to register the device.",
            }

    # Validate token
    await validate_livelink_token(db, authorization, device_id)

    # Check if LiveLink is enabled (use existing service instance)
    if not await livelink_service.is_enabled():
        logger.debug("LiveLink disabled, ignoring payload from %s", device_id)
        return {"status": "disabled", "message": "LiveLink is currently disabled"}

    # Initialize response
    results: dict[str, str | bool | int | None] = {
        "status": "accepted",
        "timestamp": datetime.now(UTC).isoformat(),
        "device_id": device_id,
    }

    try:
        # Handle status block if present (device discovery/status update)
        if payload.status:
            # Auto-discover or update device with version info
            device, is_new = await livelink_service.auto_discover_device(
                device_id=device_id,
                hw_version=payload.status.hw_version,
                fw_version=payload.status.fw_version,
                git_version=payload.status.git_version,
                sta_ip=payload.status.sta_ip,
            )
            results["device_new"] = is_new
            results["device_linked"] = device.vin is not None

            # Update device status
            ecu_online = payload.status.ecu_status == "online"
            await livelink_service.update_device_status(
                device_id=device_id,
                sta_ip=payload.status.sta_ip,
                rssi=payload.status.rssi,
                battery_voltage=payload.status.battery_voltage,
                ecu_status="online" if ecu_online else "offline",
                device_status="online",
            )

            # Handle ECU status transitions for session management
            if device.vin:
                session_service = SessionService(db)
                if ecu_online:
                    await session_service.handle_ecu_online(device.vin, device_id)
                else:
                    await session_service.handle_ecu_offline(device.vin, device_id)
        else:
            # Telemetry-only payload - just get the existing device
            device = await livelink_service.get_device_by_id(device_id)
            if not device:
                return {
                    "status": "rejected",
                    "message": f"Unknown device {device_id}. Send a status payload first.",
                }
            # Update last_seen timestamp to indicate device is still active
            await livelink_service.update_device_status(
                device_id=device_id,
                device_status="online",
            )

        # Process telemetry if device is linked to a vehicle
        if device.vin and payload.autopid_data:
            telemetry_service = TelemetryService(db)

            # Store telemetry using the bulk method
            stored_count = await telemetry_service.store_telemetry(
                vin=device.vin,
                device_id=device_id,
                autopid_data=payload.autopid_data,
                config={
                    k: {"unit": v.unit, "class": v.param_class} for k, v in payload.config.items()
                },
                timestamp=payload.timestamp,
            )
            results["parameters_stored"] = stored_count

            # Check thresholds for each parameter
            for param_key, value in payload.autopid_data.items():
                if value is not None:
                    await telemetry_service.check_thresholds(
                        vin=device.vin,
                        param_key=param_key,
                        value=float(value),
                    )

            # Process DTCs if present in autopid_data (special key)
            dtc_key = "DIAGNOSTIC_TROUBLE_CODES"
            if dtc_key in payload.autopid_data:
                dtc_service = DTCService(db)
                dtc_value = payload.autopid_data.get(dtc_key)
                if dtc_value and isinstance(dtc_value, str):
                    # DTCs can be comma-separated string
                    dtc_codes = [c.strip() for c in dtc_value.split(",") if c.strip()]
                    for code in dtc_codes:
                        await dtc_service.record_dtc(
                            vin=device.vin,
                            device_id=device_id,
                            code=code,
                        )
                    results["dtcs_recorded"] = len(dtc_codes)

        # Commit all changes
        await db.commit()

    except Exception as e:
        logger.error("Error processing payload from %s: %s", device_id, e)
        await db.rollback()
        # Still return 202 - we accepted it even if processing failed
        results["processing_error"] = str(e)

    return results
