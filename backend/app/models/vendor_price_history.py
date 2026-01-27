"""Vendor price history database model."""

from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.maintenance_schedule_item import MaintenanceScheduleItem
    from app.models.service_line_item import ServiceLineItem
    from app.models.vendor import Vendor


class VendorPriceHistory(Base):
    """Vendor price history model for tracking service costs over time."""

    __tablename__ = "vendor_price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendors.id"), nullable=False
    )
    schedule_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("maintenance_schedule_items.id"), nullable=False
    )
    service_line_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("service_line_items.id"), nullable=False
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Relationships
    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="price_history")
    schedule_item: Mapped["MaintenanceScheduleItem"] = relationship(
        "MaintenanceScheduleItem"
    )
    service_line_item: Mapped["ServiceLineItem"] = relationship("ServiceLineItem")

    __table_args__ = (
        Index("idx_vendor_price_vendor", "vendor_id"),
        Index("idx_vendor_price_schedule", "schedule_item_id"),
        Index("idx_vendor_price_vendor_schedule", "vendor_id", "schedule_item_id"),
        Index("idx_vendor_price_date", "date"),
    )
