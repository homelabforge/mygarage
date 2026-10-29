"""The fuel CSV carries kWh, propane, tank size and count, and the price's basis (batch 3b task 13, K9)."""

import csv
import io
import uuid
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="RV",
            year=2024,
            make="Test",
            model="FuelCsv",
        )
    )
    await db_session.commit()
    return vin


async def _uk_gallon_user(db_session: AsyncSession) -> dict[str, str]:
    """Imperial with UK gallons: volume gal_uk, mass lb. Its own user, so no preference leaks."""
    user = User(
        username="b3b_ukgal_" + uuid.uuid4().hex[:8],
        email=f"b3b-ukgal-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=True,
        unit_preference="imperial",
        unit_volume="gal_uk",
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


def _rows(body: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(body)))


async def _import(client: AsyncClient, headers: dict, vin: str, body: str) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/fuel/csv",
        headers=headers,
        files={"file": ("fuel.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _stored(sessionmaker: Any, vin: str) -> list[tuple]:
    async with sessionmaker() as fresh:
        rows = (
            (
                await fresh.execute(
                    select(FuelRecord).where(FuelRecord.vin == vin).order_by(FuelRecord.date)
                )
            )
            .scalars()
            .all()
        )
    return [
        (
            r.date,
            r.kwh,
            r.propane_liters,
            r.tank_size_kg,
            r.tank_quantity,
            r.price_per_unit,
            r.price_basis,
        )
        for r in rows
    ]


async def test_a_kwh_and_a_per_tank_price_keep_their_figures_on_an_imperial_file(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(db_session, test_user["id"], "B3BFUELEVSRC0001")
    target = await _vehicle(db_session, test_user["id"], "B3BFUELEVDST0001")
    db_session.add_all(
        [
            FuelRecord(
                vin=source,
                date=date(2026, 7, 1),
                kwh=Decimal("50.000"),
                price_per_unit=Decimal("0.3000"),
                price_basis="per_kwh",
                cost=Decimal("15.00"),
            ),
            FuelRecord(
                vin=source,
                date=date(2026, 7, 2),
                tank_size_kg=Decimal("9.072"),
                tank_quantity=1,
                price_per_unit=Decimal("25.0000"),
                price_basis="per_tank",
                cost=Decimal("25.00"),
            ),
        ]
    )
    await db_session.commit()

    exported = await client.get(
        f"/api/export/vehicles/{source}/fuel/csv?units=imperial", headers=auth_headers
    )
    assert exported.status_code == 200, exported.text
    ev, tank = sorted(_rows(exported.text), key=lambda r: r["Date"])
    # main: KeyError 'kWh', and the EV price went out as 1.1356 per gal_us
    assert (ev["kWh"], ev["Price Per Unit (gal_us)"], ev["Price Basis"]) == (
        "50.000",
        "0.3000",
        "per_kwh",
    )
    assert (tank["Tank Size (lb)"], tank["Tank Quantity"], tank["Price Per Unit (gal_us)"]) == (
        "20.000",
        "1",
        "25.0000",
    )
    assert tank["Price Basis"] == "per_tank"

    data = await _import(client, auth_headers, target, exported.text)
    assert (data["success_count"], data["error_count"]) == (2, 0), data
    assert await _stored(test_sessionmaker, target) == [
        (date(2026, 7, 1), Decimal("50.000"), None, None, None, Decimal("0.3000"), "per_kwh"),
        (date(2026, 7, 2), None, None, Decimal("9.072"), 1, Decimal("25.0000"), "per_tank"),
    ]

    # Back into the source: every row is already there.
    again = await _import(client, auth_headers, source, exported.text)
    assert (again["success_count"], again["skipped_count"]) == (0, 2), again


async def test_a_propane_row_round_trips_in_uk_gallons_and_pounds(
    client: AsyncClient, test_user, db_session: AsyncSession, test_sessionmaker
):
    headers = await _uk_gallon_user(db_session)
    source = await _vehicle(db_session, test_user["id"], "B3BFUELLPGSRC001")
    target = await _vehicle(db_session, test_user["id"], "B3BFUELLPGDST001")
    db_session.add_all(
        [
            # 4 UK gal of propane at 0.88/L.
            FuelRecord(
                vin=source,
                date=date(2026, 8, 1),
                propane_liters=Decimal("18.184"),
                price_per_unit=Decimal("0.8800"),
                price_basis="per_volume",
                cost=Decimal("16.00"),
            ),
            # Two 20 lb tanks, priced by weight at 2.2047/kg. Four places a pound
            # would bring it back as 2.2046, so a pound price carries five.
            FuelRecord(
                vin=source,
                date=date(2026, 8, 2),
                tank_size_kg=Decimal("9.072"),
                tank_quantity=2,
                price_per_unit=Decimal("2.2047"),
                price_basis="per_weight",
                cost=Decimal("40.00"),
            ),
        ]
    )
    await db_session.commit()

    exported = await client.get(f"/api/export/vehicles/{source}/fuel/csv", headers=headers)
    assert exported.status_code == 200, exported.text
    by_volume, by_weight = sorted(_rows(exported.text), key=lambda r: r["Date"])
    # 18.184 / 4.54609 = 3.99992; 0.88 * 4.54609 = 4.00056
    # main: KeyError 'Propane Volume (gal_uk)'
    assert (by_volume["Propane Volume (gal_uk)"], by_volume["Price Per Unit (gal_uk)"]) == (
        "3.9999",
        "4.0006",
    )
    # 9.072 / 0.45359237 = 20.00034; 2.2047 * 0.45359237 = 1.00004 a pound
    assert (by_weight["Tank Size (lb)"], by_weight["Price Per Unit (gal_uk)"]) == (
        "20.000",
        "1.00004",
    )
    assert (by_volume["Price Basis"], by_weight["Price Basis"]) == ("per_volume", "per_weight")

    data = await _import(client, headers, target, exported.text)
    assert (data["success_count"], data["error_count"]) == (2, 0), data
    assert await _stored(test_sessionmaker, target) == [
        (date(2026, 8, 1), None, Decimal("18.184"), None, None, Decimal("0.8800"), "per_volume"),
        (date(2026, 8, 2), None, None, Decimal("9.072"), 2, Decimal("2.2047"), "per_weight"),
    ]


# One stored fill-up and a file row that differs from it in one column only.
# Each is (VIN, stored fields, the file's Propane/Tank Size/Tank Quantity/kWh
# cells, basis, where that column sits in `_stored`'s tuple, both values).
_ONE_COLUMN_APART: dict[str, tuple[str, dict[str, Any], str, str, int, list[Any]]] = {
    "kwh": (
        "B3BFUELKEYKWH001",
        {"kwh": Decimal("50.000"), "price_basis": "per_kwh"},
        ",,,30.000",
        "per_kwh",
        1,
        [Decimal("30.000"), Decimal("50.000")],
    ),
    "propane": (
        "B3BFUELKEYLPG001",
        {"propane_liters": Decimal("18.184"), "price_basis": "per_volume"},
        "10.000,,,",
        "per_volume",
        2,
        [Decimal("10.000"), Decimal("18.184")],
    ),
    "tank-size": (
        "B3BFUELKEYSIZE01",
        {"tank_size_kg": Decimal("9.072"), "tank_quantity": 1, "price_basis": "per_tank"},
        ",4.536,1,",
        "per_tank",
        3,
        [Decimal("4.536"), Decimal("9.072")],
    ),
    # Two same-day tank refills: no odometer to tell them apart, only the count.
    "tank-quantity": (
        "B3BFUELKEYQTY001",
        {"tank_size_kg": Decimal("9.072"), "tank_quantity": 1, "price_basis": "per_tank"},
        ",9.072,2,",
        "per_tank",
        4,
        [1, 2],
    ),
}


@pytest.mark.parametrize("case", sorted(_ONE_COLUMN_APART))
async def test_a_fill_up_that_differs_in_one_new_column_is_not_a_duplicate(
    case: str,
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
):
    vin, stored, cells, basis, index, expected = _ONE_COLUMN_APART[case]
    await _vehicle(db_session, test_user["id"], vin)
    db_session.add(
        FuelRecord(
            vin=vin,
            date=date(2026, 9, 1),
            price_per_unit=Decimal("0.3000"),
            cost=Decimal("15.00"),
            **stored,
        )
    )
    await db_session.commit()
    body = (
        "units_version,unit_system,Date,Total Cost,Propane Volume (L),Tank Size (kg),"
        "Tank Quantity,kWh,Price Per Unit (L),Price Basis\n"
        f"8,metric,2026-09-01,15.00,{cells},0.3000,{basis}\n"
    )

    data = await _import(client, auth_headers, vin, body)

    # main: none of the four is read, so the row matches the stored one and is skipped
    assert (data["success_count"], data["skipped_count"]) == (1, 0), data
    assert sorted(r[index] for r in await _stored(test_sessionmaker, vin)) == expected


async def test_a_kwh_row_with_no_price_basis_column_is_priced_per_kwh(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """A file without Price Basis derives it from what the row has, kWh included (S11)."""
    vin = await _vehicle(db_session, test_user["id"], "B3BFUELEVNOBASIS")
    body = (
        "units_version,unit_system,Date,Total Cost,kWh,Price Per Unit (gal_us)\n"
        "8,imperial,2026-09-05,15.00,50.000,0.3000\n"
    )

    data = await _import(client, auth_headers, vin, body)

    # Derived from litres alone it'd be no basis, and 0.3 a gallon would land as 0.0793 a litre.
    assert (data["success_count"], data["error_count"]) == (1, 0), data
    assert await _stored(test_sessionmaker, vin) == [
        (date(2026, 9, 5), Decimal("50.000"), None, None, None, Decimal("0.3000"), "per_kwh"),
    ]


async def test_a_per_weight_price_needs_the_tank_size_column(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Its weight unit comes from that column's header; without it the price is a guess."""
    vin = await _vehicle(db_session, test_user["id"], "B3BFUELLPGBAD001")
    body = (
        "units_version,unit_system,Date,Total Cost,Price Per Unit (gal_us),Price Basis\n"
        "8,imperial,2026-09-02,20.00,1.00000,per_weight\n"
        "8,imperial,2026-09-03,20.00,1.0000,per_tonne\n"
    )

    data = await _import(client, auth_headers, vin, body)

    # main: both rows import, the price read as per gallon and the basis dropped
    assert data["errors"] == [
        "Row 2: a per_weight price needs the Tank Size column to say what weight it's per",
        "Row 3: price_basis must be one of per_volume, per_weight, per_tank, per_kwh",
    ], data
    assert await _stored(test_sessionmaker, vin) == []


async def test_a_tank_size_in_a_volume_unit_refuses_the_file(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3BFUELLPGUNIT01")
    body = (
        "units_version,unit_system,Date,Tank Size (gal_us),Tank Quantity\n"
        "8,custom,2026-09-04,5.0000,1\n"
    )
    r = await client.post(
        f"/api/import/vehicles/{vin}/fuel/csv",
        headers=auth_headers,
        files={"file": ("fuel.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )

    # main: 200, the column ignored
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == (
        "CSV column 'Tank Size (gal_us)' declares unit 'gal_us', which is not a mass unit. "
        "Expected one of: kg, lb."
    )
    assert await _stored(test_sessionmaker, vin) == []
