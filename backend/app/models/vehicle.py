"""Vehicle database models."""

from sqlalchemy import String, Integer, Numeric, Date, DateTime, CheckConstraint, Index, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import date, datetime
from typing import Optional
from decimal import Decimal

from app.database import Base


class Vehicle(Base):
    """Main vehicle model."""

    __tablename__ = "vehicles"

    vin: Mapped[str] = mapped_column(String(17), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(20), nullable=False)
    year: Mapped[Optional[int]] = mapped_column(Integer)
    make: Mapped[Optional[str]] = mapped_column(String(50))
    model: Mapped[Optional[str]] = mapped_column(String(50))
    license_plate: Mapped[Optional[str]] = mapped_column(String(20))
    color: Mapped[Optional[str]] = mapped_column(String(30))
    purchase_date: Mapped[Optional[date]] = mapped_column(Date)
    purchase_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    sold_date: Mapped[Optional[date]] = mapped_column(Date)
    sold_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    main_photo: Mapped[Optional[str]] = mapped_column(String(255))
    # VIN decoded fields
    trim: Mapped[Optional[str]] = mapped_column(String(50))
    body_class: Mapped[Optional[str]] = mapped_column(String(50))
    drive_type: Mapped[Optional[str]] = mapped_column(String(30))
    doors: Mapped[Optional[int]] = mapped_column(Integer)
    gvwr_class: Mapped[Optional[str]] = mapped_column(String(50))
    displacement_l: Mapped[Optional[str]] = mapped_column(String(20))
    cylinders: Mapped[Optional[int]] = mapped_column(Integer)
    fuel_type: Mapped[Optional[str]] = mapped_column(String(50))
    transmission_type: Mapped[Optional[str]] = mapped_column(String(50))
    transmission_speeds: Mapped[Optional[str]] = mapped_column(String(20))
    # Window sticker fields
    window_sticker_file_path: Mapped[Optional[str]] = mapped_column(String(255))
    window_sticker_uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    msrp_base: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    msrp_options: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    msrp_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    fuel_economy_city: Mapped[Optional[int]] = mapped_column(Integer)
    fuel_economy_highway: Mapped[Optional[int]] = mapped_column(Integer)
    fuel_economy_combined: Mapped[Optional[int]] = mapped_column(Integer)
    standard_equipment: Mapped[Optional[dict]] = mapped_column(JSON)
    optional_equipment: Mapped[Optional[dict]] = mapped_column(JSON)
    assembly_location: Mapped[Optional[str]] = mapped_column(String(100))
    # Enhanced window sticker fields
    destination_charge: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    window_sticker_options_detail: Mapped[Optional[dict]] = mapped_column(JSON)
    window_sticker_packages: Mapped[Optional[dict]] = mapped_column(JSON)
    exterior_color: Mapped[Optional[str]] = mapped_column(String(100))
    interior_color: Mapped[Optional[str]] = mapped_column(String(100))
    sticker_engine_description: Mapped[Optional[str]] = mapped_column(String(150))
    sticker_transmission_description: Mapped[Optional[str]] = mapped_column(String(150))
    sticker_drivetrain: Mapped[Optional[str]] = mapped_column(String(50))
    wheel_specs: Mapped[Optional[str]] = mapped_column(String(100))
    tire_specs: Mapped[Optional[str]] = mapped_column(String(100))
    warranty_powertrain: Mapped[Optional[str]] = mapped_column(String(100))
    warranty_basic: Mapped[Optional[str]] = mapped_column(String(100))
    environmental_rating_ghg: Mapped[Optional[str]] = mapped_column(String(10))
    environmental_rating_smog: Mapped[Optional[str]] = mapped_column(String(10))
    window_sticker_parser_used: Mapped[Optional[str]] = mapped_column(String(50))
    window_sticker_confidence_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    window_sticker_extracted_vin: Mapped[Optional[str]] = mapped_column(String(17))
    # Multi-user support
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Archive fields
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    archive_reason: Mapped[Optional[str]] = mapped_column(String(50))  # Sold, Totaled, Gifted, Trade-in, Other
    archive_sale_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    archive_sale_date: Mapped[Optional[date]] = mapped_column(Date)
    archive_notes: Mapped[Optional[str]] = mapped_column(String(1000))
    archived_visible: Mapped[bool] = mapped_column(Integer, server_default="1")  # SQLite uses INTEGER for BOOLEAN
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=func.now())

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", foreign_keys="[Vehicle.user_id]")
    trailer_details: Mapped[Optional["TrailerDetails"]] = relationship(
        "TrailerDetails",
        back_populates="vehicle",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="[TrailerDetails.vin]"
    )
    spot_rentals: Mapped[list["SpotRental"]] = relationship(
        "SpotRental", back_populates="vehicle", cascade="all, delete-orphan"
    )
    service_records: Mapped[list["ServiceRecord"]] = relationship(
        "ServiceRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    fuel_records: Mapped[list["FuelRecord"]] = relationship(
        "FuelRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    odometer_records: Mapped[list["OdometerRecord"]] = relationship(
        "OdometerRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder", back_populates="vehicle", cascade="all, delete-orphan"
    )
    tax_records: Mapped[list["TaxRecord"]] = relationship(
        "TaxRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(
        "Note", back_populates="vehicle", cascade="all, delete-orphan"
    )
    recalls: Mapped[list["Recall"]] = relationship(
        "Recall", back_populates="vehicle", cascade="all, delete-orphan"
    )
    photos: Mapped[list["VehiclePhoto"]] = relationship(
        "VehiclePhoto", back_populates="vehicle", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="vehicle", cascade="all, delete-orphan"
    )
    warranty_records: Mapped[list["WarrantyRecord"]] = relationship(
        "WarrantyRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    insurance_policies: Mapped[list["InsurancePolicy"]] = relationship(
        "InsurancePolicy", back_populates="vehicle", cascade="all, delete-orphan"
    )
    toll_tags: Mapped[list["TollTag"]] = relationship(
        "TollTag", back_populates="vehicle", cascade="all, delete-orphan"
    )
    toll_transactions: Mapped[list["TollTransaction"]] = relationship(
        "TollTransaction", back_populates="vehicle", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "vehicle_type IN ('Car', 'Truck', 'SUV', 'Motorcycle', 'RV', 'Trailer', 'FifthWheel', 'Electric', 'Hybrid')",
            name="check_vehicle_type"
        ),
        Index("idx_vehicles_type", "vehicle_type"),
        Index("idx_vehicles_nickname", "nickname"),
    )


