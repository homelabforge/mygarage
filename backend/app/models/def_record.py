from __future__ import annotations

"""DEF (Diesel Exhaust Fluid) record database model."""

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class DEFRecord(Base):
    """DEF record model for tracking diesel exhaust fluid purchases and fill levels."""

    __tablename__ = "def_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    mileage: Mapped[int | None] = mapped_column(Integer)
    gallons: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    fill_level: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    source: Mapped[str | None] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="def_records")

    __table_args__ = (
        Index("idx_def_records_vin", "vin"),
        Index("idx_def_records_date", "date"),
        Index("idx_def_records_vin_date", "vin", "date"),
        Index("idx_def_records_mileage", "mileage"),
    )


from app.models.vehicle import Vehicle
