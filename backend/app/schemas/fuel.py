"""Pydantic schemas for Fuel Record operations.

Canonical units (since v2.26.2): SI metric.
- odometer_km, liters, propane_liters, tank_size_kg
- price_per_unit denominator depends on price_basis (per_volume = per liter,
  per_weight = per kilogram, per_kwh = per kWh, per_tank = per tank)
- l_per_100km is computed on the fly from liters + odometer_km deltas

Issue #69 extended fuel tracking adds (all optional):
- filled_at: optional fill-up timestamp; required for OBC auto-suggest
- station: address_book FK + freetext fallback ("one-time visit")
- driver: user FK + freetext fallback
- payment_method, trip_type: validated against the constants/fuel.py enums
- outside_temp_c: canonical Celsius
- obc_l_per_100km / obc_avg_speed_kmh / obc_trip_duration_s
- fuel_type_used: actual fuel dispensed (multi-fuel vehicles only)

Legacy `fuel_type` (free-text) is preserved as a compatibility alias for one
release; new clients should use `fuel_type_used`. The service layer mirrors
between them during the compatibility window — see services/fuel_service.py.
"""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from app.constants.fuel import (
    FUEL_TYPE_VALUES,
    PAYMENT_METHOD_VALUES,
    TRIP_TYPE_VALUES,
)

PRICE_BASIS_VALUES = ("per_volume", "per_weight", "per_tank", "per_kwh")


def _validate_payment_method(v: str | None) -> str | None:
    if v is not None and v not in PAYMENT_METHOD_VALUES:
        raise ValueError(f"payment_method must be one of {PAYMENT_METHOD_VALUES}, got {v!r}")
    return v


def _validate_trip_type(v: str | None) -> str | None:
    if v is not None and v not in TRIP_TYPE_VALUES:
        raise ValueError(f"trip_type must be one of {TRIP_TYPE_VALUES}, got {v!r}")
    return v


def _validate_fuel_type_enum(v: str | None) -> str | None:
    if v is not None and v not in FUEL_TYPE_VALUES:
        raise ValueError(f"fuel_type_used must be one of {FUEL_TYPE_VALUES}, got {v!r}")
    return v


