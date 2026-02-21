"""Pydantic schemas for DEF (Diesel Exhaust Fluid) Record operations."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class DEFRecordBase(BaseModel):
    """Base DEF record schema with common fields."""

    date: date_type = Field(..., description="Purchase/fill date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0, le=9999999)
    gallons: Decimal | None = Field(
        None, description="DEF volume added in gallons", ge=0, le=999.999, decimal_places=3
    )
    cost: Decimal | None = Field(None, description="Total cost", ge=0, le=99999.99)
    price_per_unit: Decimal | None = Field(None, description="Cost per gallon", ge=0, le=999.999)
    fill_level: Decimal | None = Field(
        None,
        description="Tank level after adding DEF (0.00=empty, 1.00=full)",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )
    source: str | None = Field(None, description="Where purchased", max_length=100)
    brand: str | None = Field(None, description="DEF brand name", max_length=100)
    notes: str | None = Field(None, description="Additional notes")


class DEFRecordCreate(DEFRecordBase):
    """Schema for creating a new DEF record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "3C7WRTCL8NG123456",
                    "date": "2026-02-10",
                    "mileage": 55000,
                    "gallons": 5.5,
                    "cost": 24.75,
                    "price_per_unit": 4.50,
                    "fill_level": 1.0,
                    "source": "Truck Stop / Station Nozzle",
                    "brand": "BlueDEF",
                }
            ]
        }
    }


class DEFRecordUpdate(BaseModel):
    """Schema for updating an existing DEF record."""

    date: date_type | None = Field(None, description="Purchase/fill date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0, le=9999999)
    gallons: Decimal | None = Field(
        None, description="DEF volume added in gallons", ge=0, le=999.999, decimal_places=3
    )
    cost: Decimal | None = Field(None, description="Total cost", ge=0, le=99999.99)
    price_per_unit: Decimal | None = Field(None, description="Cost per gallon", ge=0, le=999.999)
    fill_level: Decimal | None = Field(
        None,
        description="Tank level after adding DEF (0.00=empty, 1.00=full)",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )
    source: str | None = Field(None, description="Where purchased", max_length=100)
    brand: str | None = Field(None, description="DEF brand name", max_length=100)
    notes: str | None = Field(None, description="Additional notes")

    model_config = {"json_schema_extra": {"examples": [{"cost": 22.50, "notes": "Bought on sale"}]}}


class DEFRecordResponse(DEFRecordBase):
    """Schema for DEF record response."""

    id: int
    vin: str
    created_at: datetime
    entry_type: str = "purchase"
    origin_fuel_record_id: int | None = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "3C7WRTCL8NG123456",
                    "date": "2026-02-10",
                    "mileage": 55000,
                    "gallons": "5.500",
                    "cost": "24.75",
                    "price_per_unit": "4.500",
                    "fill_level": "1.00",
                    "source": "Truck Stop / Station Nozzle",
                    "brand": "BlueDEF",
                    "notes": None,
                    "created_at": "2026-02-10T14:30:00",
                }
            ]
        },
    }


class DEFRecordListResponse(BaseModel):
    """Schema for DEF record list response."""

    records: list[DEFRecordResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "records": [
                        {
                            "id": 1,
                            "vin": "3C7WRTCL8NG123456",
                            "date": "2026-02-10",
                            "mileage": 55000,
                            "gallons": "5.500",
                            "cost": "24.75",
                            "fill_level": "1.00",
                            "source": "Truck Stop / Station Nozzle",
                            "brand": "BlueDEF",
                            "created_at": "2026-02-10T14:30:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }


class DEFAnalytics(BaseModel):
    """DEF analytics and consumption predictions."""

    total_gallons: Decimal | None = None
    total_cost: Decimal | None = None
    avg_cost_per_gallon: Decimal | None = None
    gallons_per_1000_miles: Decimal | None = None
    avg_purchase_frequency_days: int | None = None
    estimated_remaining_gallons: Decimal | None = None
    estimated_miles_remaining: int | None = None
    estimated_days_remaining: int | None = None
    last_fill_level: Decimal | None = None
    record_count: int = 0
    data_confidence: str = "insufficient"  # "high", "low", "insufficient"

    model_config = {"from_attributes": True}
