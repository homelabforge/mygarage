"""Pydantic schemas for Odometer Record operations."""

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field


class OdometerRecordBase(BaseModel):
    """Base odometer record schema with common fields."""

    date: date_type = Field(..., description="Reading date")
    mileage: int = Field(..., description="Odometer reading", ge=0)
    notes: str | None = Field(None, description="Additional notes")


class OdometerRecordCreate(OdometerRecordBase):
    """Schema for creating a new odometer record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "mileage": 45000,
                    "notes": "Monthly reading",
                }
            ]
        }
    }


class OdometerRecordUpdate(BaseModel):
    """Schema for updating an existing odometer record."""

    date: date_type | None = Field(None, description="Reading date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0)
    notes: str | None = Field(None, description="Additional notes")

    model_config = {
        "json_schema_extra": {
            "examples": [{"mileage": 45100, "notes": "Corrected reading"}]
        }
    }


class OdometerRecordResponse(OdometerRecordBase):
    """Schema for odometer record response."""

    id: int
    vin: str
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "mileage": 45000,
                    "notes": "Monthly reading",
                    "created_at": "2025-01-15T09:00:00",
                }
            ]
        },
    }


class OdometerRecordListResponse(BaseModel):
    """Schema for odometer record list response."""

    records: list[OdometerRecordResponse]
    total: int
    latest_mileage: int | None = Field(
        None, description="Most recent odometer reading"
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
                            "mileage": 45000,
                            "notes": "Monthly reading",
                            "created_at": "2025-01-15T09:00:00",
                        }
                    ],
                    "total": 1,
                    "latest_mileage": 45000,
                }
            ]
        }
    }
