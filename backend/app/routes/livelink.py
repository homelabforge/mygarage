"""LiveLink ingestion endpoint for WiCAN device data."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.livelink_ingest import WiCANPayload
from app.services.livelink_ingest import ingest
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import WicanHttpsEnvelope
from app.services.livelink_sources.wican import WicanModule
from app.utils.datetime_utils import utc_now

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
    Authentication is via Bearer token (global or per-device). The payload is
    processed before the response is sent, through the same pipeline as MQTT.

    WiCAN sends two types of payloads:
    - Status payloads (with device_id): sent with `config` on the first POST after
      a cold boot, and used for discovery and status updates
    - Telemetry-only payloads (just autopid_data): every cycle; the device is
      found by its token

    **Headers:**
    - **Authorization**: Bearer token (required)

    **Request Body:**
    WiCAN payload containing:
    - **autopid_data**: Dictionary of parameter names to values (decoded OBD2 data)
    - **config**: Dictionary of parameter metadata (units, classes); kept per device
    - **status**: Device status information - optional

    **Returns:**
    - 202 Accepted: Payload processed (a `processing_error` key says it failed)
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
                "message": "No device_id in payload and cannot resolve device from token. "
                "Send a status payload first to register the device, or use per-device "
                "tokens for multi-device setups.",
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
        "timestamp": utc_now().isoformat() + "Z",
        "device_id": device_id,
    }

    try:
        outcome = await ingest(
            WicanModule(), WicanHttpsEnvelope(device_id=device_id, payload=payload), db
        )
        device = outcome.device
        if device is None:
            return {
                "status": "rejected",
                "message": f"Unknown device {device_id}. Send a status payload first.",
            }
        if outcome.reason == "device_disabled":
            # Its declared units and versions were still recorded.
            await db.commit()
            return {
                "status": "disabled",
                "timestamp": results["timestamp"],
                "device_id": device_id,
                "message": "This device is disabled",
            }

        if payload.status:
            results["device_new"] = outcome.discovered
            results["device_linked"] = device.vin is not None
        if device.vin and payload.autopid_data:
            results["parameters_stored"] = outcome.stored_count
        if outcome.dtc_count:
            results["dtcs_recorded"] = outcome.dtc_count

        await db.commit()

    except Exception as e:
        logger.error("Error processing payload from %s: %s", device_id, e)
        await db.rollback()
        # Still return 202 - we accepted it even if processing failed
        results["processing_error"] = True

    return results
