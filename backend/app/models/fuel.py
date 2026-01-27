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
    """Fuel record model for tracking fill-ups and MPG calculations."""

    __tablename__ = "fuel_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    mileage: Mapped[int | None] = mapped_column(Integer)
    gallons: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    propane_gallons: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    tank_size_lb: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    tank_quantity: Mapped[int | None] = mapped_column(Integer)
    kwh: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    fuel_type: Mapped[str | None] = mapped_column(String(50))
    is_full_tank: Mapped[bool] = mapped_column(Boolean, default=True)
    missed_fillup: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hauling: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Vehicle was towing/hauling during this fuel cycle",
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="fuel_records")

    __table_args__ = (
        Index("idx_fuel_records_vin", "vin"),
        Index("idx_fuel_records_date", "date"),
        Index("idx_fuel_records_mileage", "mileage"),  # For mileage-based queries
        Index("idx_fuel_vin_date", "vin", "date"),  # Composite for common queries
        Index("idx_fuel_is_full_tank", "is_full_tank"),  # For MPG calculations
        Index("idx_fuel_full_tank_vin", "vin", "is_full_tank"),  # Optimized MPG queries
        Index("idx_fuel_hauling", "is_hauling"),  # For filtering hauling records
        Index(
            "idx_fuel_normal_mpg", "vin", "is_full_tank", "is_hauling"
        ),  # Optimized filtered MPG
    )


from app.models.vehicle import Vehicle
