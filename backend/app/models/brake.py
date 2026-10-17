"""Brake tracking models (#202): axle setup, measurements and brake jobs.

Everything here belongs to a corner of the vehicle (FL/FR/RL/RR), never to a
tire. A tire rotation moves tires between corners; it can't move brake data.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

_POSITION_CHECK = "position IN ('FL', 'FR', 'RL', 'RR')"
_TYPE_CHECK = "brake_type IN ('disc', 'drum')"


class BrakeAxle(Base):
    """How one axle is braked, set once: disc or drum, and its limits.

    A vehicle with no row for an axle gets the defaults (disc, 3.0 mm minimum,
    10.0 mm new). The row exists only once someone saves Axle setup.
    """

    __tablename__ = "brake_axles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    axle: Mapped[str] = mapped_column(String(5), nullable=False)
    brake_type: Mapped[str] = mapped_column(String(4), nullable=False)
    # Pad (disc) or shoe lining (drum) thickness, in millimetres.
    min_thickness_mm: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    new_thickness_mm: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    # The "MIN TH" stamped on a rotor, or the "MAX DIA" cast into a drum.
    rotor_min_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    drum_max_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("vin", "axle", name="uq_brake_axles_vin_axle"),
        CheckConstraint("axle IN ('front', 'rear')", name="check_brake_axles_axle"),
        CheckConstraint(_TYPE_CHECK, name="check_brake_axles_brake_type"),
    )


class BrakeJob(Base):
    """Work done on one corner's brakes: pads or shoes, and the rotor or drum.

    One row per corner, so a front brake job is two rows. `brake_type` is a
    copy of the axle's type on the day, so "pads replaced" still reads right
    after the axle is set up as drum.
    """

    __tablename__ = "brake_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[str] = mapped_column(String(2), nullable=False)
    brake_type: Mapped[str] = mapped_column(String(4), nullable=False)
    performed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Context for the wear estimate. Never published to the odometer history.
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    engine_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    # Pads on a disc corner, shoes on a drum one. Starts the wear estimate over.
    friction_replaced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # What happened to the rotor or the drum, if anything.
    surface: Mapped[str | None] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_POSITION_CHECK, name="check_brake_jobs_position"),
        CheckConstraint(_TYPE_CHECK, name="check_brake_jobs_brake_type"),
        CheckConstraint(
            "surface IS NULL OR surface IN ('replaced', 'resurfaced')",
            name="check_brake_jobs_surface",
        ),
        Index("idx_brake_jobs_vin_position", "vin", "position"),
    )


class BrakeMeasurement(Base):
    """What one corner measured on one day.

    Disc corners take inner and outer pad plus the rotor, drum corners take the
    shoe lining plus the drum. All in millimetres, any of them may be missing.
    """

    __tablename__ = "brake_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[str] = mapped_column(String(2), nullable=False)
    recorded_at: Mapped[dt.date] = mapped_column(Date, nullable=False)
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    engine_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    inner_pad_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    outer_pad_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    rotor_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    shoe_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    drum_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # Set on the new-pads figure a brake job wrote. It counts as after that job
    # even though it shares the job's date, and it goes when the job goes.
    brake_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("brake_jobs.id", ondelete="CASCADE")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_POSITION_CHECK, name="check_brake_measurements_position"),
        Index("idx_brake_measurements_vin_position", "vin", "position"),
        Index("idx_brake_measurements_brake_job", "brake_job_id"),
    )
