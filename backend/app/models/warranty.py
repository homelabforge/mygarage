"""Warranty record database model."""

from sqlalchemy import String, Integer, Date, DateTime, Text, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional

from app.database import Base


class WarrantyRecord(Base):
    """Warranty coverage record model."""

    __tablename__ = "warranty_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False)
    warranty_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    mileage_limit: Mapped[Optional[int]] = mapped_column(Integer)
    coverage_details: Mapped[Optional[str]] = mapped_column(Text)
    policy_number: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="warranty_records")

    __table_args__ = (
        CheckConstraint(
            "warranty_type IN ('Manufacturer', 'Powertrain', 'Extended', 'Bumper-to-Bumper', 'Emissions', 'Corrosion', 'Other')",
            name="check_warranty_type"
        ),
        Index("idx_warranty_records_vin", "vin"),
        Index("idx_warranty_records_end_date", "end_date"),
    )


from app.models.vehicle import Vehicle
