from __future__ import annotations

"""Saved reminder packs: a vehicle's schedule, named and reusable.

The built-in packs are JSON files under `app/data/reminder_packs/` and stay
that way: they are shipped content, reviewed in git, and importing them into
these tables would fork them from the files on the next release. These tables
hold only what a user saved.

A pack item's columns are deliberately the same types as
`vehicle_maintenance_rules`, because every value here was projected out of that
table and goes back into it when the pack is applied. What a pack CANNOT carry
is not a storage limit: `maintenance_service` resolves a pack item to a rule by
`maintenance_type`, so a typeless rule and the second rule of a repeated type
are refused when the pack is saved rather than silently reshaped. See
`reminder_pack_service.unsavable_reason`.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models._types import ScaledNumeric

if TYPE_CHECKING:
    from app.models.user import User


class ReminderPack(Base):
    """One saved pack, visible to every user of the instance.

    `pack_id` is the id the API speaks, always `custom-<slug>`, and it shares a
    namespace with the built-in packs' filenames. The prefix is what makes a
    collision with a shipped file impossible rather than merely checked, and it
    is stable across a rename so rules already created keep resolving through
    `vehicle_maintenance_rules.source_pack_id`.

    `created_by_user_id` is nullable on purpose: it is NULL for a pack saved
    while `auth_mode='none'`, and ON DELETE SET NULL keeps a departing user's
    pack in the household rather than deleting the standard everyone applies.
    A NULL creator is admin-only to change, because nobody can prove they made
    it.
    """

    __tablename__ = "reminder_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pack_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    #: Vehicle types this pack offers itself for; an empty list means every type.
    #: One column rather than a child table: it is read only as a whole, never
    #: joined or filtered on in SQL.
    #:
    #: A real `JSON` column, so the list arrives as a list and no caller spells
    #: `json.dumps`/`json.loads` around it. `JSON` is the generic type on
    #: purpose: it emits `JSON` on both dialects, where PostgreSQL's `JSONB`
    #: would not compile on SQLite, and SQLite gives it TEXT affinity and stores
    #: the same bytes the old `Text` column did.
    #:
    #: Assign a new list to change it. There is no `MutableList` wrapper, so an
    #: in-place `append` would not be seen by the flush -- the same contract as
    #: `Vehicle.standard_equipment` and every other JSON column here.
    vehicle_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, server_default="[]")
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    created_by: Mapped[User | None] = relationship("User")
    items: Mapped[list[ReminderPackItemRow]] = relationship(
        "ReminderPackItemRow",
        back_populates="pack",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ReminderPackItemRow.sort_order",
    )


class ReminderPackItemRow(Base):
    """One maintenance rule template inside a saved pack.

    Named `...Row` to keep it apart from `schemas.reminder_pack.ReminderPackItem`,
    which is the same data on the wire and is what the apply pipeline consumes.

    The CHECK constraints mirror `vehicle_maintenance_rules` so the table cannot
    hold what `ReminderPackItem` refuses, and add the distance-versus-hours rule
    that the rule table leaves to its request schema: both ends of this table are
    ours, so it belongs here.
    """

    __tablename__ = "reminder_pack_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pack_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reminder_packs.id", ondelete="CASCADE"), nullable=False
    )
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    maintenance_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    interval_km: Mapped[Decimal | None] = mapped_column(ScaledNumeric(10, 2), nullable=True)
    interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_hours: Mapped[Decimal | None] = mapped_column(ScaledNumeric(10, 1), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    pack: Mapped[ReminderPack] = relationship("ReminderPack", back_populates="items")

    __table_args__ = (
        UniqueConstraint("pack_id", "item_key", name="uq_reminder_pack_item"),
        CheckConstraint(
            "interval_km IS NULL OR interval_km > 0", name="check_pack_item_interval_km"
        ),
        CheckConstraint(
            "interval_months IS NULL OR interval_months > 0",
            name="check_pack_item_interval_months",
        ),
        CheckConstraint(
            "interval_days IS NULL OR interval_days > 0", name="check_pack_item_interval_days"
        ),
        CheckConstraint(
            "interval_hours IS NULL OR interval_hours > 0", name="check_pack_item_interval_hours"
        ),
        CheckConstraint(
            "interval_km IS NOT NULL OR interval_months IS NOT NULL "
            "OR interval_days IS NOT NULL OR interval_hours IS NOT NULL",
            name="check_pack_item_has_interval",
        ),
        CheckConstraint(
            "interval_km IS NULL OR interval_hours IS NULL",
            name="check_pack_item_distance_or_hours",
        ),
    )
