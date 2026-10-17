"""The update contract, checked across every PUT/PATCH body the API accepts.

Omitted keeps the stored value, an explicit null clears a nullable column, and
an explicit null on a NOT NULL column is a 422. The last part is the one a
schema can get wrong on its own: a null that passes validation reaches the
database and comes back as a 500, a misleading 409, or a silent skip.

The schema set comes from the router, not from class names, so a new update
route fails here until its body is registered. A name filter missed
FamilyMemberUpdateRequest, whose NOT NULL `family_dashboard_order` was
null-skipped.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel, ValidationError
from sqlalchemy import inspect as sa_inspect

from app.main import app
from app.models.address_book import AddressBookEntry
from app.models.def_record import DEFRecord
from app.models.document import Document
from app.models.external_vehicle import ExternalVehicle
from app.models.financing import FinancingRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.maintenance_rule import MaintenanceRule
from app.models.note import Note
from app.models.odometer import OdometerRecord
from app.models.photo import VehiclePhoto
from app.models.recall import Recall
from app.models.reminder import Reminder
from app.models.reminder_pack import ReminderPack
from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.spot_rental import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.supply import Supply
from app.models.tax import TaxRecord
from app.models.tire import Tire, TireMountPeriod, TireReading, TireSet
from app.models.toll import TollTag, TollTransaction
from app.models.user import User
from app.models.vehicle import TrailerDetails, Vehicle
from app.models.vehicle_dtc import VehicleDTC
from app.models.vehicle_share import VehicleShare
from app.models.vendor import Vendor
from app.models.warranty import WarrantyRecord
from app.routes.oidc import OIDCAdminConfig
from app.routes.window_sticker import WindowStickerDataUpdate
from app.schemas.address_book import AddressBookEntryUpdate
from app.schemas.def_record import DEFRecordUpdate
from app.schemas.document import DocumentUpdate
from app.schemas.dtc import VehicleDTCUpdate
from app.schemas.external_vehicle import ExternalVehicleUpdate
from app.schemas.family import FamilyMemberUpdateRequest, VehicleShareUpdate
from app.schemas.financing import FinancingRecordUpdate
from app.schemas.fuel import FuelRecordUpdate
from app.schemas.hours import HoursRecordUpdate
from app.schemas.insurance import InsurancePolicyUpdate, PolicyVehicleUpdate
from app.schemas.livelink import (
    LiveLinkDeviceUpdate,
    LiveLinkParameterUpdate,
    LiveLinkSettingsUpdate,
    MQTTSettingsUpdate,
    SdConfigUpdate,
)
from app.schemas.livelink_topic_map import TopicMapUpdate
from app.schemas.maintenance import MaintenanceRuleUpdate
from app.schemas.note import NoteUpdate
from app.schemas.odometer import OdometerRecordUpdate
from app.schemas.photo import PhotoUpdate
from app.schemas.recall import RecallUpdate
from app.schemas.reminder import ReminderUpdate
from app.schemas.reminder_pack import RenameReminderPackRequest, SaveReminderPackRequest
from app.schemas.service_visit import ServiceVisitUpdate
from app.schemas.settings import POIProviderUpdate, SettingUpdate
from app.schemas.spot_rental import SpotRentalUpdate
from app.schemas.spot_rental_billing import SpotRentalBillingUpdate
from app.schemas.supply import SupplyUpdate
from app.schemas.tax import TaxRecordUpdate
from app.schemas.tire import MountPeriodUpdate, TireReadingUpdate, TireSetUpdate, TireUpdate
from app.schemas.toll import TollTagUpdate, TollTransactionUpdate
from app.schemas.torque import LocationTrackingUpdate
from app.schemas.user import (
    AdminPasswordReset,
    AdminUserUpdate,
    UnitPreferenceUpdate,
    UserPasswordUpdate,
    UserSelfUpdate,
)
from app.schemas.vehicle import TrailerDetailsUpdate, VehicleUpdate
from app.schemas.vendor import VendorUpdate
from app.schemas.warranty import WarrantyRecordUpdate

_VIN = "1HGBH41JXMN109186"


@dataclass(frozen=True)
class Entry:
    """Where an update body lands, and a payload it accepts as is."""

    model: type
    # A payload that validates. The rule swaps one field to null in it, so a
    # schema with other required fields fails for the right reason.
    baseline: dict[str, Any] = field(default_factory=dict)
    # Schema field -> column, for the fields whose names differ.
    columns: dict[str, str] = field(default_factory=dict)
    # Fields that write no column of the model, each with where it goes. A
    # field that is neither mapped nor listed here fails the test, which is how
    # a missed rename (transaction_date writes `date`) stays caught.
    unmapped: dict[str, str] = field(default_factory=dict)


REGISTRY: dict[type[BaseModel], Entry] = {
    AddressBookEntryUpdate: Entry(AddressBookEntry),
    AdminUserUpdate: Entry(User),
    DEFRecordUpdate: Entry(DEFRecord),
    DocumentUpdate: Entry(Document),
    ExternalVehicleUpdate: Entry(ExternalVehicle),
    FamilyMemberUpdateRequest: Entry(User, baseline={"show_on_family_dashboard": True}),
    FinancingRecordUpdate: Entry(FinancingRecord),
    FuelRecordUpdate: Entry(
        FuelRecord,
        unmapped={
            "def_fill_level": "creates a DEF observation row",
            "one_time_visit": "form flag, keeps the station out of the address book",
        },
    ),
    HoursRecordUpdate: Entry(HoursRecord),
    InsurancePolicyUpdate: Entry(
        InsurancePolicy,
        unmapped={
            "fields": "InsurancePolicyField child rows",
            "vehicles": "InsurancePolicyVehicle child rows",
            "share_strategy": "how the premium is split across vehicles",
        },
    ),
    LiveLinkDeviceUpdate: Entry(LiveLinkDevice),
    LiveLinkParameterUpdate: Entry(LiveLinkParameter),
    LocationTrackingUpdate: Entry(
        Vehicle, baseline={"enabled": True}, columns={"enabled": "location_tracking_enabled"}
    ),
    MaintenanceRuleUpdate: Entry(
        MaintenanceRule, unmapped={"recurrence": "nested RecurrenceSpec over several columns"}
    ),
    MountPeriodUpdate: Entry(TireMountPeriod),
    NoteUpdate: Entry(Note),
    OdometerRecordUpdate: Entry(OdometerRecord),
    PhotoUpdate: Entry(VehiclePhoto),
    PolicyVehicleUpdate: Entry(
        InsurancePolicyVehicle,
        unmapped={"coverages": "InsuranceCoverage child rows", "fields": "policy field rows"},
    ),
    RecallUpdate: Entry(Recall),
    ReminderUpdate: Entry(
        Reminder, unmapped={"recurrence": "nested spec; null deactivates the rule, documented"}
    ),
    RenameReminderPackRequest: Entry(ReminderPack, baseline={"name": "Pack"}),
    SaveReminderPackRequest: Entry(
        ReminderPack,
        baseline={"vin": _VIN, "name": "Pack", "rule_ids": [1]},
        unmapped={"vin": "the vehicle the rules are read from", "rule_ids": "pack item rows"},
    ),
    ServiceVisitUpdate: Entry(ServiceVisit, unmapped={"line_items": "ServiceLineItem child rows"}),
    SettingUpdate: Entry(Setting),
    SpotRentalBillingUpdate: Entry(SpotRentalBilling),
    SpotRentalUpdate: Entry(SpotRental),
    SupplyUpdate: Entry(Supply),
    TaxRecordUpdate: Entry(TaxRecord),
    TireReadingUpdate: Entry(TireReading),
    TireSetUpdate: Entry(TireSet),
    TireUpdate: Entry(Tire),
    TollTagUpdate: Entry(TollTag),
    TollTransactionUpdate: Entry(TollTransaction, columns={"transaction_date": "date"}),
    TopicMapUpdate: Entry(LiveLinkTopicMap),
    TrailerDetailsUpdate: Entry(TrailerDetails),
    # show_both_units is optional on a NOT NULL column, so it is an update
    # field like any other even though the unit preset itself is required.
    UnitPreferenceUpdate: Entry(
        User,
        baseline={"unit_preference": "imperial"},
        unmapped={"units": "expands to the eleven per-quantity unit columns"},
    ),
    UserSelfUpdate: Entry(User),
    VehicleDTCUpdate: Entry(VehicleDTC),
    VehicleShareUpdate: Entry(VehicleShare, baseline={"permission": "read"}),
    VehicleUpdate: Entry(Vehicle),
    VendorUpdate: Entry(Vendor),
    WarrantyRecordUpdate: Entry(WarrantyRecord),
    WindowStickerDataUpdate: Entry(Vehicle),
}

#: PUT/PATCH bodies that are not partial updates of a mapped row.
EXEMPT: dict[type[BaseModel], str] = {
    AdminPasswordReset: "an action carrying a new password, not a row update",
    UserPasswordUpdate: "an action carrying passwords, not a row update",
    OIDCAdminConfig: "writes key/value settings rows, not columns of a model",
    LiveLinkSettingsUpdate: "writes key/value settings rows, not columns of a model",
    MQTTSettingsUpdate: "writes key/value settings rows, not columns of a model",
    POIProviderUpdate: "writes key/value settings rows, not columns of a model",
    SdConfigUpdate: "a full replace of two device fields; omitted means the default, not keep",
}

#: NOT NULL columns where a null body value has a documented meaning.
ALLOWED_NULL: dict[tuple[str, str], str] = {}

#: The NOT NULL (schema, field) pairs the 2026-09-29 run found. A floor: the rule
#: must keep covering all of them, so a registry edit can't quietly shrink what
#: the test checks. New pairs are fine; a lost one fails.
EXPECTED_NOT_NULL: dict[str, set[str]] = {
    "AddressBookEntryUpdate": {"business_name", "source"},
    "AdminUserUpdate": {
        "currency_code",
        "email",
        "family_dashboard_order",
        "is_active",
        "is_admin",
        "language",
        "mobile_quick_entry_enabled",
        "show_both_units",
        "show_on_family_dashboard",
        "time_format",
    },
    "DEFRecordUpdate": {"date"},
    "DocumentUpdate": {"title"},
    "ExternalVehicleUpdate": {"nickname"},
    "FamilyMemberUpdateRequest": {"family_dashboard_order", "show_on_family_dashboard"},
    "FinancingRecordUpdate": {"amount", "category", "date"},
    "FuelRecordUpdate": {"date", "is_full_tank", "is_hauling", "missed_fillup"},
    "HoursRecordUpdate": {"date", "engine_hours"},
    "InsurancePolicyUpdate": {"end_date", "policy_number", "provider", "start_date"},
    "LiveLinkDeviceUpdate": {"enabled"},
    "LiveLinkParameterUpdate": {
        "archive_only",
        "display_order",
        "show_on_dashboard",
        "storage_interval_seconds",
    },
    "LocationTrackingUpdate": {"enabled"},
    "MaintenanceRuleUpdate": {"is_active", "title"},
    "NoteUpdate": {"content", "date"},
    "OdometerRecordUpdate": {"date", "odometer_km"},
    "PhotoUpdate": {"is_main"},
    "PolicyVehicleUpdate": {"policy_type"},
    "RecallUpdate": {"is_resolved"},
    "ReminderUpdate": {"reminder_type", "title"},
    "RenameReminderPackRequest": {"name"},
    "SaveReminderPackRequest": {"description", "name", "vehicle_types"},
    "ServiceVisitUpdate": {"date"},
    "SettingUpdate": {"category", "encrypted"},
    "SpotRentalBillingUpdate": {"billing_date"},
    "SpotRentalUpdate": {"check_in_date"},
    "SupplyUpdate": {"is_active", "name"},
    "TaxRecordUpdate": {"amount", "date"},
    "TireReadingUpdate": {"recorded_at"},
    "TireSetUpdate": {"name"},
    "TollTagUpdate": {"status", "tag_number", "toll_system"},
    "TollTransactionUpdate": {"amount", "location", "transaction_date"},
    "TopicMapUpdate": {"enabled", "scale", "value_offset"},
    "UnitPreferenceUpdate": {"show_both_units", "unit_preference"},
    "UserSelfUpdate": {
        "currency_code",
        "dashboard_sort",
        "email",
        "language",
        "mobile_quick_entry_enabled",
        "show_both_units",
        "time_format",
    },
    "VehicleDTCUpdate": {"severity"},
    "VehicleShareUpdate": {"permission"},
    "VehicleUpdate": {"nickname", "secondary_usage_enabled", "usage_unit", "vehicle_type"},
    "VendorUpdate": {"name"},
    "WarrantyRecordUpdate": {"start_date", "warranty_type"},
}

#: PUT/PATCH routes whose body is not a pydantic model, and so not checkable here.
NON_MODEL_BODIES: set[str] = set()


def _discover() -> tuple[dict[type[BaseModel], list[str]], set[str], list[str]]:
    """Walk the app's routes: model bodies, non-model bodies, and unsupported bodies."""
    models: dict[type[BaseModel], list[str]] = {}
    non_model: set[str] = set()
    unsupported: list[str] = []
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute):
            continue
        methods = route.methods & {"PUT", "PATCH"}
        if not methods:
            continue
        label = f"{sorted(methods)[0]} {ctx.path}"
        for param in route.dependant.body_params:
            kind = type(param.field_info).__name__
            if kind in ("Form", "File"):
                unsupported.append(f"{label} takes {kind}, which this test cannot see")
                continue
            annotation = param.field_info.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                models.setdefault(annotation, []).append(label)
            else:
                non_model.add(label)
    return models, non_model, unsupported


