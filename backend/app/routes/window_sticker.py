"""Window sticker routes for MyGarage API."""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas._money import MONEY_MAX, OptionalMoney
from app.services.auth import (
    get_vehicle_for_owner_or_403,
    get_vehicle_or_403,
    require_auth,
)
from app.services.window_sticker_ocr import WindowStickerOCRService
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.vin import validate_vin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["window-sticker"])

# Window sticker storage configuration
STICKER_STORAGE_PATH = settings.documents_dir

# Allowed file extensions
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# Numeric(5,2) on the vehicle row.
_FUEL_ECONOMY_MAX = Decimal("999.99")

# The parsed numbers and the largest each column holds. OCR can misread a
# price, and nothing validates what a parser returns before it is written.
_PARSED_NUMBER_MAX = {
    "msrp_base": MONEY_MAX,
    "msrp_options": MONEY_MAX,
    "msrp_total": MONEY_MAX,
    "destination_charge": MONEY_MAX,
    "fuel_economy_city_l_per_100km": _FUEL_ECONOMY_MAX,
    "fuel_economy_highway_l_per_100km": _FUEL_ECONOMY_MAX,
    "fuel_economy_combined_l_per_100km": _FUEL_ECONOMY_MAX,
}


def _drop_numbers_that_cannot_be_stored(extracted: dict[str, Any]) -> None:
    """Drop a parsed number that is negative, not a number, or past its column.

    It's a misread, not a value: written, it was a 500 on PostgreSQL with the
    upload already on disk. The review form shows the field empty instead.
    """
    for key, top in _PARSED_NUMBER_MAX.items():
        value = extracted.get(key)
        if value is None:
            continue
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
            fits = number.is_finite() and 0 <= number <= top
        except ArithmeticError:  # Decimal's InvalidOperation: not a number at all
            fits = False
        if not fits:
            logger.warning(
                "Window sticker: dropped parsed %s=%s, outside 0 to %s",
                key,
                sanitize_for_log(value),
                top,
            )
            del extracted[key]


def _fit_to_column(column: str, value: Any) -> Any:
    """Cut a parsed string to what its vehicle column holds; anything else passes.

    OCR sometimes reads a paragraph into a short field. PostgreSQL refused it,
    a 500 with the upload already on disk, and SQLite kept it whole.
    """
    length: int | None = getattr(Vehicle.__table__.c[column].type, "length", None)
    if not isinstance(value, str) or length is None or len(value) <= length:
        return value
    # Never the text itself: it's OCR output, so it's whatever was on the paper.
    logger.warning(
        "Window sticker: cut parsed %s from %d to %d characters", column, len(value), length
    )
    return value[:length]


#: Sticker data columns: filled from a scan only where empty, unless replacing.
STICKER_DATA_FIELDS: tuple[str, ...] = (
    "msrp_base",
    "msrp_options",
    "msrp_total",
    "destination_charge",
    "fuel_economy_city_l_per_100km",
    "fuel_economy_highway_l_per_100km",
    "fuel_economy_combined_l_per_100km",
    "standard_equipment",
    "optional_equipment",
    "assembly_location",
    "exterior_color",
    "interior_color",
    "sticker_engine_description",
    "sticker_transmission_description",
    "sticker_drivetrain",
    "wheel_specs",
    "tire_specs",
    "warranty_powertrain",
    "warranty_basic",
    "environmental_rating_ghg",
    "environmental_rating_smog",
    "window_sticker_options_detail",
    "window_sticker_packages",
)
#: What the scan of the file on record found: reset by every upload.
STICKER_SCAN_FIELDS: tuple[str, ...] = (
    "window_sticker_parser_used",
    "window_sticker_confidence_score",
    "window_sticker_extracted_vin",
)


def _is_empty_sticker_value(value: object) -> bool:
    """None, a blank string, or an empty JSON object/list. 0 and False are values."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list)):
        return not value
    return False


def _unlink_quietly(path: Path) -> None:
    """Remove a sticker file if it's there; a failure is an orphan, not an error."""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(
            "Failed to delete window sticker file %s: %s",
            sanitize_for_log(path),
            sanitize_for_log(e),
        )


