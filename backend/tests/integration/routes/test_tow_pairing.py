"""Integration tests for tow pairing / trailer details."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestTowPairing:
    async def test_create_trailer_with_tow_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session, test_user
    ):
        # Create a trailer vehicle
        trailer = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": "1HGCM82633A004999",
                "nickname": "Utility Trailer",
                "vehicle_type": "Trailer",
            },
        )
        assert trailer.status_code == 201, trailer.text
        trailer_vin = trailer.json()["vin"]

        created = await client.post(
            f"/api/vehicles/{trailer_vin}/trailer",
            headers=auth_headers,
            json={
                "vin": trailer_vin,
                "hitch_type": "Ball",
                "tow_vehicle_vin": test_vehicle["vin"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["tow_vehicle_vin"] == test_vehicle["vin"]

        linked = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/towed-trailers",
            headers=auth_headers,
        )
        assert linked.status_code == 200
        vins = [v["vin"] for v in linked.json()]
        assert trailer_vin in vins

    async def test_reject_trailer_as_tow_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        trailer_a = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": "1HGCM82633A004998",
                "nickname": "Trailer A",
                "vehicle_type": "Trailer",
            },
        )
        trailer_b = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": "1HGCM82633A004997",
                "nickname": "Trailer B",
                "vehicle_type": "Trailer",
            },
        )
        assert trailer_a.status_code == 201
        assert trailer_b.status_code == 201

        response = await client.post(
            f"/api/vehicles/{trailer_a.json()['vin']}/trailer",
            headers=auth_headers,
            json={
                "vin": trailer_a.json()["vin"],
                "tow_vehicle_vin": trailer_b.json()["vin"],
            },
        )
        assert response.status_code == 400
