"""Window sticker storage, scanning and the vehicle columns it fills.

Every method takes the gated `Vehicle`, so the routes' owner and read checks
stay the only way in. The routes keep the settings switches and shape the
responses.
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.vehicle import Vehicle
from app.schemas._money import MONEY_MAX
from app.schemas.window_sticker import (
    FUEL_ECONOMY_MAX,
    WindowStickerDataUpdate,
    WindowStickerTestResponse,
)
from app.services.window_sticker_ocr import WindowStickerOCRService
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.vehicle_columns import fit_to_column
from app.utils.vehicle_key import is_vehicle_key

logger = logging.getLogger(__name__)

# Window sticker storage configuration
STICKER_STORAGE_PATH = settings.documents_dir

# Allowed file extensions
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
#: A sticker is stored with the documents, so it gets their limit
#: (`MYGARAGE_MAX_DOCUMENT_SIZE_MB`), the one Settings > Files shows.
MAX_FILE_SIZE = settings.max_document_size_bytes

ALLOWED_STICKER_MIMES = {"application/pdf", "image/jpeg", "image/png"}

#: The code on an upload 500 raised before the commit or after the rollback. The
#: drawer reads it as "nothing was saved"; any other 500 may still have saved it.
STICKER_NOT_SAVED = "sticker_not_saved"

# The parsed numbers and the largest each column holds. OCR can misread a
# price, and nothing validates what a parser returns before it is written.
_PARSED_NUMBER_MAX = {
    "msrp_base": MONEY_MAX,
    "msrp_options": MONEY_MAX,
    "msrp_total": MONEY_MAX,
    "destination_charge": MONEY_MAX,
    "fuel_economy_city_l_per_100km": FUEL_ECONOMY_MAX,
    "fuel_economy_highway_l_per_100km": FUEL_ECONOMY_MAX,
    "fuel_economy_combined_l_per_100km": FUEL_ECONOMY_MAX,
}

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
    a 500 with the upload already on disk, and SQLite kept it whole. The
    work lives in `app.utils.vehicle_columns`, shared with the registration
    certificate import (#211).
    """
    return fit_to_column(column, value, source="Window sticker", log=logger)


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
    except (OSError, ValueError) as e:  # ValueError: a NUL in a stored path
        logger.warning(
            "Failed to delete window sticker file %s: %s",
            sanitize_for_log(path),
            sanitize_for_log(e),
        )


def validate_sticker_file(file: UploadFile) -> str:
    """Validate uploaded window sticker file (extension, MIME, and magic bytes).

    Returns:
        The file's extension, lowercased.
    """
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
    return ext


def _refuse_oversize(file: UploadFile) -> None:
    """400 when the file is over the documents limit. Leaves it rewound."""
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Seek back to beginning

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )


@dataclass(frozen=True)
class StickerUpload:
    """What an upload did: the saved vehicle plus the two flags the response carries."""

    vehicle: Vehicle
    ocr_skipped: bool
    scan_read_nothing: bool


