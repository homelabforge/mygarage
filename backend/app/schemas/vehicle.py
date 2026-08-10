"""Pydantic schemas for Vehicle operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.constants.fuel import FUEL_TYPE_VALUES, normalize_fuel_type


def _normalize_fuel_type_input(v: Any) -> Any:
    """Normalize free-text / NHTSA fuel-type input to the canonical vocabulary.

    Used as a `mode="before"` validator on `VehicleCreate` / `VehicleUpdate`
    only — never on `VehicleBase`/`VehicleResponse`. Response schemas
    validate from DB attributes, and a legacy unrecognized value already
    persisted must not make a vehicle read 500.

    - `None` / empty / whitespace-only -> `None`
    - recognized (case/whitespace-insensitive) -> canonical enum value (str)
    - unrecognized -> `ValueError` (Pydantic turns this into a 422), listing
      the canonical values. Bulk import paths (see `import_data.py`) fall
      back to `other` on unrecognized input; interactive writes fail loudly
      instead.
    """
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    if not v.strip():
        return None
    normalized = normalize_fuel_type(v)
    if normalized is None:
        raise ValueError(f"fuel_type must be one of {FUEL_TYPE_VALUES}, got {v!r}")
    return normalized.value


# Shared vehicle type literal for OpenAPI schema generation
VehicleType = Literal[
    "Car",
    "Truck",
    "SUV",
    "Motorcycle",
    "ATV",
    "RV",
    "Trailer",
    "FifthWheel",
    "TravelTrailer",
    "Electric",
    "Hybrid",
    "Boat",
    "UTV",
    "Snowmobile",
    "Bicycle",
    "EBike",
]


class VehicleBase(BaseModel):
    """Base vehicle schema with common fields."""

    nickname: str = Field(
        ..., description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: VehicleType = Field(..., description="Type of vehicle")
    usage_unit: Literal["distance", "hours"] = Field(
        "distance",
        description="Usage tracking dimension: 'distance' (odometer) or 'hours' (hour meter)",
    )
    current_hours: Decimal | None = Field(
        None, description="Current engine-hour reading (used when usage_unit == 'hours')", ge=0
    )
    secondary_usage_enabled: bool = Field(
        False,
        description="Also track the non-primary usage dimension (distance+hours dual tracking)",
    )
    year: int | None = Field(None, description="Model year", ge=1900, le=2100)
    make: str | None = Field(None, description="Manufacturer brand", max_length=50)
    model: str | None = Field(None, description="Model name", max_length=50)
    license_plate: str | None = Field(None, description="License plate number", max_length=20)
    color: str | None = Field(None, description="Vehicle color", max_length=30)
    purchase_date: date | None = Field(None, description="Date purchased")
    purchase_price: Decimal | None = Field(None, description="Purchase price")
    sold_date: date | None = Field(None, description="Date sold")
    sold_price: Decimal | None = Field(None, description="Sale price")
    # VIN decoded fields
    trim: str | None = Field(None, description="Trim level", max_length=50)
    body_class: str | None = Field(None, description="Body class", max_length=100)
    drive_type: str | None = Field(
        None, description="Drive type (FWD, RWD, AWD, etc.)", max_length=30
    )
    doors: int | None = Field(None, description="Number of doors")
    gvwr_class: str | None = Field(None, description="GVWR class", max_length=50)
    displacement_l: str | None = Field(
        None, description="Engine displacement in liters", max_length=20
    )
    cylinders: int | None = Field(None, description="Number of cylinders")
    fuel_type: str | None = Field(None, description="Fuel type (primary capability)", max_length=50)
    fuel_type_secondary: str | None = Field(
        None,
        description=(
            "Secondary fuel capability for PHEV / flex / dual-fuel vehicles. "
            "Stored as a FuelTypeEnum value."
        ),
        max_length=20,
    )
    transmission_type: str | None = Field(None, description="Transmission type", max_length=50)
    transmission_speeds: str | None = Field(None, description="Transmission speeds", max_length=20)
    # DEF tracking
    def_tank_capacity_liters: Decimal | None = Field(
        None, description="DEF tank capacity in liters", ge=0, le=9999.99
    )


class VehicleCreate(VehicleBase):
    """Schema for creating a new vehicle."""

    vin: str = Field(
        ...,
        description="17-character Vehicle Identification Number",
        min_length=17,
        max_length=17,
    )

    @field_validator("vin")
    @classmethod
    def validate_vin_format(cls, v: str) -> str:
        """Validate VIN format."""
        from app.utils.vin import validate_vin

        v = v.strip().upper()
        is_valid, error = validate_vin(v)
        if not is_valid:
            raise ValueError(error or "Invalid VIN format")
        return v

    @field_validator("fuel_type", "fuel_type_secondary", mode="before")
    @classmethod
    def normalize_fuel_type_fields(cls, v: Any) -> Any:
        """Normalize free-text fuel-type input to the canonical vocabulary."""
        return _normalize_fuel_type_input(v)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "nickname": "Red Mirage",
                    "vehicle_type": "Car",
                    "year": 2019,
                    "make": "MITSUBISHI",
                    "model": "Mirage",
                    "license_plate": "ABC-1234",
                    "color": "Red",
                    "purchase_date": "2019-03-15",
                    "purchase_price": 15000.00,
                }
            ]
        }
    }


class VehicleUpdate(VehicleBase):
    """Schema for updating an existing vehicle."""

    nickname: str | None = Field(
        None, description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: VehicleType | None = Field(None, description="Type of vehicle")
    # Overridden as optional: VehicleBase gives these non-null defaults, which
    # the generated OpenAPI otherwise marks REQUIRED — forcing every partial
    # update (equipment/pricing sidecars) to resend them. exclude_unset makes an
    # omitted field a no-op, so callers editing unrelated fields can drop them.
    usage_unit: Literal["distance", "hours"] | None = Field(
        None, description="Usage tracking dimension (omit to leave unchanged)"
    )
    secondary_usage_enabled: bool | None = Field(
        None, description="Dual distance+hours tracking (omit to leave unchanged)"
    )
    # Equipment is editable from the vehicle-detail sidecar. Declared here (not
    # only on VehicleResponse) so partial PUTs actually persist it — Pydantic's
    # default extra='ignore' silently drops unknown keys otherwise.
    standard_equipment: dict[str, Any] | None = Field(
        None, description="Standard equipment (category -> list of items)"
    )
    optional_equipment: dict[str, Any] | None = Field(
        None, description="Optional equipment (category -> list of items)"
    )
    # MSRP is editable from the pricing sidecar. Like equipment, these live only
    # on VehicleResponse otherwise, so a PUT would silently drop them.
    msrp_base: Decimal | None = Field(None, description="MSRP base price")
    msrp_options: Decimal | None = Field(None, description="MSRP options total")
    msrp_total: Decimal | None = Field(None, description="MSRP total")
    destination_charge: Decimal | None = Field(None, description="Destination charge")
    # Window-sticker / VIN-decoded descriptive fields, editable from the
    # vehicle-detail card sidecars (Basic Information / Vehicle Details /
    # Powertrain / Warranty). Same rationale as equipment/MSRP: they live only
    # on VehicleResponse otherwise, so a partial PUT would silently drop them.
    # max_length mirrors the model columns (app/models/vehicle.py).
    exterior_color: str | None = Field(None, description="Exterior color", max_length=100)
    interior_color: str | None = Field(None, description="Interior color", max_length=100)
    wheel_specs: str | None = Field(None, description="Wheel specifications", max_length=100)
    tire_specs: str | None = Field(None, description="Tire specifications", max_length=100)
    warranty_basic: str | None = Field(None, description="Basic warranty", max_length=100)
    warranty_powertrain: str | None = Field(None, description="Powertrain warranty", max_length=100)
    sticker_engine_description: str | None = Field(
        None, description="Engine description (window sticker)", max_length=150
    )
    sticker_transmission_description: str | None = Field(
        None, description="Transmission description (window sticker)", max_length=150
    )
    sticker_drivetrain: str | None = Field(
        None, description="Drivetrain (window sticker)", max_length=50
    )
    assembly_location: str | None = Field(None, description="Assembly location", max_length=100)

    @field_validator("fuel_type", "fuel_type_secondary", mode="before")
    @classmethod
    def normalize_fuel_type_fields(cls, v: Any) -> Any:
        """Normalize free-text fuel-type input to the canonical vocabulary."""
        return _normalize_fuel_type_input(v)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "nickname": "My Red Mirage",
                    "license_plate": "XYZ-5678",
                    "color": "Cherry Red",
                }
            ]
        }
    }


class VehicleResponse(VehicleBase):
    """Schema for vehicle response."""

    vin: str
    main_photo: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    # Window sticker fields
    window_sticker_file_path: str | None = None
    window_sticker_uploaded_at: datetime | None = None
    msrp_base: Decimal | None = None
    msrp_options: Decimal | None = None
    msrp_total: Decimal | None = None
    fuel_economy_city_l_per_100km: Decimal | None = None
    fuel_economy_highway_l_per_100km: Decimal | None = None
    fuel_economy_combined_l_per_100km: Decimal | None = None
    standard_equipment: dict[str, Any] | None = None
    optional_equipment: dict[str, Any] | None = None
    assembly_location: str | None = None
    # Enhanced window sticker fields
    destination_charge: Decimal | None = None
    window_sticker_options_detail: dict[str, Any] | None = None
    window_sticker_packages: dict[str, Any] | None = None
    exterior_color: str | None = None
    interior_color: str | None = None
    sticker_engine_description: str | None = None
    sticker_transmission_description: str | None = None
    sticker_drivetrain: str | None = None
    wheel_specs: str | None = None
    tire_specs: str | None = None
    warranty_powertrain: str | None = None
    warranty_basic: str | None = None
    environmental_rating_ghg: str | None = None
    environmental_rating_smog: str | None = None
    window_sticker_parser_used: str | None = None
    window_sticker_confidence_score: Decimal | None = None
    window_sticker_extracted_vin: str | None = None
    # Archive fields
    archived_at: datetime | None = None
    archive_reason: str | None = None
    archive_sale_price: Decimal | None = None
    archive_sale_date: date | None = None
    archive_notes: str | None = None
    archived_visible: bool = True
    # GPS location tracking opt-out (default on), migration 075, #118
    location_tracking_enabled: bool = True

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "nickname": "Red Mirage",
                    "vehicle_type": "Car",
                    "year": 2019,
                    "make": "MITSUBISHI",
                    "model": "Mirage",
                    "license_plate": "ABC-1234",
                    "color": "Red",
                    "purchase_date": "2019-03-15",
                    "purchase_price": 15000.00,
                    "main_photo": "/data/photos/ML32A5HJ9KH009478/main.jpg",
                    "created_at": "2025-11-07T22:00:00",
                    "updated_at": None,
                }
            ]
        },
    }


class VehicleListResponse(BaseModel):
    """Schema for vehicle list response."""

    vehicles: list[VehicleResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vehicles": [
                        {
                            "vin": "ML32A5HJ9KH009478",
                            "nickname": "Red Mirage",
                            "vehicle_type": "Car",
                            "year": 2019,
                            "make": "MITSUBISHI",
                            "model": "Mirage",
                            "main_photo": None,
                            "created_at": "2025-11-07T22:00:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }


class TrailerDetailsBase(BaseModel):
    """Base schema for trailer details."""

    gvwr_kg: Decimal | None = Field(None, description="Gross Vehicle Weight Rating (kg)")
    hitch_type: str | None = Field(None, description="Hitch type")
    axle_count: int | None = Field(None, description="Number of axles", ge=1, le=10)
    brake_type: str | None = Field(None, description="Brake type")
    length_m: Decimal | None = Field(None, description="Length in meters")
    width_m: Decimal | None = Field(None, description="Width in meters")
    height_m: Decimal | None = Field(None, description="Height in meters")
    tow_vehicle_vin: str | None = Field(
        None, description="VIN of tow vehicle", min_length=17, max_length=17
    )

    @field_validator("hitch_type")
    @classmethod
    def validate_hitch_type(cls, v: str | None) -> str | None:
        """Validate hitch type."""
        if v is None:
            return v
        valid_types = ["Ball", "Pintle", "Fifth Wheel", "Gooseneck"]
        if v not in valid_types:
            raise ValueError(f"Hitch type must be one of: {', '.join(valid_types)}")
        return v

    @field_validator("brake_type")
    @classmethod
    def validate_brake_type(cls, v: str | None) -> str | None:
        """Validate brake type."""
        if v is None:
            return v
        valid_types = ["None", "Electric", "Hydraulic"]
        if v not in valid_types:
            raise ValueError(f"Brake type must be one of: {', '.join(valid_types)}")
        return v


class TrailerDetailsCreate(TrailerDetailsBase):
    """Schema for creating trailer details."""

    vin: str = Field(..., description="VIN of the trailer", min_length=17, max_length=17)


class TrailerDetailsUpdate(TrailerDetailsBase):
    """Schema for updating trailer details."""

    pass


class TrailerDetailsResponse(TrailerDetailsBase):
    """Schema for trailer details response."""

    vin: str

    model_config = {"from_attributes": True}


class VehicleArchiveRequest(BaseModel):
    """Schema for archiving a vehicle."""

    reason: str = Field(
        ...,
        description="Reason for archiving (Sold, Totaled, Gifted, Trade-in, Other)",
        max_length=50,
    )
    sale_price: Decimal | None = Field(None, description="Sale price (if applicable)")
    sale_date: date | None = Field(None, description="Sale/disposal date")
    notes: str | None = Field(
        None, description="Additional notes about the archive", max_length=1000
    )
    visible: bool = Field(True, description="Whether to show vehicle in main list with watermark")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate archive reason."""
        valid_reasons = ["Sold", "Totaled", "Gifted", "Trade-in", "Other"]
        if v not in valid_reasons:
            raise ValueError(f"Archive reason must be one of: {', '.join(valid_reasons)}")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "reason": "Sold",
                    "sale_price": 25000.00,
                    "sale_date": "2025-12-01",
                    "notes": "Sold to private buyer via Craigslist",
                    "visible": True,
                }
            ]
        }
    }


