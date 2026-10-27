from __future__ import annotations

"""Engine-hours record database model.

Parallel to :class:`~app.models.odometer.OdometerRecord` for hour-metered
vehicles (ATVs, side-by-sides, equipment). Distance rows live in
``odometer_records``; engine-hour rows live here. The deliberate improvement
over the odometer mirror is a real ``service_visit_id`` foreign key (in addition
to ``fuel_record_id``), so service-sourced hours rows have a stable identity and
are removed by FK cascade on service-visit delete rather than by note-parsing.
"""

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models._types import ScaledNumeric


class HoursRecord(Base):
    """Engine-hours reading model."""

    __tablename__ = "hours_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    engine_hours: Mapped[Decimal] = mapped_column(ScaledNumeric(10, 1), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual, fuel, service_visit
    # Set when this row was synced from a fuel record. Nullable — manual and
    # service-sourced rows have no parent fuel record. ON DELETE CASCADE removes
    # the synced row with its source fuel record (PG enforced; SQLite via
    # PRAGMA foreign_keys=ON, active in prod).
    fuel_record_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fuel_records.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Set when this row was synced from a service visit. The deliberate
    # improvement over the odometer track's note-linkage: a real FK cascade
    # removes the synced row when its service visit is deleted.
    service_visit_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("service_visits.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="hours_records")

    __table_args__ = (
        Index("idx_hours_records_vin", "vin"),
        Index("idx_hours_records_date", "date"),
        Index("idx_hours_records_engine_hours", "engine_hours"),  # For hours queries
        Index("idx_hours_vin_date", "vin", "date"),  # Composite for common queries
        Index("idx_hours_vin_engine_hours", "vin", "engine_hours"),  # For hours tracking
        Index("idx_hours_source", "source"),  # For filtering by source
    )

    # A synced row goes with its fuel record or service visit by FK cascade,
    # so when a vehicle delete cascades both, the ORM's own DELETE for it finds
    # nothing. That's expected, not a lost row, so don't warn about it.
    __mapper_args__ = {"confirm_deleted_rows": False}


from app.models.vehicle import Vehicle
