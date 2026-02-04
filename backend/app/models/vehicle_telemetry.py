from __future__ import annotations

"""Vehicle telemetry models for LiveLink time-series data."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.livelink_device import LiveLinkDevice
    from app.models.vehicle import Vehicle


class VehicleTelemetry(Base):
    """Historical telemetry time-series data.

    Stores parameter values respecting storage_interval_seconds.
    For high-frequency live data, use VehicleTelemetryLatest instead.
    """

    __tablename__ = "vehicle_telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(20), nullable=False)  # From status.device_id
    param_key: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # References livelink_parameters.param_key
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )  # Device-reported or derived
    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )  # Server receive time

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", foreign_keys=[vin])
    device: Mapped[LiveLinkDevice] = relationship(
        "LiveLinkDevice",
        foreign_keys=[device_id],
        primaryjoin="VehicleTelemetry.device_id == LiveLinkDevice.device_id",
        back_populates="telemetry_records",
    )

    __table_args__ = (
        # Indexes for efficient time-range queries
        Index("idx_telemetry_vehicle_time", "vin", "timestamp"),
        Index("idx_telemetry_param_time", "vin", "param_key", "timestamp"),
        Index("idx_telemetry_device", "device_id", "timestamp"),
        # Idempotency index: prevent duplicate rows from retries
        UniqueConstraint("device_id", "param_key", "timestamp", name="uq_telemetry_dedup"),
    )


class VehicleTelemetryLatest(Base):
    """Latest telemetry values cache for fast dashboard lookups.

    Updated via upsert on every ingestion, regardless of storage_interval_seconds.
    This powers the live dashboard with O(1) lookups per parameter.
    """

    __tablename__ = "vehicle_telemetry_latest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    param_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", foreign_keys=[vin])

    __table_args__ = (
        UniqueConstraint("vin", "param_key", name="uq_telemetry_latest_vin_param"),
        Index("idx_telemetry_latest_vehicle", "vin"),
    )


class TelemetryDailySummary(Base):
    """Daily aggregated telemetry for long-term charts.

    Populated by the daily aggregation job. Survives raw data retention cleanup.
    """

    __tablename__ = "telemetry_daily_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    param_key: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )  # Date at midnight UTC for this aggregate
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    avg_value: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # Raw readings count

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", foreign_keys=[vin])

    __table_args__ = (
        UniqueConstraint("vin", "param_key", "date", name="uq_daily_summary_vin_param_date"),
        Index("idx_daily_summary_vehicle_date", "vin", "date"),
        Index("idx_daily_summary_param", "vin", "param_key", "date"),
    )
