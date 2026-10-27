"""A value typed at display precision reads back as typed, on both dialects.

Storage is metric, so the browser converts what was typed and posts the result
unrounded. A column too coarse for the conversion rounds it, and the round trip
shows a different number: a UK 6.000/gal price came back 6.001, 72.2 °F came
back 72.1, 1.00 fl oz came back 1.01. These columns are wide enough now.

The supply ledger gets its own grain on top: 13 places hold each entry exactly
enough, but their rounding residue still adds up, so the balance rounds to
1E-9 L and a zero balance goes out as plain 0.
"""

import uuid
from collections.abc import AsyncGenerator
from decimal import ROUND_HALF_UP, Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

US_GAL_L = Decimal("3.785411784")
UK_GAL_L = Decimal("4.54609")
MILE_KM = Decimal("1.609344")
LB_KG = Decimal("0.45359237")
US_FL_OZ_L = US_GAL_L / 128  # 0.0295735295625, exact
US_MPG = 100 * US_GAL_L / MILE_KM  # L/100km = US_MPG / mpg


def _wire(value: Decimal) -> float:
    """What the browser posts: the converted double, unrounded."""
    return float(value)


def _shown(value: str | Decimal, places: int) -> Decimal:
    """A number rounded the way the UI prints it."""
    return Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


@pytest_asyncio.fixture
async def diesel_vehicle(
    db_session: AsyncSession, test_user: dict[str, object]
) -> AsyncGenerator[Vehicle]:
    """A throwaway diesel, so DEF records are allowed and nothing leaks into
    the shared test vehicle's totals."""
    vehicle = Vehicle(
        vin="WID" + uuid.uuid4().hex[:14].upper(),
        user_id=test_user["id"],
        nickname="Widened",
        vehicle_type="Truck",
        year=2020,
        make="Ram",
        model="2500",
        fuel_type="diesel",
    )
    db_session.add(vehicle)
    await db_session.commit()
    vin = vehicle.vin
    yield vehicle
    await db_session.rollback()
    stored = await db_session.get(Vehicle, vin)
    if stored is not None:
        await db_session.delete(stored)
        await db_session.commit()


