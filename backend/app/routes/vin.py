"""VIN-related API endpoints."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.countries import normalize_country_code
from app.database import get_db
from app.models.user import User
from app.schemas.vin import (
    AutoRefTestRequest,
    AutoRefTestResponse,
    AutoRefVersionRequest,
    Provider,
    VINDecodeRequest,
    VINDecodeResponse,
    VINProvidersResponse,
    country_input,
)
from app.services import vin_decoder
from app.services.auth import get_current_admin_user, require_auth
from app.services.autoref import (
    AutoRefAuthError,
    AutoRefError,
    AutoRefQuotaError,
    AutoRefService,
    AutoRefUnavailableError,
)
from app.services.country_profile_service import instance_default_country
from app.services.nhtsa import NHTSAService
from app.services.oidc import MASKED_SECRET_PLACEHOLDER
from app.services.settings_service import SecretUnreadableError, SettingsService, reenter_message
from app.utils import wmi as wmi_table
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vin", tags=["VIN"])


async def _resolve_country(
    db: AsyncSession, current_user: User | None, sent: str | None
) -> str | None:
    """The country that orders the decoders: the client's, the user's, the instance's."""
    if sent:
        return sent
    if current_user is not None:
        code = normalize_country_code(current_user.country)
        if code:
            return code
    return await instance_default_country(db)


def _autoref_http_error(exc: Exception) -> HTTPException | None:
    """The status for an AutoRef failure, None for anything else.

    A no-match isn't here: each route words its own 404.
    """
    if isinstance(exc, vin_decoder.AutoRefNotConfiguredError):
        return HTTPException(status_code=409, detail="AutoRef is not configured")
    if isinstance(exc, AutoRefAuthError):
        return HTTPException(status_code=502, detail="AutoRef rejected the API key")
    if isinstance(exc, AutoRefQuotaError):
        return HTTPException(status_code=429, detail="AutoRef quota used up")
    if isinstance(exc, AutoRefUnavailableError):
        if exc.timed_out:
            return HTTPException(status_code=504, detail="AutoRef request timed out")
        if exc.status is None:
            return HTTPException(status_code=503, detail="Cannot connect to AutoRef")
        return HTTPException(status_code=502, detail="AutoRef error")
    return None


