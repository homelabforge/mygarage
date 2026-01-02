"""Address book database model."""

from sqlalchemy import String, Integer, Text, DateTime, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional
from decimal import Decimal

from app.database import Base


class AddressBookEntry(Base):
    """Address book entry for vendors, shops, and contacts."""

    __tablename__ = "address_book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_name: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(50))
    zip_code: Mapped[Optional[str]] = mapped_column(String(20))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(
        String(50)
    )  # service, insurance, parts, etc.
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Geolocation fields for shop discovery
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 8))
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(11, 8))

    # Shop discovery metadata
    source: Mapped[str] = mapped_column(
        String(20), default="manual"
    )  # 'manual' or 'google_places'
    external_id: Mapped[Optional[str]] = mapped_column(
        String(100)
    )  # Google Place ID or other external ID

    # Ratings
    rating: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2)
    )  # Google rating (0.00 - 5.00)
    user_rating: Mapped[Optional[int]] = mapped_column(Integer)  # User's 1-5 star rating

    # Usage tracking for recommendations
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_address_book_name", "name"),
        Index("idx_address_book_category", "category"),
    )
