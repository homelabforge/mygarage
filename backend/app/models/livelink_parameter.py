from __future__ import annotations

"""LiveLink parameter model for auto-discovered telemetry PIDs."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class LiveLinkParameter(Base):
    """Auto-discovered telemetry parameter from WiCAN config block.

    Parameters are auto-registered when new keys appear in autopid_data.
    Users control display settings and thresholds, but all data is always stored.
    """

    __tablename__ = "livelink_parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    param_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )  # e.g., "ENGINE_RPM", "COOLANT_TMP"

    # Display settings (user-editable)
    display_name: Mapped[str | None] = mapped_column(String(100))  # Friendly name for UI
    unit: Mapped[str | None] = mapped_column(String(20))  # From config.{key}.unit
    param_class: Mapped[str | None] = mapped_column(
        String(50)
    )  # From config.{key}.class (temperature, speed, etc.)
    category: Mapped[str | None] = mapped_column(
        String(50)
    )  # engine, fuel, temperature, electrical, etc.
    icon: Mapped[str | None] = mapped_column(String(50))  # Optional icon identifier for frontend

    # Alert thresholds (ntfy notifications)
    warning_min: Mapped[float | None] = mapped_column(Float)  # Alert if value drops below
    warning_max: Mapped[float | None] = mapped_column(Float)  # Alert if value exceeds

    # Display control
    display_order: Mapped[int] = mapped_column(Integer, default=0)  # User-configurable gauge order
    show_on_dashboard: Mapped[bool] = mapped_column(Boolean, default=True)  # Show in live gauges
    archive_only: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Hidden from default views, still stored

    # Storage control
    storage_interval_seconds: Mapped[int] = mapped_column(
        Integer, default=0
    )  # Minimum seconds between persisted values (0 = store all)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    __table_args__ = (
        Index("idx_livelink_params_category", "category"),
        Index("idx_livelink_params_class", "param_class"),
        Index("idx_livelink_params_order", "display_order"),
    )
