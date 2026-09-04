"""Tire position / tread / DOT tracking models."""

from __future__ import annotations

import datetime as dt
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class TireSet(Base):
    """A named group of tires, so a seasonal swap is one action not eight.

    UX grouping only (D6). No calculation depends on set membership: distance,
    wear and position all read `tire_mount_periods`. A set exists so the user
    can say "Winter studded" and swap four tires at once.
    """

    __tablename__ = "tire_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tires: Mapped[list[Tire]] = relationship("Tire", back_populates="tire_set")

    __table_args__ = (Index("idx_tire_sets_vin", "vin"),)


class TireMountPeriod(Base):
    """One interval during which a tire was mounted at one position.

    The half-open interval ``[mounted_on, dismounted_on)``: a tire dismounted
    and remounted on the same day yields an empty period, which is correct --
    it accrued no distance.

    Deliberately carries **no `vin`**. The parent tire has one, and duplicating
    it would create a second place for the two to disagree. The cost is stated
    in the design (D4): the "one open period per corner per vehicle" rule
    cannot be written as a database constraint here, because the constraint
    would need a `vin` this table does not have. It is enforced in the service
    under the parent-tire row lock, and it has its own test, because no index
    will catch it.
    """

    __tablename__ = "tire_mount_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tire_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False
    )
    # Where the tire sat during this period. NOT nullable: a period exists
    # because the tire was mounted somewhere. A stored tire has no open period.
    position: Mapped[str] = mapped_column(String(10), nullable=False)
    # Nullable because migration 097 backfills from `tires.installed_date`,
    # which is itself nullable and unset on most rows.
    mounted_on: Mapped[dt.date | None] = mapped_column(Date)
    dismounted_on: Mapped[dt.date | None] = mapped_column(Date)
    mounted_odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dismounted_odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # True for the period 097 invents for an existing tire. Such a period
    # asserts only "this tire was mounted here as of the migration date"; its
    # start is unknown, which is why `distance_on_tire` reports
    # `nothing_bounded` rather than a confident figure.
    is_assumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The date the assumption was made, so an assumed period can say when it
    # was last known to be true even though it cannot say when it began.
    observed_active_on: Mapped[dt.date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tire: Mapped[Tire] = relationship("Tire", back_populates="mount_periods")

    __table_args__ = (
        Index("idx_tire_mount_periods_tire", "tire_id"),
        # One OPEN period per tire. A tire cannot be mounted in two places at
        # once. Partial unique index: valid on both SQLite and PostgreSQL.
        Index(
            "uq_tire_single_open_period",
            "tire_id",
            unique=True,
            sqlite_where=text("dismounted_on IS NULL"),
            postgresql_where=text("dismounted_on IS NULL"),
        ),
    )


class Tire(Base):
    """Current tire mounted at a vehicle position (one row per position)."""

    __tablename__ = "tires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    # FL / FR / RL / RR / SPARE, or NULL for a tire that is off the vehicle.
    #
    # Nullable since migration 097 (D2b): "in storage" is a real state a tire
    # spends half the year in, and the pre-097 schema could not express it --
    # a seasonal set had to be deleted and re-entered, losing its history.
    #
    # `uq_tires_vin_position` is KEPT and needs no partial-index replacement:
    # NULLs compare as distinct under UNIQUE on both SQLite and PostgreSQL, so
    # once this column is nullable the constraint permits any number of stored
    # tires per vehicle while still rejecting a second MOUNTED tire at one
    # corner. It becomes a mounted-only constraint for free.
    position: Mapped[str | None] = mapped_column(String(10))
    brand: Mapped[str | None] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[str | None] = mapped_column(String(40))
    # DOT week/year code, e.g. "2324"
    dot_code: Mapped[str | None] = mapped_column(String(20))
    # `installed_date` was dropped by migration 097 (D12). It is DERIVED in the
    # response from the earliest mount period that has a `mounted_on`, so there
    # are not two writable sources for the same fact. Deliberately absent from
    # this model: leaving it here would put the column on a fresh `create_all`
    # database and make that database match 097's "legacy schema" re-entrancy
    # branch, running a seven-step rebuild against a schema already correct.
    set_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tire_sets.id", ondelete="SET NULL")
    )
    # Set when a tire is retired rather than deleted (D18). A retired tire
    # keeps every reading and mount period; hard DELETE is reserved for a tire
    # entered by mistake.
    retired_on: Mapped[dt.date | None] = mapped_column(Date)
    # Latest tread depth in millimetres (canonical).
    tread_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Optional cold pressure in kPa (canonical).
    pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    # Wear-out threshold used for reminder hooks (default 2.0 mm / ~2/32").
    min_tread_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), default=Decimal("2.0"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    readings: Mapped[list[TireReading]] = relationship(
        "TireReading",
        back_populates="tire",
        cascade="all, delete-orphan",
    )

    mount_periods: Mapped[list[TireMountPeriod]] = relationship(
        "TireMountPeriod",
        back_populates="tire",
        cascade="all, delete-orphan",
        order_by="TireMountPeriod.mounted_on",
    )
    tire_set: Mapped[TireSet | None] = relationship("TireSet", back_populates="tires")

    __table_args__ = (
        UniqueConstraint("vin", "position", name="uq_tires_vin_position"),
        # The composite target for `tire_readings (tire_id, vin)`, so a reading
        # cannot reference a tire belonging to a different vehicle.
        UniqueConstraint("id", "vin", name="uq_tires_id_vin"),
        Index("idx_tires_vin", "vin"),
    )


class TireReading(Base):
    """Historical tread / pressure reading for wear projection."""

    __tablename__ = "tire_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tire_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tires.id", ondelete="CASCADE"), nullable=False
    )
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    # A SNAPSHOT of where the tire was when the reading was taken, not a live
    # pointer. Nullable since 097: a stored tire can still be measured.
    position: Mapped[str | None] = mapped_column(String(10))
    # Which mount period this reading falls in. Nullable: readings taken before
    # 097 have no period to attribute them to, and a reading on a stored tire
    # has none by definition.
    mount_period_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tire_mount_periods.id", ondelete="SET NULL")
    )
    recorded_at: Mapped[dt.date] = mapped_column(Date, nullable=False)
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Nullable since migration 094: a reader with no tread gauge logs pressure
    # alone (#152). ``TireReadingCreate`` still refuses a reading that carries
    # neither, and ``TireService.add_reading`` leaves the parent tire's tread
    # untouched when a reading omits one.
    tread_depth_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    pressure_kpa: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tire: Mapped[Tire] = relationship("Tire", back_populates="readings")

    __table_args__ = (
        Index("idx_tire_readings_tire", "tire_id"),
        Index("idx_tire_readings_vin", "vin"),
        Index("idx_tire_readings_mount_period", "mount_period_id"),
    )
