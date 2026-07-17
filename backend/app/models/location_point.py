"""GPS breadcrumb points for Torque-sourced drives (#118)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LocationPoint(Base):
    __tablename__ = "location_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    drive_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("drive_sessions.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)  # 'torque' (only v1 source)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    speed: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # km/h (canonical)
    heading: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))  # degrees
    altitude: Mapped[Decimal | None] = mapped_column(Numeric(7, 1))  # metres
    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_location_points_vin_time", "vin", "timestamp"),
        Index("idx_location_points_session", "drive_session_id"),
        UniqueConstraint("vin", "timestamp", "source", name="uq_location_points_dedup"),
    )
