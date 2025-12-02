"""Pydantic schemas for toll tag and transaction operations."""

from typing import Optional
import datetime as dt
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


class TollTagBase(BaseModel):
    """Base toll tag schema with common fields."""

    toll_system: str = Field(..., description="Toll system name", min_length=1, max_length=50)
    tag_number: str = Field(..., description="Transponder/tag number", min_length=1, max_length=50)
    status: str = Field("active", description="Tag status")
    notes: Optional[str] = Field(None, description="Additional notes")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status."""
        valid_statuses = ['active', 'inactive']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of: {", ".join(valid_statuses)}')
        return v

    @field_validator('toll_system')
    @classmethod
    def validate_toll_system(cls, v: str) -> str:
        """Validate and suggest common toll systems."""
        # Allow any toll system but normalize common ones
        common_systems = {
            'eztag': 'EZ TAG',
            'ez tag': 'EZ TAG',
            'txtag': 'TxTag',
            'tx tag': 'TxTag',
            'ezpass': 'E-ZPass',
            'e-zpass': 'E-ZPass',
            'sunpass': 'SunPass',
            'ntta': 'NTTA TollTag',
            'tolltag': 'NTTA TollTag',
        }
        return common_systems.get(v.lower(), v)


class TollTagCreate(TollTagBase):
    """Schema for creating a new toll tag."""

    vin: str = Field(..., description="VIN of the vehicle", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "toll_system": "EZ TAG",
                    "tag_number": "0012345678",
                    "status": "active",
                    "notes": "Primary toll tag for truck"
                }
            ]
        }
    }


class TollTagUpdate(BaseModel):
    """Schema for updating an existing toll tag."""

    toll_system: Optional[str] = Field(None, description="Toll system name", min_length=1, max_length=50)
    tag_number: Optional[str] = Field(None, description="Transponder/tag number", min_length=1, max_length=50)
    status: Optional[str] = Field(None, description="Tag status")
    notes: Optional[str] = Field(None, description="Additional notes")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        """Validate status."""
        if v is None:
            return v
        valid_statuses = ['active', 'inactive']
        if v not in valid_statuses:
            raise ValueError(f'Status must be one of: {", ".join(valid_statuses)}')
        return v


class TollTagResponse(TollTagBase):
    """Schema for toll tag response."""

    id: int
    vin: str
    created_at: dt.datetime
    updated_at: Optional[dt.datetime] = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "toll_system": "EZ TAG",
                    "tag_number": "0012345678",
                    "status": "active",
                    "notes": "Primary toll tag for truck",
                    "created_at": "2025-11-08T10:00:00",
                    "updated_at": None
                }
            ]
        }
    }


class TollTagListResponse(BaseModel):
    """Schema for toll tag list response."""

    toll_tags: list[TollTagResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "toll_tags": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "toll_system": "EZ TAG",
                            "tag_number": "0012345678",
                            "status": "active",
                            "notes": None,
                            "created_at": "2025-11-08T10:00:00",
                            "updated_at": None
                        }
                    ],
                    "total": 1
                }
            ]
        }
    }


class TollTransactionBase(BaseModel):
    """Base toll transaction schema with common fields."""

    transaction_date: dt.date = Field(..., description="Transaction date")
    amount: Decimal = Field(..., description="Toll amount", ge=0)
    location: str = Field(..., description="Toll location/plaza", min_length=1, max_length=200)
    toll_tag_id: Optional[int] = Field(None, description="Associated toll tag ID")
    notes: Optional[str] = Field(None, description="Additional notes")


class TollTransactionCreate(TollTransactionBase):
    """Schema for creating a new toll transaction."""

    vin: str = Field(..., description="VIN of the vehicle", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-11-08",
                    "amount": 2.50,
                    "location": "Hardy Toll Road - Spring",
                    "toll_tag_id": 1,
                    "notes": "Morning commute"
                }
            ]
        }
    }


class TollTransactionUpdate(BaseModel):
    """Schema for updating an existing toll transaction."""

    transaction_date: Optional[dt.date] = Field(None, description="Transaction date")
    amount: Optional[Decimal] = Field(None, description="Toll amount", ge=0)
    location: Optional[str] = Field(None, description="Toll location/plaza", min_length=1, max_length=200)
    toll_tag_id: Optional[int] = Field(None, description="Associated toll tag ID")
    notes: Optional[str] = Field(None, description="Additional notes")


class TollTransactionResponse(TollTransactionBase):
    """Schema for toll transaction response."""

    id: int
    vin: str
    created_at: dt.datetime

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-11-08",
                    "amount": 2.50,
                    "location": "Hardy Toll Road - Spring",
                    "toll_tag_id": 1,
                    "notes": "Morning commute",
                    "created_at": "2025-11-08T10:00:00"
                }
            ]
        }
    }


class TollTransactionListResponse(BaseModel):
    """Schema for toll transaction list response."""

    transactions: list[TollTransactionResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "transactions": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2025-11-08",
                            "amount": 2.50,
                            "location": "Hardy Toll Road - Spring",
                            "toll_tag_id": 1,
                            "notes": None,
                            "created_at": "2025-11-08T10:00:00"
                        }
                    ],
                    "total": 1
                }
            ]
        }
    }


class TollTransactionSummary(BaseModel):
    """Schema for toll transaction summary/statistics."""

    total_transactions: int
    total_amount: Decimal
    monthly_totals: list[dict]  # [{"month": "2025-11", "count": 10, "amount": 25.00}]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "total_transactions": 25,
                    "total_amount": 62.50,
                    "monthly_totals": [
                        {"month": "2025-11", "count": 15, "amount": 37.50},
                        {"month": "2025-10", "count": 10, "amount": 25.00}
                    ]
                }
            ]
        }
    }
