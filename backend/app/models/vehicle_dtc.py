from __future__ import annotations

"""Vehicle DTC (Diagnostic Trouble Code) tracking model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.livelink_device import LiveLinkDevice
    from app.models.vehicle import Vehicle


class VehicleDTC(Base):
    """Active and historical DTCs per vehicle.

    DTCs are created when detected in WiCAN telemetry.
    is_active tracks current state; cleared_at records when manually cleared.
    """

    __tablename__ = "vehicle_dtcs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(20), nullable=False)

    # DTC info
    code: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g., "P0657"
    description: Mapped[str | None] = mapped_column(
        Text
    )  # Pulled from dtc_definitions, user-editable for manufacturer-specific
    severity: Mapped[str] = mapped_column(String(20), default="warning")

    # User notes
    user_notes: Mapped[str | None] = mapped_column(Text)  # User-editable notes field

    # Timestamps
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime)

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", foreign_keys=[vin])
    device: Mapped[LiveLinkDevice] = relationship(
        "LiveLinkDevice",
        foreign_keys=[device_id],
        primaryjoin="VehicleDTC.device_id == LiveLinkDevice.device_id",
        back_populates="dtcs",
    )

    __table_args__ = (
        Index("idx_dtcs_vehicle_active", "vin", "is_active"),
        Index("idx_dtcs_vehicle_code", "vin", "code"),
        Index("idx_dtcs_device", "device_id"),
        Index("idx_dtcs_first_seen", "first_seen"),
    )
