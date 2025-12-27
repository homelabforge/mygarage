"""VIN-related API endpoints."""

import logging
from typing import Optional
import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse

from app.models.user import User
from app.schemas.vin import VINDecodeRequest, VINDecodeResponse
from app.services.auth import require_auth
from app.services.nhtsa import NHTSAService

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
        nhtsa = NHTSAService()
        vehicle_info = await nhtsa.decode_vin(vin)
        return VINDecodeResponse(**vehicle_info)

    except ValueError as e:
        # Invalid VIN format
        logger.warning("Invalid VIN format: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    except httpx.TimeoutException:
        logger.error("NHTSA API timeout for VIN %s", vin)
        raise HTTPException(status_code=504, detail="NHTSA API request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to NHTSA API for VIN %s", vin)
        raise HTTPException(status_code=503, detail="Cannot connect to NHTSA API")
    except httpx.HTTPStatusError as e:
        logger.error("NHTSA API error for VIN %s: %s", vin, e)
        raise HTTPException(
            status_code=e.response.status_code, detail="NHTSA API error"
        )


@router.post("/decode", response_model=VINDecodeResponse)
async def decode_vin(
    request: VINDecodeRequest, current_user: Optional[User] = Depends(require_auth)
):
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
async def decode_vin_get(
    vin: str, current_user: Optional[User] = Depends(require_auth)
):
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
async def validate_vin_endpoint(
    vin: str, current_user: Optional[User] = Depends(require_auth)
):
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
        return JSONResponse(
            status_code=200,
            content={
                "valid": True,
                "vin": vin.strip().upper(),
                "message": "VIN format is valid",
            },
        )
    else:
        return JSONResponse(
            status_code=400,
            content={"valid": False, "vin": vin.strip().upper(), "error": error_msg},
        )
