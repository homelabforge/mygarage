"""Service visit database model."""

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
import datetime as dt
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from decimal import Decimal

from app.database import Base

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle
    from app.models.vendor import Vendor
    from app.models.service_line_item import ServiceLineItem


class ServiceVisit(Base):
    """Service visit model representing a single trip to a shop."""

    __tablename__ = "service_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("vendors.id"))
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    mileage: Mapped[Optional[int]] = mapped_column(Integer)
    total_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    shop_supplies: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    misc_fees: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    service_category: Mapped[Optional[str]] = mapped_column(String(30))
    insurance_claim_number: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now()
    )

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle", back_populates="service_visits"
    )
    vendor: Mapped[Optional["Vendor"]] = relationship(
        "Vendor", back_populates="service_visits"
    )
    line_items: Mapped[list["ServiceLineItem"]] = relationship(
        "ServiceLineItem",
        back_populates="visit",
        cascade="all, delete-orphan",
        order_by="ServiceLineItem.id",
    )

    __table_args__ = (
        CheckConstraint(
            "service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades', 'Detailing')",
            name="check_service_visit_category",
        ),
        Index("idx_service_visits_vin", "vin"),
        Index("idx_service_visits_date", "date"),
        Index("idx_service_visits_vendor", "vendor_id"),
        Index("idx_service_visits_vin_date", "vin", "date"),
    )

    @property
    def subtotal(self) -> Decimal:
        """Calculate subtotal from line items only (before tax/fees)."""
        total = Decimal(0)
        for item in self.line_items:
            if item.cost:
                total += item.cost
        return total

    @property
    def calculated_total_cost(self) -> Decimal:
        """Calculate total cost from line items + tax + fees."""
        total = self.subtotal
        if self.tax_amount:
            total += self.tax_amount
        if self.shop_supplies:
            total += self.shop_supplies
        if self.misc_fees:
            total += self.misc_fees
        return total

    @property
    def line_item_count(self) -> int:
        """Return number of line items."""
        return len(self.line_items)

    @property
    def has_failed_inspections(self) -> bool:
        """Check if any inspection line items failed."""
        return any(
            item.is_inspection and item.inspection_result == "failed"
            for item in self.line_items
        )
