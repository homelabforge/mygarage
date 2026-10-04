"""Pydantic schemas for toll tag and transaction operations."""

import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas._money import Money, OptionalMoney
from app.schemas._nullability import reject_null

# Spellings people type for the US systems, mapped to the names the app lists.
_TOLL_SYSTEM_ALIASES = {
    "eztag": "EZ TAG",
    "ez tag": "EZ TAG",
    "txtag": "TxTag",
    "tx tag": "TxTag",
    "ezpass": "E-ZPass",
    "e-zpass": "E-ZPass",
    "sunpass": "SunPass",
    "ntta": "NTTA TollTag",
    "tolltag": "NTTA TollTag",
}


def _tidy_toll_system(value: Any) -> Any:
    """Trim and collapse whitespace so the length checks see the real name."""
    return " ".join(value.split()) if isinstance(value, str) else value


def _normalize_toll_system(value: str) -> str:
    """Map a known spelling to the listed name, e.g. "eztag" to "EZ TAG"."""
    return _TOLL_SYSTEM_ALIASES.get(value.lower(), value)


class TollTagBase(BaseModel):
    """Base toll tag schema with common fields."""

    toll_system: str = Field(..., description="Toll system name", min_length=1, max_length=50)
    tag_number: str = Field(..., description="Transponder/tag number", min_length=1, max_length=50)
    status: str = Field("active", description="Tag status")
    notes: str | None = Field(None, description="Additional notes")

    @field_validator("toll_system")
    @classmethod
    def validate_toll_system(cls, v: str) -> str:
        """Normalize common toll system spellings. Runs on reads too, so it never rejects."""
        return _normalize_toll_system(v)


class TollTagCreate(TollTagBase):
    """Schema for creating a new toll tag."""

    vin: str = Field(..., description="VIN of the vehicle", min_length=17, max_length=17)

    # A blank name has to fail here, on input. On the base it would 500 a
    # stored row on read, same as status.
    @field_validator("toll_system", mode="before")
    @classmethod
    def tidy_toll_system(cls, v: Any) -> Any:
        """Trim and collapse whitespace before min_length runs."""
        return _tidy_toll_system(v)

    # Here and not on the base: the status column has no CHECK, and the
    # response shares the base, so a stored "lost" would 500 the tag list.
    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status."""
        valid_statuses = ["active", "inactive"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {', '.join(valid_statuses)}")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "toll_system": "EZ TAG",
                    "tag_number": "0012345678",
                    "status": "active",
                    "notes": "Primary toll tag for truck",
                }
            ]
        }
    }


class TollTagUpdate(BaseModel):
    """Schema for updating an existing toll tag."""

    toll_system: str | None = Field(
        None, description="Toll system name", min_length=1, max_length=50
    )
    tag_number: str | None = Field(
        None, description="Transponder/tag number", min_length=1, max_length=50
    )
    status: str | None = Field(None, description="Tag status")
    notes: str | None = Field(None, description="Additional notes")

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("tag_number", "toll_system", "status")

    @field_validator("toll_system", mode="before")
    @classmethod
    def tidy_toll_system(cls, v: Any) -> Any:
        """Trim and collapse whitespace before min_length runs. None passes through to reject_null."""
        return _tidy_toll_system(v)

    @field_validator("toll_system")
    @classmethod
    def normalize_toll_system(cls, v: str | None) -> str | None:
        """Same spellings create normalizes."""
        return None if v is None else _normalize_toll_system(v)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        """Validate status."""
        if v is None:
            return v
        valid_statuses = ["active", "inactive"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of: {', '.join(valid_statuses)}")
        return v


class TollTagResponse(TollTagBase):
    """Schema for toll tag response."""

    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    toll_system: str = Field(..., description="Toll system name")
    tag_number: str = Field(..., description="Transponder/tag number")
    id: int
    vin: str
    created_at: dt.datetime
    updated_at: dt.datetime | None = None

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
                    "updated_at": None,
                }
            ]
        },
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
                            "updated_at": None,
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }


class TollTransactionBase(BaseModel):
    """Base toll transaction schema with common fields."""

    transaction_date: dt.date = Field(..., description="Transaction date")
    amount: Money = Field(..., description="Toll amount")
    location: str = Field(..., description="Toll location/plaza", min_length=1, max_length=200)
    toll_tag_id: int | None = Field(None, description="Associated toll tag ID")
    notes: str | None = Field(None, description="Additional notes")


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
                    "notes": "Morning commute",
                }
            ]
        }
    }


class TollTransactionUpdate(BaseModel):
    """Schema for updating an existing toll transaction."""

    transaction_date: dt.date | None = Field(None, description="Transaction date")
    amount: OptionalMoney = Field(None, description="Toll amount")
    location: str | None = Field(
        None, description="Toll location/plaza", min_length=1, max_length=200
    )
    toll_tag_id: int | None = Field(None, description="Associated toll tag ID")
    notes: str | None = Field(None, description="Additional notes")

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("transaction_date", "amount", "location")


class TollTransactionResponse(BaseModel):
    """Schema for toll transaction response."""

    id: int
    vin: str
    transaction_date: dt.date = Field(..., alias="date", description="Transaction date")
    amount: Decimal = Field(..., description="Toll amount")
    location: str = Field(..., description="Toll location/plaza")
    toll_tag_id: int | None = Field(None, description="Associated toll tag ID")
    notes: str | None = Field(None, description="Additional notes")
    created_at: dt.datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
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
                    "created_at": "2025-11-08T10:00:00",
                }
            ]
        },
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
                            "created_at": "2025-11-08T10:00:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }


class TollTransactionSummary(BaseModel):
    """Schema for toll transaction summary/statistics."""

    total_transactions: int
    total_amount: Decimal
    monthly_totals: list[dict[str, Any]]  # [{"month": "2025-11", "count": 10, "amount": 25.00}]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "total_transactions": 25,
                    "total_amount": 62.50,
                    "monthly_totals": [
                        {"month": "2025-11", "count": 15, "amount": 37.50},
                        {"month": "2025-10", "count": 10, "amount": 25.00},
                    ],
                }
            ]
        }
    }
