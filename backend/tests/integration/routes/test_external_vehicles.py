"""Tests for external vehicle CRUD routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestExternalVehicleRoutes:
    async def test_customer_crud(self, client: AsyncClient, auth_headers):
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

    async def test_reference_kind(self, client: AsyncClient, auth_headers):
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