class WindowStickerService:
    """Window sticker file handling and the vehicle columns it fills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upload(
        self, vehicle: Vehicle, file: UploadFile, *, replace: bool, ocr_enabled: bool
    ) -> StickerUpload:
        """Store the file, scan it unless OCR is off, fill the empty fields and commit.

        The commit happens here, before the route builds its response. With
        `replace` and a sticker on file, the old sticker's fields clear first.
        """
        vin = vehicle.vin
        ocr_skipped = not ocr_enabled

        file_ext = validate_sticker_file(file)
        _refuse_oversize(file)

        # Generate unique filename
        unique_filename = f"window_sticker_{uuid.uuid4()}{file_ext}"

        # Validate the key before using it in a path (prevent path traversal). A
        # window sticker belongs to a VIN; a vehicle without one has none (#226).
        if not is_vehicle_key(vin):
            raise HTTPException(status_code=400, detail="Invalid vehicle key")
        if vehicle.identifier_type != "vin":
            raise HTTPException(status_code=409, detail="Window stickers need a vehicle with a VIN")

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
            raise HTTPException(
                status_code=500,
                detail={"code": STICKER_NOT_SAVED, "message": "Failed to save file"},
            )

        try:
            extracted_data: dict[str, Any] = {}
            ocr_failed = False
            if ocr_skipped:
                logger.info("Window sticker OCR is switched off; stored the file unscanned")
            else:
                try:
                    extracted_data = await WindowStickerOCRService().extract_data_from_file(
                        str(file_path), vin=vin, make=vehicle.make
                    )
                    logger.info("Extracted %d fields from window sticker", len(extracted_data))
                except Exception as e:
                    logger.error("OCR extraction failed: %s", sanitize_for_log(e))
                    ocr_failed = True
            _drop_numbers_that_cannot_be_stored(extracted_data)
            # No scan ran when OCR is off, so it can't have read nothing.
            scan_read_nothing = not ocr_skipped and (
                ocr_failed or not any(f in extracted_data for f in STICKER_DATA_FIELDS)
            )

            # A scan fills empty fields only, so values typed by hand or
            # corrected in the review survive a re-upload. `replace` clears
            # first, but never on a scan that read nothing (it would just erase),
            # nor on a file OCR never scanned (nothing would take their place).
            # `old_path`: replace means replacing a sticker; with none on file it
            # would only erase values typed through PATCH.
            if replace and old_path and not ocr_skipped and not scan_read_nothing:
                for field in STICKER_DATA_FIELDS:
                    setattr(vehicle, field, None)
            for field in STICKER_DATA_FIELDS:
                if field in extracted_data and _is_empty_sticker_value(getattr(vehicle, field)):
                    setattr(vehicle, field, _fit_to_column(field, extracted_data[field]))
            # Unscanned (OCR off) included: these describe the file on record.
            for field in STICKER_SCAN_FIELDS:  # None passes _fit_to_column untouched
                setattr(vehicle, field, _fit_to_column(field, extracted_data.get(field)))
            # From the colour the row ends up with: keep mode may have kept a typed
            # one over the scan's. Only when the scan read a colour, though, so a
            # scan that read nothing still changes nothing.
            if not vehicle.color and extracted_data.get("exterior_color"):
                vehicle.color = _fit_to_column("color", vehicle.exterior_color)
            vehicle.window_sticker_file_path = str(file_path)
            vehicle.window_sticker_uploaded_at = utc_now()
            await self.db.commit()
        except Exception as e:
            # Nothing committed points at the new file, so it goes first; the old
            # one was never touched.
            _unlink_quietly(file_path)
            await self.db.rollback()
            logger.exception("Window sticker upload failed for %s", sanitize_for_log(vin))
            # Starlette answers anything else with a 500 and then re-raises it,
            # which the test client turns into an exception. Same 500 as the write.
            raise HTTPException(
                status_code=500,
                detail={"code": STICKER_NOT_SAVED, "message": "Failed to save window sticker"},
            ) from e
        # Only now is the old file unreferenced.
        if old_path and old_path != str(file_path):
            _unlink_quietly(Path(old_path))
        await self.db.refresh(vehicle)
        return StickerUpload(
            vehicle=vehicle, ocr_skipped=ocr_skipped, scan_read_nothing=scan_read_nothing
        )

    async def test_extraction(
        self, file: UploadFile, *, vehicle: Vehicle, parser: str | None
    ) -> WindowStickerTestResponse:
        """Scan a temp copy of the file and say what came out; nothing is saved."""
        file_ext = validate_sticker_file(file)
        _refuse_oversize(file)

        # Save to temp file
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
                vin=vehicle.vin,
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

    async def update_data(self, vehicle: Vehicle, data: WindowStickerDataUpdate) -> Vehicle:
        """Write the fields sent (omitted keeps, null clears) and commit."""
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(vehicle, field, value)

        await self.db.commit()
        await self.db.refresh(vehicle)
        return vehicle

    async def delete(self, vehicle: Vehicle) -> None:
        """Clear every sticker column, commit, then remove the file."""
        if not vehicle.window_sticker_file_path:
            raise HTTPException(status_code=404, detail="No window sticker found for this vehicle")

        # Read before the commit: a rollback expires the row.
        vin = vehicle.vin
        old_path = Path(vehicle.window_sticker_file_path)
        for field in (
            "window_sticker_file_path",
            "window_sticker_uploaded_at",
            *STICKER_DATA_FIELDS,
            *STICKER_SCAN_FIELDS,
        ):
            setattr(vehicle, field, None)
        try:
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            logger.exception("Window sticker delete failed for %s", sanitize_for_log(vin))
            raise HTTPException(status_code=500, detail="Failed to delete window sticker") from e
        # Only now is the file unreferenced (the upload swaps files the same way).
        _unlink_quietly(old_path)

    def stored_file(self, vehicle: Vehicle) -> Path:
        """The sticker file on record; a 404 when there's none or it's gone from disk."""
        if not vehicle.window_sticker_file_path:
            raise HTTPException(status_code=404, detail="No window sticker found for this vehicle")

        file_path = Path(vehicle.window_sticker_file_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Window sticker file not found on disk")
        return file_path
