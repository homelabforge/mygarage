from __future__ import annotations

"""Maps an exact MQTT topic to a telemetry parameter.

This is what lets a device be added from the UI with no code. Topics are
EXACT, never wildcards: subscriptions are then just the distinct topic values,
dispatch is a dict lookup at 79,000 messages/day, and there is no way to
configure a `#` that firehoses the broker into the database.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.models._types import ScaledNumeric


class LiveLinkTopicMap(Base):
    """One topic to one parameter."""

    __tablename__ = "livelink_topic_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: No ForeignKey, matching every other LiveLink child table. Cleanup is
    #: explicit in LiveLinkService.delete_device.
    device_id: Mapped[str] = mapped_column(String(20), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 'telemetry' stores a Reading; 'status' sets the device online/offline.
    role: Mapped[str] = mapped_column(String(12), nullable=False, default="telemetry")
    #: NULL only when role='status'.
    param_key: Mapped[str | None] = mapped_column(String(100))
    #: NULL means the payload IS the value (a bare scalar, as ESPHome sends).
    #: Otherwise a dotted path into a JSON payload, e.g. "battery.voltage".
    value_path: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(20))
    param_class: Mapped[str | None] = mapped_column(String(50))
    #: value = raw * scale + value_offset
    scale: Mapped[Decimal] = mapped_column(ScaledNumeric(12, 6), nullable=False, default=1)
    value_offset: Mapped[Decimal] = mapped_column(ScaledNumeric(12, 6), nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("topic", "param_key", name="uq_topic_maps_topic_param"),
        Index("idx_topic_maps_device", "device_id"),
    )
