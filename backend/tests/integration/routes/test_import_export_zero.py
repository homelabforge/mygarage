"""A 0 km reading and a $0 bill survive export and import (batch 3a task 4)."""

import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DEFRecord,
    FuelRecord,
    OdometerRecord,
    ServiceLineItem,
    ServiceVisit,
    TaxRecord,
    Vehicle,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    """The import and export limiters are per route; this module posts more than they allow."""
    from app.routes.export import limiter as export_limiter
    from app.routes.import_data import limiter as import_limiter

    export_limiter.reset()
    import_limiter.reset()


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str, **fields: Any) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Zero",
            fuel_type="diesel",
            **fields,
        )
    )
    await db_session.commit()
    return vin


_DAY = date(2026, 9, 1)


async def _seed_service(db: AsyncSession, vin: str) -> None:
    visit = ServiceVisit(
        vin=vin, date=_DAY, odometer_km=Decimal("0"), service_category="Maintenance"
    )
    db.add(visit)
    await db.flush()
    db.add(ServiceLineItem(visit_id=visit.id, description="Free check", cost=Decimal("0")))


async def _seed_fuel(db: AsyncSession, vin: str) -> None:
    db.add(
        FuelRecord(
            vin=vin,
            date=_DAY,
            odometer_km=Decimal("0"),
            liters=Decimal("0"),
            price_per_unit=Decimal("0"),
            rebate=Decimal("0"),
            cost=Decimal("0"),
            obc_trip_duration_s=0,
        )
    )


async def _seed_def(db: AsyncSession, vin: str) -> None:
    db.add(
        DEFRecord(
            vin=vin,
            date=_DAY,
            odometer_km=Decimal("0"),
            liters=Decimal("0"),
            price_per_unit=Decimal("0"),
            cost=Decimal("0"),
            fill_level=Decimal("0"),
        )
    )


async def _seed_odometer(db: AsyncSession, vin: str) -> None:
    db.add(OdometerRecord(vin=vin, date=_DAY, odometer_km=Decimal("0")))


async def _seed_tax(db: AsyncSession, vin: str) -> None:
    db.add(TaxRecord(vin=vin, date=_DAY, tax_type="Registration", amount=Decimal("0")))


# pair -> (seed, {metric header: the cell a zero must export as})
_CSV_ZEROS = {
    "service": (_seed_service, {"Odometer (km)": "0.00", "Cost": "0.00"}),
    "fuel": (
        _seed_fuel,
        {
            "Odometer (km)": "0.00",
            "Volume (L)": "0.000",
            "Price Per Unit (L)": "0.0000",
            "Rebate": "0.00",
            "Total Cost": "0.00",
            "OBC Trip Duration (s)": "0",
        },
    ),
    "def": (
        _seed_def,
        {
            "Odometer (km)": "0.00",
            "Volume (L)": "0.000",
            "Price Per Unit (L)": "0.0000",
            "Total Cost": "0.00",
            "Fill Level": "0.00",
        },
    ),
    "odometer": (_seed_odometer, {"Reading (km)": "0.00"}),
    "tax": (_seed_tax, {"Amount": "0.00"}),
}