class FuelRecordBase(BaseModel):
    """Base fuel record schema with common fields (metric canonical)."""

    date: date_type = Field(..., description="Fill-up date")
    filled_at: datetime | None = Field(
        None,
        description=(
            "Optional fill-up timestamp (naive local). Required for OBC "
            "auto-suggest from a matching DriveSession."
        ),
    )
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
        None,
        description=(
            "Legacy fuel type column. New clients should use fuel_type_used. "
            "Kept for one release as a compatibility alias."
        ),
        max_length=50,
    )
    fuel_type_used: str | None = Field(
        None,
        description=(
            "Actual fuel dispensed for this fill-up (canonical enum). Only "
            "surfaced in UI when the vehicle has a secondary fuel capability."
        ),
        max_length=20,
    )
    is_full_tank: bool = Field(True, description="Full tank fill-up")
    missed_fillup: bool = Field(False, description="Skipped recording a fill-up")
    is_hauling: bool = Field(False, description="Vehicle was towing/hauling during this fuel cycle")
    notes: str | None = Field(None, description="Additional notes")

    # Issue #69 — extended fuel tracking
    station_address_book_id: int | None = Field(
        None,
        description="FK to address_book entry with poi_category='fuel_station'",
        ge=1,
    )
    station_name_freetext: str | None = Field(
        None,
        description="Freetext station name (one-time visit, no address-book entry created)",
        max_length=150,
    )
    driver_user_id: int | None = Field(
        None,
        description="FK to users.id when driver is a known household user",
        ge=1,
    )
    driver_name_freetext: str | None = Field(
        None,
        description="Freetext driver name (non-account household member)",
        max_length=100,
    )
    payment_method: str | None = Field(
        None,
        description=f"Payment method, one of {PAYMENT_METHOD_VALUES}",
        max_length=20,
    )
    trip_type: str | None = Field(
        None,
        description=f"Trip type for this fuel cycle, one of {TRIP_TYPE_VALUES}",
        max_length=20,
    )
    outside_temp_c: Decimal | None = Field(
        None,
        description="Outside temperature in Celsius (canonical)",
        ge=Decimal("-60.0"),
        le=Decimal("70.0"),
    )
    obc_l_per_100km: Decimal | None = Field(
        None,
        description="OBC reported fuel consumption (L/100 km)",
        ge=0,
        le=999.99,
    )
    obc_avg_speed_kmh: Decimal | None = Field(
        None,
        description="OBC reported average speed (km/h)",
        ge=0,
        le=9999.9,
    )
    obc_trip_duration_s: int | None = Field(
        None,
        description="OBC reported trip duration in seconds",
        ge=0,
    )

    @field_validator("price_basis")
    @classmethod
    def _check_price_basis(cls, v: str | None) -> str | None:
        if v is not None and v not in PRICE_BASIS_VALUES:
            raise ValueError(f"price_basis must be one of {PRICE_BASIS_VALUES}, got {v!r}")
        return v

    @field_validator("obc_trip_duration_s", mode="before")
    @classmethod
    def _parse_obc_trip_duration(cls, v: object) -> int | None:
        """Accept OBC trip duration as ``int`` seconds OR an ``HH:MM`` /
        ``HH:MM:SS`` string and store canonical seconds.

        Surfaced by issue #69: many onboard computers display trip
        duration as ``HH:MM`` (e.g. the reporter's reads ``02:15``).
        Forcing users to convert to seconds before submitting was
        friction; accepting the raw OBC string and converting
        server-side keeps canonical-seconds storage while improving UX.
        The frontend can keep sending integer seconds for the
        auto-suggest path.
        """
        if v is None or v == "":
            return None
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            if s.isdigit():
                return int(s)
            parts = s.split(":")
            if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = int(parts[2]) if len(parts) == 3 else 0
                if minutes >= 60 or seconds >= 60:
                    raise ValueError(
                        f"obc_trip_duration_s {v!r} has minute or second component ≥ 60"
                    )
                return hours * 3600 + minutes * 60 + seconds
            raise ValueError(
                f"obc_trip_duration_s must be an int (seconds), 'HH:MM', or 'HH:MM:SS'; got {v!r}"
            )
        raise ValueError(f"obc_trip_duration_s must be int or str; got {type(v).__name__}")

    # Note: enum validators for fuel_type_used / payment_method / trip_type
    # live on FuelRecordCreate / FuelRecordUpdate (input schemas) only.
    # FuelRecordResponse (which inherits from this base) must accept whatever
    # the DB returns, since legacy records may carry pre-migration values
    # that were mirrored into fuel_type_used during the compatibility window.