class TrailerDetails(Base):
    """Trailer-specific details model."""

    __tablename__ = "trailer_details"

    vin: Mapped[str] = mapped_column(String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), primary_key=True)
    gvwr: Mapped[Optional[int]] = mapped_column(Integer)
    hitch_type: Mapped[Optional[str]] = mapped_column(String(30))
    axle_count: Mapped[Optional[int]] = mapped_column(Integer)
    brake_type: Mapped[Optional[str]] = mapped_column(String(20))
    length_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    width_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    height_ft: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    tow_vehicle_vin: Mapped[Optional[str]] = mapped_column(String(17), ForeignKey("vehicles.vin", ondelete="SET NULL"))

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship(
        "Vehicle",
        back_populates="trailer_details",
        foreign_keys="[TrailerDetails.vin]"
    )

    __table_args__ = (
        CheckConstraint(
            "hitch_type IN ('Ball', 'Pintle', 'Fifth Wheel', 'Gooseneck')",
            name="check_hitch_type"
        ),
        CheckConstraint(
            "brake_type IN ('None', 'Electric', 'Hydraulic')",
            name="check_brake_type"
        ),
    )


# Forward references for type hints
from app.models.user import User
from app.models.spot_rental import SpotRental
from app.models.service import ServiceRecord
from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.tax import TaxRecord
from app.models.note import Note
from app.models.recall import Recall
from app.models.photo import VehiclePhoto
from app.models.warranty import WarrantyRecord
from app.models.insurance import InsurancePolicy
from app.models.toll import TollTag, TollTransaction
from app.models.document import Document
