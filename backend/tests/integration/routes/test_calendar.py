"""
Integration tests for calendar routes.

Tests calendar event aggregation and iCal export.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HoursRecord, OdometerRecord, Reminder, Vehicle


async def _isolated_vehicle(db_session: AsyncSession) -> tuple[str, dict[str, str]]:
    """Create a throwaway non-admin owner + one vehicle and return
    ``(vin, auth_headers)`` whose ``/api/calendar`` scope is EXACTLY that
    vehicle. Mirrors ``test_dashboard.py``'s ``_isolated_fleet`` — the
    integration test DB is session-scoped and accumulates rows across
    files/tests, so a fresh, uniquely-named owner keeps hours-history-
    dependent assertions (rate computed from ONLY this vin's HoursRecord
    rows) from being polluted by other tests' data on the shared
    ``test_vehicle`` vin.
    """
    import uuid

    from app.models.user import User
    from app.services.auth import create_access_token

    suffix = uuid.uuid4().hex[:12]
    password_hash = (
        "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
        "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
    )
    user = User(
        username=f"cal_{suffix}",
        email=f"cal_{suffix}@example.com",
        hashed_password=password_hash,
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # "CALDR" + 12 hex chars = exactly 17 chars, no I/O/Q -> a valid unique VIN.
    vin = f"CALDR{suffix.upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user.id,
            nickname=f"Calendar {suffix}",
            vehicle_type="Car",
        )
    )
    await db_session.commit()

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return vin, {"Authorization": f"Bearer {token}"}


async def _reminder_events(client: AsyncClient, headers: dict[str, str], title: str) -> list[dict]:
    """GET /api/calendar for maintenance events over (today-30d, today+365d)
    and return the events whose title contains ``title``."""
    response = await client.get(
        "/api/calendar",
        params={
            "event_types": "maintenance",
            "start_date": (date.today() - timedelta(days=30)).isoformat(),
            "end_date": (date.today() + timedelta(days=365)).isoformat(),
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return [e for e in response.json()["events"] if title in e.get("title", "")]


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

    async def test_calendar_hours_reminder_with_history_gets_estimated_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Phase 6b: a pure `hours` reminder (due_hours, no due_date) with
        enough engine-hours history to compute a rate gets an ESTIMATED
        calendar event date, projected from the engine-hours rate the same
        way a mileage reminder projects from km/day."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                HoursRecord(
                    vin=vin, date=date.today() - timedelta(days=20), engine_hours=Decimal("100.0")
                ),
                HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("300.0")),
            ]
        )
        db_session.add(
            Reminder(
                vin=vin,
                title="Hydraulic Service Hours Test",
                reminder_type="hours",
                due_hours=Decimal("500.0"),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        test_events = [
            e for e in data["events"] if "Hydraulic Service Hours Test" in e.get("title", "")
        ]
        assert len(test_events) == 1
        event = test_events[0]

        # Rate = (300 - 100) / 20 days = 10.0 hr/day. Remaining = 500 - 300 =
        # 200 hr -> 20 days from today.
        assert event["is_estimated"] is True
        assert event["date"] == (date.today() + timedelta(days=20)).isoformat()
        assert event["due_hours"] == "500.0"
        assert event["hours_until_due"] == "200.0"

    async def test_calendar_hours_reminder_insufficient_history_no_crash(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """No hours history at all -> current hours unknown -> no estimate
        possible -> the reminder yields no calendar event (mirrors the
        mileage no-odometer-record case), and the endpoint does not crash."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add(
            Reminder(
                vin=vin,
                title="No History Hours Test",
                reminder_type="hours",
                due_hours=Decimal("500.0"),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        test_events = [e for e in data["events"] if "No History Hours Test" in e.get("title", "")]
        assert test_events == []

    async def test_calendar_hours_reminder_single_reading_no_rate_no_crash(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Exactly one hours reading -> current hours known but no rate can
        be computed (needs >= 2 points) -> no estimate -> no event, mirroring
        the mileage single-odometer-record case. No crash."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add(HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("100.0")))
        db_session.add(
            Reminder(
                vin=vin,
                title="Single Reading Hours Test",
                reminder_type="hours",
                due_hours=Decimal("500.0"),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        test_events = [
            e for e in data["events"] if "Single Reading Hours Test" in e.get("title", "")
        ]
        assert test_events == []

    async def test_calendar_smart_hours_reminder_surfaces_via_due_date(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A 'smart' reminder targeting hours (due_date + due_hours, no
        due_mileage_km) with no hours history has no usage projection, so it
        must surface via its due_date directly, never dropped. (With history
        it sits at the EARLIER of date and projection; see
        test_calendar_usage_reminder_sits_on_its_projection.)"""
        vin, headers = await _isolated_vehicle(db_session)
        due_date = date.today() + timedelta(days=10)
        db_session.add(
            Reminder(
                vin=vin,
                title="Smart Hours Test",
                reminder_type="smart",
                due_date=due_date,
                due_hours=Decimal("500.0"),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "event_types": "maintenance",
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        test_events = [e for e in data["events"] if "Smart Hours Test" in e.get("title", "")]
        assert len(test_events) == 1
        event = test_events[0]
        assert event["date"] == due_date.isoformat()
        assert event["is_estimated"] is False

    @pytest.mark.parametrize(
        ("reminder_type", "due_in_days"),
        [("mileage", None), ("smart", 300)],
        ids=["mileage-only", "smart-hard-date-later"],
    )
    async def test_calendar_usage_reminder_sits_on_its_projection(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        reminder_type: str,
        due_in_days: int | None,
    ):
        """Rate = (51000 - 50000) / 10 days = 100 km/day; 2,000 km remaining
        projects 20 days out. A smart reminder's hard date 300 days out must
        not win: the event sits at the EARLIER of its date and its projection
        (expected_due_date), the same date the reminders list and bell show."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                OdometerRecord(
                    vin=vin, date=date.today() - timedelta(days=10), odometer_km=Decimal("50000")
                ),
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("51000")),
                Reminder(
                    vin=vin,
                    title="Usage Projection Test",
                    reminder_type=reminder_type,
                    due_date=(date.today() + timedelta(days=due_in_days) if due_in_days else None),
                    due_mileage_km=Decimal("53000"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Usage Projection Test")
        assert len(events) == 1
        assert events[0]["is_estimated"] is True
        assert events[0]["date"] == (date.today() + timedelta(days=20)).isoformat()

    async def test_calendar_date_overdue_outside_window_pinned_to_today(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """#195: a long-overdue date reminder must surface TODAY, not on its
        past date. The frontend fetches ±3 months around the viewed month, so
        an event placed on the old due date falls out of the window entirely
        and the reminder silently vanishes from the calendar."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add(
            Reminder(
                vin=vin,
                title="Ancient Overdue Inspection",
                reminder_type="date",
                due_date=date.today() - timedelta(days=200),
                status="pending",
            )
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Ancient Overdue Inspection")
        assert len(events) == 1
        assert events[0]["date"] == date.today().isoformat()
        assert events[0]["urgency"] == "overdue"
        assert events[0]["status"] == "overdue"

    @pytest.mark.parametrize("shape", ["date-overdue", "mileage-reached", "mileage-no-reading"])
    async def test_calendar_snoozed_due_reminder_surfaces_on_its_return_day(
        self, client: AsyncClient, db_session: AsyncSession, shape: str
    ):
        """A snooze silences the nag, not the plan: a reminder already due
        (by date or by a reached usage target), or one with no determinable
        date at all, sits on the day it comes back (the list's "Snoozed
        until X" chip), exact, under the normal ladder. Left on a long-past
        date it falls out of the fetch window and vanishes (#195 again for
        snoozed rows); left on today it nags daily straight through the
        snooze."""
        vin, headers = await _isolated_vehicle(db_session)
        comeback = date.today() + timedelta(days=5)
        kwargs: dict = {"reminder_type": "date", "due_date": date.today() - timedelta(days=200)}
        if shape != "date-overdue":
            kwargs = {"reminder_type": "mileage", "due_mileage_km": Decimal("50000")}
        if shape == "mileage-reached":
            db_session.add_all(
                [
                    OdometerRecord(
                        vin=vin,
                        date=date.today() - timedelta(days=10),
                        odometer_km=Decimal("50200"),
                    ),
                    OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("51200")),
                ]
            )
        db_session.add(
            Reminder(
                vin=vin,
                title="Snoozed Due Service",
                snoozed_until=comeback,
                status="pending",
                **kwargs,
            )
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Snoozed Due Service")
        assert len(events) == 1
        assert events[0]["date"] == comeback.isoformat()
        # Snoozed reads as snoozed, with no warning border beside the chip (F-10).
        assert events[0]["urgency"] == "low"
        assert events[0]["status"] == "snoozed"
        # The return day is a fact, not a projection.
        assert events[0]["is_estimated"] is False

    async def test_calendar_undated_due_soon_reminder_is_pinned_to_today(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """RD-7, D5a: a mileage-only reminder with no rate has no date to sit
        on. At 92% of its span it is due soon by the 90% fallback, so it is
        pinned to today, estimated, as the list and the hero call it."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("19200")),
                Reminder(
                    vin=vin,
                    title="Undated Due Soon Plugs",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("20000"),
                    start_odometer_km=Decimal("10000"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Undated On Track Belt",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("50000"),
                    start_odometer_km=Decimal("10000"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Undated Due Soon Plugs")
        assert len(events) == 1
        event = events[0]
        assert event["date"] == date.today().isoformat()
        assert event["is_estimated"] is True
        assert event["status"] == "due_soon"
        assert event["urgency"] == "high"
        assert Decimal(event["km_until_due"]) == Decimal("800")
        # On track and undated: nothing to place.
        assert await _reminder_events(client, headers, "Undated On Track Belt") == []

    async def test_calendar_due_soon_reminder_twenty_days_out_is_high_urgency(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """RD-3: the warning border keys on urgency, so a "Due soon" chip 20
        days out sat on a plain card ("medium" past 7 days). Due soon is
        "high" across the whole 30-day window."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add(
            Reminder(
                vin=vin,
                title="Twenty Day Coolant",
                reminder_type="date",
                due_date=date.today() + timedelta(days=20),
                status="pending",
            )
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Twenty Day Coolant")
        assert len(events) == 1
        assert events[0]["status"] == "due_soon"
        assert events[0]["urgency"] == "high"
        assert events[0]["is_estimated"] is False

    async def test_calendar_reminder_description_drops_the_type_token(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """D6a: the description was "Reminder (smart)", a raw token the
        backend can't translate, shown in the notes drawer and the iCal
        export."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add(
            Reminder(
                vin=vin,
                title="Smart Token Service",
                reminder_type="smart",
                due_date=date.today() + timedelta(days=40),
                due_mileage_km=Decimal("90000"),
                status="pending",
            )
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Smart Token Service")
        assert len(events) == 1
        assert events[0]["description"] == "Reminder"

        response = await client.get(
            "/api/calendar/export", params={"event_types": "maintenance"}, headers=headers
        )
        assert response.status_code == 200
        assert "DESCRIPTION:Reminder\r\n" in response.text
        assert "Reminder (smart)" not in response.text

    async def test_calendar_low_tread_event_carries_the_tread(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """D7a: a low-tread event carries its tread and minimum in canonical
        mm; every other event leaves both null."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Tire tread low (FL)",
                    reminder_type="date",
                    source="low_tread",
                    due_date=date.today() + timedelta(days=10),
                    tread_depth_mm=Decimal("1.5"),
                    tread_threshold_mm=Decimal("3.0"),
                    status="pending",
                ),
                Reminder(
                    vin=vin,
                    title="Plain Wiper Blades",
                    reminder_type="date",
                    due_date=date.today() + timedelta(days=10),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        tread = (await _reminder_events(client, headers, "Tire tread low (FL)"))[0]
        assert Decimal(tread["tread_depth_mm"]) == Decimal("1.5")
        assert Decimal(tread["tread_threshold_mm"]) == Decimal("3.0")
        plain = (await _reminder_events(client, headers, "Plain Wiper Blades"))[0]
        assert plain["tread_depth_mm"] is None
        assert plain["tread_threshold_mm"] is None

    async def test_calendar_summary_counts_overdue_apart_from_upcoming(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """An overdue reminder pinned to today must not double into the
        Next 7/30 Days KPIs; overdue has its own box."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add(
            Reminder(
                vin=vin,
                title="Summary Overdue",
                reminder_type="date",
                due_date=date.today() - timedelta(days=60),
                status="pending",
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/calendar",
            params={
                "start_date": (date.today() - timedelta(days=30)).isoformat(),
                "end_date": (date.today() + timedelta(days=365)).isoformat(),
            },
            headers=headers,
        )
        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["overdue"] == 1
        assert summary["upcoming_7_days"] == 0
        assert summary["upcoming_30_days"] == 0

    async def test_calendar_mileage_overdue_with_future_due_date_is_overdue_today(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """#195 ('Brake inspection'): overdue by mileage but not yet by time.
        The old code used due_date unconditionally, so the event sat months in
        the future as on_track while the bell called it overdue."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("51200")),
                Reminder(
                    vin=vin,
                    title="Brake Inspection Mileage First",
                    reminder_type="smart",
                    due_date=date.today() + timedelta(days=180),
                    due_mileage_km=Decimal("50000"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Brake Inspection Mileage First")
        assert len(events) == 1
        event = events[0]
        assert event["date"] == date.today().isoformat()
        assert event["urgency"] == "overdue"
        assert event["status"] == "overdue"
        assert Decimal(event["km_until_due"]) == Decimal("-1200")

    async def test_calendar_mileage_only_overdue_is_marked_overdue_not_due_soon(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """#195 ('Tire rotation'): a mileage-only overdue reminder was pinned
        to today but labelled due_soon/high, because the urgency ladder only
        knew dates and today is not < today."""
        vin, headers = await _isolated_vehicle(db_session)
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("51200")),
                Reminder(
                    vin=vin,
                    title="Tire Rotation Mileage Only",
                    reminder_type="mileage",
                    due_mileage_km=Decimal("50000"),
                    status="pending",
                ),
            ]
        )
        await db_session.commit()

        events = await _reminder_events(client, headers, "Tire Rotation Mileage Only")
        assert len(events) == 1
        assert events[0]["date"] == date.today().isoformat()
        assert events[0]["urgency"] == "overdue"
        assert events[0]["status"] == "overdue"

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
