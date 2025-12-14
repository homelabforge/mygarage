"""Spot rental database model."""

from sqlalchemy import String, Integer, Numeric, Date, DateTime, Text, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from decimal import Decimal

from app.database import Base

if TYPE_CHECKING:
    from app.models.spot_rental_billing import SpotRentalBilling


class SpotRental(Base):
    """Spot rental tracking for trailers/RVs."""

    __tablename__ = "spot_rentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False)
    location_name: Mapped[Optional[str]] = mapped_column(String(100))
    location_address: Mapped[Optional[str]] = mapped_column(Text)
    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_out_date: Mapped[Optional[date]] = mapped_column(Date)
    nightly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    weekly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    monthly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    electric: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    water: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    waste: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    total_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    amenities: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="spot_rentals")
    billings: Mapped[list["SpotRentalBilling"]] = relationship(
        "SpotRentalBilling",
        back_populates="spot_rental",
        cascade="all, delete-orphan",
        order_by="SpotRentalBilling.billing_date.desc()"
    )

    __table_args__ = (
        Index("idx_spot_rentals_vin", "vin"),
        Index("idx_spot_rentals_dates", "check_in_date", "check_out_date"),
        # Check constraints to ensure non-negative values
        CheckConstraint("electric IS NULL OR electric >= 0", name="ck_spot_rentals_electric_positive"),
        CheckConstraint("water IS NULL OR water >= 0", name="ck_spot_rentals_water_positive"),
        CheckConstraint("waste IS NULL OR waste >= 0", name="ck_spot_rentals_waste_positive"),
        CheckConstraint("nightly_rate IS NULL OR nightly_rate >= 0", name="ck_spot_rentals_nightly_rate_positive"),
        CheckConstraint("weekly_rate IS NULL OR weekly_rate >= 0", name="ck_spot_rentals_weekly_rate_positive"),
        CheckConstraint("monthly_rate IS NULL OR monthly_rate >= 0", name="ck_spot_rentals_monthly_rate_positive"),
        CheckConstraint("total_cost IS NULL OR total_cost >= 0", name="ck_spot_rentals_total_cost_positive"),
    )


from app.models.vehicle import Vehicle
