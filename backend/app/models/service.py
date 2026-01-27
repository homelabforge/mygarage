"""Service record database model."""

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
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


class ServiceRecord(Base):
    """Service record model for maintenance, repairs, and inspections."""

    __tablename__ = "service_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    mileage: Mapped[int | None] = mapped_column(Integer)
    service_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # CHANGED: was description
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    vendor_name: Mapped[str | None] = mapped_column(String(100))
    vendor_location: Mapped[str | None] = mapped_column(String(100))
    service_category: Mapped[str | None] = mapped_column(
        String(30)
    )  # CHANGED: was service_type
    insurance_claim: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle", back_populates="service_records"
    )

    __table_args__ = (
        CheckConstraint(
            "service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades')",
            name="check_service_category",
        ),
        Index("idx_service_records_vin", "vin"),
        Index("idx_service_records_date", "date"),
        Index(
            "idx_service_vin_date", "vin", "date"
        ),  # Composite index for common queries
        Index("idx_service_mileage", "mileage"),  # For mileage-based queries
        Index("idx_service_category", "service_category"),  # For category filtering
        Index(
            "idx_service_type", "service_type"
        ),  # For specific service type filtering
        Index("idx_service_vendor", "vendor_name"),  # For vendor analytics
        Index(
            "idx_service_vin_category", "vin", "service_category"
        ),  # For vehicle category queries
    )


from app.models.vehicle import Vehicle
