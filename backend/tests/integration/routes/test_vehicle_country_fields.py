"""The country fields of #211: on the user, on the vehicle, on the instance."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestUserCountry:
    async def test_set_normalises_and_clears(self, client: AsyncClient, auth_headers):
        response = await client.put("/api/auth/me", json={"country": "fr"}, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["country"] == "FR"
        assert response.json()["inspection_auto_schedule"] is True

        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.json()["country"] == "FR"

        response = await client.put("/api/auth/me", json={"country": None}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["country"] is None

    async def test_unknown_code_is_422(self, client: AsyncClient, auth_headers):
        response = await client.put("/api/auth/me", json={"country": "XX"}, headers=auth_headers)
        assert response.status_code == 422
        response = await client.put("/api/auth/me", json={"country": "FRA"}, headers=auth_headers)
        assert response.status_code == 422

    async def test_inspection_auto_schedule_toggle(self, client: AsyncClient, auth_headers):
        response = await client.put(
            "/api/auth/me", json={"inspection_auto_schedule": False}, headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["inspection_auto_schedule"] is False
        # NOT NULL: null is refused, omitted keeps the value.
        response = await client.put(
            "/api/auth/me", json={"inspection_auto_schedule": None}, headers=auth_headers
        )
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleCountryFields:
    async def test_create_with_country_and_first_registration(
        self, client: AsyncClient, auth_headers
    ):
        payload = {
            "vin": "VF1RFB00X56123456",
            "nickname": "Clio",
            "vehicle_type": "Car",
            "registration_country": "lu",
            "first_registration_date": "2023-03-12",
        }
        response = await client.post("/api/vehicles", json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["registration_country"] == "LU"
        assert body["first_registration_date"] == "2023-03-12"

    async def test_update_and_clear(self, client: AsyncClient, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        response = await client.put(
            f"/api/vehicles/{vin}",
            json={"registration_country": "FR", "first_registration_date": "2019-06-01"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["registration_country"] == "FR"
        assert response.json()["first_registration_date"] == "2019-06-01"

        response = await client.put(
            f"/api/vehicles/{vin}",
            json={"registration_country": None, "first_registration_date": None},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["registration_country"] is None
        assert response.json()["first_registration_date"] is None

    async def test_invalid_country_is_422(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}",
            json={"registration_country": "ZZ"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_defaults_are_null(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["registration_country"] is None
        assert response.json()["first_registration_date"] is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestInstanceDefaultCountry:
    async def test_batch_write_validates_and_publishes(self, client: AsyncClient, auth_headers):
        response = await client.post(
            "/api/settings/batch",
            json={"settings": {"default_country": "XX"}},
            headers=auth_headers,
        )
        assert response.status_code == 422

        response = await client.post(
            "/api/settings/batch",
            json={"settings": {"default_country": "fr"}},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

        response = await client.get("/api/settings/public")
        assert response.status_code == 200
        values = {s["key"]: s["value"] for s in response.json()["settings"]}
        assert values["default_country"] == "fr"

        # Blank clears it.
        response = await client.post(
            "/api/settings/batch",
            json={"settings": {"default_country": ""}},
            headers=auth_headers,
        )
        assert response.status_code == 200
