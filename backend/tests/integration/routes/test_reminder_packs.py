"""Integration tests for reminder pack list/apply endpoints."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestReminderPacks:
    async def test_list_reminder_packs(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/reminder-packs", headers=auth_headers)
        assert response.status_code == 200
        packs = response.json()
        assert isinstance(packs, list)
        assert len(packs) >= 3
        ids = {p["id"] for p in packs}
        assert {
            "oil_and_filter",
            "tire_rotation",
            "boat_winterization",
        }.issubset(ids)
        for pack in packs:
            assert pack["name"]
            assert pack["description"]
            assert pack["reminder_count"] >= 1

    async def test_apply_pack_creates_pending_reminders(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        response = await client.post(
            f"/api/vehicles/{vin}/reminders/apply-pack",
            json={"pack_id": "oil_and_filter"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        created = response.json()
        assert len(created) == 2
        titles = {r["title"] for r in created}
        assert titles == {"Oil & Filter Change", "Inspect Drain Plug Washer"}
        oil = next(r for r in created if r["title"] == "Oil & Filter Change")
        assert oil["reminder_type"] == "smart"
        assert oil["status"] == "pending"
        assert oil["due_date"] == (date.today() + timedelta(days=180)).isoformat()
        # No odometer history → pack interval used as absolute
        assert float(oil["due_mileage_km"]) == 8000.0

    async def test_apply_boat_winterization_pack(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        response = await client.post(
            f"/api/vehicles/{vin}/reminders/apply-pack",
            json={"pack_id": "boat_winterization"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        created = response.json()
        assert len(created) == 4
        assert all(r["status"] == "pending" for r in created)
        assert all(r["due_date"] is not None for r in created)

    async def test_apply_unknown_pack_404(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/apply-pack",
            json={"pack_id": "does_not_exist"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_apply_path_traversal_pack_404(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/apply-pack",
            json={"pack_id": "../oil_and_filter"},
            headers=auth_headers,
        )
        assert response.status_code == 404
