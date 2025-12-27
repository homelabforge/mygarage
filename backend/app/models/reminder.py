"""Reminder database model."""

from sqlalchemy import String, Integer, Date, DateTime, Text, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional

from app.database import Base


class Reminder(Base):
    """Maintenance reminder model."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    due_mileage: Mapped[Optional[int]] = mapped_column(Integer)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_days: Mapped[Optional[int]] = mapped_column(Integer)
    recurrence_miles: Mapped[Optional[int]] = mapped_column(Integer)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="reminders")

    __table_args__ = (
        Index("idx_reminders_vin", "vin"),
        Index("idx_reminders_due_date", "due_date"),
        Index("idx_reminders_completed", "is_completed"),
    )


from app.models.vehicle import Vehicle
