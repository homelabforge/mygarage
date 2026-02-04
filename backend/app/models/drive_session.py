from __future__ import annotations

"""Drive session model for LiveLink ECU status tracking."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.livelink_device import LiveLinkDevice
    from app.models.vehicle import Vehicle


class DriveSession(Base):
    """Drive sessions detected from ECU status transitions.

    Sessions are created when ECU goes online and closed when:
    1. ECU goes offline (normal end)
    2. No data received for timeout period (connection lost)

    Aggregates are calculated on session end.
    """

    __tablename__ = "drive_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(20), nullable=False)

    # Session timing
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    # Odometer capture
    start_odometer: Mapped[float | None] = mapped_column(Float)  # Captured at session start
    end_odometer: Mapped[float | None] = mapped_column(Float)  # Captured at session end
    distance_km: Mapped[float | None] = mapped_column(Float)  # From odometer delta or speed*time

    # Session aggregates (calculated on session end)
    avg_speed: Mapped[float | None] = mapped_column(Float)
    max_speed: Mapped[float | None] = mapped_column(Float)
    avg_rpm: Mapped[float | None] = mapped_column(Float)
    max_rpm: Mapped[float | None] = mapped_column(Float)
    avg_coolant_temp: Mapped[float | None] = mapped_column(Float)
    max_coolant_temp: Mapped[float | None] = mapped_column(Float)
    avg_throttle: Mapped[float | None] = mapped_column(Float)
    max_throttle: Mapped[float | None] = mapped_column(Float)

    # Fuel metrics (if available)
    avg_fuel_level: Mapped[float | None] = mapped_column(Float)  # Percentage
    fuel_used_estimate: Mapped[float | None] = mapped_column(Float)  # Liters (estimated)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", foreign_keys=[vin])
    device: Mapped[LiveLinkDevice] = relationship(
        "LiveLinkDevice",
        foreign_keys=[device_id],
        primaryjoin="DriveSession.device_id == LiveLinkDevice.device_id",
        back_populates="drive_sessions",
    )

    __table_args__ = (
        Index("idx_sessions_vehicle_time", "vin", "started_at"),
        Index("idx_sessions_device", "device_id", "started_at"),
        Index("idx_sessions_ended", "ended_at"),
    )
