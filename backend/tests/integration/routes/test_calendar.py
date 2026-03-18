"""
Integration tests for calendar routes.

Tests calendar event aggregation and iCal export.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder


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
        for event in data["events"]:
            assert event["type"] in ["maintenance", "insurance"]

    async def test_calendar_includes_reminder_events(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that reminders appear as calendar events."""
        due_date = date.today() + timedelta(days=15)
        item = Reminder(
            vin=test_vehicle["vin"],
            title="Oil Change Test",
            reminder_type="date",
            due_date=due_date,
            status="pending",
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

        test_events = [e for e in data["events"] if "Oil Change Test" in e.get("title", "")]
        assert len(test_events) >= 1

        event = test_events[0]
        assert event["type"] == "maintenance"
        assert event["category"] == "maintenance"
        assert event["vehicle_vin"] == test_vehicle["vin"]
        assert "id" in event
        assert event["id"].startswith("reminder-")

    async def test_calendar_reminder_overdue_urgency(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that overdue reminders show correct urgency."""
        item = Reminder(
            vin=test_vehicle["vin"],
            title="Overdue Brake Check",
            reminder_type="date",
            due_date=date.today() - timedelta(days=30),
            status="pending",
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
        item = Reminder(
            vin=test_vehicle["vin"],
            title="Structure Test Item",
            reminder_type="date",
            due_date=date.today() + timedelta(days=30),
            status="pending",
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

        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert ".ics" in content_disp

    async def test_calendar_export_content_structure(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
    ):
        """Test that iCal export has proper structure."""
        item = Reminder(
            vin=test_vehicle["vin"],
            title="Export Test Item",
            reminder_type="date",
            due_date=date.today() + timedelta(days=30),
            status="pending",
        )
        db_session.add(item)
        await db_session.commit()

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

        assert "PRODID:-//MyGarage//Vehicle Maintenance Calendar//EN" in content
        assert "CALSCALE:GREGORIAN" in content
        assert "X-WR-CALNAME:MyGarage Maintenance" in content

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

    async def test_calendar_empty_response(self, client: AsyncClient, auth_headers):
        """Test calendar response when no events in range."""
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

    async def test_calendar_excludes_non_owned_vehicles(
        self, client: AsyncClient, non_admin_headers
    ):
        """Test that calendar only shows events for owned/shared vehicles."""
        response = await client.get(
            "/api/calendar",
            headers=non_admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total"] == 0