async def _fuel(client: AsyncClient, headers: dict[str, str], vin: str, **fields) -> dict:
    payload = {
        "vin": vin,
        "date": "2026-09-01",
        "odometer_km": 10000,
        "liters": 40,
        "is_full_tank": True,
        **fields,
    }
    created = await client.post(f"/api/vehicles/{vin}/fuel", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    read = await client.get(f"/api/vehicles/{vin}/fuel/{created.json()['id']}", headers=headers)
    assert read.status_code == 200, read.text
    return read.json()


# --- Fuel and DEF prices: (12,3) -> (13,4) per litre ---------------------------


@pytest.mark.parametrize(
    ("typed", "gallon"),
    [
        # 6.000 / 4.54609 = 1.319827...: at 3 places 1.320, which shows 6.001.
        pytest.param(Decimal("6.000"), UK_GAL_L, id="uk-6.000"),
        # 3.999 / 3.785411784 = 1.056438...: at 3 places 1.056, which shows 3.997.
        pytest.param(Decimal("3.999"), US_GAL_L, id="us-3.999"),
    ],
)
async def test_a_fuel_price_per_gallon_reads_back_as_typed(
    client: AsyncClient, auth_headers, diesel_vehicle, typed: Decimal, gallon: Decimal
):
    record = await _fuel(
        client,
        auth_headers,
        diesel_vehicle.vin,
        price_per_unit=_wire(typed / gallon),
        price_basis="per_volume",
    )
    assert _shown(Decimal(record["price_per_unit"]) * gallon, 3) == typed


@pytest.mark.parametrize(
    ("typed", "gallon"),
    [
        pytest.param(Decimal("6.000"), UK_GAL_L, id="uk-6.000"),
        pytest.param(Decimal("3.999"), US_GAL_L, id="us-3.999"),
    ],
)
async def test_a_def_price_per_gallon_reads_back_as_typed(
    client: AsyncClient, auth_headers, diesel_vehicle, typed: Decimal, gallon: Decimal
):
    vin = diesel_vehicle.vin
    created = await client.post(
        f"/api/vehicles/{vin}/def",
        json={
            "vin": vin,
            "date": "2026-09-01",
            "liters": 10,
            "price_per_unit": _wire(typed / gallon),
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    read = await client.get(f"/api/vehicles/{vin}/def/{created.json()['id']}", headers=auth_headers)
    assert read.status_code == 200, read.text
    assert _shown(Decimal(read.json()["price_per_unit"]) * gallon, 3) == typed


# --- Outside temperature: (4,1) -> (5,2) ------------------------------------------


async def test_a_fahrenheit_temperature_reads_back_as_typed(
    client: AsyncClient, auth_headers, diesel_vehicle
):
    # 72.2 F = 22.333 C: at 1 place 22.3, which shows 72.1.
    typed = Decimal("72.2")
    record = await _fuel(
        client, auth_headers, diesel_vehicle.vin, outside_temp_c=_wire((typed - 32) * 5 / 9)
    )
    assert _shown(Decimal(record["outside_temp_c"]) * 9 / 5 + 32, 1) == typed


# --- Consumption: (5,2) -> (7,4) L/100km -----------------------------------------

CONSUMPTION = [
    # 50.1 MPG = 4.6949 L/100km: at 2 places 4.69, which shows 50.2.
    pytest.param(Decimal("50.1"), US_MPG, 1, id="50.1-mpg-us"),
    # 10.23 km/L = 9.7752 L/100km: at 2 places 9.78, which shows 10.22.
    pytest.param(Decimal("10.23"), Decimal(100), 2, id="10.23-km-l"),
]


@pytest.mark.parametrize(("typed", "numerator", "places"), CONSUMPTION)
async def test_an_obc_consumption_reads_back_as_typed(
    client: AsyncClient,
    auth_headers,
    diesel_vehicle,
    typed: Decimal,
    numerator: Decimal,
    places: int,
):
    record = await _fuel(
        client, auth_headers, diesel_vehicle.vin, obc_l_per_100km=_wire(numerator / typed)
    )
    assert _shown(numerator / Decimal(record["obc_l_per_100km"]), places) == typed


@pytest.mark.parametrize(("typed", "numerator", "places"), CONSUMPTION)
async def test_a_sticker_fuel_economy_reads_back_as_typed(
    client: AsyncClient,
    auth_headers,
    diesel_vehicle,
    typed: Decimal,
    numerator: Decimal,
    places: int,
):
    vin = diesel_vehicle.vin
    fields = (
        "fuel_economy_city_l_per_100km",
        "fuel_economy_highway_l_per_100km",
        "fuel_economy_combined_l_per_100km",
    )
    patched = await client.patch(
        f"/api/vehicles/{vin}/window-sticker/data",
        json=dict.fromkeys(fields, _wire(numerator / typed)),
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    read = await client.get(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)
    assert read.status_code == 200, read.text
    for field in fields:
        assert _shown(numerator / Decimal(read.json()[field]), places) == typed, field


# --- Propane tank size: (6,2) -> (7,3) kg -----------------------------------------


async def test_a_tank_size_in_pounds_reads_back_as_typed(
    client: AsyncClient, auth_headers, diesel_vehicle
):
    # 20.01 lb = 9.0764 kg: at 2 places 9.08, which shows 20.02.
    typed = Decimal("20.01")
    vin = diesel_vehicle.vin
    created = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json={
            "vin": vin,
            "date": "2026-09-01",
            "fuel_type": "Propane",
            "propane_liters": 8.5,
            "tank_size_kg": _wire(typed * LB_KG),
            "tank_quantity": 1,
            "is_full_tank": False,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    read = await client.get(
        f"/api/vehicles/{vin}/fuel/{created.json()['id']}", headers=auth_headers
    )
    assert read.status_code == 200, read.text
    assert _shown(Decimal(read.json()["tank_size_kg"]) / LB_KG, 2) == typed


# --- Supply quantities: (12,3) -> (25,13) L, and the ledger's balance grain --------


def _fl_oz(amount: str) -> float:
    """What the history modal posts for `amount` US fl oz: the JS double."""
    return float(amount) * float(US_FL_OZ_L)


async def _supply(client: AsyncClient, headers: dict[str, str]) -> int:
    created = await client.post(
        "/api/supplies",
        json={
            "name": f"Brake fluid {uuid.uuid4().hex[:8]}",
            "unit_type": "volume",
            "volume_unit": "fl_oz_us",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _buy(client: AsyncClient, headers: dict[str, str], sid: int, fl_oz: str) -> dict:
    bought = await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": "2026-09-01", "quantity": _fl_oz(fl_oz)},
        headers=headers,
    )
    assert bought.status_code == 201, bought.text
    return bought.json()


async def _use(client: AsyncClient, headers: dict[str, str], sid: int, fl_oz: str) -> None:
    used = await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": _fl_oz(fl_oz)}, headers=headers
    )
    assert used.status_code == 201, used.text


async def _ledger(client: AsyncClient, headers: dict[str, str], sid: int) -> tuple[dict, dict]:
    supply = await client.get(f"/api/supplies/{sid}", headers=headers)
    assert supply.status_code == 200, supply.text
    history = await client.get(f"/api/supplies/{sid}/history", headers=headers)
    assert history.status_code == 200, history.text
    return supply.json(), history.json()


async def test_one_fluid_ounce_reads_back_as_typed(client: AsyncClient, auth_headers):
    # 1 US fl oz = 0.0295735295625 L: at 3 places 0.030, which shows 1.01.
    sid = await _supply(client, auth_headers)
    bought = await _buy(client, auth_headers, sid, "1.00")
    assert _shown(Decimal(bought["quantity"]) / US_FL_OZ_L, 2) == Decimal("1.00")
    supply, _ = await _ledger(client, auth_headers, sid)
    assert _shown(Decimal(supply["on_hand"]) / US_FL_OZ_L, 2) == Decimal("1.00")


@pytest.mark.parametrize(
    ("bought", "each"),
    [
        # At 3 places 32 x 0.030 L outran the 0.946 L bought: -0.47 fl oz, flagged.
        pytest.param("32", "1", id="32-x-1"),
        # 1.03 fl oz is 0.030460735449375 L, 15 places, so even 13 places leave
        # 32 of them 8E-13 L past the 32.96 bought. The balance grain eats that.
        pytest.param("32.96", "1.03", id="32-x-1.03"),
    ],
)
async def test_using_up_exactly_what_was_bought_leaves_zero(
    client: AsyncClient, auth_headers, bought: str, each: str
):
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, bought)
    for _ in range(32):
        await _use(client, auth_headers, sid, each)

    supply, history = await _ledger(client, auth_headers, sid)
    # Plain 0: never -0E-9 or 0E-9 on the wire.
    assert supply["on_hand"] == "0"
    assert supply["is_negative"] is False
    assert history["on_hand"] == "0"
    assert history["entries"][-1]["running_balance"] == "0"


async def test_one_ounce_short_still_reads_minus_one_and_flags(client: AsyncClient, auth_headers):
    """Guard (Fable F-10): the balance grain must stay far below one real entry.

    The flag already held at t=0 (the old 0.001 grain left -1.49 fl oz). Mutant
    killed: a BALANCE_GRAIN wide enough to swallow one 0.0296 L entry (0.1 L)
    rounds the shortage to zero and drops the flag.
    """
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, "32")
    for _ in range(33):
        await _use(client, auth_headers, sid, "1")

    supply, history = await _ledger(client, auth_headers, sid)
    assert supply["is_negative"] is True
    for on_hand in (
        supply["on_hand"],
        history["on_hand"],
        history["entries"][-1]["running_balance"],
    ):
        assert _shown(Decimal(on_hand) / US_FL_OZ_L, 2) == Decimal("-1.00")
