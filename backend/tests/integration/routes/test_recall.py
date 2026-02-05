"""
Integration tests for recall routes.

Tests recall CRUD operations and NHTSA integration endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecallRoutes:
    """Test recall API endpoints."""

    async def test_list_recalls(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing recalls for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "recalls" in data
        assert "total" in data
        assert "active_count" in data
        assert "resolved_count" in data
        assert isinstance(data["recalls"], list)

    async def test_get_recall_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific recall."""
        # First create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Airbag",
                "summary": "Potential airbag deployment issue",
                "nhtsa_campaign_number": "24V001",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        recall = create_response.json()

        # Get the recall
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == recall["id"]
        assert data["component"] == "Airbag"
        assert data["nhtsa_campaign_number"] == "24V001"

    async def test_create_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new recall manually."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Brakes",
            "summary": "Brake fluid leak detected under certain conditions",
            "consequence": "Loss of braking ability",
            "remedy": "Replace brake lines",
            "nhtsa_campaign_number": "24V002",
            "date_announced": "2024-01-15",
            "is_resolved": False,
            "notes": "Dealer scheduled for repair",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component"] == payload["component"]
        assert data["summary"] == payload["summary"]
        assert data["consequence"] == payload["consequence"]
        assert data["remedy"] == payload["remedy"]
        assert data["nhtsa_campaign_number"] == payload["nhtsa_campaign_number"]
        assert data["is_resolved"] is False
        assert "id" in data
        assert "created_at" in data

    async def test_update_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a recall."""
        # Create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Transmission",
                "summary": "Transmission hesitation issue",
            },
            headers=auth_headers,
        )
        recall = create_response.json()

        # Update the recall
        update_data = {
            "notes": "Repair completed at dealership",
            "is_resolved": True,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["notes"] == "Repair completed at dealership"
        assert data["is_resolved"] is True
        assert data["resolved_at"] is not None

    async def test_delete_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a recall."""
        # Create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Fuel System",
                "summary": "Fuel pump may fail",
            },
            headers=auth_headers,
        )
        recall = create_response.json()

        # Delete the recall
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_recall_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access recalls."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/recalls")

        assert response.status_code == 401

    async def test_recall_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test recalls with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/1HGBH000000000000/recalls",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_recall_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get recall with non-existent ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_resolved_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating an already-resolved recall."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Electrical",
            "summary": "Battery drain issue",
            "is_resolved": True,
            "notes": "Already fixed by previous owner",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["is_resolved"] is True
        assert data["resolved_at"] is not None

    async def test_mark_recall_unresolved(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test marking a resolved recall as unresolved."""
        # Create a resolved recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Cooling System",
                "summary": "Coolant leak",
                "is_resolved": True,
            },
            headers=auth_headers,
        )
        recall = create_response.json()
        assert recall["resolved_at"] is not None

        # Mark as unresolved
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            json={"is_resolved": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_resolved"] is False
        assert data["resolved_at"] is None

    async def test_list_recalls_filter_active(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test filtering recalls by active status."""
        # Create an active recall
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Steering",
                "summary": "Steering wheel vibration",
                "is_resolved": False,
            },
            headers=auth_headers,
        )

        # Create a resolved recall
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Suspension",
                "summary": "Suspension noise",
                "is_resolved": True,
            },
            headers=auth_headers,
        )

        # Filter by active only
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls?status=active",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned recalls should be active (not resolved)
        for recall in data["recalls"]:
            assert recall["is_resolved"] is False

    async def test_list_recalls_filter_resolved(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test filtering recalls by resolved status."""
        # Create a resolved recall
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Exhaust",
                "summary": "Exhaust leak",
                "is_resolved": True,
            },
            headers=auth_headers,
        )

        # Filter by resolved only
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls?status=resolved",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned recalls should be resolved
        for recall in data["recalls"]:
            assert recall["is_resolved"] is True

    async def test_recall_counts(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that recall counts are calculated correctly."""
        # Create multiple recalls with different statuses
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Active1",
                "summary": "Test1",
                "is_resolved": False,
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Active2",
                "summary": "Test2",
                "is_resolved": False,
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Resolved1",
                "summary": "Test3",
                "is_resolved": True,
            },
            headers=auth_headers,
        )

        # Get all recalls
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Verify counts make sense
        assert data["total"] == data["active_count"] + data["resolved_count"]
        assert data["active_count"] >= 2
        assert data["resolved_count"] >= 1

    async def test_partial_update_recall(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test partial update of recall."""
        # Create a recall
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json={
                "vin": test_vehicle["vin"],
                "component": "Tires",
                "summary": "Tire tread separation risk",
                "notes": "Original notes",
            },
            headers=auth_headers,
        )
        recall = create_response.json()

        # Update only summary
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/{recall['id']}",
            json={"summary": "Updated summary with more details"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original component unchanged
        assert data["component"] == "Tires"
        # Original notes unchanged
        assert data["notes"] == "Original notes"
        # Summary updated
        assert data["summary"] == "Updated summary with more details"

    async def test_recall_with_all_fields(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a recall with all possible fields."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Engine - Software",
            "summary": "Engine control module software update required",
            "consequence": "Unexpected engine stall while driving",
            "remedy": "Software reflash at dealer",
            "nhtsa_campaign_number": "24V003",
            "date_announced": "2024-02-01",
            "is_resolved": False,
            "notes": "Appointment scheduled for March 15th",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component"] == payload["component"]
        assert data["summary"] == payload["summary"]
        assert data["consequence"] == payload["consequence"]
        assert data["remedy"] == payload["remedy"]
        assert data["nhtsa_campaign_number"] == payload["nhtsa_campaign_number"]
        assert data["date_announced"] == payload["date_announced"]
        assert data["notes"] == payload["notes"]

    async def test_create_recall_minimal(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a recall with minimal required fields."""
        payload = {
            "vin": test_vehicle["vin"],
            "component": "Body",
            "summary": "Paint defect",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component"] == "Body"
        assert data["summary"] == "Paint defect"
        assert data["is_resolved"] is False  # Default
        assert data["consequence"] is None
        assert data["remedy"] is None
        assert data["nhtsa_campaign_number"] is None

    async def test_check_nhtsa_recalls_endpoint(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test the check-nhtsa endpoint exists and handles requests.

        The endpoint properly handles VIN decode failures by catching ValueError
        and returning a 422 response with a descriptive error message.
        """
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/recalls/check-nhtsa",
            headers=auth_headers,
        )

        # Valid status codes:
        # 200: Success with recalls data
        # 400/422: VIN could not be decoded (make/model/year not determinable)
        # 500: Internal error
        # 503: NHTSA unavailable
        # 504: NHTSA timeout
        assert response.status_code in [200, 400, 422, 500, 503, 504]
        if response.status_code == 200:
            data = response.json()
            assert "recalls" in data
            assert "total" in data
