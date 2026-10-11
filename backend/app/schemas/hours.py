"""Pydantic schemas for Hours Record operations.

Engine-hours analog of ``schemas/odometer.py`` (s/odometer_km/engine_hours/).
Hours are dimensionless -- no unit conversion, no metric/imperial split.
"""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas._nullability import reject_null


class HoursRecordBase(BaseModel):
    """Base hours record schema with common fields."""

    date: date_type = Field(..., description="Reading date")
    engine_hours: Decimal = Field(..., description="Engine hours reading", ge=0, le=999999999.9)
    notes: str | None = Field(None, description="Additional notes")


class HoursRecordCreate(HoursRecordBase):
    """Schema for creating a new hours record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "engine_hours": 812.4,
                    "notes": "Monthly reading",
                }
            ]
        }
    }


class HoursRecordUpdate(BaseModel):
    """Schema for updating an existing hours record."""

    date: date_type | None = Field(None, description="Reading date")
    engine_hours: Decimal | None = Field(
        None, description="Engine hours reading", ge=0, le=999999999.9
    )
    notes: str | None = Field(None, description="Additional notes")

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("date", "engine_hours")

    model_config = {
        "json_schema_extra": {"examples": [{"engine_hours": 815.2, "notes": "Corrected reading"}]}
    }


class HoursRecordResponse(HoursRecordBase):
    """Schema for hours record response."""

    # No input bounds, so a stored reading past today's rules still reads
    # instead of 500ing (test_response_contract).
    engine_hours: Decimal = Field(..., description="Engine hours reading")
    id: int
    vin: str
    source: str
    fuel_record_id: int | None
    service_visit_id: int | None
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "engine_hours": 812.4,
                    "notes": "Monthly reading",
                    "source": "manual",
                    "fuel_record_id": None,
                    "service_visit_id": None,
                    "created_at": "2025-01-15T09:00:00",
                }
            ]
        },
    }


class HoursRecordListResponse(BaseModel):
    """Schema for hours record list response."""

    records: list[HoursRecordResponse]
    total: int
    latest_engine_hours: Decimal | None = Field(
        None, description="Canonical latest engine-hours reading (highest on record)"
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
                            "engine_hours": 812.4,
                            "notes": "Monthly reading",
                            "source": "manual",
                            "fuel_record_id": None,
                            "service_visit_id": None,
                            "created_at": "2025-01-15T09:00:00",
                        }
                    ],
                    "total": 1,
                    "latest_engine_hours": 812.4,
                }
            ]
        }
    }


class NearestHoursResponse(BaseModel):
    """The hours reading closest to a requested day, for the tire dialogs' suggestion."""

    date: date_type
    engine_hours: Decimal
    source: str
    #: Signed days from the requested date to the reading. Negative is before.
    days_away: int
