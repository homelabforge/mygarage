from __future__ import annotations

"""LiveLink WiCAN device model."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
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
    device_address: Mapped[str | None] = mapped_column(
        String(255)
    )  # admin-set IP/host for SD pulls
    sd_backfill_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Units the device reports its odometer in. NULL = infer from the param key
    # shape (see app/utils/odometer_units.py): the standard SAE J1979 PID
    # 'A6-ODOMETER' is metric, a bare 'ODOMETER' autopid is a user-defined CAN
    # expression and is usually miles on a US-market car. The inference is only
    # a default — hardware varies, so an explicit value always wins.
    odometer_unit: Mapped[str | None] = mapped_column(String(4))  # 'km' | 'mi' | None
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'wican'")
    )  # 'wican' | 'torque'
    torque_device_id: Mapped[str | None] = mapped_column(
        String(40)
    )  # Torque's raw 32-hex id (kind='torque' only)
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

    # Session grace period (WiFi drop resilience)
    pending_offline_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Movement state (migration 098). Durable, per device, and never in process
    # memory: the MQTT subscriber, the HTTPS route and the scheduler are three
    # execution contexts, so an in-memory candidate is invisible to two of them
    # and is lost on every restart -- which silently converts "keep the warm-up
    # samples" into "drop them" every time the container cycles.
    #
    # Scoped per DEVICE, never per VIN: a vehicle carrying both a WiCAN dongle
    # and a Torque phone would otherwise let one source confirm the other's
    # pending drive.
    #
    # All four pending fields reset together — on promotion to a session, on
    # expiry past the drive gap, and when an explicit offline FINALIZES (not
    # when it arrives, or a brief WiFi drop inside the grace period would
    # discard the warm-up samples this state exists to preserve).
    last_movement_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    #: Engine on, nothing moving yet. NULL = no pending drive.
    pending_since: Mapped[datetime | None] = mapped_column(DateTime)
    #: Which signal opened the pending drive: 'rpm' or 'speed'.
    pending_source: Mapped[str | None] = mapped_column(String(10))
    #: First of the two consecutive above-floor speed samples the debounce needs.
    movement_candidate_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: Odometer at pending open, for the odometer-increase movement signal.
    movement_baseline_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

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
    # `passive_deletes=True` on all three: deleting a device must NOT touch its
    # history. Without it SQLAlchemy's default is to load the children and NULL
    # their `device_id` on parent delete — but that column is `nullable=False`
    # on telemetry, sessions and DTCs alike, so every delete of a device that
    # had ever reported anything died with
    #   IntegrityError: NOT NULL constraint failed: vehicle_telemetry.device_id
    # i.e. a 500 from both the Torque-source revoke route and the admin device
    # delete. Retaining the rows is the documented intent (see
    # LiveLinkService.delete_device) — a user revoking a phone should not lose
    # their driving history — and none of these columns carries a ForeignKey,
    # so there is no database-level rule being deferred to here either.
    telemetry_records: Mapped[list[VehicleTelemetry]] = relationship(
        "VehicleTelemetry",
        back_populates="device",
        foreign_keys="[VehicleTelemetry.device_id]",
        primaryjoin="LiveLinkDevice.device_id == foreign(VehicleTelemetry.device_id)",
        passive_deletes=True,
    )
    drive_sessions: Mapped[list[DriveSession]] = relationship(
        "DriveSession",
        back_populates="device",
        foreign_keys="[DriveSession.device_id]",
        primaryjoin="LiveLinkDevice.device_id == foreign(DriveSession.device_id)",
        passive_deletes=True,
    )
    dtcs: Mapped[list[VehicleDTC]] = relationship(
        "VehicleDTC",
        back_populates="device",
        foreign_keys="[VehicleDTC.device_id]",
        primaryjoin="LiveLinkDevice.device_id == foreign(VehicleDTC.device_id)",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_livelink_devices_vin", "vin"),
        Index("idx_livelink_devices_status", "device_status"),
        Index("idx_livelink_devices_last_seen", "last_seen"),
    )
