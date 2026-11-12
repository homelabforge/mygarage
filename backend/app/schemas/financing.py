"""Pydantic schemas for financing record operations."""

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas._money import Money, OptionalMoney
from app.schemas._nullability import reject_null
from app.schemas.service_visit import VendorSummary

FinancingCategory = Literal["lease_payment", "loan_payment", "upfront_fee"]


class FinancingRecordBase(BaseModel):
    """Base financing record schema with common fields."""

    date: dt.date = Field(..., description="Date of the payment or fee")
    amount: Money = Field(..., description="Payment or fee amount", decimal_places=2)
    category: FinancingCategory = Field(..., description="Type of financing cost")
    vendor_id: int | None = Field(default=None, description="Associated vendor/lender ID")
    notes: str | None = Field(default=None, description="Additional notes")


class FinancingRecordCreate(FinancingRecordBase):
    """Schema for creating a new financing record."""

    vin: str = Field(..., description="VIN of the vehicle", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2026-01-01",
                    "amount": 450.00,
                    "category": "lease_payment",
                    "vendor_id": None,
                    "notes": "Monthly lease payment",
                }
            ]
        }
    }


class FinancingRecordUpdate(BaseModel):
    """Schema for updating an existing financing record."""

    date: dt.date | None = Field(default=None, description="Date of the payment or fee")
    amount: OptionalMoney = Field(
        default=None, description="Payment or fee amount", decimal_places=2
    )
    category: FinancingCategory | None = Field(default=None, description="Type of financing cost")
    vendor_id: int | None = Field(default=None, description="Associated vendor/lender ID")
    notes: str | None = Field(default=None, description="Additional notes")

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("amount", "category", "date")


class FinancingRecordResponse(FinancingRecordBase):
    """Schema for financing record response."""

    # Money without the input bounds, so a stored amount past today's rules
    # still reads instead of 500ing (test_response_contract).
    amount: Decimal = Field(..., description="Payment or fee amount")
    id: int
    vin: str
    created_at: dt.datetime
    updated_at: dt.datetime | None = None
    lender: VendorSummary | None = Field(
        default=None, validation_alias="vendor", description="Lender/vendor details, if set"
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2026-01-01",
                    "amount": 450.00,
                    "category": "lease_payment",
                    "vendor_id": None,
                    "notes": "Monthly lease payment",
                    "created_at": "2026-01-01T10:00:00",
                    "updated_at": None,
                    "lender": None,
                }
            ]
        },
    }


class FinancingRecordListResponse(BaseModel):
    """Schema for financing record list response."""

    financing_records: list[FinancingRecordResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "financing_records": [],
                    "total": 0,
                }
            ]
        }
    }
