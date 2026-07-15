from __future__ import annotations

"""Fuel record database model."""

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class FuelRecord(Base):
    """Fuel record model for tracking fill-ups and L/100km calculations."""

    __tablename__ = "fuel_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Optional fill-up timestamp. Drives DriveSession matching for OBC auto-suggest.
    # When set, application code mirrors `filled_at.date()` into `date` so
    # legacy date-only consumers (lists, reports, CSV export) keep working.
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    liters: Mapped[Decimal | None] = mapped_column(Numeric(9, 3))
    propane_liters: Mapped[Decimal | None] = mapped_column(Numeric(9, 3))
    tank_size_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    tank_quantity: Mapped[int | None] = mapped_column(Integer)
    kwh: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # Rebate/discount/points redeemed on this fill-up. `cost` stores the NET
    # (price × volume − rebate); this keeps the redeemed amount for display and
    # export/import round-trips.
    rebate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    # Per-row classifier added by migration 053. Drives unit-aware price math.
    price_basis: Mapped[str | None] = mapped_column(String(12))
    # Legacy free-text fuel type. Migration 054 normalized values to the
    # FuelTypeEnum vocabulary; new writes prefer `fuel_type_used`. Kept as a
    # compatibility alias for one release (planned removal in v2.28.0).
    fuel_type: Mapped[str | None] = mapped_column(String(50))
    # Per-fillup actual fuel dispensed. Surfaced in UI only when the vehicle
    # has a non-null `fuel_type_secondary` (PHEV / flex / dual-fuel).
    fuel_type_used: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_full_tank: Mapped[bool] = mapped_column(Boolean, default=True)
    missed_fillup: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hauling: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Vehicle was towing/hauling during this fuel cycle",
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Extended metadata (issue #69).
    # Station: optional FK to address_book (POI), with a freetext fallback
    # used when the user checks "one-time visit" or no FK is set.
    station_address_book_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("address_book.id", ondelete="SET NULL"), nullable=True
    )
    station_name_freetext: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Driver: optional FK to a household user, with a freetext fallback for
    # non-account drivers.
    driver_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    driver_name_freetext: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trip_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Outside temperature in Celsius (canonical, per migration 053 metric pattern).
    outside_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    # On-board computer reported metrics. Optional manual entry; can be
    # auto-suggested from a matching DriveSession when filled_at is set.
    obc_l_per_100km: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    obc_avg_speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    obc_trip_duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="fuel_records")

    __table_args__ = (
        Index("idx_fuel_records_vin", "vin"),
        Index("idx_fuel_records_date", "date"),
        Index("idx_fuel_records_odometer_km", "odometer_km"),  # For mileage-based queries
        Index("idx_fuel_vin_date", "vin", "date"),  # Composite for common queries
        Index("idx_fuel_is_full_tank", "is_full_tank"),  # For MPG calculations
        Index("idx_fuel_full_tank_vin", "vin", "is_full_tank"),  # Optimized MPG queries
        Index("idx_fuel_hauling", "is_hauling"),  # For filtering hauling records
        Index("idx_fuel_normal_mpg", "vin", "is_full_tank", "is_hauling"),
        # Issue #69 — extended fuel tracking
        Index("idx_fuel_records_station_id", "station_address_book_id"),
        Index("idx_fuel_records_driver_id", "driver_user_id"),
        Index("idx_fuel_records_trip_type", "trip_type"),
        Index("idx_fuel_records_filled_at", "filled_at"),
    )


from app.models.vehicle import Vehicle
