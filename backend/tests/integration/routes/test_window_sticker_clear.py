"""The sticker review PATCH clears, keeps, and saves every field it shows.

It skipped every null, so a value cleared in the review came back. Six fields
the review edits (engine and transmission descriptions, wheel and tire specs,
the two environmental ratings) weren't on the schema at all and were dropped
without a word, and `sticker_drivetrain` was written by the upload but never
returned or editable.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Field -> column width (models/vehicle.py).
STRING_FIELDS = {
    "assembly_location": 100,
    "exterior_color": 100,
    "interior_color": 100,
    "warranty_powertrain": 100,
    "warranty_basic": 100,
    "sticker_engine_description": 150,
    "sticker_transmission_description": 150,
    "sticker_drivetrain": 50,
    "wheel_specs": 100,
    "tire_specs": 100,
    "environmental_rating_ghg": 10,
    "environmental_rating_smog": 10,
}
NEW_FIELDS = [
    "sticker_engine_description",
    "sticker_transmission_description",
    "sticker_drivetrain",
    "wheel_specs",
    "tire_specs",
    "environmental_rating_ghg",
    "environmental_rating_smog",
]
FUEL_ECONOMY = [
    "fuel_economy_city_l_per_100km",
    "fuel_economy_highway_l_per_100km",
    "fuel_economy_combined_l_per_100km",
]


@pytest_asyncio.fixture
async def own_vehicle(db_session: AsyncSession, test_user: dict[str, object]):
    """A fresh vehicle with a wizard colour, deleted afterwards."""
    vehicle = Vehicle(
        vin="STK" + uuid.uuid4().hex[:14].upper(),
        user_id=test_user["id"],
        nickname="Sticker Test",
        vehicle_type="Car",
        year=2024,
        make="Honda",
        model="Civic",
        color="Red",
    )
    db_session.add(vehicle)
    await db_session.commit()
    yield vehicle.vin
    await db_session.delete(vehicle)
    await db_session.commit()


async def _patch(client: AsyncClient, headers: dict, vin: str, body: dict):
    return await client.patch(
        f"/api/vehicles/{vin}/window-sticker/data", json=body, headers=headers
    )


async def _sticker(client: AsyncClient, headers: dict, vin: str) -> dict:
    r = await client.get(f"/api/vehicles/{vin}/window-sticker", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("field", list(STRING_FIELDS))
async def test_null_clears(client: AsyncClient, auth_headers, own_vehicle, field):
    r = await _patch(client, auth_headers, own_vehicle, {field: "V6"})
    assert r.status_code == 200, r.text
    assert r.json()[field] == "V6"

    r = await _patch(client, auth_headers, own_vehicle, {field: None})
    assert r.status_code == 200, r.text
    assert (await _sticker(client, auth_headers, own_vehicle))[field] is None


async def test_clearing_the_exterior_colour_leaves_the_wizard_colour(
    client: AsyncClient, auth_headers, own_vehicle
):
    # Fable's F-A1 case: the review clears a wrong OCR colour, and the
    # overview falls back to the colour the owner typed.
    await _patch(client, auth_headers, own_vehicle, {"exterior_color": "Blu"})
    r = await _patch(client, auth_headers, own_vehicle, {"exterior_color": None})
    assert r.status_code == 200, r.text

    vehicle = (await client.get(f"/api/vehicles/{own_vehicle}", headers=auth_headers)).json()
    assert vehicle["exterior_color"] is None
    assert vehicle["color"] == "Red"


async def test_omitted_keeps(client: AsyncClient, auth_headers, own_vehicle):
    await _patch(
        client,
        auth_headers,
        own_vehicle,
        {"interior_color": "Black", "fuel_economy_city_l_per_100km": "7.84"},
    )
    r = await _patch(client, auth_headers, own_vehicle, {"assembly_location": "Ohio"})
    assert r.status_code == 200, r.text

    stored = await _sticker(client, auth_headers, own_vehicle)
    assert stored["interior_color"] == "Black"
    assert stored["fuel_economy_city_l_per_100km"] == "7.8400"
    assert stored["assembly_location"] == "Ohio"


@pytest.mark.parametrize("field", NEW_FIELDS)
async def test_fields_the_review_edits_are_saved(
    client: AsyncClient, auth_headers, own_vehicle, field
):
    r = await _patch(client, auth_headers, own_vehicle, {field: "AWD"})
    assert r.status_code == 200, r.text
    assert (await _sticker(client, auth_headers, own_vehicle))[field] == "AWD"


@pytest.mark.parametrize(("field", "width"), list(STRING_FIELDS.items()))
async def test_too_long_is_a_422(client: AsyncClient, auth_headers, own_vehicle, field, width):
    r = await _patch(client, auth_headers, own_vehicle, {field: "x" * (width + 1)})
    assert r.status_code == 422, r.text
    assert ["body", field] in [e["loc"] for e in r.json()["details"]]

    r = await _patch(client, auth_headers, own_vehicle, {field: "x" * width})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("field", FUEL_ECONOMY)
@pytest.mark.parametrize("value", ["-0.01", "999.99995", "1000"])
async def test_fuel_economy_outside_the_column_is_a_422(
    client: AsyncClient, auth_headers, own_vehicle, field, value
):
    r = await _patch(client, auth_headers, own_vehicle, {field: value})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("field", FUEL_ECONOMY)
async def test_fuel_economy_at_the_column_limit_saves(
    client: AsyncClient, auth_headers, own_vehicle, field
):
    # Numeric(7,4).
    r = await _patch(client, auth_headers, own_vehicle, {field: "999.9999"})
    assert r.status_code == 200, r.text
    assert r.json()[field] == "999.9999"


async def test_the_extracted_vin_is_returned(
    client: AsyncClient, auth_headers, own_vehicle, db_session: AsyncSession
):
    # The upload stores the VIN it read off the sticker so the review can show
    # it next to the vehicle's; the response never carried it.
    vehicle = await db_session.get(Vehicle, own_vehicle)
    assert vehicle is not None
    vehicle.window_sticker_extracted_vin = "1HGCM82633A004352"
    await db_session.commit()

    assert (await _sticker(client, auth_headers, own_vehicle))[
        "window_sticker_extracted_vin"
    ] == "1HGCM82633A004352"
