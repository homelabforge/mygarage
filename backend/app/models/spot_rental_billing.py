"""Spot rental billing database model."""

from sqlalchemy import Integer, Numeric, Date, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from decimal import Decimal

from app.database import Base

if TYPE_CHECKING:
    from app.models.spot_rental import SpotRental


class SpotRentalBilling(Base):
    """Individual billing entry for a spot rental period.

    Allows tracking multiple billing entries for a single rental,
    such as monthly charges as they occur. Each billing entry can
    include monthly rate, utilities (electric, water, waste), and notes.
    """

    __tablename__ = "spot_rental_billings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spot_rental_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("spot_rentals.id", ondelete="CASCADE"),
        nullable=False
    )
    billing_date: Mapped[date] = mapped_column(Date, nullable=False)
    monthly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    electric: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    water: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    waste: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    total: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    spot_rental: Mapped["SpotRental"] = relationship(
        "SpotRental",
        back_populates="billings"
    )

    __table_args__ = (
        Index("idx_spot_rental_billings_rental_id", "spot_rental_id"),
        Index("idx_spot_rental_billings_date", "billing_date"),
    )

    def __repr__(self) -> str:
        return f"<SpotRentalBilling(id={self.id}, rental_id={self.spot_rental_id}, date={self.billing_date}, total={self.total})>"
