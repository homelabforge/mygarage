"""VIN-related API endpoints."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.vin import VINDecodeRequest, VINDecodeResponse
from app.services.auth import require_auth
from app.services.nhtsa import NHTSAService
from app.services.vin_decoders import NHTSAVINDecoder, get_vin_decoder_router
from app.services.vin_decoders.european import EuropeanVINDecoder
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vin", tags=["VIN"])


async def _decode_vin_helper(vin: str, db: AsyncSession | None = None) -> VINDecodeResponse:
    """
    Shared helper for VIN decoding logic with multi-provider routing.

    Args:
        vin: 17-character Vehicle Identification Number
        db: Optional database session to load user/system settings

    Returns:
        VINDecodeResponse with decoded vehicle information

    Raises:
        HTTPException: For invalid VIN format or upstream API errors
    """
    try:
        # Instantiate NHTSAService so tests patching app.routes.vin.NHTSAService remain effective
        nhtsa = NHTSAService()
        vin_router = get_vin_decoder_router()
        vin_router.register_decoder(NHTSAVINDecoder(nhtsa_service=nhtsa))

        # Check DB settings for European VIN decoder if database session is provided
        if db is not None:
            try:
                from app.services.settings_service import SettingsService

                api_key_setting = await SettingsService.get(db, "european_vin_api_key")
                enabled_setting = await SettingsService.get_bool(
                    db, "european_vin_enabled", default=True
                )

                european_decoder = vin_router.get_decoder("european")
                if european_decoder and isinstance(european_decoder, EuropeanVINDecoder):
                    if api_key_setting and api_key_setting.value:
                        european_decoder.set_api_key(api_key_setting.value)
                    european_decoder.enabled = enabled_setting
            except Exception as e:
                logger.warning(
                    "Failed to load VIN settings from database: %s", sanitize_for_log(e)
                )

        vehicle_info = await vin_router.decode_vin(vin)
        return VINDecodeResponse(**vehicle_info)

    except ValueError as e:
        # Invalid VIN format or no vehicle found
        logger.warning("VIN decode error: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=400, detail=str(e))

    except httpx.TimeoutException:
        logger.error("VIN API timeout for VIN %s", sanitize_for_log(vin))
        raise HTTPException(status_code=504, detail="NHTSA API request timed out")
    except httpx.ConnectError:
        logger.error("Cannot connect to VIN API for VIN %s", sanitize_for_log(vin))
        raise HTTPException(status_code=503, detail="Cannot connect to NHTSA API")
    except httpx.HTTPStatusError as e:
        logger.error(
            "VIN API error for VIN %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=e.response.status_code, detail="NHTSA API error")


@router.post("/decode", response_model=VINDecodeResponse)
async def decode_vin(
    request: VINDecodeRequest,
    current_user: User | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
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
    return await _decode_vin_helper(request.vin, db=db)


@router.get("/decode/{vin}", response_model=VINDecodeResponse)
async def decode_vin_get(
    vin: str,
    current_user: User | None = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
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
    return await _decode_vin_helper(vin, db=db)


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
