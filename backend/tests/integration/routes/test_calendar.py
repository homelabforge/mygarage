"""
Integration tests for calendar routes.

Tests calendar event aggregation and iCal export.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MaintenanceScheduleItem


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
            params={"event_types": "maintenance,insurance"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All events should be of the specified types
        for event in data["events"]:
            assert event["type"] in ["maintenance", "insurance"]

    async def test_calendar_includes_maintenance_events(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that maintenance schedule items appear as calendar events."""
        # Create a maintenance schedule item with a due date in the future
        due_date = date.today() + timedelta(days=15)
        item = MaintenanceScheduleItem(
            vin=test_vehicle["vin"],
            name="Oil Change Test",
            component_category="Engine",
            item_type="service",
            interval_months=6,
            source="custom",
            last_performed_date=due_date - timedelta(days=180),
        )
        db_session.add(item)
        await db_session.commit()

        # Get calendar events
        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Find our test maintenance event
        test_events = [e for e in data["events"] if "Oil Change Test" in e.get("title", "")]
        assert len(test_events) >= 1

        event = test_events[0]
        assert event["type"] == "maintenance"
        assert event["category"] == "maintenance"
        assert event["vehicle_vin"] == test_vehicle["vin"]
        assert "id" in event
        assert event["id"].startswith("maintenance-")

    async def test_calendar_maintenance_overdue_urgency(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that overdue maintenance items show correct urgency."""
        # Create an overdue maintenance item (last performed long ago)
        item = MaintenanceScheduleItem(
            vin=test_vehicle["vin"],
            name="Overdue Brake Check",
            component_category="Brakes",
            item_type="inspection",
            interval_months=3,
            source="custom",
            last_performed_date=date.today() - timedelta(days=365),
        )
        db_session.add(item)
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=365)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        test_events = [e for e in data["events"] if "Overdue Brake Check" in e.get("title", "")]
        assert len(test_events) >= 1
        assert test_events[0]["urgency"] == "overdue"

    async def test_calendar_event_structure(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that calendar events have correct structure."""
        # Create a maintenance item to ensure we have an event
        item = MaintenanceScheduleItem(
            vin=test_vehicle["vin"],
            name="Structure Test Item",
            component_category="General",
            item_type="service",
            interval_months=6,
            source="custom",
            last_performed_date=date.today() - timedelta(days=150),
        )
        db_session.add(item)
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        test_events = [e for e in data["events"] if "Structure Test" in e.get("title", "")]
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
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that iCal export has proper structure."""
        # Create a maintenance item
        item = MaintenanceScheduleItem(
            vin=test_vehicle["vin"],
            name="Export Test Item",
            component_category="General",
            item_type="service",
            interval_months=6,
            source="custom",
            last_performed_date=date.today() - timedelta(days=150),
        )
        db_session.add(item)
        await db_session.commit()

        # Export calendar
        response = await client.get(
            "/api/calendar/export",
            params={
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
                "event_types": "maintenance",
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
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test calendar with multiple event sources."""
        # Create a maintenance item
        item = MaintenanceScheduleItem(
            vin=test_vehicle["vin"],
            name="Multi-type test item",
            component_category="General",
            item_type="service",
            interval_months=6,
            source="custom",
            last_performed_date=date.today() - timedelta(days=150),
        )
        db_session.add(item)
        await db_session.commit()

        # Get calendar with all types
        response = await client.get(
            "/api/calendar",
            params={
                "start_date": (date.today() - timedelta(days=365)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have events
        assert data["summary"]["total"] >= 0

    async def test_calendar_maintenance_filter(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that maintenance filter correctly includes/excludes events."""
        # Create a maintenance item
        item = MaintenanceScheduleItem(
            vin=test_vehicle["vin"],
            name="Filter Test Item",
            component_category="Engine",
            item_type="service",
            interval_months=3,
            source="custom",
            last_performed_date=date.today() - timedelta(days=60),
        )
        db_session.add(item)
        await db_session.commit()

        # Request only insurance events (maintenance should be excluded)
        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "insurance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # No maintenance events should appear
        maintenance_events = [e for e in data["events"] if e["type"] == "maintenance"]
        assert len(maintenance_events) == 0

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
