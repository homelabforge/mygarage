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
from app.utils.datetime_utils import utc_now

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
    # Firmware notification state (plan 2026-09-18, feature B). Stamped by the
    # daily check: notified only when at least one backend accepted the send
    # (notify-once per version); skipped is the admin's "skip this version".
    # An exact match against the latest release suppresses the notification;
    # a newer release matches neither and notifies again.
    firmware_notified_version: Mapped[str | None] = mapped_column(String(20))
    firmware_skipped_version: Mapped[str | None] = mapped_column(String(20))
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
    #: Which telemetry parameter carries THIS device's odometer.
    #:
    #: NULL means "declares nothing", the correct default and the reason
    #: existing installs are unaffected: odometer recording stays as it is.
    #:
    #: Exists because name matching does not generalise. Only a WiCAN records
    #: odometers by the ODOMETER_NAME_PATTERNS scan; every other kind records
    #: nothing until it declares a key, so a Torque-only user gets no odometer
    #: records at all without one. Rather than grow a vendor pattern list
    #: forever, a device declares its own, and that declaration REPLACES the
    #: matching rather than filtering it (see `is_recorded_odometer_key`).
    #:
    #: Pairs with `odometer_unit`: there is no unit inference outside WiCAN, so
    #: a device setting this MUST also set `odometer_unit` or its value is read
    #: as kilometres.
    odometer_param_key: Mapped[str | None] = mapped_column(String(100))

    #: Which preset created this device, or NULL for a handmade one. The
    #: integrations card names a preset-backed tab from this rather than by
    #: matching the user-editable label against a preset title.
    preset_key: Mapped[str | None] = mapped_column(String(50))

    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'wican'")
    )  # Validated by app.services.livelink_sources.registry, not a DB CHECK
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
    )  # Dead: nothing writes or reads it; kept so dropping it doesn't need a migration

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
    #: Which signal opened the pending drive. Only ``'rpm'`` is written today:
    #: a pending drive IS "engine on, nothing moving yet", and a sample above the
    #: movement floor confirms movement outright rather than opening one.
    pending_source: Mapped[str | None] = mapped_column(String(10))
    #: First of the two consecutive above-floor speed samples the debounce needs.
    movement_candidate_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: Odometer at pending open, for the odometer-increase movement signal.
    movement_baseline_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # State
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    #: The app clock as well as the server default, so the odometer-history
    #: bound compares it with telemetry timestamps on one clock (Fable F5-6).
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), default=utc_now
    )
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