class VehicleDetailStats(BaseModel):
    """Read-aggregation for the Vehicle Detail hero + key-facts strip (P5).

    Metric-canonical: latest_odometer_km is raw km (frontend converts at the
    boundary). spent_this_year is currency (Decimal -> JSON string).
    """

    overdue_count: int
    upcoming_count: int
    usage_unit: str  # 'distance' | 'hours' — drives the odometer/hours relabel
    # Kept for API compat only — NO LONGER the display source (R2-H1). The
    # canonical reading is `latest_hours` below, via `latest_engine_hours_and_date`.
    current_hours: Decimal | None  # required-but-nullable — legacy column value
    # Canonical latest engine-hours reading (the §1 helper) + hours-economy
    # figures — required-but-nullable (M2) — NO `= None` default. Null for a
    # pure-distance vehicle.
    latest_hours: Decimal | None
    average_l_per_hr: Decimal | None
    average_cost_per_hr: Decimal | None
    secondary_usage_enabled: bool
    latest_odometer_km: Decimal | None  # required-but-nullable (M2) — NO `= None` default
    latest_odometer_date: date | None  # required-but-nullable (M2) — NO `= None` default
    last_service_date: date | None  # required-but-nullable (M2) — NO `= None` default
    last_fillup_date: date | None  # required-but-nullable (M2) — NO `= None` default
    spent_this_year: Decimal
    year: int
