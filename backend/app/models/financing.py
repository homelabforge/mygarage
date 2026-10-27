from __future__ import annotations

"""Financing record model for lease/loan payments and upfront fees."""

import datetime as dt
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

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
from app.models._types import ScaledNumeric

if TYPE_CHECKING:
    from app.models.vendor import Vendor


class FinancingRecord(Base):
    """A single lease payment, loan payment, or upfront financing fee."""

    __tablename__ = "financing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("vendors.id"))
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(ScaledNumeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="financing_records")
    vendor: Mapped[Vendor | None] = relationship("Vendor", back_populates="financing_records")

    __table_args__ = (
        CheckConstraint(
            "category IN ('lease_payment', 'loan_payment', 'upfront_fee')",
            name="check_financing_records_category",
        ),
        Index("idx_financing_records_vin", "vin"),
        Index("idx_financing_records_date", "date"),
        Index("idx_financing_records_vendor_id", "vendor_id"),
    )


from app.models.vehicle import Vehicle
