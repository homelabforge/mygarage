"""Window sticker routes for MyGarage API."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.window_sticker import (
    OCRStatusResponse,
    ParserInfo,
    WindowStickerDataUpdate,
    WindowStickerResponse,
    WindowStickerTestResponse,
)
from app.services.auth import (
    get_vehicle_for_owner_or_403,
    get_vehicle_or_403,
    require_auth,
)
from app.services.settings_service import SettingsService
from app.services.window_sticker_ocr import WindowStickerOCRService
from app.services.window_sticker_service import WindowStickerService
from app.utils.vehicle_key import download_tag

router = APIRouter(prefix="/api/vehicles", tags=["window-sticker"])

# The Settings > Files switches. Off stops new stickers and scans only: the
# sticker on file can still be read, downloaded, edited and deleted (Fable F-12).
STICKERS_SWITCHED_OFF = "Window sticker uploads are switched off in Settings > Files"
OCR_SWITCHED_OFF = "Window sticker OCR is switched off in Settings > Files"


async def _require_stickers_on(db: AsyncSession) -> None:
    """409 when `window_sticker_enabled` is off. Call it after the access check,
    so a caller who can't reach the vehicle learns nothing about the switch."""
    if not await SettingsService.get_bool(db, "window_sticker_enabled", True):
        raise HTTPException(status_code=409, detail=STICKERS_SWITCHED_OFF)


async def _ocr_on(db: AsyncSession) -> bool:
    """Whether `window_sticker_ocr_enabled` is on (missing or blank reads as on)."""
    return await SettingsService.get_bool(db, "window_sticker_ocr_enabled", True)


@router.get("/{vin}/window-sticker", response_model=WindowStickerResponse)
async def get_window_sticker(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> WindowStickerResponse:
    """Get window sticker data for a vehicle."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    return WindowStickerResponse.model_validate(vehicle)


@router.post(
    "/{vin}/window-sticker/upload",
    response_model=WindowStickerResponse,
    status_code=201,
)
async def upload_window_sticker(
    vin: str,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    replace: Annotated[bool, Form()] = False,
    current_user: User | None = Depends(require_auth),
) -> WindowStickerResponse:
    """
    Upload a window sticker file and extract data using OCR.

    The scan fills only the sticker fields that are empty. With `replace` and a
    sticker already on file, the old sticker's fields are cleared first. A scan
    that read nothing changes no field and says so in `scan_read_nothing`.
    Extracted data can be edited via the PATCH endpoint.

    With `window_sticker_enabled` off this is a 409. With
    `window_sticker_ocr_enabled` off the file is stored without a scan: no
    field is filled or cleared, the scan metadata empties, and the response
    says so in `ocr_skipped`.
    """
    # Window-sticker upload mutates the vehicle row (incl. vehicle.color) -> OWNER-only (D-8).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)
    await _require_stickers_on(db)
    ocr_enabled = await _ocr_on(db)

    saved = await WindowStickerService(db).upload(
        vehicle, file, replace=replace, ocr_enabled=ocr_enabled
    )
    response = WindowStickerResponse.model_validate(saved.vehicle)
    response.scan_read_nothing = saved.scan_read_nothing
    response.ocr_skipped = saved.ocr_skipped
    return response


@router.post("/{vin}/window-sticker/test", response_model=WindowStickerTestResponse)
async def test_window_sticker_extraction(
    vin: str,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
    parser: str | None = Query(None, description="Specific parser to use"),
) -> WindowStickerTestResponse:
    """
    Test window sticker extraction without saving.

    Returns detailed extraction results including raw text,
    parsed data, validation warnings, and debug information. A 409 when
    window stickers or their OCR are switched off.
    """
    # Dry-run OCR test: reads the vehicle but persists nothing, so read access
    # (incl. a read-share) is sufficient.
    vehicle = await get_vehicle_or_403(vin, current_user, db)  # tripwire: read-only
    await _require_stickers_on(db)
    if not await _ocr_on(db):
        raise HTTPException(status_code=409, detail=OCR_SWITCHED_OFF)

    return await WindowStickerService(db).test_extraction(file, vehicle=vehicle, parser=parser)


@router.patch("/{vin}/window-sticker/data", response_model=WindowStickerResponse)
async def update_window_sticker_data(
    vin: str,
    update_data: WindowStickerDataUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> WindowStickerResponse:
    """
    Update window sticker extracted data.

    Use this endpoint to manually correct or add data that was not extracted by OCR.
    """
    # Editing sticker data mutates the vehicle row -> OWNER-only (D-8).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    saved = await WindowStickerService(db).update_data(vehicle, update_data)
    return WindowStickerResponse.model_validate(saved)


@router.delete("/{vin}/window-sticker", status_code=204)
async def delete_window_sticker(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete window sticker file and clear all extracted data."""
    # Deleting the sticker clears vehicle-row fields -> OWNER-only (D-8).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    await WindowStickerService(db).delete(vehicle)


@router.get("/{vin}/window-sticker/file")
async def download_window_sticker_file(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> FileResponse:
    """Download the window sticker file."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    file_path = WindowStickerService(db).stored_file(vehicle)

    # Determine media type based on extension
    media_type_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    media_type = media_type_map.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=f"window_sticker_{download_tag(vehicle)}{file_path.suffix}",
    )


# Additional routes for parser management


@router.get("/window-sticker/parsers", response_model=list[ParserInfo])
async def list_parsers(
    current_user: User | None = Depends(require_auth),
) -> list[ParserInfo]:
    """List all available window sticker parsers."""
    ocr_service = WindowStickerOCRService()
    parsers = ocr_service.list_available_parsers()
    return [ParserInfo(**p) for p in parsers]


@router.get("/window-sticker/ocr-status", response_model=OCRStatusResponse)
async def get_ocr_status(
    current_user: User | None = Depends(require_auth),
) -> OCRStatusResponse:
    """Get OCR engine status and availability."""
    ocr_service = WindowStickerOCRService()
    return OCRStatusResponse(**ocr_service.get_ocr_status())
