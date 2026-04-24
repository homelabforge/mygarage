"""Pydantic schemas for Fuel Record operations.

Canonical units (since v2.26.2): SI metric.
- odometer_km, liters, propane_liters, tank_size_kg
- price_per_unit denominator depends on price_basis (per_volume = per liter,
  per_weight = per kilogram, per_kwh = per kWh, per_tank = per tank)
- l_per_100km is computed on the fly from liters + odometer_km deltas
"""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

PRICE_BASIS_VALUES = ("per_volume", "per_weight", "per_tank", "per_kwh")


class FuelRecordBase(BaseModel):
    """Base fuel record schema with common fields (metric canonical)."""

    date: date_type = Field(..., description="Fill-up date")
    odometer_km: Decimal | None = Field(
        None, description="Odometer reading in kilometers", ge=0, le=99999999.99
    )
    liters: Decimal | None = Field(
        None, description="Fuel amount in liters", ge=0, le=9999.999, decimal_places=3
    )
    propane_liters: Decimal | None = Field(
        None,
        description="Propane amount in liters",
        ge=0,
        le=9999.999,
        decimal_places=3,
    )
    tank_size_kg: Decimal | None = Field(
        None, description="Propane tank size in kilograms", ge=0, le=9999.99
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
    price_per_unit: Decimal | None = Field(
        None,
        description=(
            "Price per unit; denominator depends on price_basis "
            "(per_volume=per liter, per_weight=per kg, per_kwh=per kWh, per_tank=per tank)"
        ),
        ge=0,
        le=999.999,
    )
    price_basis: str | None = Field(
        None,
        description="Price denominator: per_volume / per_weight / per_tank / per_kwh",
        max_length=12,
    )
    fuel_type: str | None = Field(
        None, description="Fuel type (Gasoline, Diesel, etc.)", max_length=50
    )
    is_full_tank: bool = Field(True, description="Full tank fill-up")
    missed_fillup: bool = Field(False, description="Skipped recording a fill-up")
    is_hauling: bool = Field(False, description="Vehicle was towing/hauling during this fuel cycle")
    notes: str | None = Field(None, description="Additional notes")

    @field_validator("price_basis")
    @classmethod
    def _check_price_basis(cls, v: str | None) -> str | None:
        if v is not None and v not in PRICE_BASIS_VALUES:
            raise ValueError(f"price_basis must be one of {PRICE_BASIS_VALUES}, got {v!r}")
        return v


class FuelRecordCreate(FuelRecordBase):
    """Schema for creating a new fuel record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)
    def_fill_level: Decimal | None = Field(
        None,
        description="DEF tank level (0.00=empty, 1.00=full) — auto-creates a DEF observation",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )

    @field_validator("tank_quantity")
    @classmethod
    def validate_tank_data_complete(cls, v: int | None, info: ValidationInfo) -> int | None:
        """Ensure both tank_size_kg and tank_quantity are provided together."""
        tank_size = info.data.get("tank_size_kg")
        has_size = tank_size is not None
        has_qty = v is not None

        if has_size != has_qty:
            raise ValueError("Both tank_size_kg and tank_quantity must be provided together")

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "odometer_km": 72420.33,
                    "liters": 39.747,
                    "cost": 35.70,
                    "price_per_unit": 0.898,
                    "price_basis": "per_volume",
                    "is_full_tank": True,
                    "missed_fillup": False,
                }
            ]
        }
    }


class FuelRecordUpdate(BaseModel):
    """Schema for updating an existing fuel record (metric canonical)."""

    date: date_type | None = Field(None, description="Fill-up date")
    odometer_km: Decimal | None = Field(
        None, description="Odometer reading in kilometers", ge=0, le=99999999.99
    )
    liters: Decimal | None = Field(
        None, description="Fuel amount in liters", ge=0, le=9999.999, decimal_places=3
    )
    propane_liters: Decimal | None = Field(
        None,
        description="Propane amount in liters",
        ge=0,
        le=9999.999,
        decimal_places=3,
    )
    tank_size_kg: Decimal | None = Field(
        None, description="Propane tank size in kilograms", ge=0, le=9999.99
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
    price_per_unit: Decimal | None = Field(
        None, description="Price per unit (see price_basis for denominator)", ge=0, le=999.999
    )
    price_basis: str | None = Field(None, max_length=12)
    fuel_type: str | None = Field(
        None, description="Fuel type (Gasoline, Diesel, etc.)", max_length=50
    )
    is_full_tank: bool | None = Field(None, description="Full tank fill-up")
    missed_fillup: bool | None = Field(None, description="Skipped recording a fill-up")
    is_hauling: bool | None = Field(
        None, description="Vehicle was towing/hauling during this fuel cycle"
    )
    notes: str | None = Field(None, description="Additional notes")
    def_fill_level: Decimal | None = Field(
        None,
        description="DEF tank level (0.00=empty, 1.00=full) — auto-creates a DEF observation",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )

    @field_validator("price_basis")
    @classmethod
    def _check_price_basis(cls, v: str | None) -> str | None:
        if v is not None and v not in PRICE_BASIS_VALUES:
            raise ValueError(f"price_basis must be one of {PRICE_BASIS_VALUES}, got {v!r}")
        return v

    @field_validator("tank_quantity")
    @classmethod
    def validate_tank_data_complete(cls, v: int | None, info: ValidationInfo) -> int | None:
        """Ensure both tank_size_kg and tank_quantity are provided together."""
        tank_size = info.data.get("tank_size_kg")
        has_size = tank_size is not None
        has_qty = v is not None

        if has_size != has_qty:
            raise ValueError("Both tank_size_kg and tank_quantity must be provided together")

        return v

    model_config = {"json_schema_extra": {"examples": [{"cost": 38.50, "notes": "Premium fuel"}]}}


class FuelRecordResponse(FuelRecordBase):
    """Schema for fuel record response (metric canonical)."""

    id: int
    vin: str
    created_at: datetime
    l_per_100km: Decimal | None = Field(None, description="Calculated fuel economy (L/100 km)")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "odometer_km": 72420.33,
                    "liters": "39.747",
                    "cost": "35.70",
                    "price_per_unit": "0.898",
                    "price_basis": "per_volume",
                    "is_full_tank": True,
                    "missed_fillup": False,
                    "is_hauling": False,
                    "notes": None,
                    "created_at": "2025-01-15T14:30:00",
                    "l_per_100km": "7.24",
                }
            ]
        },
    }


class FuelRecordListResponse(BaseModel):
    """Schema for fuel record list response."""

    records: list[FuelRecordResponse]
    total: int
    average_l_per_100km: Decimal | None = Field(
        None, description="Average fuel consumption (L/100 km) across all records"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "records": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2025-01-15",
                            "odometer_km": 72420.33,
                            "liters": "39.747",
                            "cost": "35.70",
                            "is_full_tank": True,
                            "l_per_100km": "7.24",
                            "created_at": "2025-01-15T14:30:00",
                        }
                    ],
                    "total": 1,
                    "average_l_per_100km": "7.24",
                }
            ]
        }
    }
