"""Fuel prices near a point and near a saved station (#211)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AddressBookEntry
from app.models.settings import Setting
from app.services.fuel_prices import france
from app.services.fuel_prices.base import FuelPrice, StationPrices

NEARBY = "app.services.fuel_prices.france.FrenchFuelPriceProvider.nearby"

STATION = StationPrices(
    external_id="63000012",
    name=None,
    address="12 Avenue de la République",
    city="Clermont-Ferrand",
    postal_code="63000",
    latitude=45.7797,
    longitude=3.0862,
    distance_km=0.041,
    prices=[
        FuelPrice(grade="B7", octane=None, price=Decimal("1.689"), currency="EUR"),
        FuelPrice(grade="E10", octane=95, price=Decimal("1.729"), currency="EUR"),
    ],
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _set(db: AsyncSession, key: str, value: str) -> None:
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row is None:
        db.add(Setting(key=key, value=value, category="integrations"))
    else:
        row.value = value
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _french_instance(db_session: AsyncSession):
    await _set(db_session, "default_country", "FR")
    await _set(db_session, france.ENABLED_SETTING, "true")
    yield
    await _set(db_session, "default_country", "")
    await _set(db_session, france.ENABLED_SETTING, "true")
    await db_session.execute(
        delete(AddressBookEntry).where(AddressBookEntry.business_name.like("FP test%"))
    )
    await db_session.commit()


async def _station(db: AsyncSession, *, with_coordinates: bool = True) -> int:
    entry = AddressBookEntry(
        business_name="FP test Total",
        category="fuel",
        poi_category="gas_station",
        latitude=Decimal("45.78000000") if with_coordinates else None,
        longitude=Decimal("3.08700000") if with_coordinates else None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry.id


class TestNearby:
    async def test_requires_auth(self, client: AsyncClient):
        response = await client.get("/api/fuel-prices/nearby", params={"lat": 45.78, "lon": 3.08})
        assert response.status_code == 401

    async def test_answers_the_stations_with_their_prices(self, client: AsyncClient, auth_headers):
        with patch(NEARBY, new=AsyncMock(return_value=[STATION])) as nearby:
            response = await client.get(
                "/api/fuel-prices/nearby",
                params={"lat": 45.78, "lon": 3.087, "radius_km": 1.5, "limit": 3},
                headers=auth_headers,
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["provider"], body["currency"], body["country"]) == (
            "fr_instantane",
            "EUR",
            "FR",
        )
        (station,) = body["stations"]
        assert station["external_id"] == "63000012"
        assert station["city"] == "Clermont-Ferrand"
        assert station["prices"] == [
            {
                "grade": "B7",
                "octane": None,
                "price": "1.689",
                "currency": "EUR",
                "updated_at": None,
            },
            {"grade": "E10", "octane": 95, "price": "1.729", "currency": "EUR", "updated_at": None},
        ]
        assert nearby.call_args.kwargs == {"radius_km": 1.5, "limit": 3}

    async def test_a_country_without_a_source_answers_no_provider(
        self, client: AsyncClient, auth_headers
    ):
        with patch(NEARBY, new=AsyncMock(return_value=[STATION])) as nearby:
            response = await client.get(
                "/api/fuel-prices/nearby",
                params={"lat": 45.78, "lon": 3.08, "country": "DE"},
                headers=auth_headers,
            )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "provider": None,
            "currency": None,
            "country": "DE",
            "stations": [],
            "warnings": [],
        }
        nearby.assert_not_called()

    async def test_the_setting_turns_it_off(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession
    ):
        await _set(db_session, france.ENABLED_SETTING, "false")
        response = await client.get(
            "/api/fuel-prices/nearby", params={"lat": 45.78, "lon": 3.08}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["provider"] is None

    async def test_a_failing_source_is_a_warning(self, client: AsyncClient, auth_headers):
        with patch(NEARBY, new=AsyncMock(side_effect=httpx.ConnectError("down"))):
            response = await client.get(
                "/api/fuel-prices/nearby", params={"lat": 45.78, "lon": 3.08}, headers=auth_headers
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "fr_instantane"
        assert body["stations"] == []
        assert body["warnings"] == ["fr_instantane: request failed"]

    async def test_bad_coordinates_are_422(self, client: AsyncClient, auth_headers):
        response = await client.get(
            "/api/fuel-prices/nearby", params={"lat": 95, "lon": 3.08}, headers=auth_headers
        )
        assert response.status_code == 422


class TestAddressBook:
    async def test_the_saved_station_is_the_point(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession
    ):
        entry_id = await _station(db_session)
        with patch(NEARBY, new=AsyncMock(return_value=[STATION])) as nearby:
            response = await client.get(
                f"/api/address-book/{entry_id}/fuel-prices", headers=auth_headers
            )
        assert response.status_code == 200, response.text
        assert response.json()["provider"] == "fr_instantane"
        args = nearby.call_args.args
        assert (round(args[1], 5), round(args[2], 5)) == (45.78, 3.087)

    async def test_a_station_without_coordinates_is_422_and_an_unknown_one_404(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession
    ):
        entry_id = await _station(db_session, with_coordinates=False)
        response = await client.get(
            f"/api/address-book/{entry_id}/fuel-prices", headers=auth_headers
        )
        assert response.status_code == 422
        response = await client.get("/api/address-book/987654321/fuel-prices", headers=auth_headers)
        assert response.status_code == 404
