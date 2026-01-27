"""Maintenance Template database model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle


class MaintenanceTemplate(Base):
    """
    Tracks which maintenance templates have been applied to vehicles.

    Templates are YAML files hosted on GitHub that define manufacturer-recommended
    maintenance schedules. When a template is applied, it creates reminders
    based on the template's maintenance items.
    """

    __tablename__ = "maintenance_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )

    # Template identification
    template_source: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # e.g., "github:ram/1500/2019-2024-normal.yml"
    template_version: Mapped[str | None] = mapped_column(
        String(50)
    )  # Git commit SHA or version tag (e.g., "1.0.0")

    # Template content (stored for reference/auditing)
    template_data: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # Full template content as JSON

    # Application tracking
    applied_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[str] = mapped_column(
        String(20), default="auto"
    )  # "auto" or "manual"
    reminders_created: Mapped[int] = mapped_column(
        Integer, default=0
    )  # Count of reminders generated

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, onupdate=func.now()
    )

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle", back_populates="maintenance_templates"
    )

    __table_args__ = (
        Index("idx_maintenance_templates_vin", "vin"),
        Index("idx_maintenance_templates_source", "template_source"),
    )
