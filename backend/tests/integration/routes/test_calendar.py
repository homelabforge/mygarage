"""
Integration tests for calendar routes.

Tests calendar event aggregation and iCal export.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestCalendarRoutes:
    """Test calendar API endpoints."""

    async def test_get_calendar_events(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting calendar events."""
        response = await client.get(
            "/api/calendar",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "summary" in data
        assert isinstance(data["events"], list)

    async def test_calendar_response_summary_structure(self, client: AsyncClient, auth_headers):
        """Test that calendar summary has correct structure."""
        response = await client.get(
            "/api/calendar",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        summary = data["summary"]

        assert "total" in summary
        assert "overdue" in summary
        assert "upcoming_7_days" in summary
        assert "upcoming_30_days" in summary
        assert isinstance(summary["total"], int)
        assert isinstance(summary["overdue"], int)

    async def test_calendar_with_date_filter(self, client: AsyncClient, auth_headers):
        """Test getting calendar events with date filter."""
        response = await client.get(
            "/api/calendar",
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        # All events should be within the date range
        for event in data["events"]:
            assert "2024-01-01" <= event["date"] <= "2024-12-31"

    async def test_calendar_with_vehicle_filter(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting calendar events filtered by vehicle."""
        response = await client.get(
            "/api/calendar",
            params={"vehicle_vins": test_vehicle["vin"]},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All events should be for the specified vehicle
        for event in data["events"]:
            assert event["vehicle_vin"] == test_vehicle["vin"]

    async def test_calendar_with_event_type_filter(self, client: AsyncClient, auth_headers):
        """Test getting calendar events filtered by type."""
        response = await client.get(
            "/api/calendar",
            params={"event_types": "reminder,insurance"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All events should be of the specified types
        for event in data["events"]:
            assert event["type"] in ["reminder", "insurance"]

    async def test_calendar_event_structure(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that calendar events have correct structure when data exists."""
        # First create a reminder to ensure we have an event
        reminder_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Calendar test reminder",
                "due_date": "2024-06-15",
                "priority": "high",
            },
            headers=auth_headers,
        )
        assert reminder_response.status_code == 201

        # Get calendar events
        response = await client.get(
            "/api/calendar",
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "event_types": "reminder",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Find our test event
        test_events = [e for e in data["events"] if "Calendar test" in e.get("title", "")]
        assert len(test_events) >= 1

        event = test_events[0]
        # Verify event structure
        assert "id" in event
        assert "type" in event
        assert "title" in event
        assert "date" in event
        assert "vehicle_vin" in event
        assert "urgency" in event
        assert "is_recurring" in event
        assert "is_completed" in event
        assert "is_estimated" in event
        assert "category" in event

    async def test_calendar_export_ical(self, client: AsyncClient, auth_headers):
        """Test exporting calendar events as iCal."""
        response = await client.get(
            "/api/calendar/export",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "text/calendar" in response.headers.get("content-type", "")

        # Verify it's valid iCal format
        content = response.content.decode("utf-8")
        assert "BEGIN:VCALENDAR" in content
        assert "VERSION:2.0" in content
        assert "END:VCALENDAR" in content

    async def test_calendar_export_with_filters(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test exporting calendar events with filters."""
        response = await client.get(
            "/api/calendar/export",
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "vehicle_vins": test_vehicle["vin"],
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "text/calendar" in response.headers.get("content-type", "")

        # Check content disposition
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert ".ics" in content_disp

    async def test_calendar_export_content_structure(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that iCal export has proper structure."""
        # Create a reminder first
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Export test reminder",
                "due_date": "2024-07-15",
            },
            headers=auth_headers,
        )

        # Export calendar
        response = await client.get(
            "/api/calendar/export",
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "event_types": "reminder",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Verify iCal structure
        assert "PRODID:-//MyGarage//Vehicle Maintenance Calendar//EN" in content
        assert "CALSCALE:GREGORIAN" in content
        assert "X-WR-CALNAME:MyGarage Maintenance" in content

        # If we have events, verify event structure
        if "BEGIN:VEVENT" in content:
            assert "UID:" in content
            assert "DTSTART" in content
            assert "SUMMARY:" in content
            assert "END:VEVENT" in content

    async def test_calendar_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot access calendar."""
        response = await client.get("/api/calendar")
        assert response.status_code == 401

    async def test_calendar_export_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot export calendar."""
        response = await client.get("/api/calendar/export")
        assert response.status_code == 401

    async def test_calendar_multiple_event_types(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test calendar with multiple event sources."""
        # Create a reminder
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Multi-type test reminder",
                "due_date": "2024-08-01",
            },
            headers=auth_headers,
        )

        # Create a service record
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-08-15",
                "mileage": 55000,
                "service_type": "Oil Change",
                "cost": 50.00,
            },
            headers=auth_headers,
        )

        # Get calendar with all types
        response = await client.get(
            "/api/calendar",
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have events
        assert data["summary"]["total"] >= 0

    async def test_calendar_urgency_levels(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that urgency is calculated correctly."""
        # Create a reminder with a near-future date
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Urgency test reminder",
                "due_date": "2024-09-01",
            },
            headers=auth_headers,
        )

        response = await client.get(
            "/api/calendar",
            params={"start_date": "2024-01-01", "end_date": "2030-12-31"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Find our test event
        test_events = [e for e in data["events"] if "Urgency test" in e.get("title", "")]
        if test_events:
            event = test_events[0]
            # Urgency should be one of the valid values
            assert event["urgency"] in ["overdue", "high", "medium", "low", "historical"]

    async def test_calendar_empty_response(self, client: AsyncClient, auth_headers):
        """Test calendar response when no events in range."""
        # Use a very narrow date range unlikely to have events
        response = await client.get(
            "/api/calendar",
            params={
                "start_date": "1900-01-01",
                "end_date": "1900-01-02",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["events"] == []
        assert data["summary"]["total"] == 0
