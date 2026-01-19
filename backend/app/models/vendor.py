"""Vendor database model."""

from sqlalchemy import String, Integer, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.service_visit import ServiceVisit
    from app.models.vendor_price_history import VendorPriceHistory


class Vendor(Base):
    """Vendor/shop model for service providers."""

    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(50))
    zip_code: Mapped[Optional[str]] = mapped_column(String(20))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now()
    )

    # Relationships
    service_visits: Mapped[list["ServiceVisit"]] = relationship(
        "ServiceVisit", back_populates="vendor"
    )
    price_history: Mapped[list["VendorPriceHistory"]] = relationship(
        "VendorPriceHistory", back_populates="vendor"
    )

    __table_args__ = (Index("idx_vendors_name", "name"),)

    @property
    def full_address(self) -> Optional[str]:
        """Return formatted full address."""
        parts = []
        if self.address:
            parts.append(self.address)
        if self.city:
            city_state = self.city
            if self.state:
                city_state += f", {self.state}"
            if self.zip_code:
                city_state += f" {self.zip_code}"
            parts.append(city_state)
        return ", ".join(parts) if parts else None
