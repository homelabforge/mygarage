"""
Integration tests for reminder routes.

Tests reminder CRUD operations and upcoming reminders.
"""

import pytest
from httpx import AsyncClient
from datetime import date, timedelta


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
                "title": "Oil Change Due",
                "description": "5000 miles since last change",
                "due_date": tomorrow,
                "due_mileage": 20000,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Oil Change Due"
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
        assert isinstance(data, list) or ("reminders" in data)

    async def test_get_reminder_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving a specific reminder."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Test Reminder",
                "due_date": tomorrow,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )
        reminder = create_response.json()

        # Get the reminder
        response = await client.get(
            f"/api/reminders/{reminder['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == reminder["id"]
        assert data["title"] == "Test Reminder"

    async def test_update_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test updating a reminder."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Original Title",
                "due_date": tomorrow,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )
        reminder = create_response.json()

        # Update the reminder
        update_data = {
            "title": "Updated Title",
            "description": "Updated description",
        }

        response = await client.put(
            f"/api/reminders/{reminder['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    async def test_delete_reminder(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a reminder."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Create a reminder
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Delete Me",
                "due_date": tomorrow,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )
        reminder = create_response.json()

        # Delete the reminder
        response = await client.delete(
            f"/api/reminders/{reminder['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/reminders/{reminder['id']}",
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
                "title": "Complete Me",
                "due_date": tomorrow,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )
        reminder = create_response.json()

        # Mark as complete
        response = await client.post(
            f"/api/reminders/{reminder['id']}/complete",
            headers=auth_headers,
        )

        assert response.status_code in [200, 204]

        # Verify status changed
        get_response = await client.get(
            f"/api/reminders/{reminder['id']}",
            headers=auth_headers,
        )
        if get_response.status_code == 200:
            data = get_response.json()
            if "completed" in data:
                assert data["completed"] is True

    async def test_upcoming_reminders(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving upcoming reminders."""
        # Create reminders with different due dates
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        next_week = (date.today() + timedelta(days=7)).isoformat()

        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Soon",
                "due_date": tomorrow,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )

        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "title": "Later",
                "due_date": next_week,
                "reminder_type": "maintenance",
            },
            headers=auth_headers,
        )

        # Get upcoming reminders
        response = await client.get(
            "/api/reminders/upcoming",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Should return list of upcoming reminders
        assert isinstance(data, list) or ("reminders" in data)

    async def test_reminder_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test reminder validation."""
        # Missing required fields
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "description": "No title",
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
                "title": "Test",
                "due_date": tomorrow,
                "reminder_type": "maintenance",
            },
        )

        assert response.status_code == 401
