"""Every model column is in the JSON backup, or named here with the reason it isn't (R1).

The CSV twin is `test_export_schema_coverage.py`. A JSON section only shows
its keys on a row, so the fixture writes one row of every section, then each
spec compares that row's keys with its model's columns. Add a column to a
model and its spec fails until the column is exported or excluded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DEFRecord,
    FuelRecord,
    HoursRecord,
    Note,
    OdometerRecord,
    ServiceLineItem,
    ServiceVisit,
    TaxRecord,
    Vehicle,
    WarrantyRecord,
)
from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement
from app.models.financing import FinancingRecord
from app.models.maintenance_rule import MaintenanceRule
from app.models.recall import Recall
from app.models.reminder import Reminder
from app.models.spot_rental import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.models.tire import Tire, TireMountPeriod, TireReading, TireSet
from app.models.toll import TollTag, TollTransaction
from app.models.vehicle_dtc import VehicleDTC

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_VIN = "B3RTJSONCOVERAGE1"
_OTHER_VIN = "B3RTJSONCOVERAGE2"

# Left out of every section: the row's own key, its vehicle (the file is the
# vehicle's), and the bookkeeping timestamps.
_ALWAYS = frozenset({"id", "vin", "created_at"})


@dataclass(frozen=True)
class JsonSection:
    """One list (or object) in the backup and the model its rows come from."""

    path: str  # "fuel_records", "service_visits.line_items", or "vehicle"
    model: type[Any]
    keys: frozenset[str]  # the model columns the section writes
    exclude: frozenset[str]  # the model columns it leaves out, each with a reason below
    portable: frozenset[str] = frozenset()  # keys that are not model columns


#: A reminder a person made or a rule made, as both reminder lists write it (K5).
_REMINDER_KEYS = frozenset(
    {
        "title",
        "reminder_type",
        "due_date",
        "due_mileage_km",
        "due_hours",
        "status",
        "notes",
        "snoozed_until",
        "maintenance_type",
        "anchor_kind",
        "anchor_date",
        "anchor_odometer_km",
        "anchor_hours",
        "start_odometer_km",
        "start_hours",
        "completed_at",
        "completed_date",
        "completed_odometer_km",
        "completed_hours",
        "created_at",
    }
)
_REMINDER_EXCLUDE = frozenset(
    {
        "id",
        "vin",
        "updated_at",
        "rule_id",  # the rule is the parent, or there's none
        "line_item_id",  # line items here; a service anchor imports as a completion (S8)
        "completed_line_item_id",  # as above
        "superseded_by_id",  # another reminder here
        "last_notified_at",  # notification marker
        "tire_id",  # sync-owned reminders don't travel (J1)
        "source",  # as above
        "tread_depth_mm",  # as above
        "tread_threshold_mm",  # as above
    }
)


SECTIONS = [
    JsonSection(
        "vehicle",
        Vehicle,
        keys=frozenset(
            {
                "vin",
                "nickname",
                "vehicle_type",
                "usage_unit",
                "secondary_usage_enabled",
                "distance_unit",
                "year",
                "make",
                "model",
                "license_plate",
                "color",
                "purchase_date",
                "purchase_price",
                "sold_date",
                "sold_price",
                "trim",
                "body_class",
                "drive_type",
                "doors",
                "gvwr_class",
                "displacement_l",
                "cylinders",
                "fuel_type",
                "fuel_type_secondary",
                "transmission_type",
                "transmission_speeds",
                "msrp_base",
                "msrp_options",
                "msrp_total",
                "fuel_economy_city_l_per_100km",
                "fuel_economy_highway_l_per_100km",
                "fuel_economy_combined_l_per_100km",
                "standard_equipment",
                "optional_equipment",
                "assembly_location",
                "destination_charge",
                "window_sticker_options_detail",
                "window_sticker_packages",
                "exterior_color",
                "interior_color",
                "sticker_engine_description",
                "sticker_transmission_description",
                "sticker_drivetrain",
                "wheel_specs",
                "tire_specs",
                "warranty_powertrain",
                "warranty_basic",
                "environmental_rating_ghg",
                "environmental_rating_smog",
                "window_sticker_parser_used",
                "window_sticker_confidence_score",
                "window_sticker_extracted_vin",
                "archived_at",
                "archive_reason",
                "archive_sale_price",
                "archive_sale_date",
                "archive_notes",
                "archived_visible",
                "location_tracking_enabled",
                "def_tank_capacity_liters",
                "oil_viscosity",
                "oil_capacity_liters",
                "oil_filter_part_number",
                "fuel_filter_part_number",
                "lug_nut_torque_nm",
                "coolant_type",
                "brake_fluid_type",
                "transmission_fluid_type",
                "maintenance_specs_notes",
            }
        ),
        exclude=frozenset(
            {
                "user_id",  # the owner on this instance; the import targets an existing vehicle
                "main_photo",  # a file; photos are full-backup only (J4)
                "window_sticker_file_path",  # a file, as above
                "window_sticker_uploaded_at",  # when that file was stored
                "current_hours",  # legacy cache; the hours history carries the readings
                "last_milestone_notified_km",  # notification marker
                "def_low_notified_at",  # notification marker
                "created_at",
                "updated_at",
            }
        ),
    ),
    JsonSection(
        "service_visits",
        ServiceVisit,
        keys=frozenset(
            {
                "date",
                "odometer_km",
                "engine_hours",
                "tax_amount",
                "shop_supplies",
                "misc_fees",
                "notes",
                "service_category",
                "insurance_claim_number",
            }
        ),
        # vendor_id travels as vendor_name; total_cost is recomputed from the items and fees.
        exclude=_ALWAYS | {"vendor_id", "total_cost", "updated_at"},
        portable=frozenset({"vendor_name", "line_items"}),
    ),
    JsonSection(
        "service_visits.line_items",
        ServiceLineItem,
        keys=frozenset(
            {
                "description",
                "category",
                "maintenance_type",
                "cost",
                "notes",
                "is_inspection",
                "inspection_result",
                "inspection_severity",
            }
        ),
        # The visit is the parent; the inspection link travels as an index in the visit.
        exclude=frozenset({"id", "visit_id", "triggered_by_inspection_id", "created_at"}),
        portable=frozenset({"triggered_by_inspection", "supply_usages"}),
    ),
    JsonSection(
        "fuel_records",
        FuelRecord,
        keys=frozenset(
            {
                "date",
                "filled_at",
                "odometer_km",
                "engine_hours",
                "liters",
                "propane_liters",
                "tank_size_kg",
                "tank_quantity",
                "kwh",
                "soc_start_pct",
                "soc_end_pct",
                "charge_level",
                "charge_location",
                "battery_soh_pct",
                "cost",
                "rebate",
                "price_per_unit",
                "price_basis",
                "fuel_type_used",
                "octane",
                "diesel_grade",
                "is_full_tank",
                "missed_fillup",
                "is_hauling",
                "notes",
                "station_address_book_id",
                "station_name_freetext",
                "driver_user_id",
                "driver_name_freetext",
                "payment_method",
                "trip_type",
                "outside_temp_c",
                "obc_l_per_100km",
                "obc_avg_speed_kmh",
                "obc_trip_duration_s",
            }
        ),
        exclude=_ALWAYS,
        # The ids are checked against these names on import (R6).
        portable=frozenset({"station_name", "driver_username"}),
    ),
    JsonSection(
        "def_records",
        DEFRecord,
        keys=frozenset(
            {
                "date",
                "odometer_km",
                "liters",
                "cost",
                "price_per_unit",
                "fill_level",
                "source",
                "brand",
                "notes",
                "entry_type",
            }
        ),
        # A fuel row on this instance; the restored fuel row is a new one.
        exclude=_ALWAYS | {"origin_fuel_record_id"},
    ),
    JsonSection(
        "odometer_records",
        OdometerRecord,
        keys=frozenset({"date", "odometer_km", "notes", "source"}),
        # The fill-up that owned the reading here; an imported reading is never owned (R4).
        exclude=_ALWAYS | {"fuel_record_id"},
    ),
    JsonSection(
        "hours_records",
        HoursRecord,
        keys=frozenset({"date", "engine_hours", "notes", "source"}),
        exclude=_ALWAYS | {"fuel_record_id", "service_visit_id"},
    ),
    JsonSection(
        "notes",
        Note,
        keys=frozenset({"date", "title", "content"}),
        exclude=_ALWAYS | {"updated_at"},
    ),
    JsonSection(
        "financing_records",
        FinancingRecord,
        keys=frozenset({"date", "amount", "category", "notes"}),
        exclude=_ALWAYS | {"vendor_id", "updated_at"},
        portable=frozenset({"vendor_name"}),
    ),
    JsonSection(
        "tax_records",
        TaxRecord,
        keys=frozenset({"date", "tax_type", "amount", "renewal_date", "notes"}),
        exclude=_ALWAYS,
    ),
    JsonSection(
        "toll_tags",
        TollTag,
        keys=frozenset({"toll_system", "tag_number", "status", "notes"}),
        exclude=_ALWAYS | {"updated_at"},
    ),
    JsonSection(
        "toll_transactions",
        TollTransaction,
        keys=frozenset({"date", "amount", "location", "notes"}),
        # The tag travels as its place in this file's toll_tags.
        exclude=_ALWAYS | {"toll_tag_id"},
        portable=frozenset({"toll_tag_index"}),
    ),
    JsonSection(
        "warranties",
        WarrantyRecord,
        keys=frozenset(
            {
                "warranty_type",
                "provider",
                "start_date",
                "end_date",
                "mileage_limit_km",
                "coverage_details",
                "policy_number",
                "notes",
            }
        ),
        exclude=_ALWAYS | {"last_notified_at"},  # notification marker
    ),
    JsonSection(
        "spot_rentals",
        SpotRental,
        keys=frozenset(
            {
                "location_name",
                "location_address",
                "check_in_date",
                "check_out_date",
                "nightly_rate",
                "weekly_rate",
                "monthly_rate",
                "electric",
                "water",
                "waste",
                "total_cost",
                "amenities",
                "notes",
            }
        ),
        exclude=_ALWAYS,
        portable=frozenset({"billings"}),
    ),
    JsonSection(
        "spot_rentals.billings",
        SpotRentalBilling,
        keys=frozenset(
            {"billing_date", "monthly_rate", "electric", "water", "waste", "total", "notes"}
        ),
        exclude=frozenset({"id", "spot_rental_id", "created_at"}),
    ),
    JsonSection(
        "supplies",
        Supply,
        keys=frozenset(
            {
                "name",
                "part_number",
                "barcode",
                "category",
                "unit_type",
                "volume_unit",
                "is_active",
                "notes",
            }
        ),
        # Pinned to this vehicle by being in the file; who made it is a user here.
        exclude=_ALWAYS | {"created_by_user_id", "updated_at"},
        portable=frozenset({"purchases", "usages", "used_elsewhere"}),
    ),
    JsonSection(
        "supplies.purchases",
        SupplyPurchase,
        keys=frozenset({"date", "quantity", "total_cost", "part_number", "notes"}),
        # The supply is the parent; the supplier travels by name, like a vendor.
        exclude=frozenset({"id", "supply_id", "supplier_id", "created_at"}),
        portable=frozenset({"supplier_name"}),
    ),
    JsonSection(
        "supplies.usages",
        SupplyUsage,
        # created_at is a standalone usage's ledger date.
        keys=frozenset({"quantity", "unit_cost_snapshot", "cost_snapshot", "created_at"}),
        # Standalone only; a line item's usage travels under its line item.
        exclude=frozenset({"id", "supply_id", "service_line_item_id"}),
    ),
    JsonSection(
        "supplies.used_elsewhere",
        SupplyUsage,
        keys=frozenset({"quantity", "unit_cost_snapshot", "cost_snapshot"}),
        # The other vehicle's line item is named by its visit and description;
        # the visit dates it.
        exclude=frozenset({"id", "supply_id", "service_line_item_id", "created_at"}),
        portable=frozenset({"vin", "date", "description", "item_index", "item_cost"}),
    ),
    JsonSection(
        "service_visits.line_items.supply_usages",
        SupplyUsage,
        keys=frozenset({"quantity", "unit_cost_snapshot", "cost_snapshot"}),
        # The line item is the parent; the supply travels as an index or a name key.
        exclude=frozenset({"id", "supply_id", "service_line_item_id", "created_at"}),
        portable=frozenset({"supply"}),
    ),
    JsonSection(
        "maintenance_rules",
        MaintenanceRule,
        keys=frozenset(
            {
                "maintenance_type",
                "title",
                "interval_km",
                "interval_months",
                "interval_days",
                "interval_hours",
                "source",
                "source_pack_id",
                "source_pack_key",
                "notes",
                "is_active",
            }
        ),
        exclude=_ALWAYS | {"updated_at"},
        portable=frozenset({"reminders"}),
    ),
    JsonSection(
        "maintenance_rules.reminders",
        Reminder,
        keys=_REMINDER_KEYS,
        exclude=_REMINDER_EXCLUDE,
    ),
    JsonSection(
        "manual_reminders",
        Reminder,
        keys=_REMINDER_KEYS,
        exclude=_REMINDER_EXCLUDE,
    ),
    JsonSection(
        "recalls",
        Recall,
        keys=frozenset(
            {
                "nhtsa_campaign_number",
                "component",
                "summary",
                "consequence",
                "remedy",
                "date_announced",
                "is_resolved",
                "resolved_at",
                "notes",
            }
        ),
        exclude=_ALWAYS,
    ),
    JsonSection(
        "dtcs",
        VehicleDTC,
        keys=frozenset(
            {
                "device_id",  # the WiCAN's id as text; no FK, nothing reads the link (K11)
                "code",
                "description",
                "severity",
                "user_notes",
                "first_seen",
                "last_seen",
                "cleared_at",
                "is_active",
            }
        ),
        exclude=_ALWAYS,
    ),
    JsonSection(
        "tire_sets",
        TireSet,
        keys=frozenset({"name", "notes"}),
        exclude=_ALWAYS,
    ),
    JsonSection(
        "tires",
        Tire,
        keys=frozenset(
            {
                "position",
                "brand",
                "model_name",
                "size",
                "dot_code",
                "retired_on",
                "tread_depth_mm",
                "pressure_kpa",
                "min_tread_mm",
                "notes",
                "storage_location",
            }
        ),
        # The set travels as its place in this file's tire_sets.
        exclude=_ALWAYS | {"set_id", "updated_at"},
        portable=frozenset({"set_index", "mount_periods", "readings"}),
    ),
    JsonSection(
        "tires.mount_periods",
        TireMountPeriod,
        keys=frozenset(
            {
                "position",
                "mounted_on",
                "dismounted_on",
                "mounted_odometer_km",
                "dismounted_odometer_km",
                "mounted_hours",
                "dismounted_hours",
                "is_assumed",
                "observed_active_on",
                "notes",
            }
        ),
        # The tire is the parent.
        exclude=frozenset({"id", "tire_id", "created_at"}),
    ),
    JsonSection(
        "tires.readings",
        TireReading,
        keys=frozenset(
            {
                "position",
                "recorded_at",
                "odometer_km",
                "engine_hours",
                "tread_depth_mm",
                "pressure_kpa",
                "notes",
            }
        ),
        # The tire is the parent. The period link is unused since 140, so it stays home (D2).
        exclude=_ALWAYS | {"tire_id", "mount_period_id"},
    ),
    JsonSection(
        "brake_axles",
        BrakeAxle,
        keys=frozenset(
            {
                "axle",
                "brake_type",
                "min_thickness_mm",
                "new_thickness_mm",
                "rotor_min_mm",
                "drum_max_mm",
            }
        ),
        exclude=_ALWAYS | {"updated_at"},
    ),
    JsonSection(
        "brake_jobs",
        BrakeJob,
        keys=frozenset(
            {
                "position",
                "brake_type",
                "performed_on",
                "odometer_km",
                "engine_hours",
                "friction_replaced",
                "surface",
                "notes",
            }
        ),
        exclude=_ALWAYS,
    ),
    JsonSection(
        "brake_measurements",
        BrakeMeasurement,
        keys=frozenset(
            {
                "position",
                "recorded_at",
                "odometer_km",
                "engine_hours",
                "inner_pad_mm",
                "outer_pad_mm",
                "rotor_mm",
                "shoe_mm",
                "drum_mm",
                "notes",
            }
        ),
        # The job travels as its place in this file's brake_jobs.
        exclude=_ALWAYS | {"brake_job_id"},
        portable=frozenset({"brake_job_index"}),
    ),
]


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession, test_user) -> str:
    """One row in every section, written once for the whole module."""
    if (await db_session.execute(select(Vehicle).where(Vehicle.vin == _VIN))).scalar():
        return _VIN
    day = date(2026, 9, 10)
    db_session.add(
        Vehicle(vin=_VIN, user_id=test_user["id"], nickname="Coverage", vehicle_type="RV")
    )
    await db_session.flush()
    visit = ServiceVisit(vin=_VIN, date=day, service_category="Maintenance")
    tag = TollTag(vin=_VIN, toll_system="EZ TAG", tag_number="B3COVTAG")
    rental = SpotRental(vin=_VIN, check_in_date=day)
    db_session.add_all(
        [
            visit,
            tag,
            rental,
            FuelRecord(vin=_VIN, date=day, odometer_km=Decimal("1.00"), liters=Decimal("1")),
            DEFRecord(vin=_VIN, date=day),
            OdometerRecord(vin=_VIN, date=day, odometer_km=Decimal("1.00")),
            HoursRecord(vin=_VIN, date=day, engine_hours=Decimal("1.0")),
            Note(vin=_VIN, date=day, content="x"),
            FinancingRecord(vin=_VIN, date=day, amount=Decimal("1"), category="upfront_fee"),
            TaxRecord(vin=_VIN, date=day, amount=Decimal("1")),
            WarrantyRecord(vin=_VIN, warranty_type="Other", start_date=day),
            Recall(vin=_VIN, component="x", summary="x"),
            VehicleDTC(vin=_VIN, device_id="b3bcoverage", code="P0420"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            ServiceLineItem(visit_id=visit.id, description="x"),
            TollTransaction(
                vin=_VIN, toll_tag_id=tag.id, date=day, amount=Decimal("1"), location="x"
            ),
            SpotRentalBilling(spot_rental_id=rental.id, billing_date=day),
        ]
    )
    # A rule and its reminder.
    rule = MaintenanceRule(vin=_VIN, title="Oil", interval_months=6, source="manual")
    db_session.add(rule)
    await db_session.flush()
    db_session.add(
        Reminder(vin=_VIN, rule_id=rule.id, title="Oil", reminder_type="date", due_date=day)
    )
    # A reminder a person made.
    db_session.add(Reminder(vin=_VIN, title="Plates", reminder_type="date", due_date=day))
    # A set, a tire in it, a period and a reading in that period.
    tire_set = TireSet(vin=_VIN, name="Winter")
    db_session.add(tire_set)
    await db_session.flush()
    tire = Tire(vin=_VIN, position="FL", set_id=tire_set.id)
    db_session.add(tire)
    await db_session.flush()
    period = TireMountPeriod(tire_id=tire.id, position="FL", mounted_on=day)
    db_session.add(period)
    await db_session.flush()
    db_session.add(
        TireReading(
            tire_id=tire.id,
            vin=_VIN,
            mount_period_id=period.id,
            recorded_at=day,
            tread_depth_mm=Decimal("8"),
        )
    )
    # An axle setup, a job and the check it wrote.
    brake_job = BrakeJob(
        vin=_VIN, position="FL", brake_type="disc", performed_on=day, friction_replaced=True
    )
    db_session.add_all(
        [
            brake_job,
            BrakeAxle(
                vin=_VIN,
                axle="front",
                brake_type="disc",
                min_thickness_mm=Decimal("3"),
                new_thickness_mm=Decimal("10"),
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        BrakeMeasurement(
            vin=_VIN,
            position="FL",
            recorded_at=day,
            inner_pad_mm=Decimal("9"),
            brake_job_id=brake_job.id,
        )
    )
    # A pinned supply with a purchase and an adjustment, a line item that used
    # it, and a line item on another vehicle's visit that used it too.
    pinned = Supply(name="Coverage oil", unit_type="volume", vin=_VIN)
    used_on = ServiceLineItem(visit_id=visit.id, description="oil")
    other = Vehicle(vin=_OTHER_VIN, user_id=test_user["id"], nickname="Other", vehicle_type="Car")
    db_session.add_all([pinned, used_on, other])
    await db_session.flush()
    elsewhere = ServiceVisit(vin=_OTHER_VIN, date=day, service_category="Maintenance")
    db_session.add(elsewhere)
    await db_session.flush()
    used_elsewhere = ServiceLineItem(visit_id=elsewhere.id, description="top up")
    db_session.add(used_elsewhere)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=pinned.id, date=day, quantity=Decimal("1")),
            SupplyUsage(supply_id=pinned.id, quantity=Decimal("0.5")),
            SupplyUsage(
                supply_id=pinned.id, service_line_item_id=used_on.id, quantity=Decimal("1")
            ),
            SupplyUsage(
                supply_id=pinned.id, service_line_item_id=used_elsewhere.id, quantity=Decimal("1")
            ),
        ]
    )
    await db_session.commit()
    return _VIN


def _rows_at(export: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """The rows at `path`: a top-level list, the vehicle object, or a list nested at any depth."""
    top, *nested = path.split(".")
    value = export[top]
    rows = [value] if isinstance(value, dict) else value
    for key in nested:
        rows = [child for row in rows for child in row[key]]
    return rows


@pytest.mark.parametrize("spec", SECTIONS, ids=lambda s: s.path)
async def test_every_model_column_is_exported_or_excluded(
    spec: JsonSection, client: AsyncClient, auth_headers, seeded: str
):
    response = await client.get(f"/api/export/vehicles/{seeded}/json", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = _rows_at(response.json(), spec.path)
    assert rows, f"{spec.path}: the fixture wrote no row, so there are no keys to check"

    # 1. The section writes exactly the declared keys.
    for row in rows:
        assert set(row) == spec.keys | spec.portable, (
            f"{spec.path}: exported {sorted(set(row))}, "
            f"declared {sorted(spec.keys | spec.portable)}"
        )

    # 2. Every model column is exported or excluded, never both.
    columns = {column.key for column in inspect(spec.model).columns}
    uncovered = columns - spec.keys - spec.exclude
    assert not uncovered, (
        f"{spec.path}: columns neither exported nor excluded: {sorted(uncovered)}. "
        "Export them, or exclude them here with the reason."
    )
    assert not spec.keys & spec.exclude, f"{spec.path}: both exported and excluded"

    # 3. Every declared name is a column (a stale name would weaken the check).
    assert not (spec.keys | spec.exclude) - columns, (
        f"{spec.path}: not model columns: {sorted((spec.keys | spec.exclude) - columns)}"
    )


def test_rows_at_walks_a_path_of_any_depth():
    export = {
        "vehicle": {"vin": "x"},
        "a": [{"b": [{"c": [{"k": 1}, {"k": 2}]}, {"c": []}]}, {"b": []}],
    }
    assert _rows_at(export, "vehicle") == [{"vin": "x"}]
    assert _rows_at(export, "a.b") == [{"c": [{"k": 1}, {"k": 2}]}, {"c": []}]
    # main: KeyError 'b.c', it only walks one level.
    assert _rows_at(export, "a.b.c") == [{"k": 1}, {"k": 2}]
