"""Service visits round-trip whole: CSV v8 visit numbers, JSON v9 line items (batch 3a task 2)."""

import csv
import io
import json
import zlib
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import OdometerRecord, ServiceLineItem, ServiceVisit, Vehicle, Vendor

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_V8_HEADER = (
    "units_version,unit_system,Visit,Date,Category,Description,Odometer (km),Engine Hours,"
    "Cost,Vendor,Item Notes,Tax,Shop Supplies,Misc Fees,Insurance Claim,Visit Notes"
)


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    """The import and export limiters are per route; this module posts more than they allow."""
    from app.routes.export import limiter as export_limiter
    from app.routes.import_data import limiter as import_limiter

    export_limiter.reset()
    import_limiter.reset()


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Service",
        )
    )
    await db_session.commit()
    return vin


async def _vendor(db_session: AsyncSession, name: str) -> int:
    existing = (await db_session.execute(select(Vendor).where(Vendor.name == name))).scalar()
    if existing is not None:
        return existing.id
    vendor = Vendor(name=name)
    db_session.add(vendor)
    await db_session.commit()
    return vendor.id


async def _post_csv(
    client: AsyncClient, headers: dict, vin: str, body: str, *, skip: bool = True
) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/service/csv",
        headers=headers,
        files={"file": ("service.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true" if skip else "false"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _post_json(client: AsyncClient, headers: dict, vin: str, payload: dict) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _visits(sessionmaker: Any, vin: str) -> list[ServiceVisit]:
    """The vehicle's visits oldest first, items loaded, through a fresh session."""
    async with sessionmaker() as fresh:
        result = await fresh.execute(
            select(ServiceVisit)
            .where(ServiceVisit.vin == vin)
            .options(
                selectinload(ServiceVisit.line_items),
                selectinload(ServiceVisit.vendor),
            )
            .order_by(ServiceVisit.date, ServiceVisit.id)
        )
        return list(result.scalars().all())


def _items(visit: ServiceVisit) -> list[tuple[str, Decimal | None, str | None]]:
    return [(i.description, i.cost, i.notes) for i in visit.line_items]


async def _seed_two_item_visit(db_session: AsyncSession, vin: str, vendor_name: str) -> None:
    """A two-item visit with fees and both kinds of notes, and a visit with no items."""
    vendor_id = await _vendor(db_session, vendor_name)
    visit = ServiceVisit(
        vin=vin,
        vendor_id=vendor_id,
        date=date(2026, 7, 1),
        odometer_km=Decimal("5000.00"),
        engine_hours=Decimal("10.0"),
        service_category="Maintenance",
        tax_amount=Decimal("3.00"),
        shop_supplies=Decimal("1.50"),
        misc_fees=Decimal("0.50"),
        insurance_claim_number="CLM-1",
        notes="visit note",
        total_cost=Decimal("55.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add_all(
        [
            ServiceLineItem(
                visit_id=visit.id, description="Oil", cost=Decimal("40.00"), notes="5W-30"
            ),
            ServiceLineItem(visit_id=visit.id, description="Filter", cost=Decimal("10.00")),
        ]
    )
    db_session.add(
        ServiceVisit(
            vin=vin,
            date=date(2026, 6, 1),
            odometer_km=Decimal("4000.00"),
            service_category="Inspection",
        )
    )
    await db_session.commit()


# -- CSV v8: one row per line item, with its visit number ----------------------


async def test_the_service_csv_export_numbers_each_visit_and_splits_the_notes(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCEXPORT0001")
    await _seed_two_item_visit(db_session, vin, "B3 Svc Export Shop")

    r = await client.get(
        f"/api/export/vehicles/{vin}/service/csv?units=metric", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    rows = list(csv.reader(io.StringIO(r.text)))

    # main: the v7 header (eight columns after the two markers), and "Notes" merging
    # the item's and the visit's
    assert rows[0] == _V8_HEADER.split(",")
    assert rows[1:] == [
        [
            "8",
            "metric",
            "1",
            "2026-07-01",
            "Maintenance",
            "Oil",
            "5000.00",
            "10.0",
            "40.00",
            "B3 Svc Export Shop",
            "5W-30",
            "3.00",
            "1.50",
            "0.50",
            "CLM-1",
            "visit note",
        ],
        [
            "8",
            "metric",
            "1",
            "2026-07-01",
            "Maintenance",
            "Filter",
            "5000.00",
            "10.0",
            "10.00",
            "B3 Svc Export Shop",
            "",
            "3.00",
            "1.50",
            "0.50",
            "CLM-1",
            "visit note",
        ],
        [
            "8",
            "metric",
            "2",
            "2026-06-01",
            "Inspection",
            "",
            "4000.00",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
    ]


async def test_a_v8_service_csv_imports_each_visit_number_as_one_visit(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Visits 1 and 2 share a day, odometer, shop and category; the number keeps them apart."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCV8GROUP001")
    body = (
        f"{_V8_HEADER}\n"
        "8,metric,1,2026-07-01,Maintenance,Oil change,5000.00,10.0,40.00,B3 Svc Shop B,"
        "5W-30,3.00,1.50,0.50,CLM-1,visit note\n"
        "8,metric,1,2026-07-01,Maintenance,Air filter,5000.00,10.0,10.00,B3 Svc Shop B,"
        ",3.00,1.50,0.50,CLM-1,visit note\n"
        "8,metric,2,2026-07-01,Maintenance,Wiper blades,5000.00,10.0,20.00,B3 Svc Shop B,"
        ",,,,,\n"
    )
    data = await _post_csv(client, auth_headers, vin, body)
    assert (data["success_count"], data["skipped_count"], data["error_count"]) == (3, 0, 0), data

    first, second = await _visits(test_sessionmaker, vin)  # main: three visits
    assert _items(first) == [
        ("Oil change", Decimal("40.00"), "5W-30"),
        ("Air filter", Decimal("10.00"), None),
    ]
    assert (first.tax_amount, first.shop_supplies, first.misc_fees) == (
        Decimal("3.00"),
        Decimal("1.50"),
        Decimal("0.50"),
    )
    assert (first.insurance_claim_number, first.notes) == ("CLM-1", "visit note")
    assert first.vendor.name == "B3 Svc Shop B"
    # 40 + 10 + 3 + 1.50 + 0.50
    assert first.total_cost == Decimal("55.00")
    assert _items(second) == [("Wiper blades", Decimal("20.00"), None)]
    assert (second.tax_amount, second.notes, second.total_cost) == (None, None, Decimal("20.00"))


async def test_a_v8_visit_row_with_no_item_imports_a_visit_with_no_items(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCV8NOITEM01")
    body = f"{_V8_HEADER}\n8,metric,1,2026-06-01,Inspection,,4000.00,,,,,,,,,checked\n"
    data = await _post_csv(client, auth_headers, vin, body)
    assert data["success_count"] == 1, data
    (visit,) = await _visits(test_sessionmaker, vin)
    # main: one line item named "Inspection" with cost 0
    assert visit.line_items == []
    assert (visit.service_category, visit.notes, visit.total_cost) == (
        "Inspection",
        "checked",
        Decimal("0"),
    )


async def test_a_v7_service_csv_groups_one_visits_rows(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """A v7 file has no visit number: one visit's rows share date, odometer, shop and category.

    Every v7 row carried the visit's notes when its item had none, so the same
    Notes on every row of a group are the visit's.
    """
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCV7GROUP001")
    body = (
        "units_version,unit_system,Date,Category,Description,Odometer (km),Engine Hours,"
        "Cost,Vendor,Notes\n"
        "7,metric,2026-07-02,Maintenance,Oil,6000.00,11.0,40.00,B3 Svc Shop C,shared\n"
        "7,metric,2026-07-02,Maintenance,Filter,6000.00,11.0,10.00,B3 Svc Shop C,shared\n"
        "7,metric,2026-07-02,Collision,Bumper,6000.00,11.0,300.00,B3 Svc Shop C,shared\n"
    )
    data = await _post_csv(client, auth_headers, vin, body)
    assert (data["success_count"], data["skipped_count"], data["error_count"]) == (3, 0, 0), data

    visits = await _visits(test_sessionmaker, vin)
    # main: rows 2 and 3 skipped as duplicates of row 1, one visit with one item
    assert [(v.service_category, _items(v), v.notes) for v in visits] == [
        (
            "Maintenance",
            [("Oil", Decimal("40.00"), None), ("Filter", Decimal("10.00"), None)],
            "shared",
        ),
        ("Collision", [("Bumper", Decimal("300.00"), None)], "shared"),
    ]


async def test_a_v7_group_whose_notes_differ_keeps_them_on_the_items(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCV7NOTES001")
    body = (
        "units_version,unit_system,Date,Category,Description,Odometer (km),Engine Hours,"
        "Cost,Vendor,Notes\n"
        "7,metric,2026-07-03,Maintenance,Oil,7000.00,,40.00,B3 Svc Shop C,5W-30\n"
        "7,metric,2026-07-03,Maintenance,Filter,7000.00,,10.00,B3 Svc Shop C,OEM\n"
    )
    data = await _post_csv(client, auth_headers, vin, body, skip=False)
    assert data["success_count"] == 2, data
    (visit,) = await _visits(test_sessionmaker, vin)  # main: two visits
    assert visit.notes is None
    assert _items(visit) == [
        ("Oil", Decimal("40.00"), "5W-30"),
        ("Filter", Decimal("10.00"), "OEM"),
    ]


async def test_a_v7_visit_reimported_into_its_vehicle_skips_every_row(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """A v7 export of a three-item visit, posted back to the vehicle that holds it.

    Its three rows are one visit, so they match the stored visit once and are
    all skipped; matched one row at a time, rows 2 and 3 found nothing left to
    match and imported as new visits.
    """
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCV7REIMP001")
    vendor_id = await _vendor(db_session, "B3 Svc Shop D")
    visit = ServiceVisit(
        vin=vin,
        vendor_id=vendor_id,
        date=date(2026, 7, 7),
        odometer_km=Decimal("6500.00"),
        service_category="Maintenance",
        notes="spring",
        total_cost=Decimal("65.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add_all(
        [
            ServiceLineItem(visit_id=visit.id, description="Oil", cost=Decimal("40.00")),
            ServiceLineItem(visit_id=visit.id, description="Filter", cost=Decimal("10.00")),
            ServiceLineItem(visit_id=visit.id, description="Wipers", cost=Decimal("15.00")),
        ]
    )
    await db_session.commit()
    # What the v7 export wrote: one row per item, the visit's notes on each.
    body = (
        "units_version,unit_system,Date,Category,Description,Odometer (km),Engine Hours,"
        "Cost,Vendor,Notes\n"
        "7,metric,2026-07-07,Maintenance,Oil,6500.00,,40.00,B3 Svc Shop D,spring\n"
        "7,metric,2026-07-07,Maintenance,Filter,6500.00,,10.00,B3 Svc Shop D,spring\n"
        "7,metric,2026-07-07,Maintenance,Wipers,6500.00,,15.00,B3 Svc Shop D,spring\n"
    )

    data = await _post_csv(client, auth_headers, vin, body)
    # e8b964e8: (2, 1, 0), rows 2 and 3 written as two new one-item visits
    assert (data["success_count"], data["skipped_count"], data["error_count"]) == (0, 3, 0), data
    visits = await _visits(test_sessionmaker, vin)
    assert [(v.id, len(v.line_items)) for v in visits] == [(visit.id, 3)]


async def test_a_service_csv_round_trip_keeps_items_fees_and_notes(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(db_session, test_user["id"], "B3RTSVCCSVSRC0001")
    target = await _vehicle(db_session, test_user["id"], "B3RTSVCCSVDST0001")
    await _seed_two_item_visit(db_session, source, "B3 Svc Round Shop")

    exported = await client.get(
        f"/api/export/vehicles/{source}/service/csv?units=metric", headers=auth_headers
    )
    assert exported.status_code == 200, exported.text
    data = await _post_csv(client, auth_headers, target, exported.text)
    assert data["error_count"] == 0, data

    empty, full = await _visits(test_sessionmaker, target)
    # main: three visits, fees and the claim number dropped, notes merged
    assert (empty.date, empty.line_items, empty.service_category) == (
        date(2026, 6, 1),
        [],
        "Inspection",
    )
    assert _items(full) == [("Oil", Decimal("40.00"), "5W-30"), ("Filter", Decimal("10.00"), None)]
    assert (
        full.tax_amount,
        full.shop_supplies,
        full.misc_fees,
        full.insurance_claim_number,
        full.notes,
        full.engine_hours,
        full.total_cost,
    ) == (
        Decimal("3.00"),
        Decimal("1.50"),
        Decimal("0.50"),
        "CLM-1",
        "visit note",
        Decimal("10.0"),
        Decimal("55.00"),
    )


# -- JSON v9: service_visits with nested line items ----------------------------


async def test_a_json_backup_round_trip_keeps_every_line_item(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(db_session, test_user["id"], "B3RTSVCJSONSRC001")
    target = await _vehicle(db_session, test_user["id"], "B3RTSVCJSONDST001")
    vendor_id = await _vendor(db_session, "B3 Svc Json Shop")
    visit = ServiceVisit(
        vin=source,
        vendor_id=vendor_id,
        date=date(2026, 7, 4),
        odometer_km=Decimal("8000.00"),
        engine_hours=Decimal("12.3"),
        service_category="Inspection",
        tax_amount=Decimal("4.00"),
        shop_supplies=Decimal("2.00"),
        misc_fees=Decimal("1.00"),
        insurance_claim_number="CLM-9",
        notes="annual",
        total_cost=Decimal("187.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    inspection = ServiceLineItem(
        visit_id=visit.id,
        description="Brake inspection",
        category="Inspection",
        maintenance_type="brake_inspection",
        cost=Decimal("0.00"),
        is_inspection=True,
        inspection_result="failed",
        inspection_severity="red",
    )
    db_session.add(inspection)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(
            visit_id=visit.id,
            description="Replace pads",
            category="Maintenance",
            maintenance_type="brake_pads",
            cost=Decimal("180.00"),
            notes="front",
            triggered_by_inspection_id=inspection.id,
        )
    )
    await db_session.commit()

    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    data = await _post_json(client, auth_headers, target, exported.json())
    assert data["service_records"]["success_count"] == 1, data

    (restored,) = await _visits(test_sessionmaker, target)
    found, pads = restored.line_items
    # main: one line item, "Brake inspection", carrying the visit total of 187.00
    assert [
        (
            i.description,
            i.category,
            i.maintenance_type,
            i.cost,
            i.notes,
            i.is_inspection,
            i.inspection_result,
            i.inspection_severity,
        )
        for i in restored.line_items
    ] == [
        (
            "Brake inspection",
            "Inspection",
            "brake_inspection",
            Decimal("0.00"),
            None,
            True,
            "failed",
            "red",
        ),
        (
            "Replace pads",
            "Maintenance",
            "brake_pads",
            Decimal("180.00"),
            "front",
            False,
            None,
            None,
        ),
    ]
    assert pads.triggered_by_inspection_id == found.id
    assert (
        restored.engine_hours,
        restored.tax_amount,
        restored.shop_supplies,
        restored.misc_fees,
        restored.insurance_claim_number,
        restored.notes,
        restored.vendor.name,
        restored.total_cost,
    ) == (
        Decimal("12.3"),
        Decimal("4.00"),
        Decimal("2.00"),
        Decimal("1.00"),
        "CLM-9",
        "annual",
        "B3 Svc Json Shop",
        Decimal("187.00"),
    )


async def test_a_line_item_link_outside_its_visit_is_a_row_error(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCJSONLINK01")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "service_visits": [
                {
                    "date": "2026-07-05",
                    "odometer_km": 9000.0,
                    "line_items": [
                        {"description": "Pads", "cost": 100.0, "triggered_by_inspection": 3}
                    ],
                }
            ],
        },
    )
    # main: the section is ignored, nothing counted
    assert data["service_records"]["error_count"] == 1, data
    assert data["errors"] == [
        "Service visit 0: line item 0: triggered_by_inspection must be the index "
        "of another line item in this visit"
    ]
    assert await _visits(test_sessionmaker, vin) == []


_CATEGORY_WORDS = "Maintenance, Inspection, Collision, Upgrades, Detailing"


@pytest.mark.parametrize(
    ("visit", "reason"),
    [
        pytest.param(
            {"tax_amount": "abc", "line_items": []},
            "tax_amount is not a number",
            id="a-fee-that-is-not-a-number",
        ),
        pytest.param(
            {"misc_fees": True, "line_items": []},
            "misc_fees is not a number",
            id="a-fee-that-is-a-bool",
        ),
        pytest.param({"line_items": "Oil"}, "line_items must be a list", id="items-not-a-list"),
        pytest.param({}, "line_items must be a list", id="items-missing"),
        pytest.param(
            {"line_items": ["Oil"]}, "line item 0: must be an object", id="item-not-an-object"
        ),
        pytest.param(
            {"line_items": [{"description": "Oil", "category": "Bogus"}]},
            f"line item 0: category must be one of {_CATEGORY_WORDS}",
            id="item-category",
        ),
        pytest.param(
            {"line_items": [{"description": "Pads", "inspection_result": "meh"}]},
            "line item 0: inspection_result must be one of passed, failed, needs_attention",
            id="item-inspection-result",
        ),
        pytest.param(
            {"line_items": [{"description": "Pads", "inspection_severity": "blue"}]},
            "line item 0: inspection_severity must be one of green, yellow, red",
            id="item-inspection-severity",
        ),
        pytest.param(
            {"line_items": [{"description": "Oil", "maintenance_type": "Oil Change"}]},
            "line item 0: maintenance_type must be a lowercase snake_case code (2-50 chars)",
            id="item-maintenance-type",
        ),
        pytest.param(
            {"line_items": [{"description": 5}]},
            "line item 0: description must be text",
            id="item-description-not-text",
        ),
        pytest.param({"notes": 5, "line_items": []}, "notes must be text", id="notes-not-text"),
        pytest.param(
            {"insurance_claim_number": 123, "line_items": []},
            "insurance_claim_number must be text",
            id="claim-not-text",
        ),
        pytest.param(
            {"vendor_name": 7, "line_items": []}, "vendor_name must be text", id="vendor-not-text"
        ),
        pytest.param(
            {
                "tax_amount": 1.0,
                "line_items": [{"description": "Engine", "cost": 9999999999.99}],
            },
            "The visit total would exceed the largest amount MyGarage can store (9999999999.99)",
            id="total-past-the-column",
        ),
    ],
)
async def test_a_json_visit_the_api_would_refuse_is_a_row_error(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
    visit: dict[str, Any],
    reason: str,
    request: pytest.FixtureRequest,
):
    """Each refusal names its reason, and the backends agree: nothing is written (R2)."""
    # One vehicle per case: the suite's database outlives a test.
    case = zlib.crc32(request.node.callspec.id.encode()) % 10**9
    vin = await _vehicle(db_session, test_user["id"], f"B3SVCBAD{case:09d}")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "9",
            "units": "metric",
            "service_visits": [{"date": "2026-07-11", "odometer_km": 9200.0, **visit}],
        },
    )
    assert data["errors"] == [f"Service visit 0: {reason}"], data
    assert await _visits(test_sessionmaker, vin) == []


async def test_a_json_visit_at_a_vendor_past_100_characters_restores_with_it(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The CSV and v8 imports make vendors with no length cap and SQLite keeps the whole
    name, so the v9 backup has to bring the visit back on that same vendor."""
    if db_session.get_bind().dialect.name != "sqlite":
        pytest.skip("only SQLite stores a vendor name past its column")
    source = await _vehicle(db_session, test_user["id"], "B3RTSVCLONGVSRC01")
    target = await _vehicle(db_session, test_user["id"], "B3RTSVCLONGVDST01")
    long_name = "B3 Long Shop " + "v" * 88
    assert len(long_name) == 101
    vendor_id = await _vendor(db_session, long_name)
    db_session.add(
        ServiceVisit(
            vin=source,
            vendor_id=vendor_id,
            date=date(2026, 7, 14),
            odometer_km=Decimal("9400.00"),
            service_category="Maintenance",
            total_cost=Decimal("0.00"),
        )
    )
    await db_session.commit()

    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    assert exported.json()["service_visits"][0]["vendor_name"] == long_name
    data = await _post_json(client, auth_headers, target, exported.json())
    # 30150423: a row error, "vendor_name must be at most 100 characters"
    assert (data["service_records"]["success_count"], data["errors"]) == (1, []), data
    (restored,) = await _visits(test_sessionmaker, target)
    assert (restored.vendor_id, restored.vendor.name) == (vendor_id, long_name)


async def test_a_csv_visit_whose_total_is_past_the_column_is_a_row_error_on_every_row(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Each amount fits on its own; the visit total they add up to does not."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCCSVBIG0001")
    body = (
        f"{_V8_HEADER}\n"
        "8,metric,1,2026-07-12,Maintenance,Engine,9300.00,,9999999999.99,,,1.00,,,,\n"
        "8,metric,1,2026-07-12,Maintenance,Oil,9300.00,,40.00,,,1.00,,,,\n"
    )
    data = await _post_csv(client, auth_headers, vin, body)
    reason = "The visit total would exceed the largest amount MyGarage can store (9999999999.99)"
    assert (data["success_count"], data["error_count"]) == (0, 2), data
    assert data["errors"] == [f"Row 2: {reason}", f"Row 3: {reason}"]
    assert await _visits(test_sessionmaker, vin) == []


async def test_a_v8_service_records_backup_still_imports_and_syncs_its_reading(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCJSONV8REC1")
    data = await _post_json(
        client,
        auth_headers,
        vin,
        {
            "export_version": "8",
            "units": "metric",
            "service_records": [
                {
                    "date": "2026-07-06",
                    "service_category": "Maintenance",
                    "service_type": "Oil",
                    "odometer_km": 9100.0,
                    "cost": 45.0,
                    "vendor_name": None,
                    "notes": "v8",
                }
            ],
        },
    )
    assert data["service_records"]["success_count"] == 1, data
    (visit,) = await _visits(test_sessionmaker, vin)
    assert (_items(visit), visit.notes) == ([("Oil", Decimal("45.00"), None)], "v8")
    async with test_sessionmaker() as fresh:
        readings = (
            await fresh.execute(
                select(OdometerRecord.odometer_km, OdometerRecord.source).where(
                    OdometerRecord.vin == vin
                )
            )
        ).all()
    # main: [] (no sync on a JSON import)
    assert [tuple(r) for r in readings] == [(Decimal("9100.00"), "service_visit")]


async def test_a_visit_sharing_a_stored_visits_day_and_odometer_still_imports(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Same day and odometer, other work: a different visit, so it imports (R1-H1)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCSHAREKEY01")
    stored = ServiceVisit(
        vin=vin,
        date=date(2026, 7, 8),
        odometer_km=Decimal("6000.00"),
        service_category="Maintenance",
        total_cost=Decimal("40.00"),
    )
    db_session.add(stored)
    await db_session.flush()
    db_session.add(ServiceLineItem(visit_id=stored.id, description="Oil", cost=Decimal("40.00")))
    await db_session.commit()
    body = f"{_V8_HEADER}\n8,metric,1,2026-07-08,Maintenance,Wipers,6000.00,,20.00,,,,,,,\n"

    data = await _post_csv(client, auth_headers, vin, body)
    # main: (0, 1), skipped on the day and odometer alone
    assert (data["success_count"], data["skipped_count"]) == (1, 0), data
    again = await _post_csv(client, auth_headers, vin, body)
    assert (again["success_count"], again["skipped_count"]) == (0, 1), again
    visits = await _visits(test_sessionmaker, vin)
    assert [_items(v) for v in visits] == [
        [("Oil", Decimal("40.00"), None)],
        [("Wipers", Decimal("20.00"), None)],
    ]


async def _seed_taxed_visit(db_session: AsyncSession, vin: str, tax: str) -> None:
    """Visit B of the partial-target tests: one $40 oil change and its tax."""
    visit = ServiceVisit(
        vin=vin,
        date=date(2026, 7, 9),
        odometer_km=Decimal("7000.00"),
        service_category="Maintenance",
        tax_amount=Decimal(tax),
        total_cost=Decimal("40.00") + Decimal(tax),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(ServiceLineItem(visit_id=visit.id, description="Oil", cost=Decimal("40.00")))
    await db_session.commit()


async def _taxes(sessionmaker: Any, vin: str) -> list[Decimal | None]:
    return sorted(v.tax_amount for v in await _visits(sessionmaker, vin))


async def test_a_json_visit_differing_only_in_tax_does_not_spend_another_visits_match(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The target holds B ($10 tax); the file lists A ($5), then B. A must not take B's match."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCTAXJSON001")
    await _seed_taxed_visit(db_session, vin, "10.00")
    visit = {
        "date": "2026-07-09",
        "odometer_km": 7000.0,
        "service_category": "Maintenance",
        "vendor_name": None,
        "line_items": [{"description": "Oil", "cost": 40.0}],
    }
    payload = {
        "export_version": "9",
        "units": "metric",
        "service_visits": [{**visit, "tax_amount": 5.0}, {**visit, "tax_amount": 10.0}],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # main: [Decimal('10.00')], the section isn't read
    assert await _taxes(test_sessionmaker, vin) == [Decimal("5.00"), Decimal("10.00")]
    assert (data["service_records"]["success_count"], data["service_records"]["skipped_count"]) == (
        1,
        1,
    ), data


async def test_a_csv_visit_differing_only_in_tax_does_not_spend_another_visits_match(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCTAXCSV0001")
    await _seed_taxed_visit(db_session, vin, "10.00")
    body = (
        f"{_V8_HEADER}\n"
        "8,metric,1,2026-07-09,Maintenance,Oil,7000.00,,40.00,,,5.00,,,,\n"
        "8,metric,2,2026-07-09,Maintenance,Oil,7000.00,,40.00,,,10.00,,,,\n"
    )
    data = await _post_csv(client, auth_headers, vin, body)
    # main: [Decimal('10.00')], both rows skipped on the day and odometer
    assert await _taxes(test_sessionmaker, vin) == [Decimal("5.00"), Decimal("10.00")]
    assert (data["success_count"], data["skipped_count"]) == (1, 1), data


async def test_a_header_only_service_csv_imports_nothing(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """The key flags come from the header, so an upload with no rows is not a 500 (Fable F-2)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCHEADONLY01")
    data = await _post_csv(client, auth_headers, vin, f"{_V8_HEADER}\n")
    assert (data["success_count"], data["error_count"], data["skipped_count"]) == (0, 0, 0)


async def test_a_formula_quoted_cell_round_trips_as_typed(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The export quotes a cell that starts like a formula; the import takes the quote off
    again, so the restored text is what was typed and a re-import matches it (Fable F-4)."""
    source = await _vehicle(db_session, test_user["id"], "B3RTSVCFORMULA001")
    target = await _vehicle(db_session, test_user["id"], "B3RTSVCFORMULA002")
    vendor_id = await _vendor(db_session, "-B3 Formula Garage")
    visit = ServiceVisit(
        vin=source,
        vendor_id=vendor_id,
        date=date(2026, 7, 10),
        odometer_km=Decimal("7100.00"),
        service_category="Maintenance",
        notes="+ also checked the lights",
        total_cost=Decimal("30.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(visit_id=visit.id, description="=Brake fluid", cost=Decimal("30.00"))
    )
    await db_session.commit()
    exported = await client.get(
        f"/api/export/vehicles/{source}/service/csv?units=metric", headers=auth_headers
    )
    assert exported.status_code == 200, exported.text
    assert "'=Brake fluid" in exported.text  # the export's own guard, unchanged

    data = await _post_csv(client, auth_headers, target, exported.text)
    assert data["success_count"] == 1, data
    (restored,) = await _visits(test_sessionmaker, target)
    # main: ("'=Brake fluid", "'-B3 Formula Garage", "'+ also checked the lights")
    assert (restored.line_items[0].description, restored.vendor.name, restored.notes) == (
        "=Brake fluid",
        "-B3 Formula Garage",
        "+ also checked the lights",
    )
    again = await _post_csv(client, auth_headers, target, exported.text)
    assert (again["success_count"], again["skipped_count"]) == (0, 1), again


async def test_a_typed_quote_before_a_formula_lead_round_trips_as_typed(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """C-3: text that already starts with a quote and a formula lead comes back whole."""
    source = await _vehicle(db_session, test_user["id"], "B3RTSVCFORMULA003")
    target = await _vehicle(db_session, test_user["id"], "B3RTSVCFORMULA004")
    visit = ServiceVisit(
        vin=source,
        date=date(2026, 7, 12),
        odometer_km=Decimal("7150.00"),
        service_category="Maintenance",
        total_cost=Decimal("30.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(visit_id=visit.id, description="'=Literal", cost=Decimal("30.00"))
    )
    await db_session.commit()
    exported = await client.get(
        f"/api/export/vehicles/{source}/service/csv?units=metric", headers=auth_headers
    )
    assert exported.status_code == 200, exported.text

    data = await _post_csv(client, auth_headers, target, exported.text)
    assert data["success_count"] == 1, data
    (restored,) = await _visits(test_sessionmaker, target)
    # a354f33a: "=Literal", the typed quote read as the export's escape
    assert restored.line_items[0].description == "'=Literal"


@pytest.mark.parametrize(
    ("suffix", "field", "value"),
    [
        ("001", "inspection_result", "failed"),
        ("002", "inspection_severity", "red"),
        ("003", "category", "Maintenance"),
        ("004", "is_inspection", False),
    ],
)
async def test_a_json_visit_whose_item_differs_beyond_description_and_cost_imports(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
    suffix: str,
    field: str,
    value: Any,
):
    """A failed inspection isn't the passed one stored on the same day (R1-H1)."""
    vin = await _vehicle(db_session, test_user["id"], f"B3RTSVCITEMKEY{suffix}")
    visit = ServiceVisit(
        vin=vin,
        date=date(2026, 7, 10),
        odometer_km=Decimal("9000.00"),
        service_category="Inspection",
        total_cost=Decimal("0.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(
            visit_id=visit.id,
            description="Brake inspection",
            category="Inspection",
            cost=Decimal("0.00"),
            is_inspection=True,
            inspection_result="passed",
            inspection_severity="green",
        )
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    own_export = exported.json()
    (stored_visit,) = own_export["service_visits"]
    other = {
        "export_version": own_export["export_version"],
        "units": own_export["units"],
        "service_visits": [
            {
                **stored_visit,
                "line_items": [{**stored_visit["line_items"][0], field: value}],
            }
        ],
    }

    data = await _post_json(client, auth_headers, vin, other)
    # main: (0, 1), matched on (description, cost) alone
    assert (
        data["service_records"]["success_count"],
        data["service_records"]["skipped_count"],
    ) == (1, 0), data
    again = await _post_json(client, auth_headers, vin, own_export)
    assert (
        again["service_records"]["success_count"],
        again["service_records"]["skipped_count"],
    ) == (0, 1), again
    assert len(await _visits(test_sessionmaker, vin)) == 2


@pytest.mark.parametrize(
    ("suffix", "drop", "cells", "expected"),
    [
        # Tax but no claim column: the stored claim isn't compared, so it matches.
        ("1", "Insurance Claim", "5.00,", (0, 1)),
        # A claim but no Tax column: another claim number is another visit.
        ("2", "Tax", ",CLM-8", (1, 0)),
    ],
    ids=["tax-without-claim", "claim-without-tax"],
)
async def test_each_service_csv_fee_column_is_keyed_only_when_the_sheet_has_it(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    suffix: str,
    drop: str,
    cells: str,
    expected: tuple[int, int],
):
    """One header check per fee column, as the JSON path does (F-3, T-16)."""
    vin = await _vehicle(db_session, test_user["id"], f"B3RTSVCFEECOLS00{suffix}")
    visit = ServiceVisit(
        vin=vin,
        date=date(2026, 7, 11),
        odometer_km=Decimal("7200.00"),
        service_category="Maintenance",
        tax_amount=Decimal("5.00"),
        insurance_claim_number="CLM-7",
        total_cost=Decimal("45.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(ServiceLineItem(visit_id=visit.id, description="Oil", cost=Decimal("40.00")))
    await db_session.commit()
    header = (
        "units_version,unit_system,Visit,Date,Category,Description,Odometer (km),"
        "Cost,Tax,Shop Supplies,Insurance Claim"
    ).replace(f",{drop}", "")
    body = f"{header}\n8,metric,1,2026-07-11,Maintenance,Oil,7200.00,40.00,{cells}\n"

    data = await _post_csv(client, auth_headers, vin, body)
    assert (data["success_count"], data["skipped_count"]) == expected, data


@pytest.mark.parametrize(
    ("suffix", "field", "value"),
    [("1", "engine_hours", 13.3), ("2", "service_category", "Inspection")],
)
async def test_a_json_visit_differing_in_hours_or_category_imports(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    suffix: str,
    field: str,
    value: Any,
):
    """C-5: the visit's own engine hours and category were missing from its key."""
    vin = await _vehicle(db_session, test_user["id"], f"B3RTSVCVISITKEY0{suffix}")
    visit = ServiceVisit(
        vin=vin,
        date=date(2026, 7, 15),
        odometer_km=Decimal("9500.00"),
        engine_hours=Decimal("12.3"),
        service_category="Maintenance",
        total_cost=Decimal("40.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(ServiceLineItem(visit_id=visit.id, description="Oil", cost=Decimal("40.00")))
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    own_export = exported.json()
    (stored,) = own_export["service_visits"]
    other = {
        "export_version": own_export["export_version"],
        "units": own_export["units"],
        "service_visits": [{**stored, field: value}],
    }

    data = await _post_json(client, auth_headers, vin, other)
    # a354f33a: (0, 1), neither column was in the key
    assert (
        data["service_records"]["success_count"],
        data["service_records"]["skipped_count"],
    ) == (1, 0), data
    again = await _post_json(client, auth_headers, vin, own_export)
    assert (
        again["service_records"]["success_count"],
        again["service_records"]["skipped_count"],
    ) == (0, 1), again


# -- PR Codex round 2 ------------------------------------------------------------


async def test_two_same_day_v7_visits_on_an_hours_only_vehicle_stay_apart(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Q-1: no odometer, same shop and category, 10 h and 20 h: two visits, not one at 10 h."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCHOURSGRP01")
    body = (
        "units_version,unit_system,Date,Category,Description,Odometer (km),Engine Hours,"
        "Cost,Vendor,Notes\n"
        "7,metric,2026-07-20,Maintenance,Oil,,10.0,40.00,B3 Hours Shop,\n"
        "7,metric,2026-07-20,Maintenance,Filter,,20.0,10.00,B3 Hours Shop,\n"
    )
    data = await _post_csv(client, auth_headers, vin, body, skip=False)
    assert (data["success_count"], data["error_count"]) == (2, 0), data
    visits = await _visits(test_sessionmaker, vin)
    # 2fbc4248: one visit at 10.0 h holding both items
    assert sorted((v.engine_hours, [i.description for i in v.line_items]) for v in visits) == [
        (Decimal("10.0"), ["Oil"]),
        (Decimal("20.0"), ["Filter"]),
    ]


async def _visit_totals(sessionmaker: Any, vin: str) -> list[tuple[Decimal, Decimal, Decimal]]:
    """(stored total, sum of stored item costs, calculated total) per visit."""
    async with sessionmaker() as fresh:
        visits = (
            await fresh.execute(
                select(ServiceVisit)
                .where(ServiceVisit.vin == vin)
                .options(
                    selectinload(ServiceVisit.line_items).selectinload(
                        ServiceLineItem.supply_usages
                    )
                )
            )
        ).scalars()
        return [
            (
                v.total_cost,
                sum((i.cost or Decimal(0) for i in v.line_items), Decimal(0)),
                v.calculated_total_cost,
            )
            for v in visits
        ]


async def test_a_csv_visit_total_is_the_sum_of_what_its_items_store(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Q-2: two 10.005 items store 10.01 each, so the visit total is 20.02, not 20.01."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCROUNDCSV01")
    body = (
        f"{_V8_HEADER}\n"
        "8,metric,1,2026-07-21,Maintenance,Oil,7300.00,,10.005,,,,,,,\n"
        "8,metric,1,2026-07-21,Maintenance,Filter,7300.00,,10.005,,,,,,,\n"
    )
    data = await _post_csv(client, auth_headers, vin, body)
    assert data["success_count"] == 2, data
    # 2fbc4248: [(20.01, 20.02, 20.02)]
    assert await _visit_totals(test_sessionmaker, vin) == [
        (Decimal("20.02"), Decimal("20.02"), Decimal("20.02"))
    ]


async def test_a_json_visit_total_is_the_sum_of_what_its_items_and_fees_store(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCROUNDJSON1")
    payload = {
        "export_version": "9",
        "units": "metric",
        "service_visits": [
            {
                "date": "2026-07-22",
                "odometer_km": 7400.0,
                "service_category": "Maintenance",
                "tax_amount": 1.005,
                "line_items": [
                    {"description": "Oil", "cost": 10.005},
                    {"description": "Filter", "cost": 10.005},
                ],
            }
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    assert data["service_records"]["success_count"] == 1, data
    # 2fbc4248: [(21.02, 20.02, 21.03)], the total summed the raw thousandths
    assert await _visit_totals(test_sessionmaker, vin) == [
        (Decimal("21.03"), Decimal("20.02"), Decimal("21.03"))
    ]


async def _seed_padded_visit(db_session: AsyncSession, vin: str) -> None:
    visit = ServiceVisit(
        vin=vin,
        date=date(2026, 7, 23),
        odometer_km=Decimal("7500.00"),
        service_category="Maintenance",
        total_cost=Decimal("40.00"),
    )
    db_session.add(visit)
    await db_session.flush()
    db_session.add(
        ServiceLineItem(visit_id=visit.id, description=" Oil change ", cost=Decimal("40.00"))
    )
    await db_session.commit()


async def test_a_padded_item_description_matches_its_own_csv_export(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """Q-3: the CSV import strips the cell, so the stored side is read stripped too."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCPADDEDCSV1")
    await _seed_padded_visit(db_session, vin)
    exported = await client.get(
        f"/api/export/vehicles/{vin}/service/csv?units=metric", headers=auth_headers
    )
    assert exported.status_code == 200, exported.text
    data = await _post_csv(client, auth_headers, vin, exported.text)
    # 2fbc4248: (1, 0), "Oil change" never met " Oil change "
    assert (data["success_count"], data["skipped_count"]) == (0, 1), data


async def test_a_padded_item_description_matches_its_own_json_export(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """Control: the JSON path keeps the spaces on both sides, so it already matched."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSVCPADDEDJSN1")
    await _seed_padded_visit(db_session, vin)
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    data = await _post_json(client, auth_headers, vin, exported.json())
    assert (
        data["service_records"]["success_count"],
        data["service_records"]["skipped_count"],
    ) == (0, 1), data
