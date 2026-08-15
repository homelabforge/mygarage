"""Tests for external vehicle CRUD routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.settings import Setting


async def _set_setting(db_session, key: str, value: str) -> None:
    result = await db_session.execute(select(Setting).where(Setting.key == key))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = value
    else:
        db_session.add(Setting(key=key, value=value, category="general"))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestExternalVehicleRoutes:
    async def test_reference_crud(self, client: AsyncClient, auth_headers, db_session):
        await _set_setting(db_session, "family_friends_enabled", "true")

        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={
                "nickname": "Dad's RAV4",
                "year": 2018,
                "make": "Toyota",
                "model": "RAV4",
                "contact_name": "Dad",
                "contact_phone": "555-0142",
                "notes": "Oil change due soon",
            },
        )
        assert create.status_code == 201, create.text
        body = create.json()
        assert body["nickname"] == "Dad's RAV4"
        assert body["contact_name"] == "Dad"
        vehicle_id = body["id"]

        listed = await client.get(
            "/api/external-vehicles",
            headers=auth_headers,
        )
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1
        assert any(v["id"] == vehicle_id for v in listed.json()["vehicles"])

        updated = await client.put(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
            json={"notes": "Brakes done"},
        )
        assert updated.status_code == 200
        assert updated.json()["notes"] == "Brakes done"

        deleted = await client.delete(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
        )
        assert deleted.status_code == 204

    async def test_optional_vin_create_and_update(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _set_setting(db_session, "family_friends_enabled", "true")
        vin = "1HGBH41JXMN109186"

        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={
                "nickname": "Lookup Civic",
                "vin": vin.lower(),
                "year": 2021,
                "make": "Honda",
                "model": "Civic",
            },
        )
        assert create.status_code == 201, create.text
        body = create.json()
        assert body["vin"] == vin
        vehicle_id = body["id"]

        cleared = await client.put(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
            json={"vin": ""},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["vin"] is None

        restored = await client.put(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
            json={"vin": vin},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["vin"] == vin

        invalid = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"nickname": "Bad VIN", "vin": "SHORT"},
        )
        assert invalid.status_code == 422

    async def test_create_forbidden_when_disabled(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _set_setting(db_session, "family_friends_enabled", "false")

        response = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"nickname": "Hidden Reference"},
        )
        assert response.status_code == 403

    async def test_list_empty_when_disabled(self, client: AsyncClient, auth_headers, db_session):
        await _set_setting(db_session, "family_friends_enabled", "true")
        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"nickname": "Temp Reference"},
        )
        assert create.status_code == 201, create.text

        await _set_setting(db_session, "family_friends_enabled", "false")
        listed = await client.get(
            "/api/external-vehicles",
            headers=auth_headers,
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 0
        assert listed.json()["vehicles"] == []
