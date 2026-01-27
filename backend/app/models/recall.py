from __future__ import annotations

"""Recall database model."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class Recall(Base):
    """NHTSA recall model."""

    __tablename__ = "recalls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    nhtsa_campaign_number: Mapped[str | None] = mapped_column(String(20))
    component: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    consequence: Mapped[str | None] = mapped_column(Text)
    remedy: Mapped[str | None] = mapped_column(Text)
    date_announced: Mapped[date | None] = mapped_column(Date)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="recalls")

    __table_args__ = (
        Index("idx_recalls_vin", "vin"),
        Index("idx_recalls_resolved", "is_resolved"),
    )


from app.models.vehicle import Vehicle
