"""Technical Service Bulletin (TSB) database model."""

from sqlalchemy import String, Integer, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional

from app.database import Base


class TSB(Base):
    """
    Tracks Technical Service Bulletins (TSBs) for vehicles.

    TSBs are manufacturer-issued documents describing known issues and fixes.
    Unlike recalls (which are mandatory), TSBs are informational and may or
    may not be covered under warranty.
    """

    __tablename__ = "tsbs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )

    # TSB identification
    tsb_number: Mapped[Optional[str]] = mapped_column(
        String(50)
    )  # e.g., "21-034-19" or "TSB-123456"
    component: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # Component/system affected (e.g., "Transmission", "Engine")
    summary: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # Description of the issue

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, acknowledged, applied, not_applicable, ignored
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime
    )  # When TSB fix was applied

    # Link to service record if TSB was addressed
    related_service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("service_records.id", ondelete="SET NULL")
    )

    # Source tracking
    source: Mapped[str] = mapped_column(
        String(50), default="manual"
    )  # "manual" or "nhtsa"

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, onupdate=func.now()
    )

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="tsbs")
    related_service: Mapped[Optional["ServiceRecord"]] = relationship(
        "ServiceRecord", foreign_keys=[related_service_id]
    )

    __table_args__ = (
        Index("idx_tsbs_vin", "vin"),
        Index("idx_tsbs_status", "status"),
        Index("idx_tsbs_tsb_number", "tsb_number"),
    )


# Import at the end to avoid circular imports
from app.models.vehicle import Vehicle  # noqa: E402
from app.models.service import ServiceRecord  # noqa: E402
