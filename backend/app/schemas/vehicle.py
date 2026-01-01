"""Pydantic schemas for Vehicle operations."""

from typing import Any, Optional
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


class VehicleBase(BaseModel):
    """Base vehicle schema with common fields."""

    nickname: str = Field(
        ..., description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: str = Field(..., description="Type of vehicle")
    year: Optional[int] = Field(None, description="Model year", ge=1900, le=2100)
    make: Optional[str] = Field(None, description="Manufacturer brand", max_length=50)
    model: Optional[str] = Field(None, description="Model name", max_length=50)
    license_plate: Optional[str] = Field(
        None, description="License plate number", max_length=20
    )
    color: Optional[str] = Field(None, description="Vehicle color", max_length=30)
    purchase_date: Optional[date] = Field(None, description="Date purchased")
    purchase_price: Optional[Decimal] = Field(None, description="Purchase price")
    sold_date: Optional[date] = Field(None, description="Date sold")
    sold_price: Optional[Decimal] = Field(None, description="Sale price")
    # VIN decoded fields
    trim: Optional[str] = Field(None, description="Trim level", max_length=50)
    body_class: Optional[str] = Field(None, description="Body class", max_length=50)
    drive_type: Optional[str] = Field(
        None, description="Drive type (FWD, RWD, AWD, etc.)", max_length=30
    )
    doors: Optional[int] = Field(None, description="Number of doors")
    gvwr_class: Optional[str] = Field(None, description="GVWR class", max_length=50)
    displacement_l: Optional[str] = Field(
        None, description="Engine displacement in liters", max_length=20
    )
    cylinders: Optional[int] = Field(None, description="Number of cylinders")
    fuel_type: Optional[str] = Field(None, description="Fuel type", max_length=50)
    transmission_type: Optional[str] = Field(
        None, description="Transmission type", max_length=50
    )
    transmission_speeds: Optional[str] = Field(
        None, description="Transmission speeds", max_length=20
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

    nickname: Optional[str] = Field(
        None, description="User-friendly display name", min_length=1, max_length=100
    )
    vehicle_type: Optional[str] = Field(None, description="Type of vehicle")

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
    main_photo: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Window sticker fields
    window_sticker_file_path: Optional[str] = None
    window_sticker_uploaded_at: Optional[datetime] = None
    msrp_base: Optional[Decimal] = None
    msrp_options: Optional[Decimal] = None
    msrp_total: Optional[Decimal] = None
    fuel_economy_city: Optional[int] = None
    fuel_economy_highway: Optional[int] = None
    fuel_economy_combined: Optional[int] = None
    standard_equipment: Optional[dict[str, Any]] = None
    optional_equipment: Optional[dict[str, Any]] = None
    assembly_location: Optional[str] = None
    # Enhanced window sticker fields
    destination_charge: Optional[Decimal] = None
    window_sticker_options_detail: Optional[dict[str, Any]] = None
    window_sticker_packages: Optional[dict[str, Any]] = None
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None
    sticker_engine_description: Optional[str] = None
    sticker_transmission_description: Optional[str] = None
    sticker_drivetrain: Optional[str] = None
    wheel_specs: Optional[str] = None
    tire_specs: Optional[str] = None
    warranty_powertrain: Optional[str] = None
    warranty_basic: Optional[str] = None
    environmental_rating_ghg: Optional[str] = None
    environmental_rating_smog: Optional[str] = None
    window_sticker_parser_used: Optional[str] = None
    window_sticker_confidence_score: Optional[Decimal] = None
    window_sticker_extracted_vin: Optional[str] = None
    # Archive fields
    archived_at: Optional[datetime] = None
    archive_reason: Optional[str] = None
    archive_sale_price: Optional[Decimal] = None
    archive_sale_date: Optional[date] = None
    archive_notes: Optional[str] = None
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

    gvwr: Optional[int] = Field(None, description="Gross Vehicle Weight Rating (lbs)")
    hitch_type: Optional[str] = Field(None, description="Hitch type")
    axle_count: Optional[int] = Field(None, description="Number of axles", ge=1, le=10)
    brake_type: Optional[str] = Field(None, description="Brake type")
    length_ft: Optional[Decimal] = Field(None, description="Length in feet")
    width_ft: Optional[Decimal] = Field(None, description="Width in feet")
    height_ft: Optional[Decimal] = Field(None, description="Height in feet")
    tow_vehicle_vin: Optional[str] = Field(
        None, description="VIN of tow vehicle", min_length=17, max_length=17
    )

    @field_validator("hitch_type")
    @classmethod
    def validate_hitch_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate hitch type."""
        if v is None:
            return v
        valid_types = ["Ball", "Pintle", "Fifth Wheel", "Gooseneck"]
        if v not in valid_types:
            raise ValueError(f"Hitch type must be one of: {', '.join(valid_types)}")
        return v

    @field_validator("brake_type")
    @classmethod
    def validate_brake_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate brake type."""
        if v is None:
            return v
        valid_types = ["None", "Electric", "Hydraulic"]
        if v not in valid_types:
            raise ValueError(f"Brake type must be one of: {', '.join(valid_types)}")
        return v


class TrailerDetailsCreate(TrailerDetailsBase):
    """Schema for creating trailer details."""

    vin: str = Field(
        ..., description="VIN of the trailer", min_length=17, max_length=17
    )


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
    sale_price: Optional[Decimal] = Field(
        None, description="Sale price (if applicable)"
    )
    sale_date: Optional[date] = Field(None, description="Sale/disposal date")
    notes: Optional[str] = Field(
        None, description="Additional notes about the archive", max_length=1000
    )
    visible: bool = Field(
        True, description="Whether to show vehicle in main list with watermark"
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """Validate archive reason."""
        valid_reasons = ["Sold", "Totaled", "Gifted", "Trade-in", "Other"]
        if v not in valid_reasons:
            raise ValueError(
                f"Archive reason must be one of: {', '.join(valid_reasons)}"
            )
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