@pytest.mark.parametrize("pair", list(_CSV_ZEROS))
async def test_a_csv_export_writes_a_zero_reading_and_a_zero_bill(
    pair: str, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], f"B3RTZEROCSV{pair[:6].upper():0<6}")
    seed, expected = _CSV_ZEROS[pair]
    await seed(db_session, vin)
    await db_session.commit()

    r = await client.get(
        f"/api/export/vehicles/{vin}/{pair}/csv?units=metric", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    (row,) = list(csv.DictReader(io.StringIO(r.text)))
    # main: every one of these cells is blank
    assert {header: row[header] for header in expected} == expected


@pytest.mark.parametrize("pair", ["fuel", "def", "odometer"])
async def test_a_csv_with_zeros_reimports_into_its_vehicle_as_duplicates(
    pair: str, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    """A v8 blank means NULL only once the export writes a 0 as 0 (Task 3's gate assumes it)."""
    vin = await _vehicle(db_session, test_user["id"], f"B3RTZEROTRIP{pair[:5].upper():0<5}")
    seed, _ = _CSV_ZEROS[pair]
    await seed(db_session, vin)
    await db_session.commit()

    exported = await client.get(
        f"/api/export/vehicles/{vin}/{pair}/csv?units=metric", headers=auth_headers
    )
    assert exported.status_code == 200, exported.text
    (row,) = list(csv.DictReader(io.StringIO(exported.text)))
    assert row["units_version"] == "8"

    r = await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=auth_headers,
        files={"file": (f"{pair}.csv", exported.content, "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # main: fuel and DEF import the row again (blank litres and odometer read
    # as NULL against the stored 0); odometer fails "Reading is required"
    assert (data["success_count"], data["skipped_count"], data["errors"]) == (0, 1, []), data


async def test_the_json_export_writes_zero_not_null(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTZEROJSONEXP01")
    for seed in (_seed_service, _seed_fuel, _seed_def):
        await seed(db_session, vin)
    await db_session.commit()

    r = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    (fuel,) = data["fuel_records"]
    (def_row,) = data["def_records"]
    # main: liters, price_per_unit, rebate and cost all null
    assert (fuel["liters"], fuel["price_per_unit"], fuel["rebate"], fuel["cost"]) == (0, 0, 0, 0)
    # main: liters, price_per_unit, cost and fill_level all null
    assert (
        def_row["liters"],
        def_row["price_per_unit"],
        def_row["cost"],
        def_row["fill_level"],
    ) == (0, 0, 0, 0)
    # main: no service_visits key (v8 wrote a visit total, null at $0)
    assert data["service_visits"][0]["line_items"][0]["cost"] == 0


async def test_a_json_import_keeps_a_zero_reading_and_a_zero_bill(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTZEROJSONIMP01")
    payload = {
        "export_version": "9",
        "units": "metric",
        "service_records": [
            {"date": "2026-09-02", "odometer_km": 0, "service_type": "Free check", "cost": 0}
        ],
        "fuel_records": [
            {
                "date": "2026-09-02",
                "odometer_km": 0,
                "liters": 0,
                "price_per_unit": 0,
                "rebate": 0,
                "cost": 0,
            }
        ],
        "def_records": [
            {
                "date": "2026-09-02",
                "odometer_km": 0,
                "liters": 0,
                "price_per_unit": 0,
                "cost": 0,
                "fill_level": 0,
            }
        ],
        "odometer_records": [{"date": "2026-09-03", "odometer_km": 0}],
    }
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=auth_headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # main: odometer_records error_count 1 ("could not be imported": 0 read as missing)
    assert data["errors"] == [], data

    async with test_sessionmaker() as fresh:
        visit = (
            await fresh.execute(select(ServiceVisit).where(ServiceVisit.vin == vin))
        ).scalar_one()
        fuel = (await fresh.execute(select(FuelRecord).where(FuelRecord.vin == vin))).scalar_one()
        def_row = (await fresh.execute(select(DEFRecord).where(DEFRecord.vin == vin))).scalar_one()
        readings = (
            await fresh.execute(
                select(OdometerRecord.date, OdometerRecord.odometer_km)
                .where(OdometerRecord.vin == vin)
                .order_by(OdometerRecord.date)
            )
        ).all()
    zero = Decimal("0")
    assert visit.odometer_km == zero
    assert (fuel.odometer_km, fuel.liters, fuel.price_per_unit, fuel.rebate, fuel.cost) == (
        zero,
        zero,
        zero,
        zero,
        zero,
    )
    assert (def_row.odometer_km, def_row.liters, def_row.price_per_unit, def_row.cost) == (
        zero,
        zero,
        zero,
        zero,
    )
    assert def_row.fill_level == zero
    # The 2nd's three zero readings sync as one; the 3rd is the reading section's own.
    assert [tuple(row) for row in readings] == [(date(2026, 9, 2), zero), (date(2026, 9, 3), zero)]