DISCOVERED, NON_MODEL_FOUND, UNSUPPORTED = _discover()


def _not_null_fields(schema: type[BaseModel], entry: Entry) -> list[str]:
    """The schema fields that write a NOT NULL column of the entry's model."""
    columns = {c.key: c for c in sa_inspect(entry.model).columns}
    fields = []
    for name in schema.model_fields:
        column = columns.get(entry.columns.get(name, name))
        if column is not None and not column.nullable:
            fields.append(name)
    return fields


def _mapped_fields(schema: type[BaseModel], entry: Entry) -> list[str]:
    columns = {c.key for c in sa_inspect(entry.model).columns}
    return [n for n in schema.model_fields if entry.columns.get(n, n) in columns]


def _unmapped_fields(schema: type[BaseModel], entry: Entry) -> set[str]:
    return set(schema.model_fields) - set(_mapped_fields(schema, entry))


def _refuses_null(schema: type[BaseModel], entry: Entry, name: str) -> bool:
    payload = {**entry.baseline, name: None}
    try:
        schema.model_validate(payload)
    except ValidationError as exc:
        return any(err["loc"] == (name,) for err in exc.errors())
    return False


def test_discovery_found_the_update_routes():
    # A floor on the walk itself, so a FastAPI change that hides routes from it
    # can't turn every check below into a pass over nothing.
    assert len(DISCOVERED) >= 45
    assert UNSUPPORTED == []
    assert NON_MODEL_FOUND == NON_MODEL_BODIES