class FuelRecordCreate(FuelRecordBase):
    """Schema for creating a new fuel record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)
    def_fill_level: Decimal | None = Field(
        None,
        description="DEF tank level (0.00=empty, 1.00=full) — auto-creates a DEF observation",
        ge=Decimal("0.00"),
        le=Decimal("1.00"),
    )
    one_time_visit: bool = Field(
        False,
        description=(
            "When True, station_name_freetext is stored as-is and no "
            "address_book entry is created. Ignored if station_address_book_id is set."
        ),
    )

    @field_validator("fuel_type_used")
    @classmethod
    def _check_fuel_type_used_create(cls, v: str | None) -> str | None:
        return _validate_fuel_type_enum(v)

    @field_validator("payment_method")
    @classmethod
    def _check_payment_method_create(cls, v: str | None) -> str | None:
        return _validate_payment_method(v)

    @field_validator("trip_type")
    @classmethod
    def _check_trip_type_create(cls, v: str | None) -> str | None:
        return _validate_trip_type(v)

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

    @model_validator(mode="after")
    def _require_odometer_and_fuel_amount(self) -> FuelRecordCreate:
        """Reject fill-ups with no odometer or no fuel-amount data.

        Surfaced by issue #69: rc1 accepted records with neither odometer
        nor any fuel-amount field. The form's "you need to fill these in"
        rule lived only in frontend code, so any non-browser client
        (curl, mobile app, importer) could write empty records.

        Rule:
          - ``odometer_km`` is always required.
          - At least one of ``liters``, ``propane_liters``, ``kwh``, or
            the propane ``tank_size_kg`` + ``tank_quantity`` pair is
            required, EXCEPT when ``missed_fillup=True`` — that's the
            explicit "I noticed the odometer but I don't have the
            fuel amount" escape hatch.
        """
        if self.odometer_km is None:
            raise ValueError(
                "odometer_km is required (set missed_fillup=True only if "
                "you also can't supply a fuel amount)"
            )

        if self.missed_fillup:
            return self

        has_amount = (
            self.liters is not None
            or self.propane_liters is not None
            or self.kwh is not None
            or (self.tank_size_kg is not None and self.tank_quantity is not None)
        )
        if not has_amount:
            raise ValueError(
                "fuel record must include at least one of: liters, "
                "propane_liters, kwh, or both tank_size_kg + tank_quantity. "
                "Set missed_fillup=True if the actual amount is unavailable."
            )

        return self

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
    filled_at: datetime | None = Field(None, description="Optional fill-up timestamp")
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
        None,
        description="Legacy fuel type (compatibility alias for fuel_type_used)",
        max_length=50,
    )
    fuel_type_used: str | None = Field(
        None,
        description="Actual fuel dispensed (canonical enum)",
        max_length=20,
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

    # Issue #69 — extended fuel tracking
    station_address_book_id: int | None = Field(None, ge=1)
    station_name_freetext: str | None = Field(None, max_length=150)
    driver_user_id: int | None = Field(None, ge=1)
    driver_name_freetext: str | None = Field(None, max_length=100)
    payment_method: str | None = Field(None, max_length=20)
    trip_type: str | None = Field(None, max_length=20)
    outside_temp_c: Decimal | None = Field(None, ge=Decimal("-60.0"), le=Decimal("70.0"))
    obc_l_per_100km: Decimal | None = Field(None, ge=0, le=999.99)
    obc_avg_speed_kmh: Decimal | None = Field(None, ge=0, le=9999.9)
    obc_trip_duration_s: int | None = Field(None, ge=0)

    @field_validator("price_basis")
    @classmethod
    def _check_price_basis(cls, v: str | None) -> str | None:
        if v is not None and v not in PRICE_BASIS_VALUES:
            raise ValueError(f"price_basis must be one of {PRICE_BASIS_VALUES}, got {v!r}")
        return v

    @field_validator("fuel_type_used")
    @classmethod
    def _check_fuel_type_used(cls, v: str | None) -> str | None:
        return _validate_fuel_type_enum(v)

    @field_validator("payment_method")
    @classmethod
    def _check_payment_method(cls, v: str | None) -> str | None:
        return _validate_payment_method(v)

    @field_validator("trip_type")
    @classmethod
    def _check_trip_type(cls, v: str | None) -> str | None:
        return _validate_trip_type(v)

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


class ObcSuggestionResponse(BaseModel):
    """OBC auto-suggest payload — returned for `GET /api/vehicles/{vin}/fuel/obc-suggestion`."""

    session_id: int = Field(..., description="DriveSession.id used for the suggestion")
    ended_at: datetime = Field(..., description="When the matched DriveSession ended")
    distance_km: Decimal | None = Field(None, description="Distance covered during the session")
    obc_l_per_100km: Decimal | None = Field(None, description="Suggested consumption (L/100 km)")
    obc_avg_speed_kmh: Decimal | None = Field(None, description="Suggested average speed (km/h)")
    obc_trip_duration_s: int | None = Field(None, description="Suggested trip duration (seconds)")
