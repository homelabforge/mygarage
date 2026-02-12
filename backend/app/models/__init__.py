"""Database models for MyGarage."""

from app.models.address_book import AddressBookEntry
from app.models.attachment import Attachment
from app.models.csrf_token import CSRFToken
from app.models.def_record import DEFRecord
from app.models.document import Document
from app.models.drive_session import DriveSession
from app.models.dtc_definition import DTCDefinition
from app.models.fuel import FuelRecord
from app.models.insurance import InsurancePolicy
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_firmware_cache import LiveLinkFirmwareCache
from app.models.livelink_parameter import LiveLinkParameter
from app.models.maintenance_schedule_item import MaintenanceScheduleItem
from app.models.note import Note
from app.models.odometer import OdometerRecord
from app.models.oidc_state import OIDCState
from app.models.photo import VehiclePhoto
from app.models.recall import Recall
from app.models.reminder import Reminder
from app.models.service import ServiceRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.spot_rental import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.tax import TaxRecord
from app.models.vehicle import TrailerDetails, Vehicle
from app.models.vehicle_dtc import VehicleDTC
from app.models.vehicle_share import VehicleShare
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.models.vehicle_transfer import VehicleTransfer
from app.models.vendor import Vendor
from app.models.vendor_price_history import VendorPriceHistory
from app.models.warranty import WarrantyRecord

__all__ = [
    # Vehicles
    "Vehicle",
    "TrailerDetails",
    # Maintenance & Records
    "DEFRecord",
    "SpotRental",
    "SpotRentalBilling",
    "ServiceRecord",
    "FuelRecord",
    "OdometerRecord",
    "Reminder",
    "TaxRecord",
    "Note",
    "Recall",
    "Attachment",
    "VehiclePhoto",
    "Document",
    "WarrantyRecord",
    "InsurancePolicy",
    # LiveLink (Telemetry)
    "LiveLinkDevice",
    "LiveLinkParameter",
    "LiveLinkFirmwareCache",
    "VehicleTelemetry",
    "VehicleTelemetryLatest",
    "TelemetryDailySummary",
    "VehicleDTC",
    "DTCDefinition",
    "DriveSession",
    # Family Multi-User
    "VehicleShare",
    "VehicleTransfer",
    # System
    "Setting",
    "AddressBookEntry",
    "CSRFToken",
    "OIDCState",
    "Vendor",
    "MaintenanceScheduleItem",
    "ServiceVisit",
    "ServiceLineItem",
    "VendorPriceHistory",
]
