from __future__ import annotations

"""LiveLink WiCAN device model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.drive_session import DriveSession
    from app.models.vehicle import Vehicle
    from app.models.vehicle_dtc import VehicleDTC
    from app.models.vehicle_telemetry import VehicleTelemetry


class LiveLinkDevice(Base):
    """WiCAN OBD2 device model for LiveLink integration."""

    __tablename__ = "livelink_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )  # 12-char hex from MAC
    vin: Mapped[str | None] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="SET NULL"), nullable=True
    )  # NULL = unlinked
    label: Mapped[str | None] = mapped_column(String(100))  # User-friendly name

    # Device info from payload status block
    hw_version: Mapped[str | None] = mapped_column(String(50))  # e.g., "WiCAN-OBD-PRO"
    fw_version: Mapped[str | None] = mapped_column(String(20))  # e.g., "4.45"
    git_version: Mapped[str | None] = mapped_column(String(20))  # e.g., "v4.45p"
    sta_ip: Mapped[str | None] = mapped_column(String(45))  # Device IP for local UI link
    rssi: Mapped[int | None] = mapped_column(Integer)  # WiFi signal strength
    battery_voltage: Mapped[float | None] = mapped_column(Float)  # Vehicle battery from device

    # Status tracking (separate ECU vs device status per spec)
    ecu_status: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )  # online/offline/unknown (vehicle ECU)
    device_status: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )  # online/offline/unknown (WiCAN itself)

    # Token and dedup
    device_token_hash: Mapped[str | None] = mapped_column(
        String(128)
    )  # Per-device token hash (NULL = uses global)
    last_payload_hash: Mapped[str | None] = mapped_column(
        String(64)
    )  # Hash of last autopid_data for dedup

    # Session tracking
    current_session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("drive_sessions.id", ondelete="SET NULL")
    )

    # State
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    # Relationships
    vehicle: Mapped[Vehicle | None] = relationship("Vehicle", foreign_keys=[vin])
    current_session: Mapped[DriveSession | None] = relationship(
        "DriveSession", foreign_keys=[current_session_id]
    )
    telemetry_records: Mapped[list[VehicleTelemetry]] = relationship(
        "VehicleTelemetry",
        back_populates="device",
        foreign_keys="[VehicleTelemetry.device_id]",
        primaryjoin="LiveLinkDevice.device_id == foreign(VehicleTelemetry.device_id)",
    )
    drive_sessions: Mapped[list[DriveSession]] = relationship(
        "DriveSession",
        back_populates="device",
        foreign_keys="[DriveSession.device_id]",
        primaryjoin="LiveLinkDevice.device_id == foreign(DriveSession.device_id)",
    )
    dtcs: Mapped[list[VehicleDTC]] = relationship(
        "VehicleDTC",
        back_populates="device",
        foreign_keys="[VehicleDTC.device_id]",
        primaryjoin="LiveLinkDevice.device_id == foreign(VehicleDTC.device_id)",
    )

    __table_args__ = (
        Index("idx_livelink_devices_vin", "vin"),
        Index("idx_livelink_devices_status", "device_status"),
        Index("idx_livelink_devices_last_seen", "last_seen"),
    )
