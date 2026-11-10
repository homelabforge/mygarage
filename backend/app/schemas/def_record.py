"""Pydantic schemas for DEF (Diesel Exhaust Fluid) Record operations.

Canonical units (since v2.26.2): kilometers + liters.
"""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas._money import OptionalMoney, OptionalUnitPrice
from app.schemas._nullability import reject_null


class DEFRecordBase(BaseModel):
    """Base DEF record schema with common fields (metric canonical)."""

    date: date_type = Field(..., description="Purchase/fill date")
    odometer_km: Decimal | None = Field(
        default=None, description="Odometer reading in kilometers", ge=0, le=99999999.99
    )
    liters: Decimal | None = Field(
        default=None, description="DEF volume added in liters", ge=0, le=9999.999, decimal_places=3
    )
    cost: OptionalMoney = Field(default=None, description="Total cost")
    price_per_unit: OptionalUnitPrice = Field(default=None, description="Cost per liter")
    fill_level: Decimal | None = Field(
        default=None,
        description="Tank level after adding DEF (0.00=empty, 1.00=full)",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )
    source: str | None = Field(default=None, description="Where purchased", max_length=100)
    brand: str | None = Field(default=None, description="DEF brand name", max_length=100)
    notes: str | None = Field(default=None, description="Additional notes")


class DEFRecordCreate(DEFRecordBase):
    """Schema for creating a new DEF record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "3C7WRTCL8NG123456",
                    "date": "2026-02-10",
                    "odometer_km": 88514,
                    "liters": 20.82,
                    "cost": 24.75,
                    "price_per_unit": 1.189,
                    "fill_level": 1.0,
                    "source": "Truck Stop / Station Nozzle",
                    "brand": "BlueDEF",
                }
            ]
        }
    }


class DEFRecordUpdate(BaseModel):
    """Schema for updating an existing DEF record."""

    date: date_type | None = Field(default=None, description="Purchase/fill date")
    odometer_km: Decimal | None = Field(
        default=None, description="Odometer reading in kilometers", ge=0, le=99999999.99
    )
    liters: Decimal | None = Field(
        default=None, description="DEF volume added in liters", ge=0, le=9999.999, decimal_places=3
    )
    cost: OptionalMoney = Field(default=None, description="Total cost")
    price_per_unit: OptionalUnitPrice = Field(default=None, description="Cost per liter")
    fill_level: Decimal | None = Field(
        default=None,
        description="Tank level after adding DEF (0.00=empty, 1.00=full)",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )
    source: str | None = Field(default=None, description="Where purchased", max_length=100)
    brand: str | None = Field(default=None, description="DEF brand name", max_length=100)
    notes: str | None = Field(default=None, description="Additional notes")

    # NOT NULL column: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("date")

    model_config = {"json_schema_extra": {"examples": [{"cost": 22.50, "notes": "Bought on sale"}]}}


class DEFRecordResponse(DEFRecordBase):
    """Schema for DEF record response."""

    # Numbers without the input bounds, so a stored value past today's rules
    # still reads instead of 500ing (test_response_contract).
    odometer_km: Decimal | None = Field(default=None, description="Odometer reading in kilometers")
    liters: Decimal | None = Field(default=None, description="DEF volume added in liters")
    cost: Decimal | None = Field(default=None, description="Total cost")
    price_per_unit: Decimal | None = Field(default=None, description="Cost per liter")
    fill_level: Decimal | None = Field(
        default=None, description="Tank level after adding DEF (0.00=empty, 1.00=full)"
    )
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    source: str | None = Field(default=None, description="Where purchased")
    brand: str | None = Field(default=None, description="DEF brand name")
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
                    "odometer_km": 88514,
                    "liters": "20.820",
                    "cost": "24.75",
                    "price_per_unit": "1.189",
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
                            "odometer_km": 88514,
                            "liters": "20.820",
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
    """DEF analytics and consumption predictions (metric canonical)."""

    total_liters: Decimal | None = None
    total_cost: Decimal | None = None
    avg_cost_per_liter: Decimal | None = None
    liters_per_1000_km: Decimal | None = None
    avg_purchase_frequency_days: int | None = None
    estimated_remaining_liters: Decimal | None = None
    estimated_km_remaining: Decimal | None = None
    estimated_days_remaining: int | None = None
    last_fill_level: Decimal | None = None
    record_count: int = 0
    data_confidence: str = "insufficient"  # "high", "low", "insufficient"

    model_config = {"from_attributes": True}
