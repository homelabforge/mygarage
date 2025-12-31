"""Toll tag and transaction models for tracking toll road usage."""

import datetime as dt
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import String, Integer, Date, Numeric, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class TollTag(Base):
    """Toll tag/transponder associated with a vehicle."""

    __tablename__ = "toll_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    toll_system: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 'EZ TAG', 'TxTag', 'E-ZPass', etc.
    tag_number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # 'active', 'inactive'
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now()
    )

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="toll_tags")
    transactions: Mapped[list["TollTransaction"]] = relationship(
        "TollTransaction", back_populates="toll_tag", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_toll_tags_vin", "vin"),
        Index("idx_toll_tags_tag_number", "tag_number"),
    )


class TollTransaction(Base):
    """Individual toll transaction record."""

    __tablename__ = "toll_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    toll_tag_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("toll_tags.id", ondelete="SET NULL")
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle", back_populates="toll_transactions"
    )
    toll_tag: Mapped[Optional["TollTag"]] = relationship(
        "TollTag", back_populates="transactions"
    )

    __table_args__ = (
        Index("idx_toll_transactions_vin", "vin"),
        Index("idx_toll_transactions_date", "date"),
        Index("idx_toll_transactions_toll_tag_id", "toll_tag_id"),
    )


from app.models.vehicle import Vehicle
