from __future__ import annotations

"""Odometer record database model."""

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class OdometerRecord(Base):
    """Odometer reading model."""

    __tablename__ = "odometer_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    odometer_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        String(20), default="manual"
    )  # manual, livelink, service, fuel
    # Cascade-link added in migration 055 (v2.27.0-rc2). Nullable because
    # manual/service/livelink rows have no parent fuel record. When set,
    # ON DELETE CASCADE on the FK ensures the synced row goes away with
    # its source fuel record on PG. SQLite doesn't enforce FKs without
    # PRAGMA foreign_keys=ON; the service layer handles cleanup there.
    fuel_record_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fuel_records.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="odometer_records")

    __table_args__ = (
        Index("idx_odometer_records_vin", "vin"),
        Index("idx_odometer_records_date", "date"),
        Index("idx_odometer_records_odometer_km", "odometer_km"),  # For mileage queries
        Index("idx_odometer_vin_date", "vin", "date"),  # Composite for common queries
        Index("idx_odometer_vin_odometer_km", "vin", "odometer_km"),  # For mileage tracking
        Index("idx_odometer_source", "source"),  # For filtering by source
    )


from app.models.vehicle import Vehicle
