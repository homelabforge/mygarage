from __future__ import annotations

"""Drive session model for LiveLink ECU status tracking."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, text
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

    # Driving insights (computed on session end from SPEED samples)
    idle_seconds: Mapped[int | None] = mapped_column(Integer)
    harsh_accel_count: Mapped[int | None] = mapped_column(Integer)
    harsh_brake_count: Mapped[int | None] = mapped_column(Integer)

    # True movement bounds, distinct from the contact window above.
    #
    # `started_at`/`ended_at` are the first and last sample of the CONTACT
    # burst, which is what every aggregate is computed from -- narrowing them to
    # the first movement sample would drop warm-up coolant, initial fuel level
    # and, critically, the OPENING ODOMETER READING, leaving a window with one
    # odometer sample and a confident `distance_km = 0.0`. These two record when
    # the vehicle actually moved. NULL means "unknown", not "did not move":
    # every session predating migration 098 has no answer.
    movement_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    movement_ended_at: Mapped[datetime | None] = mapped_column(DateTime)

    # How this session's boundaries were decided. 0 = pre-098 semantics, cut on
    # contact; 1 = the movement predicate. Torque sessions stay 0 because their
    # boundaries come from the phone, not from this algorithm, and stamping them
    # 1 would claim a provenance they do not have.
    #
    # Every constructor must set this. Defaulting new rows to 0 would make them
    # masquerade as pre-098 history, which any later pass over history would
    # then skip as already-correct.
    boundary_algorithm_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    #: The gap threshold in force when this session was cut. NULL means the old
    #: contact timeout applied.
    effective_gap_minutes: Mapped[int | None] = mapped_column(Integer)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Torque ingest
    external_session_id: Mapped[str | None] = mapped_column(
        String(64)
    )  # e.g. Torque `session` id; NULL for WiCAN

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
        Index("uq_drive_session_external", "device_id", "external_session_id", unique=True),
        # One OPEN session per device, as a constraint rather than a convention.
        # Two concurrent first-movement payloads (MQTT and HTTPS can race) both
        # read a NULL `current_session_id`, both create; one wins the pointer and
        # the other is orphaned open forever. Partial, so the second and every
        # later CLOSED session of a device stay legal.
        Index(
            "uq_drive_sessions_open_per_device",
            "device_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL"),
            postgresql_where=text("ended_at IS NULL"),
        ),
    )
