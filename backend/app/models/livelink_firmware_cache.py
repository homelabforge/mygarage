from __future__ import annotations

"""LiveLink firmware version cache model."""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class LiveLinkFirmwareCache(Base):
    """Cached WiCAN firmware release information from GitHub API.

    Updated daily by the firmware check background task.
    One row per firmware track (``obd``/``pro``), keyed by the unique ``track`` column.
    """

    __tablename__ = "livelink_firmware_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    track: Mapped[str | None] = mapped_column(String(10))  # "obd" | "pro"
    latest_version: Mapped[str | None] = mapped_column(String(20))  # e.g., "4.50"
    latest_tag: Mapped[str | None] = mapped_column(String(20))  # e.g., "v4.50p"
    release_url: Mapped[str | None] = mapped_column(Text)  # GitHub release URL
    release_notes: Mapped[str | None] = mapped_column(Text)  # Release notes/changelog
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_livelink_firmware_cache_track", "track", unique=True),)
