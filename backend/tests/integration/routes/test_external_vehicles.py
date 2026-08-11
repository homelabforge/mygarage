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
    async def test_customer_crud(self, client: AsyncClient, auth_headers, db_session):
        await _set_setting(db_session, "customers_enabled", "true")

        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={
                "kind": "customer",
                "nickname": "Smith's Civic",
                "year": 2016,
                "make": "Honda",
                "model": "Civic",
                "contact_name": "Jane Smith",
                "contact_phone": "555-0142",
                "last_service_note": "Oil change",
            },
        )
        assert create.status_code == 201, create.text
        body = create.json()
        assert body["kind"] == "customer"
        assert body["nickname"] == "Smith's Civic"
        vehicle_id = body["id"]

        listed = await client.get(
            "/api/external-vehicles",
            headers=auth_headers,
            params={"kind": "customer"},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1
        assert any(v["id"] == vehicle_id for v in listed.json()["vehicles"])

        updated = await client.put(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
            json={"last_service_note": "Brakes"},
        )
        assert updated.status_code == 200
        assert updated.json()["last_service_note"] == "Brakes"

        deleted = await client.delete(
            f"/api/external-vehicles/{vehicle_id}",
            headers=auth_headers,
        )
        assert deleted.status_code == 204

    async def test_reference_kind(self, client: AsyncClient, auth_headers, db_session):
        await _set_setting(db_session, "family_friends_enabled", "true")

        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={
                "kind": "reference",
                "nickname": "Dad's RAV4",
                "contact_name": "Dad",
            },
        )
        assert create.status_code == 201, create.text
        assert create.json()["kind"] == "reference"

    async def test_create_forbidden_when_disabled(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _set_setting(db_session, "customers_enabled", "false")
        await _set_setting(db_session, "family_friends_enabled", "false")

        customer = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"kind": "customer", "nickname": "Hidden Customer"},
        )
        assert customer.status_code == 403

        reference = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"kind": "reference", "nickname": "Hidden Reference"},
        )
        assert reference.status_code == 403

    async def test_list_empty_when_disabled(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _set_setting(db_session, "customers_enabled", "true")
        create = await client.post(
            "/api/external-vehicles",
            headers=auth_headers,
            json={"kind": "customer", "nickname": "Temp Customer"},
        )
        assert create.status_code == 201, create.text

        await _set_setting(db_session, "customers_enabled", "false")
        listed = await client.get(
            "/api/external-vehicles",
            headers=auth_headers,
            params={"kind": "customer"},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 0
        assert listed.json()["vehicles"] == []
