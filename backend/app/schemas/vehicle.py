"""Pydantic schemas for Vehicle operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


class VehicleBase(BaseModel):
    """Base vehicle schema with common fields."""

    nickname: str = Field(
        ..., description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: str = Field(..., description="Type of vehicle")
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
    fuel_type: str | None = Field(None, description="Fuel type", max_length=50)
    transmission_type: str | None = Field(None, description="Transmission type", max_length=50)
    transmission_speeds: str | None = Field(None, description="Transmission speeds", max_length=20)
    # DEF tracking
    def_tank_capacity_gallons: Decimal | None = Field(
        None, description="DEF tank capacity in gallons", ge=0, le=999.99
    )

    @field_validator("vehicle_type")
    @classmethod
    def validate_vehicle_type(cls, v: str) -> str:
        """Validate vehicle type."""
        valid_types = [
            "Car",
            "Truck",
            "SUV",
            "Motorcycle",
            "RV",
            "Trailer",
            "FifthWheel",
            "TravelTrailer",
            "Electric",
            "Hybrid",
        ]
        if v not in valid_types:
            raise ValueError(f"Vehicle type must be one of: {', '.join(valid_types)}")
        return v


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
    vehicle_type: str | None = Field(None, description="Type of vehicle")

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
    fuel_economy_city: int | None = None
    fuel_economy_highway: int | None = None
    fuel_economy_combined: int | None = None
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

    gvwr: int | None = Field(None, description="Gross Vehicle Weight Rating (lbs)")
    hitch_type: str | None = Field(None, description="Hitch type")
    axle_count: int | None = Field(None, description="Number of axles", ge=1, le=10)
    brake_type: str | None = Field(None, description="Brake type")
    length_ft: Decimal | None = Field(None, description="Length in feet")
    width_ft: Decimal | None = Field(None, description="Width in feet")
    height_ft: Decimal | None = Field(None, description="Height in feet")
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
