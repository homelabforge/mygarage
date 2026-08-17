"""Integration tests for tire tracking routes."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestTireRoutes:
    """Tire CRUD, readings, wear projection, and low-tread reminders."""

    async def test_list_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/tires",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tires"] == []
        assert data["total"] == 0

    async def test_upsert_list_and_delete(self, client: AsyncClient, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        create = await client.post(
            f"/api/vehicles/{vin}/tires",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "FL",
                "brand": "Michelin",
                "model_name": "Pilot Sport 4",
                "size": "225/45R17",
                "dot_code": "2324",
                "tread_depth_mm": "6.5",
                "pressure_kpa": "230",
                "min_tread_mm": "2.0",
            },
        )
        assert create.status_code == 201
        tire = create.json()
        assert tire["position"] == "FL"
        assert tire["brand"] == "Michelin"
        assert float(tire["tread_depth_mm"]) == pytest.approx(6.5)
        assert tire["below_threshold"] is False

        listed = await client.get(f"/api/vehicles/{vin}/tires", headers=auth_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        deleted = await client.delete(
            f"/api/vehicles/{vin}/tires/{tire['id']}",
            headers=auth_headers,
        )
        assert deleted.status_code == 204

        listed_again = await client.get(f"/api/vehicles/{vin}/tires", headers=auth_headers)
        assert listed_again.json()["total"] == 0

    async def test_invalid_position_rejected(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/tires",
            headers=auth_headers,
            json={
                "vin": test_vehicle["vin"],
                "position": "XX",
                "tread_depth_mm": "5.0",
            },
        )
        assert response.status_code == 422

    async def test_readings_project_wear(self, client: AsyncClient, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "FR",
                "brand": "Continental",
                "tread_depth_mm": "6.0",
                "min_tread_mm": "2.0",
            },
        )
        assert created.status_code == 201
        tire_id = created.json()["id"]

        first = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={
                "recorded_at": "2026-01-01",
                "odometer_km": "10000",
                "tread_depth_mm": "6.0",
            },
        )
        assert first.status_code == 201

        second = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/readings",
            headers=auth_headers,
            json={
                "recorded_at": "2026-06-01",
                "odometer_km": "12000",
                "tread_depth_mm": "4.0",
            },
        )
        assert second.status_code == 201
        data = second.json()
        assert float(data["tread_depth_mm"]) == pytest.approx(4.0)
        assert data["projected_km_remaining"] is not None
        assert float(data["projected_km_remaining"]) == pytest.approx(2000.0)
        assert data["projected_wear_date"] is not None
        assert len(data["readings"]) >= 2

    async def test_low_tread_creates_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "RR",
                "brand": "Michelin",
                "tread_depth_mm": "1.8",
                "min_tread_mm": "2.0",
            },
        )
        assert created.status_code == 201
        tire = created.json()
        assert tire["below_threshold"] is True

        reminders = await client.get(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
        )
        assert reminders.status_code == 200
        titles = [r["title"] for r in reminders.json()]
        assert "Tire tread low (RR)" in titles

    async def test_update_tire_metadata(self, client: AsyncClient, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/tires",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "RL",
                "brand": "Goodyear",
                "tread_depth_mm": "5.0",
            },
        )
        tire_id = created.json()["id"]
        updated = await client.put(
            f"/api/vehicles/{vin}/tires/{tire_id}",
            headers=auth_headers,
            json={"brand": "Pirelli", "notes": "rotated"},
        )
        assert updated.status_code == 200
        assert updated.json()["brand"] == "Pirelli"
        assert updated.json()["notes"] == "rotated"

    async def test_low_tread_reminder_cleared_with_done_status(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        """A cleared low-tread reminder must stay findable in the UI.

        'completed' is not in the app vocabulary, so a reminder set to it drops
        out of every list filter and can never be reopened or deleted.
        """
        from sqlalchemy import select

        from app.models.reminder import Reminder

        vin = test_vehicle["vin"]
        await client.post(
            f"/api/vehicles/{vin}/tires",
            headers=auth_headers,
            json={"vin": vin, "position": "RL", "tread_depth_mm": "2.0", "min_tread_mm": "3.0"},
        )
        await client.post(
            f"/api/vehicles/{vin}/tires",
            headers=auth_headers,
            json={"vin": vin, "position": "RL", "tread_depth_mm": "8.0", "min_tread_mm": "3.0"},
        )
        result = await db_session.execute(
            select(Reminder).where(Reminder.vin == vin, Reminder.title == "Tire tread low (RL)")
        )
        assert result.scalar_one().status == "done"
