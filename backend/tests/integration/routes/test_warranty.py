"""
Integration tests for warranty record routes.

Tests warranty record CRUD operations.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestWarrantyRecordRoutes:
    """Test warranty record API endpoints."""

    async def test_list_warranties(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing warranty records for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_get_warranty_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific warranty record."""
        # First create a warranty record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json={
                "warranty_type": "Powertrain",
                "provider": "Honda",
                "start_date": "2024-01-01",
                "end_date": "2029-01-01",
                "mileage_limit": 60000,
                "coverage_details": "Engine, transmission, drivetrain",
                "policy_number": "HND-PT-12345",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the warranty record
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/warranties/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["warranty_type"] == "Powertrain"
        assert data["mileage_limit"] == 60000

    async def test_create_warranty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new warranty record."""
        payload = {
            "warranty_type": "Bumper-to-Bumper",
            "provider": "Honda",
            "start_date": datetime.now().date().isoformat(),
            "end_date": (datetime.now() + timedelta(days=365 * 3)).date().isoformat(),
            "mileage_limit": 36000,
            "coverage_details": "Comprehensive coverage excluding wear items",
            "notes": "Factory warranty",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["warranty_type"] == payload["warranty_type"]
        assert data["provider"] == payload["provider"]
        assert data["mileage_limit"] == payload["mileage_limit"]
        assert "id" in data
        assert "created_at" in data

    async def test_update_warranty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a warranty record."""
        # Create a warranty record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json={
                "warranty_type": "Extended",
                "start_date": "2024-01-01",
                "end_date": "2027-01-01",
                "mileage_limit": 100000,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the record
        update_data = {
            "mileage_limit": 125000,
            "notes": "Extended coverage purchased",
            "policy_number": "EXT-12345",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/warranties/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["mileage_limit"] == 125000
        assert data["notes"] == "Extended coverage purchased"
        assert data["policy_number"] == "EXT-12345"

    async def test_delete_warranty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a warranty record."""
        # Create a warranty record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json={
                "warranty_type": "Corrosion",
                "start_date": "2024-01-01",
                "end_date": "2031-01-01",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the record
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/warranties/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/warranties/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_warranty_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access warranty records."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/warranties")

        assert response.status_code == 401

    async def test_create_warranty_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid warranty records are rejected."""
        invalid_payload = {
            "warranty_type": "Test",
            "start_date": "2024-01-01",
            "mileage_limit": -1000,  # Negative mileage should fail
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_warranty_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test warranty with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/warranties",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_warranty_record_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get warranty with non-existent record ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/warranties/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_warranty_minimal(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a warranty with minimal required fields."""
        payload = {
            "warranty_type": "Other",  # Must be valid: Manufacturer, Powertrain, Extended, Bumper-to-Bumper, Emissions, Corrosion, Other
            "start_date": "2024-06-01",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["warranty_type"] == "Other"
        assert data["provider"] is None
        assert data["end_date"] is None
        assert data["mileage_limit"] is None

    async def test_warranty_ordering(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that warranties are ordered by start_date descending."""
        # Create warranties out of order using valid types
        warranty_data = [
            ("2022-01-01", "Manufacturer"),
            ("2024-01-01", "Powertrain"),
            ("2023-01-01", "Emissions"),
        ]

        for date, warranty_type in warranty_data:
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/warranties",
                json={
                    "warranty_type": warranty_type,
                    "start_date": date,
                },
                headers=auth_headers,
            )

        # Get list
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should be ordered by start_date descending
        if len(data) >= 2:
            for i in range(len(data) - 1):
                assert data[i]["start_date"] >= data[i + 1]["start_date"]

    async def test_update_warranty_partial(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test partial update of warranty record."""
        # Create a warranty record using a valid type
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json={
                "warranty_type": "Extended",
                "provider": "Original Provider",
                "start_date": "2024-01-01",
                "end_date": "2027-01-01",
                "coverage_details": "Full coverage",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.json()}"
        record = create_response.json()

        # Update only one field
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/warranties/{record['id']}",
            json={"notes": "Transferred from previous owner"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original fields unchanged
        assert data["warranty_type"] == "Extended"
        assert data["provider"] == "Original Provider"
        assert data["coverage_details"] == "Full coverage"
        # New field added
        assert data["notes"] == "Transferred from previous owner"

    async def test_warranty_with_all_fields(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a warranty with all optional fields populated."""
        payload = {
            "warranty_type": "Extended",  # Must be valid type
            "provider": "Third Party Warranty Co",
            "start_date": "2024-01-01",
            "end_date": "2030-01-01",
            "mileage_limit": 150000,
            "coverage_details": "Covers engine, transmission, drivetrain, electronics, A/C",
            "policy_number": "TPW-2024-12345-EXT",
            "notes": "Purchased at time of sale, transferable to new owner",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/warranties",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        for key, value in payload.items():
            assert data[key] == value
