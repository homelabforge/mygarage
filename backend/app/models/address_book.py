"""Address book database model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AddressBookEntry(Base):
    """Address book entry for vendors, shops, and contacts."""

    __tablename__ = "address_book"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_name: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    zip_code: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(
        String(50)
    )  # service, insurance, parts, etc.
    notes: Mapped[str | None] = mapped_column(Text)

    # Geolocation fields for shop discovery
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(11, 8))

    # Shop discovery metadata
    source: Mapped[str] = mapped_column(
        String(20), default="manual"
    )  # 'manual' or 'google_places'
    external_id: Mapped[str | None] = mapped_column(
        String(100)
    )  # Google Place ID or other external ID

    # Ratings
    rating: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2)
    )  # Google rating (0.00 - 5.00)
    user_rating: Mapped[int | None] = mapped_column(
        Integer
    )  # User's 1-5 star rating

    # Usage tracking for recommendations
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used: Mapped[datetime | None] = mapped_column(DateTime)

    # POI (Points of Interest) categorization and metadata
    poi_category: Mapped[str | None] = mapped_column(
        String(50)
    )  # auto_shop, rv_shop, ev_charging, fuel_station
    poi_metadata: Mapped[str | None] = mapped_column(
        Text
    )  # JSON metadata for category-specific data (connector types, fuel prices, etc.)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_address_book_name", "name"),
        Index("idx_address_book_category", "category"),
        Index("idx_address_book_poi_category", "poi_category"),
    )
