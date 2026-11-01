"""Money bounds through the real routes: big currencies save, past the column is a 422.

The schema-level table (tests/unit/schemas/test_money_input_bounds.py) covers
every field. These go end to end for the amounts the old caps got wrong: an
ordinary forint payment and fill-up, a per-tank propane price, the largest
amount a column holds, and a negative vehicle price, which used to save.
"""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from app.schemas._money import MONEY_MAX

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.own_vehicle(fuel_type="gas"),
]

CENT = Decimal("0.01")
DAY = "2026-01-15"


async def _post(client: AsyncClient, headers: dict[str, str], url: str, body: dict[str, Any]):
    return await client.post(url, json=body, headers=headers)


def _financing(vin: str, amount: str) -> dict[str, Any]:
    return {"vin": vin, "date": DAY, "amount": amount, "category": "loan_payment"}


async def test_a_forint_financing_payment_saves(client, auth_headers, own_vehicle):
    url = f"/api/vehicles/{own_vehicle.vin}/financing-records"
    created = await _post(client, auth_headers, url, _financing(own_vehicle.vin, "335000.00"))
    assert created.status_code == 201, created.text
    assert Decimal(str(created.json()["amount"])) == Decimal("335000.00")


async def test_the_largest_amount_a_column_holds_round_trips(client, auth_headers, own_vehicle):
    url = f"/api/vehicles/{own_vehicle.vin}/financing-records"
    created = await _post(client, auth_headers, url, _financing(own_vehicle.vin, str(MONEY_MAX)))
    assert created.status_code == 201, created.text

    read = await client.get(f"{url}/{created.json()['id']}", headers=auth_headers)
    assert read.status_code == 200, read.text
    assert Decimal(str(read.json()["amount"])) == MONEY_MAX


@pytest.mark.parametrize("amount", [MONEY_MAX + CENT, -CENT], ids=["past-max", "negative"])
async def test_an_amount_outside_the_policy_is_a_422(client, auth_headers, own_vehicle, amount):
    url = f"/api/vehicles/{own_vehicle.vin}/financing-records"
    refused = await _post(client, auth_headers, url, _financing(own_vehicle.vin, str(amount)))
    assert refused.status_code == 422, refused.text
    assert [error["loc"] for error in refused.json()["details"]] == [["body", "amount"]]

    listed = await client.get(url, headers=auth_headers)
    assert listed.json()["total"] == 0


async def test_a_forint_fill_up_saves(client, auth_headers, own_vehicle):
    # About 400 L of diesel for a truck at 620 Ft/L: past the old 99,999.99 cap.
    body = {
        "vin": own_vehicle.vin,
        "date": DAY,
        "odometer_km": 120000,
        "liters": 400,
        "price_per_unit": "620.000",
        "price_basis": "per_volume",
        "cost": "248000.00",
        "is_full_tank": True,
    }
    created = await _post(client, auth_headers, f"/api/vehicles/{own_vehicle.vin}/fuel", body)
    assert created.status_code == 201, created.text
    assert Decimal(str(created.json()["cost"])) == Decimal("248000.00")


async def test_a_forint_propane_bottle_saves(client, auth_headers, own_vehicle):
    # One 11.5 kg bottle at 12,000 Ft: past the old 999.999 unit-price cap.
    body = {
        "vin": own_vehicle.vin,
        "date": DAY,
        "tank_size_kg": "11.5",
        "tank_quantity": 1,
        "price_per_unit": "12000.000",
        "price_basis": "per_tank",
        "cost": "12000.00",
        "is_full_tank": False,
    }
    created = await _post(client, auth_headers, f"/api/vehicles/{own_vehicle.vin}/fuel", body)
    assert created.status_code == 201, created.text
    assert Decimal(str(created.json()["price_per_unit"])) == Decimal(12000)


async def test_a_negative_vehicle_price_is_a_422(client, auth_headers, own_vehicle):
    url = f"/api/vehicles/{own_vehicle.vin}"
    refused = await client.put(url, json={"purchase_price": "-0.01"}, headers=auth_headers)
    assert refused.status_code == 422, refused.text

    saved = await client.put(url, json={"purchase_price": str(MONEY_MAX)}, headers=auth_headers)
    assert saved.status_code == 200, saved.text
    assert Decimal(str(saved.json()["purchase_price"])) == MONEY_MAX
