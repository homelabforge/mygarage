"""Tax record database model."""

from sqlalchemy import (
    String,
    Integer,
    Numeric,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional
from decimal import Decimal

from app.database import Base


class TaxRecord(Base):
    """Tax/registration/inspection record model."""

    __tablename__ = "tax_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    tax_type: Mapped[Optional[str]] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    renewal_date: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="tax_records")

    __table_args__ = (
        CheckConstraint(
            "tax_type IN ('Registration', 'Inspection', 'Property Tax', 'Tolls')",
            name="check_tax_type",
        ),
        Index("idx_tax_records_vin", "vin"),
        Index("idx_tax_records_date", "date"),
    )


from app.models.vehicle import Vehicle
