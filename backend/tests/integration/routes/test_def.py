"""
Integration tests for DEF (Diesel Exhaust Fluid) record routes.

Tests DEF record CRUD operations and analytics.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFRecordRoutes:
    """Test DEF record API endpoints."""

    async def test_list_def_records_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing DEF records when none exist."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    async def test_create_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test creating a new DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert float(data["gallons"]) == payload["gallons"]
        assert float(data["cost"]) == payload["cost"]
        assert float(data["fill_level"]) == payload["fill_level"]
        assert data["source"] == payload["source"]
        assert data["brand"] == payload["brand"]

    async def test_create_def_record_minimal(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a DEF record with only required fields."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-06-01",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["date"] == "2024-06-01"

    async def test_get_def_record_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test retrieving a specific DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert float(data["gallons"]) == payload["gallons"]

    async def test_get_def_record_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a non-existent DEF record."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_update_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test updating a DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )
        record = create_response.json()

        update_data = {
            "cost": 25.00,
            "notes": "Updated cost",
            "fill_level": 0.75,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["cost"]) == 25.00
        assert data["notes"] == "Updated cost"
        assert float(data["fill_level"]) == 0.75

    async def test_delete_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test deleting a DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )
        record = create_response.json()

        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's gone
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_def_record_not_found(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a non-existent DEF record."""
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/def/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_def_record_invalid_vehicle(self, client: AsyncClient, auth_headers):
        """Test creating a DEF record for a non-existent vehicle."""
        fake_vin = "ZZZZZZZZZZZZZZ999"
        response = await client.post(
            f"/api/vehicles/{fake_vin}/def",
            json={
                "vin": fake_vin,
                "date": "2024-01-15",
                "gallons": 2.5,
            },
            headers=auth_headers,
        )

        assert response.status_code in (403, 404)

    async def test_def_record_fill_level_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that fill_level is validated between 0 and 1."""
        # fill_level > 1 should fail
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-01-15",
                "fill_level": 1.5,
            },
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_def_unauthenticated(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated requests are rejected."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def",
        )

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFAnalytics:
    """Test DEF analytics endpoint."""

    async def test_analytics_returns_valid_response(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test analytics endpoint returns valid structure."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/analytics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "record_count" in data
        assert "data_confidence" in data
        assert data["data_confidence"] in ("high", "low", "insufficient")
        assert isinstance(data["record_count"], int)

    async def test_analytics_with_records(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test analytics with multiple DEF records."""
        # Create several records with mileage data
        records = [
            {
                "vin": test_vehicle["vin"],
                "date": "2024-01-01",
                "mileage": 10000,
                "gallons": 2.5,
                "cost": 15.00,
                "fill_level": 1.0,
            },
            {
                "vin": test_vehicle["vin"],
                "date": "2024-02-01",
                "mileage": 12000,
                "gallons": 2.5,
                "cost": 16.00,
                "fill_level": 0.75,
            },
            {
                "vin": test_vehicle["vin"],
                "date": "2024-03-01",
                "mileage": 14000,
                "gallons": 2.5,
                "cost": 14.50,
                "fill_level": 0.50,
            },
        ]

        for record in records:
            resp = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/def",
                json=record,
                headers=auth_headers,
            )
            assert resp.status_code == 201

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/analytics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["record_count"] >= 3
        assert data["total_gallons"] is not None
        assert data["total_cost"] is not None
