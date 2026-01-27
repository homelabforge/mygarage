from __future__ import annotations

"""Reminder database model."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Reminder(Base):
    """Maintenance reminder model."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_mileage: Mapped[int | None] = mapped_column(Integer)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_days: Mapped[int | None] = mapped_column(Integer)
    recurrence_miles: Mapped[int | None] = mapped_column(Integer)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="reminders")

    __table_args__ = (
        Index("idx_reminders_vin", "vin"),
        Index("idx_reminders_due_date", "due_date"),
        Index("idx_reminders_completed", "is_completed"),
    )


from app.models.vehicle import Vehicle
