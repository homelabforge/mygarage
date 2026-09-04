from __future__ import annotations

"""Vehicle reminder database model."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.service_line_item import ServiceLineItem
    from app.models.vehicle import Vehicle


class Reminder(Base):
    """Vehicle reminder model for date/mileage/smart reminders."""

    __tablename__ = "vehicle_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    line_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("service_line_items.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(10), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_mileage_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Hours target for reminder_type='hours' (hour-metered vehicles). Migration 083.
    due_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 1), nullable=True)
    # Which tire this reminder is about, for tire-sourced reminders (097).
    # Part of a COMPOSITE FK to `tires (id, vin)` declared in __table_args__,
    # so a reminder cannot name a tire belonging to a different vehicle.
    #
    # That FK deliberately carries NO `ON DELETE` action. A referential action
    # applies to every column in the FK, so SET NULL would try to null `vin`
    # too -- and `vin` is NOT NULL, which makes SQLite reject the tire deletion
    # outright. The service nulls `tire_id` explicitly in the same transaction
    # as the delete instead, which keeps the reminder as history.
    tire_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What created this reminder: 'low_tread' for the tire sync, NULL for a
    # reminder a human made. The sync never adopts a row whose source is NULL.
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Canonical snapshots taken when a low-tread reminder was raised, so the
    # notification can say what it saw without re-deriving it later.
    tread_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    tread_threshold_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    projected_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="reminders")
    source_line_item: Mapped[ServiceLineItem | None] = relationship("ServiceLineItem")

    __table_args__ = (
        # Declared in the TABLE-level form on purpose: SQLAlchemy's SQLite
        # reflection parses `ON DELETE` only out of this form, so an inline
        # declaration reflects as `options: {}` and diverges from create_all
        # (measured in migration 094).
        ForeignKeyConstraint(
            ["tire_id", "vin"], ["tires.id", "tires.vin"], name="fk_reminders_tire_vin"
        ),
        # All three CHECKs, matching what migration 083 wrote. The ORM declared
        # NONE of them before v3.3.0, so a `create_all` database had zero while
        # a migrated one had three -- a divergence that let the legacy JSON
        # importer write a negative `due_mileage_km` on fresh installs only.
        CheckConstraint(
            "reminder_type IN ('date','mileage','both','smart','hours')",
            name="check_reminder_type",
        ),
        CheckConstraint("status IN ('pending','done','dismissed')", name="check_reminder_status"),
        CheckConstraint(
            "due_mileage_km IS NULL OR due_mileage_km > 0", name="check_due_mileage_km"
        ),
        Index("ix_reminders_vin_status", "vin", "status"),
        Index("ix_reminders_due_date", "due_date"),
        Index("ix_reminders_due_mileage_km", "due_mileage_km"),
    )
