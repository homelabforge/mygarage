"""Pydantic schemas for Fuel Record operations."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class FuelRecordBase(BaseModel):
    """Base fuel record schema with common fields."""

    date: date_type = Field(..., description="Fill-up date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0, le=9999999)
    gallons: Decimal | None = Field(None, description="Fuel amount in gallons", ge=0, le=999.999)
    propane_gallons: Decimal | None = Field(
        None,
        description="Propane amount in gallons",
        ge=0,
        le=999.999,
        decimal_places=3,
    )
    tank_size_lb: Decimal | None = Field(
        None, description="Propane tank size in pounds", ge=0, le=999.99
    )
    tank_quantity: int | None = Field(None, description="Number of propane tanks", ge=1)
    kwh: Decimal | None = Field(
        None,
        description="Energy amount in kilowatt-hours",
        ge=0,
        le=99999.999,
        decimal_places=3,
    )
    cost: Decimal | None = Field(None, description="Total cost", ge=0, le=99999.99)
    price_per_unit: Decimal | None = Field(None, description="Price per gallon", ge=0, le=999.999)
    fuel_type: str | None = Field(
        None, description="Fuel type (Gasoline, Diesel, etc.)", max_length=50
    )
    is_full_tank: bool = Field(True, description="Full tank fill-up")
    missed_fillup: bool = Field(False, description="Skipped recording a fill-up")
    is_hauling: bool = Field(False, description="Vehicle was towing/hauling during this fuel cycle")
    notes: str | None = Field(None, description="Additional notes")


class FuelRecordCreate(FuelRecordBase):
    """Schema for creating a new fuel record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)

    @field_validator("tank_quantity")
    @classmethod
    def validate_tank_data_complete(cls, v: int | None, info: ValidationInfo) -> int | None:
        """Ensure both tank_size_lb and tank_quantity are provided together."""
        tank_size = info.data.get("tank_size_lb")
        has_size = tank_size is not None
        has_qty = v is not None

        if has_size != has_qty:
            raise ValueError("Both tank_size_lb and tank_quantity must be provided together")

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "mileage": 45000,
                    "gallons": 10.5,
                    "cost": 35.70,
                    "price_per_unit": 3.40,
                    "is_full_tank": True,
                    "missed_fillup": False,
                }
            ]
        }
    }


class FuelRecordUpdate(BaseModel):
    """Schema for updating an existing fuel record."""

    date: date_type | None = Field(None, description="Fill-up date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0, le=9999999)
    gallons: Decimal | None = Field(None, description="Fuel amount in gallons", ge=0, le=999.999)
    propane_gallons: Decimal | None = Field(
        None,
        description="Propane amount in gallons",
        ge=0,
        le=999.999,
        decimal_places=3,
    )
    tank_size_lb: Decimal | None = Field(
        None, description="Propane tank size in pounds", ge=0, le=999.99
    )
    tank_quantity: int | None = Field(None, description="Number of propane tanks", ge=1)
    kwh: Decimal | None = Field(
        None,
        description="Energy amount in kilowatt-hours",
        ge=0,
        le=99999.999,
        decimal_places=3,
    )
    cost: Decimal | None = Field(None, description="Total cost", ge=0, le=99999.99)
    price_per_unit: Decimal | None = Field(None, description="Price per gallon", ge=0, le=999.999)
    fuel_type: str | None = Field(
        None, description="Fuel type (Gasoline, Diesel, etc.)", max_length=50
    )
    is_full_tank: bool | None = Field(None, description="Full tank fill-up")
    missed_fillup: bool | None = Field(None, description="Skipped recording a fill-up")
    is_hauling: bool | None = Field(
        None, description="Vehicle was towing/hauling during this fuel cycle"
    )
    notes: str | None = Field(None, description="Additional notes")

    @field_validator("tank_quantity")
    @classmethod
    def validate_tank_data_complete(cls, v: int | None, info: ValidationInfo) -> int | None:
        """Ensure both tank_size_lb and tank_quantity are provided together."""
        tank_size = info.data.get("tank_size_lb")
        has_size = tank_size is not None
        has_qty = v is not None

        if has_size != has_qty:
            raise ValueError("Both tank_size_lb and tank_quantity must be provided together")

        return v

    model_config = {"json_schema_extra": {"examples": [{"cost": 38.50, "notes": "Premium fuel"}]}}


class FuelRecordResponse(FuelRecordBase):
    """Schema for fuel record response."""

    id: int
    vin: str
    created_at: datetime
    mpg: Decimal | None = Field(None, description="Calculated miles per gallon")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "mileage": 45000,
                    "gallons": "10.500",
                    "cost": "35.70",
                    "price_per_unit": "3.400",
                    "is_full_tank": True,
                    "missed_fillup": False,
                    "is_hauling": False,
                    "notes": None,
                    "created_at": "2025-01-15T14:30:00",
                    "mpg": "32.5",
                }
            ]
        },
    }


class FuelRecordListResponse(BaseModel):
    """Schema for fuel record list response."""

    records: list[FuelRecordResponse]
    total: int
    average_mpg: Decimal | None = Field(None, description="Average MPG across all records")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "records": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2025-01-15",
                            "mileage": 45000,
                            "gallons": "10.500",
                            "cost": "35.70",
                            "is_full_tank": True,
                            "mpg": "32.5",
                            "created_at": "2025-01-15T14:30:00",
                        }
                    ],
                    "total": 1,
                    "average_mpg": "32.5",
                }
            ]
        }
    }
