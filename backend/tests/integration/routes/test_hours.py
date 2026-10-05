"""
Integration tests for hours record routes.

Tests hours record CRUD operations and authorization, mirroring
``test_odometer.py`` (the distance-track analog). Manual creates set
``source='manual'`` with both FKs null; "latest" derives via the canonical
``latest_engine_hours_and_date`` helper (highest reading wins, not most
recent date -- a physical hour meter is monotonic).
"""

from datetime import datetime

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestHoursRecordRoutes:
    """Test hours record API endpoints."""

    async def test_list_hours_records(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing hours records for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert "latest_engine_hours" in data
        assert isinstance(data["records"], list)

    async def test_get_hours_record_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific hours record."""
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-01-15",
                "engine_hours": 812.4,
                "notes": "Monthly reading",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/hours/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert float(data["engine_hours"]) == 812.4
        assert data["notes"] == "Monthly reading"

    async def test_create_hours_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new hours record sets source=manual with null FKs."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "engine_hours": 1024.7,
            "notes": "Test hours reading",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert float(data["engine_hours"]) == payload["engine_hours"]
        assert data["notes"] == payload["notes"]
        assert data["source"] == "manual"
        assert data["fuel_record_id"] is None
        assert data["service_visit_id"] is None
        assert "id" in data
        assert "created_at" in data

    async def test_update_hours_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating an hours record."""
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-02-01",
                "engine_hours": 500.5,
                "notes": "Original reading",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        update_data = {
            "engine_hours": 515.2,
            "notes": "Corrected reading",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/hours/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["engine_hours"]) == 515.2
        assert data["notes"] == "Corrected reading"

    async def test_delete_hours_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting an hours record."""
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-02-15",
                "engine_hours": 620.0,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/hours/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/hours/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_hours_record_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access hours records."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/hours")

        assert response.status_code == 401

    async def test_create_hours_record_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid hours records are rejected."""
        invalid_payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-01-15",
            "engine_hours": -12.5,  # Negative hours should fail
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_hours_record_pagination(self, client: AsyncClient, auth_headers, own_vehicle):
        """Two pages of five split ten readings newest-first, no overlap."""
        vin = own_vehicle.vin
        dates = [f"2025-{m:02d}-15" for m in range(1, 11)]
        for i, on in enumerate(dates):
            created = await client.post(
                f"/api/vehicles/{vin}/hours",
                json={"vin": vin, "date": on, "engine_hours": 100.0 + i * 1},
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text

        first = await client.get(f"/api/vehicles/{vin}/hours?skip=0&limit=5", headers=auth_headers)
        assert first.status_code == 200, first.text
        second = await client.get(f"/api/vehicles/{vin}/hours?skip=5&limit=5", headers=auth_headers)
        assert second.status_code == 200, second.text

        page1, page2 = first.json(), second.json()
        assert page1["total"] == 10
        assert [x["date"] for x in page1["records"] + page2["records"]] == dates[::-1]

    async def test_hours_record_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test hours record with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/hours",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_hours_latest_tracking_is_max_reading_not_latest_date(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        """Latest hours = the highest reading on record, not the most recent date.

        A physical hour meter is monotonic, so a lower-hours record dated later
        (e.g. a correction) must not make "current hours" appear to regress.
        This is the deliberate divergence from odometer's naive
        "most recent date" list semantics -- hours uses the canonical
        ``latest_engine_hours_and_date`` helper (ORDER BY engine_hours DESC).
        """
        # Sentinel values well above anything else this shared own_vehicle
        # accumulates elsewhere in the module (mirrors odometer's
        # far-future-date trick, but on the value axis since "latest" here is
        # max-reading, not max-date).
        records = [
            {"date": "2030-01-01", "engine_hours": 999900.0},
            {"date": "2030-03-01", "engine_hours": 999850.0},  # later date, lower reading
        ]

        for record in records:
            await client.post(
                f"/api/vehicles/{own_vehicle.vin}/hours",
                json={
                    "vin": own_vehicle.vin,
                    "date": record["date"],
                    "engine_hours": record["engine_hours"],
                },
                headers=auth_headers,
            )

        response = await client.get(
            f"/api/vehicles/{own_vehicle.vin}/hours",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["latest_engine_hours"]) == 999900.0

    async def test_hours_record_ordering(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that hours records are ordered by date descending."""
        dates_and_hours = [
            ("2024-02-01", 200.0),
            ("2024-01-01", 150.0),
            ("2024-03-01", 250.0),
        ]

        for date, hours in dates_and_hours:
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/hours",
                json={
                    "vin": test_vehicle["vin"],
                    "date": date,
                    "engine_hours": hours,
                },
                headers=auth_headers,
            )

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        records = data["records"]

        if len(records) >= 2:
            for i in range(len(records) - 1):
                assert records[i]["date"] >= records[i + 1]["date"]

    async def test_create_hours_record_with_notes(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating hours record with optional notes."""
        response_no_notes = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-04-01",
                "engine_hours": 300.0,
            },
            headers=auth_headers,
        )
        assert response_no_notes.status_code == 201
        data_no_notes = response_no_notes.json()
        assert data_no_notes["notes"] is None

        response_with_notes = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-04-15",
                "engine_hours": 310.0,
                "notes": "Annual inspection reading",
            },
            headers=auth_headers,
        )
        assert response_with_notes.status_code == 201
        data_with_notes = response_with_notes.json()
        assert data_with_notes["notes"] == "Annual inspection reading"

    async def test_update_hours_record_partial(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test partial update of hours record (only some fields)."""
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/hours",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-05-01",
                "engine_hours": 400.0,
                "notes": "Original notes",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/hours/{record['id']}",
            json={"notes": "Updated notes only"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["engine_hours"]) == 400.0  # Unchanged
        assert data["notes"] == "Updated notes only"


@pytest.mark.integration
def test_hours_route_registered_in_openapi() -> None:
    """The mounted app exposes /api/vehicles/{vin}/hours (mirrors odometer wiring)."""
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/vehicles/{vin}/hours" in paths
    assert "/api/vehicles/{vin}/hours/{record_id}" in paths


@pytest.mark.integration
@pytest.mark.asyncio
class TestHoursRecordAuthz:
    """Authorization matrix for hours-record CRUD: owner/write-share mutate,
    read-share GET-only, unrelated 403, unknown vin/record 404.

    Mirrors the "Group B: child writes = write-share" pattern established in
    ``test_authz_vehicle_cluster.py`` (e.g. ``TestTrailerChildWrite``), using
    the shared ``owned_vehicle``/``*_headers`` fixtures from this directory's
    ``conftest.py``.
    """

    def _payload(self, vin: str) -> dict:
        return {"vin": vin, "date": "2024-06-01", "engine_hours": 111.1}

    async def test_owner_can_create(self, client, owned_vehicle, owner_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=owner_headers,
        )
        assert resp.status_code == 201

    async def test_owner_can_update_and_delete(self, client, owned_vehicle, owner_headers):
        created = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=owner_headers,
        )
        record_id = created.json()["id"]

        update_resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}",
            json={"engine_hours": 222.2},
            headers=owner_headers,
        )
        assert update_resp.status_code == 200

        delete_resp = await client.delete(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}",
            headers=owner_headers,
        )
        assert delete_resp.status_code == 204

    async def test_write_share_can_create(self, client, owned_vehicle, writer_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=writer_headers,
        )
        assert resp.status_code == 201

    async def test_write_share_can_update(self, client, owned_vehicle, writer_headers):
        created = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=writer_headers,
        )
        record_id = created.json()["id"]

        resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}",
            json={"engine_hours": 333.3},
            headers=writer_headers,
        )
        assert resp.status_code == 200

    async def test_write_share_can_delete(self, client, owned_vehicle, writer_headers):
        created = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=writer_headers,
        )
        record_id = created.json()["id"]

        resp = await client.delete(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}",
            headers=writer_headers,
        )
        assert resp.status_code == 204

    async def test_read_share_cannot_create(self, client, owned_vehicle, reader_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_read_share_cannot_update(
        self, client, owned_vehicle, writer_headers, reader_headers
    ):
        created = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=writer_headers,
        )
        record_id = created.json()["id"]

        resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}",
            json={"engine_hours": 444.4},
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_read_share_cannot_delete(
        self, client, owned_vehicle, writer_headers, reader_headers
    ):
        created = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=writer_headers,
        )
        record_id = created.json()["id"]

        resp = await client.delete(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}",
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_read_share_can_get_and_list(
        self, client, owned_vehicle, writer_headers, reader_headers
    ):
        created = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=writer_headers,
        )
        record_id = created.json()["id"]

        list_resp = await client.get(
            f"/api/vehicles/{owned_vehicle.vin}/hours", headers=reader_headers
        )
        assert list_resp.status_code == 200

        get_resp = await client.get(
            f"/api/vehicles/{owned_vehicle.vin}/hours/{record_id}", headers=reader_headers
        )
        assert get_resp.status_code == 200

    async def test_unrelated_cannot_create(self, client, owned_vehicle, unrelated_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/hours",
            json=self._payload(owned_vehicle.vin),
            headers=unrelated_headers,
        )
        assert resp.status_code == 403

    async def test_unrelated_cannot_list(self, client, owned_vehicle, unrelated_headers):
        resp = await client.get(
            f"/api/vehicles/{owned_vehicle.vin}/hours", headers=unrelated_headers
        )
        assert resp.status_code == 403

    async def test_unknown_vin_404(self, client, owner_headers):
        resp = await client.get("/api/vehicles/NOSUCHVIN0000000AB/hours", headers=owner_headers)
        assert resp.status_code == 404

    async def test_unknown_record_404(self, client, owned_vehicle, owner_headers):
        resp = await client.get(
            f"/api/vehicles/{owned_vehicle.vin}/hours/999999", headers=owner_headers
        )
        assert resp.status_code == 404