class WindowStickerDataUpdate(BaseModel):
    """The review's edits. Omitted keeps, null clears; widths match the columns."""

    msrp_base: OptionalMoney = None
    msrp_options: OptionalMoney = None
    msrp_total: OptionalMoney = None
    destination_charge: OptionalMoney = None
    fuel_economy_city_l_per_100km: Decimal | None = Field(None, ge=0, le=_FUEL_ECONOMY_MAX)
    fuel_economy_highway_l_per_100km: Decimal | None = Field(None, ge=0, le=_FUEL_ECONOMY_MAX)
    fuel_economy_combined_l_per_100km: Decimal | None = Field(None, ge=0, le=_FUEL_ECONOMY_MAX)
    standard_equipment: dict[str, Any] | None = None
    optional_equipment: dict[str, Any] | None = None
    assembly_location: str | None = Field(None, max_length=100)
    exterior_color: str | None = Field(None, max_length=100)
    interior_color: str | None = Field(None, max_length=100)
    sticker_engine_description: str | None = Field(None, max_length=150)
    sticker_transmission_description: str | None = Field(None, max_length=150)
    sticker_drivetrain: str | None = Field(None, max_length=50)
    wheel_specs: str | None = Field(None, max_length=100)
    tire_specs: str | None = Field(None, max_length=100)
    warranty_powertrain: str | None = Field(None, max_length=100)
    warranty_basic: str | None = Field(None, max_length=100)
    environmental_rating_ghg: str | None = Field(None, max_length=10)
    environmental_rating_smog: str | None = Field(None, max_length=10)


class WindowStickerResponse(BaseModel):
    """Schema for window sticker response."""

    vin: str
    window_sticker_file_path: str | None
    window_sticker_uploaded_at: datetime | None
    msrp_base: Decimal | None
    msrp_options: Decimal | None
    msrp_total: Decimal | None
    destination_charge: Decimal | None
    fuel_economy_city_l_per_100km: Decimal | None
    fuel_economy_highway_l_per_100km: Decimal | None
    fuel_economy_combined_l_per_100km: Decimal | None
    standard_equipment: dict[str, Any] | None
    optional_equipment: dict[str, Any] | None
    assembly_location: str | None
    exterior_color: str | None
    interior_color: str | None
    sticker_engine_description: str | None
    sticker_transmission_description: str | None
    sticker_drivetrain: str | None
    wheel_specs: str | None
    tire_specs: str | None
    warranty_powertrain: str | None
    warranty_basic: str | None
    environmental_rating_ghg: str | None
    environmental_rating_smog: str | None
    window_sticker_options_detail: dict[str, Any] | None
    window_sticker_packages: dict[str, Any] | None
    window_sticker_parser_used: str | None
    window_sticker_confidence_score: Decimal | None
    window_sticker_extracted_vin: str | None
    # Only the upload sets it: the scan found no sticker field, or OCR failed.
    scan_read_nothing: bool = False

    class Config:
        from_attributes = True


class WindowStickerTestResponse(BaseModel):
    """Schema for window sticker test extraction response."""

    success: bool
    parser_name: str | None
    manufacturer_detected: str | None
    raw_text: str | None
    extracted_data: dict[str, Any] | None
    validation_warnings: list[str]
    error: str | None


class ParserInfo(BaseModel):
    """Schema for parser information."""

    manufacturer: str
    parser_class: str
    supported_makes: list[str]


class OCRStatusResponse(BaseModel):
    """Schema for OCR status response."""

    pymupdf_available: bool
    tesseract_available: bool
    paddleocr_enabled: bool
    paddleocr_available: bool


ALLOWED_STICKER_MIMES = {"application/pdf", "image/jpeg", "image/png"}


