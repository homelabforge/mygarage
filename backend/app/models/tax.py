from __future__ import annotations

"""Tax record database model."""

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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


class TaxRecord(Base):
    """Tax/registration/inspection record model."""

    __tablename__ = "tax_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # A code from `app.constants.tax.TAX_TYPE_VALUES` (#211). The schemas are
    # the gate: the `check_tax_type` CHECK that held the four original display
    # strings was dropped by migration 146, so a new type is code-only.
    tax_type: Mapped[str | None] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(ScaledNumeric(12, 2), nullable=False)
    renewal_date: Mapped[dt.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="tax_records")

    __table_args__ = (
        Index("idx_tax_records_vin", "vin"),
        Index("idx_tax_records_date", "date"),
    )


from app.models.vehicle import Vehicle
