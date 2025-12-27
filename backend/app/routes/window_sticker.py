"""Window sticker routes for MyGarage API."""

import logging
import uuid
from pathlib import Path
from typing import Annotated, Optional
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.config import settings
from app.database import get_db
from app.models import Vehicle
from app.models.user import User
from app.services.auth import require_auth
from app.services.window_sticker_ocr import WindowStickerOCRService
from app.utils.vin import validate_vin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["window-sticker"])

# Window sticker storage configuration
STICKER_STORAGE_PATH = settings.documents_dir

# Allowed file extensions
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class WindowStickerDataUpdate(BaseModel):
    """Schema for updating window sticker extracted data."""

    msrp_base: Decimal | None = None
    msrp_options: Decimal | None = None
    msrp_total: Decimal | None = None
    destination_charge: Decimal | None = None
    fuel_economy_city: int | None = None
    fuel_economy_highway: int | None = None
    fuel_economy_combined: int | None = None
    standard_equipment: dict | None = None
    optional_equipment: dict | None = None
    assembly_location: str | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    warranty_powertrain: str | None = None
    warranty_basic: str | None = None


class WindowStickerResponse(BaseModel):
    """Schema for window sticker response."""

    vin: str
    window_sticker_file_path: str | None
    window_sticker_uploaded_at: datetime | None
    msrp_base: Decimal | None
    msrp_options: Decimal | None
    msrp_total: Decimal | None
    destination_charge: Decimal | None
    fuel_economy_city: int | None
    fuel_economy_highway: int | None
    fuel_economy_combined: int | None
    standard_equipment: dict | None
    optional_equipment: dict | None
    assembly_location: str | None
    exterior_color: str | None
    interior_color: str | None
    sticker_engine_description: str | None
    sticker_transmission_description: str | None
    wheel_specs: str | None
    tire_specs: str | None
    warranty_powertrain: str | None
    warranty_basic: str | None
    environmental_rating_ghg: str | None
    environmental_rating_smog: str | None
    window_sticker_options_detail: dict | None
    window_sticker_packages: dict | None
    window_sticker_parser_used: str | None
    window_sticker_confidence_score: Decimal | None

    class Config:
        from_attributes = True


class WindowStickerTestResponse(BaseModel):
    """Schema for window sticker test extraction response."""

    success: bool
    parser_name: str | None
    manufacturer_detected: str | None
    raw_text: str | None
    extracted_data: dict | None
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


def validate_sticker_file(file: UploadFile) -> None:
    """Validate uploaded window sticker file."""
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


@router.get("/{vin}/window-sticker", response_model=WindowStickerResponse)
async def get_window_sticker(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_auth),
) -> WindowStickerResponse:
    """Get window sticker data for a vehicle."""
    # Get vehicle
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    current_user: User = Depends(require_auth),
) -> WindowStickerResponse:
    """
    Upload a window sticker file and extract data using OCR.

    The file will be saved and OCR extraction will be attempted.
    Extracted data can be edited via the PATCH endpoint.
    """
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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

    # Delete old window sticker file if exists
    if vehicle.window_sticker_file_path:
        old_file_path = Path(vehicle.window_sticker_file_path)
        if old_file_path.exists():
            try:
                old_file_path.unlink()
                logger.info("Deleted old window sticker: %s", old_file_path)
            except Exception as e:
                logger.warning("Failed to delete old window sticker: %s", e)

    # Save new file
    file_path = vin_dir / unique_filename
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        logger.info("Saved window sticker to: %s", file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Extract data using OCR with manufacturer-specific parser
    ocr_service = WindowStickerOCRService()
    try:
        extracted_data = await ocr_service.extract_data_from_file(
            str(file_path),
            vin=vin,
            make=vehicle.make,
        )
        logger.info("Extracted data from window sticker: %s", extracted_data)
    except Exception as e:
        logger.error("OCR extraction failed: %s", e)
        extracted_data = {}

    # Update vehicle with file path and extracted data
    vehicle.window_sticker_file_path = str(file_path)
    vehicle.window_sticker_uploaded_at = datetime.now(timezone.utc)

    # Update all extracted fields
    field_mappings = [
        ("msrp_base", "msrp_base"),
        ("msrp_options", "msrp_options"),
        ("msrp_total", "msrp_total"),
        ("destination_charge", "destination_charge"),
        ("fuel_economy_city", "fuel_economy_city"),
        ("fuel_economy_highway", "fuel_economy_highway"),
        ("fuel_economy_combined", "fuel_economy_combined"),
        ("standard_equipment", "standard_equipment"),
        ("optional_equipment", "optional_equipment"),
        ("assembly_location", "assembly_location"),
        ("exterior_color", "exterior_color"),
        ("interior_color", "interior_color"),
        ("sticker_engine_description", "sticker_engine_description"),
        ("sticker_transmission_description", "sticker_transmission_description"),
        ("sticker_drivetrain", "sticker_drivetrain"),
        ("wheel_specs", "wheel_specs"),
        ("tire_specs", "tire_specs"),
        ("warranty_powertrain", "warranty_powertrain"),
        ("warranty_basic", "warranty_basic"),
        ("environmental_rating_ghg", "environmental_rating_ghg"),
        ("environmental_rating_smog", "environmental_rating_smog"),
        ("window_sticker_options_detail", "window_sticker_options_detail"),
        ("window_sticker_packages", "window_sticker_packages"),
        ("window_sticker_parser_used", "window_sticker_parser_used"),
        ("window_sticker_confidence_score", "window_sticker_confidence_score"),
        ("window_sticker_extracted_vin", "window_sticker_extracted_vin"),
    ]

    for db_field, data_key in field_mappings:
        if data_key in extracted_data:
            setattr(vehicle, db_field, extracted_data[data_key])

    # Also populate main vehicle fields from window sticker data
    # Color: use exterior_color if vehicle.color is not set
    if not vehicle.color and extracted_data.get("exterior_color"):
        vehicle.color = extracted_data["exterior_color"]

    await db.commit()
    await db.refresh(vehicle)

    return WindowStickerResponse.model_validate(vehicle)


@router.post("/{vin}/window-sticker/test", response_model=WindowStickerTestResponse)
async def test_window_sticker_extraction(
    vin: str,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_auth),
    parser: Optional[str] = Query(None, description="Specific parser to use"),
) -> WindowStickerTestResponse:
    """
    Test window sticker extraction without saving.

    Returns detailed extraction results including raw text,
    parsed data, validation warnings, and debug information.
    """
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

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
    current_user: User = Depends(require_auth),
) -> WindowStickerResponse:
    """
    Update window sticker extracted data.

    Use this endpoint to manually correct or add data that was not extracted by OCR.
    """
    # Get vehicle
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Update fields (only update non-None values)
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        if value is not None:
            setattr(vehicle, field, value)

    await db.commit()
    await db.refresh(vehicle)

    return WindowStickerResponse.model_validate(vehicle)


