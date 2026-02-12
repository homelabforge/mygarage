from __future__ import annotations

"""Vehicle database models."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.def_record import DEFRecord
    from app.models.document import Document
    from app.models.fuel import FuelRecord
    from app.models.insurance import InsurancePolicy
    from app.models.maintenance_schedule_item import MaintenanceScheduleItem
    from app.models.maintenance_template import MaintenanceTemplate
    from app.models.note import Note
    from app.models.odometer import OdometerRecord
    from app.models.photo import VehiclePhoto
    from app.models.recall import Recall
    from app.models.reminder import Reminder
    from app.models.service import ServiceRecord
    from app.models.service_visit import ServiceVisit
    from app.models.spot_rental import SpotRental
    from app.models.tax import TaxRecord
    from app.models.toll import TollTag, TollTransaction
    from app.models.user import User
    from app.models.warranty import WarrantyRecord


class Vehicle(Base):
    """Main vehicle model."""

    __tablename__ = "vehicles"

    vin: Mapped[str] = mapped_column(String(17), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(50))
    license_plate: Mapped[str | None] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(30))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    sold_date: Mapped[date | None] = mapped_column(Date)
    sold_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    main_photo: Mapped[str | None] = mapped_column(String(255))
    # VIN decoded fields
    trim: Mapped[str | None] = mapped_column(String(50))
    body_class: Mapped[str | None] = mapped_column(String(100))
    drive_type: Mapped[str | None] = mapped_column(String(30))
    doors: Mapped[int | None] = mapped_column(Integer)
    gvwr_class: Mapped[str | None] = mapped_column(String(50))
    displacement_l: Mapped[str | None] = mapped_column(String(20))
    cylinders: Mapped[int | None] = mapped_column(Integer)
    fuel_type: Mapped[str | None] = mapped_column(String(50))
    transmission_type: Mapped[str | None] = mapped_column(String(50))
    transmission_speeds: Mapped[str | None] = mapped_column(String(20))
    # Window sticker fields
    window_sticker_file_path: Mapped[str | None] = mapped_column(String(255))
    window_sticker_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    msrp_base: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    msrp_options: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    msrp_total: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    fuel_economy_city: Mapped[int | None] = mapped_column(Integer)
    fuel_economy_highway: Mapped[int | None] = mapped_column(Integer)
    fuel_economy_combined: Mapped[int | None] = mapped_column(Integer)
    standard_equipment: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    optional_equipment: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assembly_location: Mapped[str | None] = mapped_column(String(100))
    # Enhanced window sticker fields
    destination_charge: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    window_sticker_options_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    window_sticker_packages: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    exterior_color: Mapped[str | None] = mapped_column(String(100))
    interior_color: Mapped[str | None] = mapped_column(String(100))
    sticker_engine_description: Mapped[str | None] = mapped_column(String(150))
    sticker_transmission_description: Mapped[str | None] = mapped_column(String(150))
    sticker_drivetrain: Mapped[str | None] = mapped_column(String(50))
    wheel_specs: Mapped[str | None] = mapped_column(String(100))
    tire_specs: Mapped[str | None] = mapped_column(String(100))
    warranty_powertrain: Mapped[str | None] = mapped_column(String(100))
    warranty_basic: Mapped[str | None] = mapped_column(String(100))
    environmental_rating_ghg: Mapped[str | None] = mapped_column(String(10))
    environmental_rating_smog: Mapped[str | None] = mapped_column(String(10))
    window_sticker_parser_used: Mapped[str | None] = mapped_column(String(50))
    window_sticker_confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    window_sticker_extracted_vin: Mapped[str | None] = mapped_column(String(17))
    # Multi-user support
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Archive fields
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    archive_reason: Mapped[str | None] = mapped_column(
        String(50)
    )  # Sold, Totaled, Gifted, Trade-in, Other
    archive_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    archive_sale_date: Mapped[date | None] = mapped_column(Date)
    archive_notes: Mapped[str | None] = mapped_column(String(1000))
    archived_visible: Mapped[bool] = mapped_column(Boolean, server_default="1")
    # DEF tracking
    def_tank_capacity_gallons: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    # Relationships
    user: Mapped[User | None] = relationship("User", foreign_keys="[Vehicle.user_id]")
    trailer_details: Mapped[TrailerDetails | None] = relationship(
        "TrailerDetails",
        back_populates="vehicle",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="[TrailerDetails.vin]",
    )
    spot_rentals: Mapped[list[SpotRental]] = relationship(
        "SpotRental", back_populates="vehicle", cascade="all, delete-orphan"
    )
    service_records: Mapped[list[ServiceRecord]] = relationship(
        "ServiceRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    def_records: Mapped[list[DEFRecord]] = relationship(
        "DEFRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    fuel_records: Mapped[list[FuelRecord]] = relationship(
        "FuelRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    odometer_records: Mapped[list[OdometerRecord]] = relationship(
        "OdometerRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    reminders: Mapped[list[Reminder]] = relationship(
        "Reminder", back_populates="vehicle", cascade="all, delete-orphan"
    )
    tax_records: Mapped[list[TaxRecord]] = relationship(
        "TaxRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    notes: Mapped[list[Note]] = relationship(
        "Note", back_populates="vehicle", cascade="all, delete-orphan"
    )
    recalls: Mapped[list[Recall]] = relationship(
        "Recall", back_populates="vehicle", cascade="all, delete-orphan"
    )
    photos: Mapped[list[VehiclePhoto]] = relationship(
        "VehiclePhoto", back_populates="vehicle", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        "Document", back_populates="vehicle", cascade="all, delete-orphan"
    )
    warranty_records: Mapped[list[WarrantyRecord]] = relationship(
        "WarrantyRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    insurance_policies: Mapped[list[InsurancePolicy]] = relationship(
        "InsurancePolicy", back_populates="vehicle", cascade="all, delete-orphan"
    )
    toll_tags: Mapped[list[TollTag]] = relationship(
        "TollTag", back_populates="vehicle", cascade="all, delete-orphan"
    )
    toll_transactions: Mapped[list[TollTransaction]] = relationship(
        "TollTransaction", back_populates="vehicle", cascade="all, delete-orphan"
    )
    maintenance_templates: Mapped[list[MaintenanceTemplate]] = relationship(
        "MaintenanceTemplate", back_populates="vehicle", cascade="all, delete-orphan"
    )
    service_visits: Mapped[list[ServiceVisit]] = relationship(
        "ServiceVisit", back_populates="vehicle", cascade="all, delete-orphan"
    )
    schedule_items: Mapped[list[MaintenanceScheduleItem]] = relationship(
        "MaintenanceScheduleItem",
        back_populates="vehicle",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "vehicle_type IN ('Car', 'Truck', 'SUV', 'Motorcycle', 'RV', 'Trailer', 'FifthWheel', 'TravelTrailer', 'Electric', 'Hybrid')",
            name="check_vehicle_type",
        ),
        Index("idx_vehicles_type", "vehicle_type"),
        Index("idx_vehicles_nickname", "nickname"),
    )


class TrailerDetails(Base):
    """Trailer-specific details model."""

    __tablename__ = "trailer_details"

    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), primary_key=True
    )
    gvwr: Mapped[int | None] = mapped_column(Integer)
    hitch_type: Mapped[str | None] = mapped_column(String(30))
    axle_count: Mapped[int | None] = mapped_column(Integer)
    brake_type: Mapped[str | None] = mapped_column(String(20))
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    width_ft: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    height_ft: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tow_vehicle_vin: Mapped[str | None] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="SET NULL")
    )

    # Relationships
    vehicle: Mapped[Vehicle] = relationship(
        "Vehicle", back_populates="trailer_details", foreign_keys="[TrailerDetails.vin]"
    )

    __table_args__ = (
        CheckConstraint(
            "hitch_type IN ('Ball', 'Pintle', 'Fifth Wheel', 'Gooseneck')",
            name="check_hitch_type",
        ),
        CheckConstraint("brake_type IN ('None', 'Electric', 'Hydraulic')", name="check_brake_type"),
    )
