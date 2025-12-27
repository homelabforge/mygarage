"""Recall database model."""

from sqlalchemy import String, Integer, Date, DateTime, Text, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional

from app.database import Base


class Recall(Base):
    """NHTSA recall model."""

    __tablename__ = "recalls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    nhtsa_campaign_number: Mapped[Optional[str]] = mapped_column(String(20))
    component: Mapped[Optional[str]] = mapped_column(String(100))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    consequence: Mapped[Optional[str]] = mapped_column(Text)
    remedy: Mapped[Optional[str]] = mapped_column(Text)
    date_announced: Mapped[Optional[date]] = mapped_column(Date)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="recalls")

    __table_args__ = (
        Index("idx_recalls_vin", "vin"),
        Index("idx_recalls_resolved", "is_resolved"),
    )


from app.models.vehicle import Vehicle
