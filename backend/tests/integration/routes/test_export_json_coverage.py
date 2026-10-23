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
from app.models.financing import FinancingRecord
from app.models.spot_rental import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.toll import TollTag, TollTransaction

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_VIN = "B3RTJSONCOVERAGE1"

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
        portable=frozenset({"triggered_by_inspection"}),
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
]


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    """The export limiter is 5 a minute and this module exports once per section."""
    from app.routes.export import limiter as export_limiter

    export_limiter.reset()


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
    await db_session.commit()
    return _VIN


def _rows_at(export: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """The rows at `path`: a top-level list, the vehicle object, or a nested list."""
    top, _, nested = path.partition(".")
    value = export[top]
    rows = [value] if isinstance(value, dict) else value
    if nested:
        rows = [child for row in rows for child in row[nested]]
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
