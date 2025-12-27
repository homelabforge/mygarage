"""Pydantic schemas for tax/registration records."""

from datetime import date as date_type, datetime as datetime_type
from decimal import Decimal
from typing import Optional, Literal

from pydantic import BaseModel, Field


TaxType = Literal["Registration", "Inspection", "Property Tax", "Tolls"]


class TaxRecordBase(BaseModel):
    """Base tax record schema."""

    date: date_type = Field(..., description="Date the fee was paid")
    tax_type: Optional[TaxType] = Field(None, description="Type of tax/fee")
    amount: Decimal = Field(..., description="Amount paid", ge=0)
    renewal_date: Optional[date_type] = Field(None, description="Next renewal date")
    notes: Optional[str] = None


class TaxRecordCreate(TaxRecordBase):
    """Schema for creating a tax record."""

    vin: str = Field(..., max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "tax_type": "Registration",
                    "amount": 85.50,
                    "renewal_date": "2026-01-15",
                    "notes": "Annual vehicle registration renewal",
                }
            ]
        }
    }


class TaxRecordUpdate(BaseModel):
    """Schema for updating a tax record."""

    date: Optional[date_type] = None
    tax_type: Optional[TaxType] = None
    amount: Optional[Decimal] = Field(None, ge=0)
    renewal_date: Optional[date_type] = None
    notes: Optional[str] = None


class TaxRecordResponse(TaxRecordBase):
    """Schema for tax record response."""

    id: int
    vin: str
    created_at: datetime_type

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "tax_type": "Registration",
                    "amount": 85.50,
                    "renewal_date": "2026-01-15",
                    "notes": "Annual vehicle registration renewal",
                    "created_at": "2025-01-15T10:30:00",
                }
            ]
        },
    }


class TaxRecordListResponse(BaseModel):
    """Schema for list of tax records."""

    records: list[TaxRecordResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "records": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2025-01-15",
                            "tax_type": "Registration",
                            "amount": 85.50,
                            "renewal_date": "2026-01-15",
                            "notes": "Annual vehicle registration renewal",
                            "created_at": "2025-01-15T10:30:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }
