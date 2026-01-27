from __future__ import annotations

"""Maintenance schedule item database model."""

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.service_line_item import ServiceLineItem
    from app.models.vehicle import Vehicle


class MaintenanceScheduleItem(Base):
    """Maintenance schedule item model for tracking vehicle maintenance schedules."""

    __tablename__ = "maintenance_schedule_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    component_category: Mapped[str] = mapped_column(String(50), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'service' or 'inspection'
    interval_months: Mapped[int | None] = mapped_column(Integer)
    interval_miles: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'template', 'custom', 'migrated_reminder'
    template_item_id: Mapped[str | None] = mapped_column(String(100))
    last_performed_date: Mapped[date | None] = mapped_column(Date)
    last_performed_mileage: Mapped[int | None] = mapped_column(Integer)
    last_service_line_item_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="schedule_items")
    service_line_items: Mapped[list[ServiceLineItem]] = relationship(
        "ServiceLineItem", back_populates="schedule_item"
    )

    __table_args__ = (
        Index("idx_maintenance_schedule_vin", "vin"),
        Index("idx_maintenance_schedule_category", "component_category"),
        Index("idx_maintenance_schedule_type", "item_type"),
    )

    @property
    def next_due_date(self) -> date | None:
        """Calculate next due date based on last performed and interval."""
        if not self.last_performed_date or not self.interval_months:
            return None
        return self.last_performed_date + timedelta(days=self.interval_months * 30)

    @property
    def next_due_mileage(self) -> int | None:
        """Calculate next due mileage based on last performed and interval."""
        if not self.last_performed_mileage or not self.interval_miles:
            return None
        return self.last_performed_mileage + self.interval_miles

    def calculate_status(self, current_date: date, current_mileage: int | None = None) -> str:
        """
        Calculate maintenance status.

        Args:
            current_date: Current date for comparison
            current_mileage: Current vehicle mileage (optional)

        Returns:
            Status string: 'never_performed', 'overdue', 'due_soon', or 'on_track'
        """
        if not self.last_performed_date:
            return "never_performed"

        next_date = self.next_due_date
        next_mileage = self.next_due_mileage

        # Calculate days until due
        days_until = (next_date - current_date).days if next_date else None

        # Calculate miles until due
        miles_until = None
        if next_mileage and current_mileage:
            miles_until = next_mileage - current_mileage

        # Check if overdue
        if (days_until is not None and days_until < 0) or (
            miles_until is not None and miles_until < 0
        ):
            return "overdue"

        # Check if due soon (30 days OR 1000 miles)
        if (days_until is not None and days_until <= 30) or (
            miles_until is not None and miles_until <= 1000
        ):
            return "due_soon"

        return "on_track"

    def update_from_service(
        self, service_date: date, mileage: int | None, line_item_id: int
    ) -> None:
        """
        Update schedule item when a service is performed.

        Args:
            service_date: Date service was performed
            mileage: Mileage at service time
            line_item_id: ID of the service line item
        """
        self.last_performed_date = service_date
        if mileage:
            self.last_performed_mileage = mileage
        self.last_service_line_item_id = line_item_id
