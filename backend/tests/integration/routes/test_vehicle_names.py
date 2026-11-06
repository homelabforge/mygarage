"""Make and model reach the database in Title Case (#219 takeover)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.settings import Setting


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleNames:
    async def test_create_and_update_store_title_case(self, client: AsyncClient, auth_headers):
        payload = {
            "nickname": "Names test",
            "vehicle_type": "Car",
            "identifier_type": "none",
            "make": "MITSUBISHI",
            "model": "MIRAGE",
        }
        response = await client.post("/api/vehicles", json=payload, headers=auth_headers)
        assert response.status_code == 201, response.text
        body = response.json()
        assert (body["make"], body["model"]) == ("Mitsubishi", "Mirage")
        vin = body["vin"]
        try:
            response = await client.put(
                f"/api/vehicles/{vin}",
                json={"make": "LAND ROVER", "model": "RANGE ROVER SPORT"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            got = await client.get(f"/api/vehicles/{vin}", headers=auth_headers)
            assert (got.json()["make"], got.json()["model"]) == ("Land Rover", "Range Rover Sport")
        finally:
            await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)

    async def test_external_vehicle_stores_title_case(
        self, client: AsyncClient, auth_headers, db_session
    ):
        row = (
            await db_session.execute(select(Setting).where(Setting.key == "family_friends_enabled"))
        ).scalar_one_or_none()
        if row is None:
            db_session.add(Setting(key="family_friends_enabled", value="true", category="general"))
        else:
            row.value = "true"
        await db_session.commit()

        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"nickname": "Names friend", "make": "HONDA", "model": "CR-V"},
        )
        assert create.status_code == 201, create.text
        assert (create.json()["make"], create.json()["model"]) == ("Honda", "CR-V")
        vehicle_id = create.json()["id"]
        updated = await client.put(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
            json={"make": "VW", "model": "GOLF GTI"},
        )
        assert updated.status_code == 200, updated.text
        assert (updated.json()["make"], updated.json()["model"]) == ("Volkswagen", "Golf GTI")
        await client.delete(f"/api/external-vehicles/{vehicle_id}", headers=auth_headers)
