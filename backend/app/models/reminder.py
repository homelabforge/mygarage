from __future__ import annotations

"""Vehicle reminder database model."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.service_line_item import ServiceLineItem
    from app.models.vehicle import Vehicle


class Reminder(Base):
    """Vehicle reminder model for date/mileage/smart reminders."""

    __tablename__ = "vehicle_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    line_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("service_line_items.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(10), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_mileage_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="reminders")
    source_line_item: Mapped[ServiceLineItem | None] = relationship("ServiceLineItem")

    __table_args__ = (
        Index("ix_reminders_vin_status", "vin", "status"),
        Index("ix_reminders_due_date", "due_date"),
        Index("ix_reminders_due_mileage_km", "due_mileage_km"),
    )
