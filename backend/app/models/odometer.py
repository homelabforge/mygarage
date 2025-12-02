"""Odometer record database model."""

from sqlalchemy import String, Integer, Date, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional

from app.database import Base


class OdometerRecord(Base):
    """Odometer reading model."""

    __tablename__ = "odometer_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    mileage: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="odometer_records")

    __table_args__ = (
        Index("idx_odometer_records_vin", "vin"),
        Index("idx_odometer_records_date", "date"),
        Index("idx_odometer_records_mileage", "mileage"),       # For mileage queries
        Index("idx_odometer_vin_date", "vin", "date"),          # Composite for common queries
        Index("idx_odometer_vin_mileage", "vin", "mileage"),    # For mileage tracking
    )


from app.models.vehicle import Vehicle
