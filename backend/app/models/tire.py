"""Tire position / tread / DOT tracking models."""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Tire(Base):
    """Current tire mounted at a vehicle position (one row per position)."""

    __tablename__ = "tires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    # FL / FR / RL / RR / SPARE
    position: Mapped[str] = mapped_column(String(10), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(40))
    # DOT week/year code, e.g. "2324"
    dot_code: Mapped[str | None] = mapped_column(String(20))
    installed_date: Mapped[dt.date | None] = mapped_column(Date)
    # Latest tread depth in millimetres (canonical).
    tread_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Optional cold pressure in kPa (canonical).
    pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    # Wear-out threshold used for reminder hooks (default 2.0 mm / ~2/32").
    min_tread_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=Decimal("2.0"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    readings: Mapped[list[TireReading]] = relationship(
        "TireReading",
        back_populates="tire",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("vin", "position", name="uq_tires_vin_position"),
        Index("idx_tires_vin", "vin"),
    )


class TireReading(Base):
    """Historical tread / pressure reading for wear projection."""

    __tablename__ = "tire_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tire_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False
    )
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[str] = mapped_column(String(10), nullable=False)
    recorded_at: Mapped[dt.date] = mapped_column(Date, nullable=False)
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Nullable since migration 094: a reader with no tread gauge logs pressure
    # alone (#152). ``TireReadingCreate`` still refuses a reading that carries
    # neither, and ``TireService.add_reading`` leaves the parent tire's tread
    # untouched when a reading omits one.
    tread_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tire: Mapped[Tire] = relationship("Tire", back_populates="readings")

    __table_args__ = (
        Index("idx_tire_readings_tire", "tire_id"),
        Index("idx_tire_readings_vin", "vin"),
    )