def test_every_body_is_registered_or_exempt():
    missing = sorted(
        f"{s.__name__} ({', '.join(DISCOVERED[s])})"
        for s in DISCOVERED
        if s not in REGISTRY and s not in EXEMPT
    )
    assert missing == [], "register these update bodies in REGISTRY (or EXEMPT, with a reason)"


def test_no_stale_registry_entries():
    stale = sorted(s.__name__ for s in {*REGISTRY, *EXEMPT} if s not in DISCOVERED)
    assert stale == [], "no PUT/PATCH route takes these bodies any more"
    assert not set(REGISTRY) & set(EXEMPT)


@pytest.mark.parametrize("schema", list(REGISTRY), ids=lambda s: s.__name__)
def test_entry_maps_at_least_one_column(schema: type[BaseModel]):
    # An entry that intersects nothing checks nothing.
    assert _mapped_fields(schema, REGISTRY[schema]), (
        f"{schema.__name__} shares no field with {REGISTRY[schema].model.__name__}"
    )


@pytest.mark.parametrize("schema", list(REGISTRY), ids=lambda s: s.__name__)
def test_every_field_maps_a_column_or_says_where_it_goes(schema: type[BaseModel]):
    entry = REGISTRY[schema]
    assert _unmapped_fields(schema, entry) == set(entry.unmapped)


@pytest.mark.parametrize("schema", list(REGISTRY), ids=lambda s: s.__name__)
def test_baseline_validates(schema: type[BaseModel]):
    schema.model_validate(REGISTRY[schema].baseline)


def test_not_null_columns_refuse_null():
    accepting = sorted(
        f"{schema.__name__}.{name}"
        for schema, entry in REGISTRY.items()
        for name in _not_null_fields(schema, entry)
        if (schema.__name__, name) not in ALLOWED_NULL and not _refuses_null(schema, entry, name)
    )
    assert accepting == [], "these accept null for a NOT NULL column: " + ", ".join(accepting)


def test_floor_is_still_covered():
    covered = {
        (schema.__name__, name)
        for schema, entry in REGISTRY.items()
        for name in _not_null_fields(schema, entry)
    }
    floor = {(schema, name) for schema, names in EXPECTED_NOT_NULL.items() for name in names}
    assert sorted(floor - covered) == []
