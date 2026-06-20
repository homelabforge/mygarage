from __future__ import annotations

"""Per-device SD-card log ingest tracking."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class SdLogIngestState(Base):
    """Tracks which SD log DB files have been ingested, and up to what point."""

    __tablename__ = "sd_log_ingest_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    last_timestamp: Mapped[int] = mapped_column(Integer, default=0)  # max epoch-sec ingested
    rows_ingested: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)  # non-active file fully read
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("device_id", "filename", name="uq_sd_log_ingest_device_file"),
    )
