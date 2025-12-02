"""Database models for MyGarage."""

from app.models.vehicle import Vehicle, TrailerDetails
from app.models.spot_rental import SpotRental
from app.models.service import ServiceRecord
from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.tax import TaxRecord
from app.models.note import Note
from app.models.recall import Recall
from app.models.attachment import Attachment
from app.models.photo import VehiclePhoto
from app.models.document import Document
from app.models.settings import Setting
from app.models.warranty import WarrantyRecord
from app.models.insurance import InsurancePolicy
from app.models.address_book import AddressBookEntry
from app.models.csrf_token import CSRFToken
from app.models.oidc_state import OIDCState

__all__ = [
    "Vehicle",
    "TrailerDetails",
    "SpotRental",
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
    "Setting",
    "WarrantyRecord",
    "InsurancePolicy",
    "AddressBookEntry",
    "CSRFToken",
    "OIDCState",
]
