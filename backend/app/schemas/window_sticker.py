"""Window sticker request and response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._money import OptionalMoney

# Numeric(7,4) on the vehicle row.
FUEL_ECONOMY_MAX = Decimal("999.9999")


class WindowStickerDataUpdate(BaseModel):
    """The review's edits. Omitted keeps, null clears; widths match the columns."""

    msrp_base: OptionalMoney = None
    msrp_options: OptionalMoney = None
    msrp_total: OptionalMoney = None
    destination_charge: OptionalMoney = None
    fuel_economy_city_l_per_100km: Decimal | None = Field(default=None, ge=0, le=FUEL_ECONOMY_MAX)
    fuel_economy_highway_l_per_100km: Decimal | None = Field(
        default=None, ge=0, le=FUEL_ECONOMY_MAX
    )
    fuel_economy_combined_l_per_100km: Decimal | None = Field(
        default=None, ge=0, le=FUEL_ECONOMY_MAX
    )
    standard_equipment: dict[str, Any] | None = None
    optional_equipment: dict[str, Any] | None = None
    assembly_location: str | None = Field(default=None, max_length=100)
    exterior_color: str | None = Field(default=None, max_length=100)
    interior_color: str | None = Field(default=None, max_length=100)
    sticker_engine_description: str | None = Field(default=None, max_length=150)
    sticker_transmission_description: str | None = Field(default=None, max_length=150)
    sticker_drivetrain: str | None = Field(default=None, max_length=50)
    wheel_specs: str | None = Field(default=None, max_length=100)
    tire_specs: str | None = Field(default=None, max_length=100)
    warranty_powertrain: str | None = Field(default=None, max_length=100)
    warranty_basic: str | None = Field(default=None, max_length=100)
    environmental_rating_ghg: str | None = Field(default=None, max_length=10)
    environmental_rating_smog: str | None = Field(default=None, max_length=10)


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
    # Only the upload sets it: OCR is switched off, so the file was stored unscanned.
    ocr_skipped: bool = False

    model_config = ConfigDict(from_attributes=True)


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