async def _decode_vin_helper(
    vin: str,
    *,
    provider: Provider = "nhtsa",
    autoref_key: str | None = None,
    fallback: bool = False,
) -> VINDecodeResponse:
    """
    Shared helper for VIN decoding logic.

    Args:
        vin: 17-character Vehicle Identification Number
        provider: Which decoder answers
        autoref_key: The AutoRef key, when AutoRef is configured
        fallback: Automatic: an AutoRef miss or error asks NHTSA instead

    Returns:
        VINDecodeResponse with decoded vehicle information

    Raises:
        HTTPException: For invalid VIN format or decoder errors
    """
    try:
        # The NHTSA call sits in `vin_decoder.decode`, which completes the
        # answer from the VIN's own structure (#211); the services are built
        # here so a test can patch them in this module as before.
        nhtsa = NHTSAService()
        autoref = AutoRefService(autoref_key) if autoref_key else None
        vehicle_info = await vin_decoder.decode(
            vin, nhtsa, provider=provider, autoref=autoref, fallback=fallback
        )
        return VINDecodeResponse(**vehicle_info)

    except vin_decoder.AutoRefNoMatchError:
        raise HTTPException(status_code=404, detail="AutoRef has no record for this VIN")
    except (vin_decoder.AutoRefNotConfiguredError, AutoRefError) as e:
        raise _autoref_http_error(e) or HTTPException(status_code=502, detail="AutoRef error")

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
async def decode_vin(
    request: VINDecodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Decode a VIN with NHTSA or AutoRef.

    Without `provider` (Automatic) the preferred decoder answers first: AutoRef
    for a European country when it has a key, NHTSA otherwise and for every
    North American VIN. An AutoRef miss or error then asks NHTSA and says so in
    `notes`. A chosen `provider` runs alone.

    **Raises:**
    - **400**: Invalid VIN format
    - **404**: AutoRef chosen and it has no record for this VIN
    - **409**: AutoRef chosen and it isn't configured
    - **429**: AutoRef chosen and its quota is used up
    - **502**: AutoRef rejected the key or failed; NHTSA failed
    - **503/504**: the chosen decoder can't be reached or timed out
    """
    key = await vin_decoder.autoref_key(db)
    if request.provider is None:
        country = await _resolve_country(db, current_user, request.country)
        available = vin_decoder.available_providers(key is not None)
        provider = vin_decoder.preferred_provider(country, available, request.vin)
        return await _decode_vin_helper(
            request.vin, provider=provider, autoref_key=key, fallback=True
        )
    return await _decode_vin_helper(request.vin, provider=request.provider, autoref_key=key)


@router.post("/autoref/version", response_model=VINDecodeResponse)
async def decode_autoref_version(
    request: AutoRefVersionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Decode the version picked from an AutoRef decode's `candidates`.

    Fetches that version's full record (1 AutoRef request), checks it still
    belongs to the VIN and is still the version picked, then answers like a
    decode.

    **Raises:**
    - **400**: Invalid VIN format
    - **404**: AutoRef no longer has this version (its ids change when it rebuilds)
    - **409**: AutoRef isn't configured
    - **422**: A malformed pick
    - **429**: AutoRef's quota is used up
    - **502**: AutoRef rejected the key or failed
    - **503/504**: AutoRef can't be reached or timed out
    """
    key = await vin_decoder.autoref_key(db)
    try:
        autoref = AutoRefService(key) if key else None
        info = await vin_decoder.decode_version(request.vin, autoref, request)
        return VINDecodeResponse(**info)
    except vin_decoder.AutoRefNoMatchError:
        raise HTTPException(
            status_code=404, detail="AutoRef no longer has this version; decode the VIN again"
        )
    except (vin_decoder.AutoRefNotConfiguredError, AutoRefError) as e:
        raise _autoref_http_error(e) or HTTPException(status_code=502, detail="AutoRef error")
    except ValueError as e:
        logger.warning("Invalid AutoRef version pick: %s", sanitize_for_log(str(e)))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/providers", response_model=VINProvidersResponse)
async def vin_providers(
    country: str | None = Query(
        None, description="ISO 3166-1 alpha-2; omitted reads the account's"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> VINProvidersResponse:
    """The decoders this instance can use and which one Automatic asks first.

    Open to every user: the settings behind it are admin-only.
    """
    try:
        sent = country_input(country)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    key = await vin_decoder.autoref_key(db)
    available = vin_decoder.available_providers(key is not None)
    resolved = await _resolve_country(db, current_user, sent)
    return VINProvidersResponse(
        available=available, preferred=vin_decoder.preferred_provider(resolved, available)
    )


@router.post("/autoref/test", response_model=AutoRefTestResponse)
async def test_autoref_key(
    body: AutoRefTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_admin_user),
) -> AutoRefTestResponse:
    """Check an AutoRef key against `/usage`, which costs no quota (admin only).

    A null key or the mask tests the stored one. Every failure is a 200 with
    `valid: false`; the key never reaches a log line or an error.
    """
    key = (body.api_key or "").strip()
    if not key or key == MASKED_SECRET_PLACEHOLDER:
        try:
            key = ((await SettingsService.get_secret(db, "autoref_api_key")) or "").strip()
        except SecretUnreadableError:
            return AutoRefTestResponse(valid=False, message=reenter_message("AutoRef API key"))
        if not key:
            return AutoRefTestResponse(valid=False, message="No AutoRef API key is saved")
    try:
        usage = await AutoRefService(key).usage()
    except AutoRefAuthError:
        return AutoRefTestResponse(valid=False, message="AutoRef rejected the API key")
    except AutoRefUnavailableError, AutoRefQuotaError:
        return AutoRefTestResponse(valid=False, message="AutoRef is not reachable")
    return AutoRefTestResponse(
        valid=True,
        message="AutoRef API key is valid",
        plan=usage.plan,
        remaining=usage.remaining,
        limit=usage.limit,
    )


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
