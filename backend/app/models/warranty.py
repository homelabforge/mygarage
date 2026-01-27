"""Warranty record database model."""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class WarrantyRecord(Base):
    """Warranty coverage record model."""

    __tablename__ = "warranty_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    warranty_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    mileage_limit: Mapped[int | None] = mapped_column(Integer)
    coverage_details: Mapped[str | None] = mapped_column(Text)
    policy_number: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle", back_populates="warranty_records"
    )

    __table_args__ = (
        CheckConstraint(
            "warranty_type IN ('Manufacturer', 'Powertrain', 'Extended', 'Bumper-to-Bumper', 'Emissions', 'Corrosion', 'Other')",
            name="check_warranty_type",
        ),
        Index("idx_warranty_records_vin", "vin"),
        Index("idx_warranty_records_end_date", "end_date"),
    )


from app.models.vehicle import Vehicle
