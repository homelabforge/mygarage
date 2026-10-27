from __future__ import annotations

"""Per-vehicle maintenance rule: WHEN a maintenance item recurs.

A rule is the interval side of the lifecycle (pack/rule -> service -> reminder).
It carries no "last performed" state: the anchor a reminder counts from lives
on the reminder itself (`vehicle_reminders.anchor_*`), so a rule can never
disagree with the reminder it generated. Migration 028 kept `last_performed_*`
on the schedule item and 049 dropped the table; this does not repeat that.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models._types import ScaledNumeric

if TYPE_CHECKING:
    from app.models.reminder import Reminder
    from app.models.vehicle import Vehicle


class MaintenanceRule(Base):
    """One recurring maintenance schedule on one vehicle.

    `maintenance_type` is a code from `app.utils.maintenance_types` (or one a
    pack declared). NULL means the rule is typeless: it never matches a
    service by type and only advances through the completion dialog.

    `source` says where the rule came from: 'pack' (with `source_pack_id` and
    `source_pack_key`), 'manual' (the reminder form) or 'service' (a line
    item's recurrence). A rule made from a pack is the vehicle's own copy: its
    intervals may be edited without touching the pack, and re-applying the
    pack leaves an existing rule of the same type alone. The one exception is an
    interval the caller retypes while applying, which is their instruction and
    overwrites this rule (see `maintenance_service._plan_item`).

    Exactly one usage interval (`interval_km` or `interval_hours`) may be set
    alongside the calendar interval; the request schemas enforce that, the
    database only requires at least one interval and positive values.
    """

    __tablename__ = "vehicle_maintenance_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    maintenance_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    interval_km: Mapped[Decimal | None] = mapped_column(ScaledNumeric(10, 2), nullable=True)
    interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_hours: Mapped[Decimal | None] = mapped_column(ScaledNumeric(10, 1), nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_pack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_pack_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="maintenance_rules")
    reminders: Mapped[list[Reminder]] = relationship("Reminder", back_populates="rule")

    __table_args__ = (
        CheckConstraint("interval_km IS NULL OR interval_km > 0", name="check_rule_interval_km"),
        CheckConstraint(
            "interval_months IS NULL OR interval_months > 0", name="check_rule_interval_months"
        ),
        CheckConstraint(
            "interval_days IS NULL OR interval_days > 0", name="check_rule_interval_days"
        ),
        CheckConstraint(
            "interval_hours IS NULL OR interval_hours > 0", name="check_rule_interval_hours"
        ),
        CheckConstraint(
            "interval_km IS NOT NULL OR interval_months IS NOT NULL "
            "OR interval_days IS NOT NULL OR interval_hours IS NOT NULL",
            name="check_rule_has_interval",
        ),
        Index("ix_maintenance_rules_vin_type", "vin", "maintenance_type"),
    )
