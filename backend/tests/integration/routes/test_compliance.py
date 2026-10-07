"""GET /api/vehicles/{vin}/compliance and the EU certificate fields (#211).

Every test creates its own vehicle (the shared one has no country). Dates
are relative to the household's today so the inspection part never expires.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from dateutil.relativedelta import relativedelta
from httpx import AsyncClient
from sqlalchemy import delete

from app.models.vehicle import Vehicle
from app.utils.household_time import household_today

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture(autouse=True)
async def _drop_compliance_vehicles(db_session):
    yield
    await db_session.rollback()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.like("MCPL%")))
    await db_session.commit()


def _vin() -> str:
    return ("MCPL" + uuid.uuid4().hex.upper())[:17]


async def _vehicle(client: AsyncClient, headers: dict, **fields) -> str:
    vin = _vin()
    payload = {"vin": vin, "nickname": f"cpl-{vin[-4:]}", "vehicle_type": "Car", **fields}
    r = await client.post("/api/vehicles", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()["vin"]


async def _compliance(client: AsyncClient, headers: dict, vin: str) -> dict:
    r = await client.get(f"/api/vehicles/{vin}/compliance", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


class TestCertificateFields:
    async def test_round_trip_and_bounds(self, client: AsyncClient, auth_headers):
        vin = await _vehicle(
            client,
            auth_headers,
            euro_emission_class="Euro 6d-TEMP",
            fiscal_power=5,
            co2_g_km=118,
            power_kw=74,
            eu_category="M1",
            national_category="VP",
        )
        r = await client.get(f"/api/vehicles/{vin}", headers=auth_headers)
        body = r.json()
        assert body["euro_emission_class"] == "Euro 6d-TEMP"
        assert body["fiscal_power"] == 5
        assert body["co2_g_km"] == 118
        assert body["power_kw"] == 74
        assert body["eu_category"] == "M1"
        assert body["national_category"] == "VP"
        assert body["lez_class"] is None

        r = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"lez_class": "1", "co2_g_km": None}
        )
        assert r.status_code == 200, r.text
        assert r.json()["lez_class"] == "1"
        assert r.json()["co2_g_km"] is None

        for bad in (
            {"fiscal_power": -1},
            {"co2_g_km": 1000},
            {"power_kw": 2001},
            {"eu_category": "M1XXXX"},
        ):
            r = await client.put(f"/api/vehicles/{vin}", headers=auth_headers, json=bad)
            assert r.status_code == 422, bad


class TestCompliance:
    async def test_no_country_says_so(self, client: AsyncClient, auth_headers):
        vin = await _vehicle(client, auth_headers)
        body = await _compliance(client, auth_headers, vin)
        assert body["country"] is None
        assert body["reason"] == "no_country"
        assert body["lez"] is None and body["inspection"] is None

    async def test_a_country_without_a_profile(self, client: AsyncClient, auth_headers):
        vin = await _vehicle(client, auth_headers, registration_country="US")
        body = await _compliance(client, auth_headers, vin)
        assert body["country"] == "US"
        assert body["reason"] == "no_profile"

    async def test_french_petrol_car_critair_from_the_registration_date(
        self, client: AsyncClient, auth_headers
    ):
        first = household_today() - relativedelta(years=3, months=6)
        vin = await _vehicle(
            client,
            auth_headers,
            registration_country="FR",
            fuel_type="gasoline",
            first_registration_date=first.isoformat(),
        )
        body = await _compliance(client, auth_headers, vin)
        assert body["country"] == "FR" and body["profile_country"] == "FR"
        assert body["euro_class"] == 6 and body["euro_class_estimated"] is True
        lez = body["lez"]
        assert lez["scheme"] == "critair" and lez["name"] == "Crit'Air"
        assert lez["value"] == "1" and lez["basis"] == "first_registration"
        assert lez["overridden"] is False and lez["computed"] is True
        assert lez["url"].startswith("https://")
        inspection = body["inspection"]
        assert inspection["name"] == "Contrôle technique"
        assert inspection["automatic"] is True
        assert inspection["next_due_date"] == (first + relativedelta(years=4)).isoformat()
        assert inspection["lead_days"] == 180
        assert (
            inspection["window_opens_on"]
            == (first + relativedelta(years=4) - relativedelta(days=180)).isoformat()
        )
        assert inspection["from_registration"] is True
        assert inspection["reminder_id"] and inspection["rule_id"]
        assert body["sources"]

    async def test_recorded_euro_class_and_override(self, client: AsyncClient, auth_headers):
        vin = await _vehicle(
            client,
            auth_headers,
            registration_country="FR",
            fuel_type="diesel",
            euro_emission_class="EURO4",
            first_registration_date="2015-06-01",
        )
        body = await _compliance(client, auth_headers, vin)
        assert body["euro_class"] == 4 and body["euro_class_estimated"] is False
        assert body["lez"]["value"] == "3" and body["lez"]["basis"] == "euro_class"

        r = await client.put(f"/api/vehicles/{vin}", headers=auth_headers, json={"lez_class": "2"})
        assert r.status_code == 200
        body = await _compliance(client, auth_headers, vin)
        assert body["lez"]["value"] == "2"
        assert body["lez"]["basis"] == "override" and body["lez"]["overridden"] is True

    async def test_a_scheme_mygarage_does_not_compute(self, client: AsyncClient, auth_headers):
        vin = await _vehicle(
            client,
            auth_headers,
            registration_country="DE",
            fuel_type="gasoline",
            first_registration_date="2012-01-01",
        )
        body = await _compliance(client, auth_headers, vin)
        assert body["lez"]["scheme"] == "umweltplakette"
        assert body["lez"]["computed"] is False
        assert body["lez"]["value"] is None and body["lez"]["basis"] is None
        assert body["inspection"]["name"] == "Hauptuntersuchung (HU)"

    async def test_unclassified_and_no_inspection_scheduled(
        self, client: AsyncClient, auth_headers
    ):
        # A Luxembourg motorcycle without a date: no LEZ scheme in LU, the
        # inspection exists in the profile but nothing is scheduled.
        vin = await _vehicle(
            client, auth_headers, registration_country="LU", vehicle_type="Motorcycle"
        )
        body = await _compliance(client, auth_headers, vin)
        assert body["lez"] is None
        assert body["inspection"]["automatic"] is False
        assert body["inspection"]["next_due_date"] is None

    async def test_unknown_vehicle_is_404_and_read_share_can_read(
        self, client: AsyncClient, auth_headers
    ):
        r = await client.get("/api/vehicles/MCPLNOSUCHVIN0001/compliance", headers=auth_headers)
        assert r.status_code == 404
