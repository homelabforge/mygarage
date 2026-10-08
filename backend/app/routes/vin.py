"""VIN-related API endpoints."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.models.user import User
from app.schemas.vin import VINDecodeRequest, VINDecodeResponse
from app.services import vin_decoder
from app.services.auth import require_auth
from app.services.nhtsa import NHTSAService
from app.utils import wmi as wmi_table
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vin", tags=["VIN"])


async def _decode_vin_helper(vin: str) -> VINDecodeResponse:
    """
    Shared helper for VIN decoding logic.

    Args:
        vin: 17-character Vehicle Identification Number

    Returns:
        VINDecodeResponse with decoded vehicle information

    Raises:
        HTTPException: For invalid VIN format or NHTSA API errors
    """
    try:
        # The NHTSA call sits in `vin_decoder.decode`, which completes the
        # answer from the VIN's own structure (#211); the service is built
        # here so a test can patch it in this module as before.
        nhtsa = NHTSAService()
        vehicle_info = await vin_decoder.decode(vin, nhtsa)
        return VINDecodeResponse(**vehicle_info)

    except ValueError as e:
        # Invalid VIN format
        logger.warning("Invalid VIN format: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=400, detail=str(e))

    except httpx.TimeoutException:
        logger.error("NHTSA API timeout for VIN %s", sanitize_for_log(vin))
        raise HTTPException(status_code=504, detail="NHTSA API request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to NHTSA API for VIN %s", sanitize_for_log(vin))
        raise HTTPException(status_code=503, detail="Cannot connect to NHTSA API")
    except httpx.HTTPStatusError as e:
        logger.error(
            "NHTSA API error for VIN %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=e.response.status_code, detail="NHTSA API error")


@router.post("/decode", response_model=VINDecodeResponse)
async def decode_vin(request: VINDecodeRequest, current_user: User | None = Depends(require_auth)):
    """
    Decode a VIN using the NHTSA vPIC API.

    This endpoint validates the VIN format and queries the NHTSA database
    to retrieve vehicle information including make, model, year, engine specs,
    and other details.

    **Args:**
    - **vin**: 17-character Vehicle Identification Number

    **Returns:**
    - Vehicle information decoded from the VIN

    **Raises:**
    - **400**: Invalid VIN format
    - **500**: NHTSA API error or service unavailable
    """
    return await _decode_vin_helper(request.vin)


@router.get("/decode/{vin}", response_model=VINDecodeResponse)
async def decode_vin_get(vin: str, current_user: User | None = Depends(require_auth)):
    """
    Decode a VIN using the NHTSA vPIC API (GET endpoint).

    This is a convenience GET endpoint for VIN decoding.
    Supports both GET and POST methods for flexibility.

    **Args:**
    - **vin**: 17-character Vehicle Identification Number

    **Returns:**
    - Vehicle information decoded from the VIN

    **Raises:**
    - **400**: Invalid VIN format
    - **500**: NHTSA API error or service unavailable
    """
    return await _decode_vin_helper(vin)


@router.get("/validate/{vin}")
async def validate_vin_endpoint(vin: str, current_user: User | None = Depends(require_auth)):
    """
    Validate a VIN format without calling NHTSA API.

    This is a quick validation endpoint that checks:
    - Length (must be 17 characters)
    - Valid characters (A-Z, 0-9, excluding I, O, Q)
    - Check digit validation (for North American VINs)

    **Args:**
    - **vin**: Vehicle Identification Number to validate

    **Returns:**
    - Validation result with status and optional error message
    """
    from app.utils.vin import validate_vin

    is_valid, error_msg = validate_vin(vin)

    if is_valid:
        clean = vin.strip().upper()
        known = wmi_table.lookup(clean)
        return JSONResponse(
            status_code=200,
            content={
                "valid": True,
                "vin": clean,
                "message": "VIN format is valid",
                # What the VIN itself says (#211), before any decode.
                "region": wmi_table.region_of(clean),
                "country": known.country if known else wmi_table.country_of(clean),
                "make": known.make if known else None,
            },
        )
    else:
        return JSONResponse(
            status_code=400,
            content={"valid": False, "vin": vin.strip().upper(), "error": error_msg},
        )