def validate_sticker_file(file: UploadFile) -> None:
    """Validate uploaded window sticker file (extension, MIME, and magic bytes)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")

    # Check file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {allowed}",
        )

    # Check declared MIME type
    if file.content_type not in ALLOWED_STICKER_MIMES:
        allowed = ", ".join(sorted(ALLOWED_STICKER_MIMES))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content type. Allowed: {allowed}",
        )

    # Magic-byte check: reject a file whose bytes don't match its declared type
    # (e.g. an executable renamed to .pdf). Read the header and rewind.
    from app.utils.file_validation import verify_file_content_type

    header = file.file.read(16)
    file.file.seek(0)
    if not verify_file_content_type(header, file.content_type):
        raise HTTPException(status_code=400, detail="File content does not match its declared type")


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
    """
    # Window-sticker upload mutates the vehicle row (incl. vehicle.color) -> OWNER-only (D-8).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    # Validate file
    validate_sticker_file(file)

    # Check file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to beginning

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Generate unique filename
    file_ext = Path(file.filename).suffix.lower()
    unique_filename = f"window_sticker_{uuid.uuid4()}{file_ext}"

    # Validate VIN before using in path (prevent path traversal)
    is_valid, error = validate_vin(vin)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid VIN format: {error}")

    # Create VIN-specific directory
    vin_dir = STICKER_STORAGE_PATH / vin
    vin_dir.mkdir(parents=True, exist_ok=True)

    # The old file stays until the new one is committed, so a failed upload
    # still leaves the saved sticker in place.
    old_path = vehicle.window_sticker_file_path

    # Save new file
    file_path = vin_dir / unique_filename
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        logger.info("Saved window sticker to: %s", file_path)
    except Exception:
        logger.exception("Failed to save window sticker for %s", sanitize_for_log(vin))
        _unlink_quietly(file_path)  # whatever got written before it failed
        raise HTTPException(status_code=500, detail="Failed to save file")

    try:
        ocr_failed = False
        try:
            extracted_data = await WindowStickerOCRService().extract_data_from_file(
                str(file_path), vin=vin, make=vehicle.make
            )
            logger.info("Extracted %d fields from window sticker", len(extracted_data))
        except Exception as e:
            logger.error("OCR extraction failed: %s", sanitize_for_log(e))
            extracted_data, ocr_failed = {}, True
        _drop_numbers_that_cannot_be_stored(extracted_data)
        scan_read_nothing = ocr_failed or not any(f in extracted_data for f in STICKER_DATA_FIELDS)

        # D1 (2026-08-01): a scan fills empty fields only, so values typed by
        # hand or corrected in the review survive a re-upload. `replace` clears
        # first, but never on a scan that read nothing (it would just erase).
        # `old_path`: replace means replacing a sticker; with none on file it
        # would only erase values typed through PATCH (Fable F-6).
        if replace and old_path and not scan_read_nothing:
            for field in STICKER_DATA_FIELDS:
                setattr(vehicle, field, None)
        for field in STICKER_DATA_FIELDS:
            if field in extracted_data and _is_empty_sticker_value(getattr(vehicle, field)):
                setattr(vehicle, field, _fit_to_column(field, extracted_data[field]))
        for field in STICKER_SCAN_FIELDS:  # None passes _fit_to_column untouched
            setattr(vehicle, field, _fit_to_column(field, extracted_data.get(field)))
        if not vehicle.color and extracted_data.get("exterior_color"):
            vehicle.color = _fit_to_column("color", extracted_data["exterior_color"])
        vehicle.window_sticker_file_path = str(file_path)
        vehicle.window_sticker_uploaded_at = utc_now()
        await db.commit()
    except Exception as e:
        # Nothing committed points at the new file, so it goes first; the old
        # one was never touched.
        _unlink_quietly(file_path)
        await db.rollback()
        if isinstance(e, HTTPException):
            raise
        logger.exception("Window sticker upload failed for %s", sanitize_for_log(vin))
        # Starlette answers anything else with a 500 and then re-raises it,
        # which the test client turns into an exception. Same 500 as the write.
        raise HTTPException(status_code=500, detail="Failed to save window sticker") from e
    # Only now is the old file unreferenced.
    if old_path and old_path != str(file_path):
        _unlink_quietly(Path(old_path))
    await db.refresh(vehicle)
    response = WindowStickerResponse.model_validate(vehicle)
    response.scan_read_nothing = scan_read_nothing
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
    parsed data, validation warnings, and debug information.
    """
    # Dry-run OCR test: reads the vehicle but persists nothing, so read access
    # (incl. a read-share) is sufficient.
    vehicle = await get_vehicle_or_403(vin, current_user, db)  # tripwire: read-only

    # Validate file
    validate_sticker_file(file)

    # Check file size
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Save to temp file
    file_ext = Path(file.filename).suffix.lower()
    temp_filename = f"temp_test_{uuid.uuid4()}{file_ext}"
    temp_dir = STICKER_STORAGE_PATH / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / temp_filename

    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        # Run test extraction
        ocr_service = WindowStickerOCRService()
        test_result = await ocr_service.test_extraction(
            str(temp_path),
            vin=vin,
            make=vehicle.make,
            parser_name=parser,
        )

        return WindowStickerTestResponse(**test_result)

    finally:
        # Clean up temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as e:
                logger.warning("Failed to delete temp file: %s", e)


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

    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)

    await db.commit()
    await db.refresh(vehicle)

    return WindowStickerResponse.model_validate(vehicle)


@router.delete("/{vin}/window-sticker", status_code=204)
async def delete_window_sticker(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete window sticker file and clear all extracted data."""
    # Deleting the sticker clears vehicle-row fields -> OWNER-only (D-8).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    if not vehicle.window_sticker_file_path:
        raise HTTPException(status_code=404, detail="No window sticker found for this vehicle")

    # Delete file
    file_path = Path(vehicle.window_sticker_file_path)
    if file_path.exists():
        try:
            file_path.unlink()
            logger.info("Deleted window sticker: %s", file_path)
        except Exception as e:
            logger.error("Failed to delete window sticker file: %s", e)

    # Clear all window sticker data
    for field in (
        "window_sticker_file_path",
        "window_sticker_uploaded_at",
        *STICKER_DATA_FIELDS,
        *STICKER_SCAN_FIELDS,
    ):
        setattr(vehicle, field, None)

    await db.commit()


@router.get("/{vin}/window-sticker/file")
async def download_window_sticker_file(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> FileResponse:
    """Download the window sticker file."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    if not vehicle.window_sticker_file_path:
        raise HTTPException(status_code=404, detail="No window sticker found for this vehicle")

    file_path = Path(vehicle.window_sticker_file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Window sticker file not found on disk")

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
        filename=f"window_sticker_{vin}{file_path.suffix}",
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
