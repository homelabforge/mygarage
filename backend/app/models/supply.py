from __future__ import annotations

"""Parts & supplies (light inventory) models: catalog + stock-in/out ledgers."""

import datetime as dt
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, true

from app.database import Base

if TYPE_CHECKING:
    from app.models.service_line_item import ServiceLineItem


class Supply(Base):
    """A reusable part or supply item. On-hand and avg cost are ledger-derived."""

    __tablename__ = "supplies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(60))
    category: Mapped[str | None] = mapped_column(String(40))
    unit_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'volume' | 'count'
    vin: Mapped[str | None] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE")
    )  # NULL = shared across all vehicles; set = pinned to one
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    # server_default (not just Python default=True): create_all runs BEFORE the migration
    # runner on a fresh boot, so the deployed schema must carry the default itself. true()
    # is dialect-safe — renders DEFAULT 1 on SQLite, DEFAULT true on PostgreSQL (R1-F3).
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )  # provenance only, not an access wall
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    purchases: Mapped[list[SupplyPurchase]] = relationship(
        "SupplyPurchase", back_populates="supply", cascade="all, delete-orphan"
    )
    usages: Mapped[list[SupplyUsage]] = relationship(
        "SupplyUsage", back_populates="supply", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("unit_type IN ('volume', 'count')", name="check_supply_unit_type"),
        Index("idx_supplies_vin", "vin"),
    )


class SupplyPurchase(Base):
    """Stock-IN ledger row. 'Opening stock' is just a purchase (cost optional)."""

    __tablename__ = "supply_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supply_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("supplies.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)  # canonical
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("address_book.id", ondelete="SET NULL")
    )
    part_number: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    supply: Mapped[Supply] = relationship("Supply", back_populates="purchases")

    __table_args__ = (Index("idx_supply_purchases_supply_date", "supply_id", "date"),)


class SupplyUsage(Base):
    """Stock-OUT ledger row. Tied to a service line item, or standalone (adjustment)."""

    __tablename__ = "supply_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supply_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("supplies.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)  # canonical
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    service_line_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("service_line_items.id", ondelete="CASCADE")
    )  # NULL = standalone adjustment
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    supply: Mapped[Supply] = relationship("Supply", back_populates="usages")
    line_item: Mapped[ServiceLineItem | None] = relationship(
        "ServiceLineItem", back_populates="supply_usages"
    )

    __table_args__ = (
        Index("idx_supply_usages_supply", "supply_id"),
        Index("idx_supply_usages_line_item", "service_line_item_id"),
    )
