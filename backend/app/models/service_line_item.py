"""Service line item database model."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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
    from app.models.maintenance_schedule_item import MaintenanceScheduleItem
    from app.models.service_visit import ServiceVisit


class ServiceLineItem(Base):
    """Service line item model representing a single service performed during a visit."""

    __tablename__ = "service_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    visit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("service_visits.id", ondelete="CASCADE"), nullable=False
    )
    schedule_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("maintenance_schedule_items.id")
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    is_inspection: Mapped[bool] = mapped_column(Boolean, default=False)
    inspection_result: Mapped[str | None] = mapped_column(
        String(20)
    )  # passed, failed, needs_attention
    inspection_severity: Mapped[str | None] = mapped_column(
        String(10)
    )  # green, yellow, red
    triggered_by_inspection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("service_line_items.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    visit: Mapped["ServiceVisit"] = relationship(
        "ServiceVisit", back_populates="line_items"
    )
    schedule_item: Mapped[Optional["MaintenanceScheduleItem"]] = relationship(
        "MaintenanceScheduleItem", back_populates="service_line_items"
    )
    triggered_repairs: Mapped[list["ServiceLineItem"]] = relationship(
        "ServiceLineItem",
        foreign_keys=[triggered_by_inspection_id],
        remote_side=[id],
        backref="triggered_by_inspection",
    )

    __table_args__ = (
        CheckConstraint(
            "inspection_result IS NULL OR inspection_result IN ('passed', 'failed', 'needs_attention')",
            name="check_inspection_result",
        ),
        CheckConstraint(
            "inspection_severity IS NULL OR inspection_severity IN ('green', 'yellow', 'red')",
            name="check_inspection_severity",
        ),
        Index("idx_service_line_items_visit", "visit_id"),
        Index("idx_service_line_items_schedule", "schedule_item_id"),
    )

    @property
    def is_failed_inspection(self) -> bool:
        """Check if this is a failed inspection."""
        return self.is_inspection and self.inspection_result == "failed"

    @property
    def needs_followup(self) -> bool:
        """Check if this inspection needs followup action."""
        return self.is_inspection and self.inspection_result in (
            "failed",
            "needs_attention",
        )

    @property
    def severity_priority(self) -> int:
        """
        Return numeric priority for sorting by severity.

        Higher number = more urgent.
        """
        if not self.inspection_severity:
            return 0
        severity_map = {"green": 1, "yellow": 2, "red": 3}
        return severity_map.get(self.inspection_severity, 0)