@router.delete("/{vin}/window-sticker", status_code=204)
async def delete_window_sticker(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_auth),
) -> None:
    """Delete window sticker file and clear all extracted data."""
    # Get vehicle
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    if not vehicle.window_sticker_file_path:
        raise HTTPException(
            status_code=404, detail="No window sticker found for this vehicle"
        )

    # Delete file
    file_path = Path(vehicle.window_sticker_file_path)
    if file_path.exists():
        try:
            file_path.unlink()
            logger.info("Deleted window sticker: %s", file_path)
        except Exception as e:
            logger.error("Failed to delete window sticker file: %s", e)

    # Clear all window sticker data
    window_sticker_fields = [
        "window_sticker_file_path",
        "window_sticker_uploaded_at",
        "msrp_base",
        "msrp_options",
        "msrp_total",
        "destination_charge",
        "fuel_economy_city",
        "fuel_economy_highway",
        "fuel_economy_combined",
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
        "window_sticker_parser_used",
        "window_sticker_confidence_score",
        "window_sticker_extracted_vin",
    ]

    for field in window_sticker_fields:
        setattr(vehicle, field, None)

    await db.commit()


@router.get("/{vin}/window-sticker/file")
async def download_window_sticker_file(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(require_auth),
) -> FileResponse:
    """Download the window sticker file."""
    # Get vehicle
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    if not vehicle.window_sticker_file_path:
        raise HTTPException(
            status_code=404, detail="No window sticker found for this vehicle"
        )

    file_path = Path(vehicle.window_sticker_file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=404, detail="Window sticker file not found on disk"
        )

    # Determine media type based on extension
    media_type_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    media_type = media_type_map.get(
        file_path.suffix.lower(), "application/octet-stream"
    )

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=f"window_sticker_{vin}{file_path.suffix}",
    )


# Additional routes for parser management


@router.get("/window-sticker/parsers", response_model=list[ParserInfo])
async def list_parsers(
    current_user: User = Depends(require_auth),
) -> list[ParserInfo]:
    """List all available window sticker parsers."""
    ocr_service = WindowStickerOCRService()
    parsers = ocr_service.list_available_parsers()
    return [ParserInfo(**p) for p in parsers]


@router.get("/window-sticker/ocr-status", response_model=OCRStatusResponse)
async def get_ocr_status(
    current_user: User = Depends(require_auth),
) -> OCRStatusResponse:
    """Get OCR engine status and availability."""
    ocr_service = WindowStickerOCRService()
    return OCRStatusResponse(**ocr_service.get_ocr_status())
