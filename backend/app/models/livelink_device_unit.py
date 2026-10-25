"""The units a LiveLink device declared on the wire, kept per device (R12).

WiCAN sends its `config` (unit and class per key) once per cold boot, and the
in-memory map in `app.services.declared_units` is gone after a restart, so a
MyGarage restart mid-drive used to forget every declared unit. A row here is a
device's latest declaration for one canonical key.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

#: Declared by the device itself.
SOURCE_WIRE = "wire"
#: Recorded by migration 133 from how main used to read a key; a `wire`
#: declaration doesn't replace it for an odometer key with history.
SOURCE_LEGACY = "legacy"


class LiveLinkDeviceUnit(Base):
    """One declared unit and class for one key on one device."""

    __tablename__ = "livelink_device_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Unlike the history tables, a declaration is the device's own config, so
    #: it goes with the device.
    device_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("livelink_devices.device_id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Canonical (`canonical_param_key`).
    param_key: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    param_class: Mapped[str | None] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(10), nullable=False, default=SOURCE_WIRE)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("device_id", "param_key", name="uq_livelink_device_units_device_param"),
        CheckConstraint("source IN ('wire', 'legacy')", name="check_livelink_device_units_source"),
    )
