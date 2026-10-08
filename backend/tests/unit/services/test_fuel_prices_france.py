"""The French fuel price provider (#211): the record mapping, the query, the
cache, the allowlist, and which provider a country gets.

`RECORD` is shaped like a record of « Prix des carburants en France, flux
instantané v2 » as captured on 2026-10-07: a price and a « maj » timestamp
per fuel the pump sells, the address, and `geom` in degrees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.exceptions import SSRFProtectionError
from app.models.settings import Setting
from app.services.country_profile_service import profile_for_country
from app.services.fuel_prices import france
from app.services.fuel_prices.france import (
    FrenchFuelPriceProvider,
    haversine_km,
    prices_of,
    station_from_record,
)
from app.services.fuel_prices.registry import enabled_provider_for, provider_by_id, provider_for
from app.utils.url_validation import validate_data_economie_url

RECORD: dict[str, Any] = {
    "id": "63000012",
    "cp": "63000",
    "pop": "R",
    "adresse": "12 Avenue de la République",
    "ville": "Clermont-Ferrand",
    "geom": {"lon": 3.0862, "lat": 45.7797},
    "gazole_prix": "1.689",
    "gazole_maj": "2026-10-07T06:12:00+00:00",
    "sp95_prix": None,
    "sp95_maj": None,
    "e10_prix": "1.729",
    "e10_maj": "2026-10-07T06:12:00+00:00",
    "sp98_prix": "1.819",
    "sp98_maj": "2026-10-06T18:40:00+00:00",
    "e85_prix": "0.799",
    "e85_maj": "2026-10-05T09:00:00+00:00",
    "gplc_prix": None,
    "gplc_maj": None,
    "carburants_disponibles": ["Gazole", "E10", "SP98", "E85"],
    "carburants_indisponibles": ["SP95", "GPLc"],
    "horaires_automate_24_24": "Oui",
}

FAR_RECORD: dict[str, Any] = {
    **RECORD,
    "id": "63000099",
    "adresse": "Route de Lyon",
    "geom": {"lon": 3.1100, "lat": 45.7900},
    "gazole_prix": "1.659",
}


def _page(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_count": len(records), "results": records}


def _client(pages: list[dict[str, Any]]):
    """`httpx.AsyncClient` answering the pages in order; returns the patcher
    and the `get` mock to inspect the query."""
    responses = []
    for page in pages:
        response = MagicMock()
        response.json.return_value = page
        response.raise_for_status.return_value = None
        responses.append(response)
    get = AsyncMock(side_effect=responses)
    client = MagicMock()
    client.get = get
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return patch("app.services.fuel_prices.france.httpx.AsyncClient", return_value=client), get


async def _set(db_session, key: str, value: str) -> None:
    row = (await db_session.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row is None:
        db_session.add(Setting(key=key, value=value, category="integrations"))
    else:
        row.value = value
    await db_session.commit()


@pytest.mark.unit
class TestMapping:
    def test_prices_in_pump_order_priced_fuels_only(self):
        prices = prices_of(RECORD)
        assert [(p.grade, p.octane, p.price) for p in prices] == [
            ("B7", None, Decimal("1.689")),
            ("E10", 95, Decimal("1.729")),
            ("E5", 98, Decimal("1.819")),
            ("E85", None, Decimal("0.799")),
        ]
        assert all(p.currency == "EUR" for p in prices)
        assert prices[0].updated_at == datetime(2026, 10, 7, 6, 12, tzinfo=UTC)

    def test_a_station_with_its_distance(self):
        station = station_from_record(RECORD, 45.7800, 3.0870)
        assert station is not None
        assert station.external_id == "63000012"
        assert station.city == "Clermont-Ferrand"
        assert station.postal_code == "63000"
        assert station.address == "12 Avenue de la République"
        assert (station.latitude, station.longitude) == (45.7797, 3.0862)
        assert 0 < station.distance_km < 0.1
        assert len(station.prices) == 4

    def test_a_record_without_coordinates_or_id_is_skipped(self):
        assert station_from_record({**RECORD, "geom": None}, 45.78, 3.08) is None
        assert station_from_record({**RECORD, "id": None}, 45.78, 3.08) is None

    def test_scaled_coordinates_are_read_as_degrees(self):
        record = {**RECORD, "geom": None, "latitude": 4577970, "longitude": 308620}
        station = station_from_record(record, 45.78, 3.08)
        assert station is not None
        assert (station.latitude, station.longitude) == (45.7797, 3.0862)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1,689", Decimal("1.689")),
            (1.5, Decimal("1.5")),
            ("0", None),
            (None, None),
            ("x", None),
        ],
    )
    def test_decimal_reading(self, raw, expected):
        assert france._decimal(raw) == expected

    def test_haversine(self):
        # Paris to Clermont-Ferrand, about 345 km.
        assert 340 < haversine_km(48.8566, 2.3522, 45.7797, 3.0862) < 350
        assert haversine_km(45.78, 3.08, 45.78, 3.08) == 0


@pytest.mark.unit
class TestRegistry:
    def test_france_names_the_instant_feed_and_others_name_none(self):
        provider = provider_for(profile_for_country("FR"))
        assert provider is not None and provider.id == "fr_instantane"
        assert provider_for(profile_for_country("DE")) is None
        assert provider_for(profile_for_country("US")) is None
        assert provider_for(None) is None
        assert provider_by_id("nope") is None

    async def test_the_setting_turns_it_off(self, db_session):
        await _set(db_session, france.ENABLED_SETTING, "false")
        try:
            assert await enabled_provider_for(db_session, profile_for_country("FR")) is None
        finally:
            await _set(db_session, france.ENABLED_SETTING, "true")
        assert await enabled_provider_for(db_session, profile_for_country("FR")) is not None


@pytest.mark.unit
class TestAllowlist:
    def test_the_default_url_passes(self):
        validate_data_economie_url(france.DEFAULT_API_URL)

    def test_another_host_and_plain_http_are_refused(self):
        with pytest.raises(SSRFProtectionError):
            validate_data_economie_url("https://example.com/records")
        with pytest.raises((SSRFProtectionError, ValueError)):
            validate_data_economie_url("http://data.economie.gouv.fr/records")

    async def test_a_refused_setting_falls_back_to_the_default(self, db_session):
        await _set(db_session, france.API_URL_SETTING, "https://example.com/records")
        try:
            assert await FrenchFuelPriceProvider().api_url(db_session) == france.DEFAULT_API_URL
        finally:
            await _set(db_session, france.API_URL_SETTING, "")
        assert await FrenchFuelPriceProvider().api_url(db_session) == france.DEFAULT_API_URL


@pytest.mark.unit
class TestNearby:
    async def test_asks_within_the_radius_nearest_first_and_maps_the_stations(self, db_session):
        france.clear_cache()
        patcher, get = _client([_page([FAR_RECORD, RECORD])])
        with patcher:
            stations = await FrenchFuelPriceProvider().nearby(
                db_session, 45.7800, 3.0870, radius_km=2, limit=5
            )
        assert [s.external_id for s in stations] == ["63000012", "63000099"]
        assert stations[0].distance_km < stations[1].distance_km
        assert get.call_args.args[0] == france.DEFAULT_API_URL
        params = get.call_args.kwargs["params"]
        assert params["where"] == "within_distance(geom, geom'POINT(3.087 45.78)', 2km)"
        assert params["order_by"] == "distance(geom, geom'POINT(3.087 45.78)')"
        assert params["limit"] == 5

    async def test_the_radius_and_the_limit_are_bounded(self, db_session):
        france.clear_cache()
        patcher, get = _client([_page([])])
        with patcher:
            await FrenchFuelPriceProvider().nearby(db_session, 45.78, 3.08, radius_km=900, limit=99)
        params = get.call_args.kwargs["params"]
        assert params["where"].endswith(f"{france.MAX_RADIUS_KM}km)")
        assert params["limit"] == france.MAX_LIMIT

    async def test_a_point_is_cached_for_ten_minutes(self, db_session):
        france.clear_cache()
        patcher, get = _client([_page([RECORD]), _page([])])
        with patcher:
            provider = FrenchFuelPriceProvider()
            first = await provider.nearby(db_session, 45.78001, 3.08002, radius_km=2, limit=5)
            again = await provider.nearby(db_session, 45.78004, 3.08001, radius_km=2, limit=5)
            other = await provider.nearby(db_session, 45.79, 3.08, radius_km=2, limit=5)
        assert first == again and len(first) == 1
        assert other == []
        assert get.await_count == 2

    async def test_a_malformed_answer_is_no_station(self, db_session):
        france.clear_cache()
        patcher, _get = _client([{"results": "not a list"}])
        with patcher:
            assert (
                await FrenchFuelPriceProvider().nearby(
                    db_session, 45.78, 3.08, radius_km=2, limit=5
                )
                == []
            )
