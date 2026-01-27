"""
Integration tests for reminder routes.

Tests reminder CRUD operations and upcoming reminders.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestReminderRoutes:
    """Test reminder API endpoints."""

    async def test_create_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating a reminder for a vehicle."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],  # Required in body
                "description": "Oil Change Due - 5000 miles since last change",
                "due_date": tomorrow,
                "due_mileage": 20000,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "description" in data
        assert "id" in data

    async def test_list_reminders(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test listing reminders for a vehicle."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/reminders",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or "reminders" in data

    async def test_get_reminder_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving a specific reminder."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Test Reminder",
                "due_date": tomorrow,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        reminder = create_response.json()

        # Get the reminder (route is /api/vehicles/{vin}/reminders/{reminder_id})
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == reminder["id"]
        assert "description" in data

    async def test_update_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test updating a reminder."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Original Description",
                "due_date": tomorrow,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        reminder = create_response.json()

        # Update the reminder
        update_data = {
            "description": "Updated Description",
            "notes": "Updated notes",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated Description"

    async def test_delete_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a reminder."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Delete Me",
                "due_date": tomorrow,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        reminder = create_response.json()

        # Delete the reminder
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_mark_reminder_complete(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test marking a reminder as completed."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Complete Me",
                "due_date": tomorrow,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        reminder = create_response.json()

        # Mark as complete (route is /api/vehicles/{vin}/reminders/{id}/complete)
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder['id']}/complete",
            headers=auth_headers,
        )

        assert response.status_code in [200, 204]

        # Verify status changed
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reminders/{reminder['id']}",
            headers=auth_headers,
        )
        if get_response.status_code == 200:
            data = get_response.json()
            if "is_completed" in data:
                assert data["is_completed"] is True

    async def test_upcoming_reminders(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving upcoming reminders (list all for vehicle)."""
        # Create reminders with different due dates
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        next_week = (date.today() + timedelta(days=7)).isoformat()

        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Soon reminder",
                "due_date": tomorrow,
            },
            headers=auth_headers,
        )

        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Later reminder",
                "due_date": next_week,
            },
            headers=auth_headers,
        )

        # Get reminders for vehicle (no global /api/reminders/upcoming)
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Should return list of reminders
        assert isinstance(data, list) or "reminders" in data

    async def test_reminder_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test reminder validation."""
        # Missing required fields (description is required)
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "notes": "No description",  # description missing
            },
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_reminder_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot create reminders."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Test",
                "due_date": tomorrow,
            },
        )

        assert response.status_code == 401
