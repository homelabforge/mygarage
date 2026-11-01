"""Reminder snooze (plan 2026-09-18, feature A): hide until date.

While ``household_today() < snoozed_until`` a pending reminder is excluded
from overdue AND upcoming counts, the inbox, fleet next-due/30-day counts
and scheduled notifications. The due fields stay real, the calendar still
shows the reminder, and completion clears the snooze.

The suppression tests were observed red before the sweep landed (the
endpoint existed, the aggregation surfaces still counted the reminder).
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.reminder import Reminder
from app.utils.household_time import household_today

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _reminder(
    client: AsyncClient, headers: dict, vin: str, *, title: str, due_in_days: int
) -> dict:
    r = await client.post(
        f"/api/vehicles/{vin}/reminders",
        headers=headers,
        json={
            "title": title,
            "reminder_type": "date",
            "due_date": (household_today() + timedelta(days=due_in_days)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _snooze(client: AsyncClient, headers: dict, vin: str, rid: int, until) -> None:
    r = await client.post(
        f"/api/vehicles/{vin}/reminders/{rid}/snooze",
        headers=headers,
        json={"until": until.isoformat()},
    )
    assert r.status_code == 200, r.text


async def _dash(client: AsyncClient, headers: dict, vin: str) -> dict:
    r = await client.get("/api/dashboard", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    mine = [v for v in body["vehicles"] if v["vin"] == vin]
    assert mine, body["vehicles"]
    return {"vehicle": mine[0], "fleet": body["fleet_health"]}


async def _detail(client: AsyncClient, headers: dict, vin: str) -> dict:
    r = await client.get(f"/api/vehicles/{vin}/detail-stats", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


class TestSnoozeEndpoint:
    async def test_snooze_and_unsnooze_round_trip(self, client, auth_headers, own_vehicle):
        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze RT", due_in_days=-5)
        until = household_today() + timedelta(days=7)
        await _snooze(client, auth_headers, vin, reminder["id"], until)

        r = await client.get(f"/api/vehicles/{vin}/reminders", headers=auth_headers)
        mine = [x for x in r.json() if x["id"] == reminder["id"]]
        assert mine and mine[0]["snoozed_until"] == until.isoformat()

        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}/unsnooze", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["snoozed_until"] is None

    async def test_snooze_rejects_past_today_and_absurd_dates(
        self, client, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze 422", due_in_days=-5)
        for until in (household_today(), household_today() - timedelta(days=1)):
            r = await client.post(
                f"/api/vehicles/{vin}/reminders/{reminder['id']}/snooze",
                headers=auth_headers,
                json={"until": until.isoformat()},
            )
            assert r.status_code == 422, r.text
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}/snooze",
            headers=auth_headers,
            json={"until": (household_today() + timedelta(days=4000)).isoformat()},
        )
        assert r.status_code == 422, r.text

    async def test_only_a_pending_reminder_can_be_snoozed(self, client, auth_headers, own_vehicle):
        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze 409", due_in_days=-5)
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}/done", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}/snooze",
            headers=auth_headers,
            json={"until": (household_today() + timedelta(days=7)).isoformat()},
        )
        assert r.status_code == 409, r.text

    async def test_completion_clears_the_snooze(
        self, client, auth_headers, own_vehicle, db_session
    ):
        vin = own_vehicle.vin
        reminder = await _reminder(
            client, auth_headers, vin, title="Snooze cleared", due_in_days=-5
        )
        await _snooze(
            client, auth_headers, vin, reminder["id"], household_today() + timedelta(days=30)
        )
        r = await client.post(
            f"/api/vehicles/{vin}/reminders/{reminder['id']}/done", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        row = await db_session.scalar(select(Reminder).where(Reminder.id == reminder["id"]))
        assert row is not None and row.status == "done"
        assert row.snoozed_until is None


class TestSnoozeSuppression:
    async def test_dashboard_and_detail_stats_drop_a_snoozed_reminder_entirely(
        self, client, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze dash", due_in_days=-5)
        before_dash = await _dash(client, auth_headers, vin)
        before_detail = await _detail(client, auth_headers, vin)

        await _snooze(
            client, auth_headers, vin, reminder["id"], household_today() + timedelta(days=7)
        )
        after_dash = await _dash(client, auth_headers, vin)
        after_detail = await _detail(client, auth_headers, vin)

        # Excluded, not reclassified: overdue drops by one and upcoming
        # does NOT grow.
        assert (
            after_dash["vehicle"]["overdue_maintenance_count"]
            == before_dash["vehicle"]["overdue_maintenance_count"] - 1
        )
        assert (
            after_dash["vehicle"]["upcoming_maintenance_count"]
            == before_dash["vehicle"]["upcoming_maintenance_count"]
        )
        assert after_detail["overdue_count"] == before_detail["overdue_count"] - 1
        assert after_detail["upcoming_count"] == before_detail["upcoming_count"]

    async def test_widget_aggregation_drops_a_snoozed_reminder(
        self, client, auth_headers, own_vehicle, db_session
    ):
        from app.services.widget_aggregation import WidgetAggregationService

        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze widget", due_in_days=-5)
        before = await WidgetAggregationService(db_session)._overdue_upcoming([vin], None, None)
        await _snooze(
            client, auth_headers, vin, reminder["id"], household_today() + timedelta(days=7)
        )
        db_session.expire_all()
        after = await WidgetAggregationService(db_session)._overdue_upcoming([vin], None, None)
        assert after[0] == before[0] - 1
        assert after[1] == before[1]

    async def test_the_inbox_drops_snoozed_overdue_and_upcoming_reminders(
        self, client, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        overdue = await _reminder(
            client, auth_headers, vin, title="Snooze inbox overdue", due_in_days=-5
        )
        upcoming = await _reminder(
            client, auth_headers, vin, title="Snooze inbox upcoming", due_in_days=7
        )

        r = await client.get("/api/notifications/inbox", headers=auth_headers)
        assert r.status_code == 200, r.text
        titles = [i["title"] for i in r.json()["items"]]
        assert "Snooze inbox overdue" in titles
        assert "Snooze inbox upcoming" in titles

        until = household_today() + timedelta(days=30)
        await _snooze(client, auth_headers, vin, overdue["id"], until)
        await _snooze(client, auth_headers, vin, upcoming["id"], until)

        r = await client.get("/api/notifications/inbox", headers=auth_headers)
        titles = [i["title"] for i in r.json()["items"]]
        assert "Snooze inbox overdue" not in titles
        assert "Snooze inbox upcoming" not in titles

    async def test_fleet_30d_count_and_next_due_skip_a_snoozed_reminder(
        self, client, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze fleet", due_in_days=10)
        before = (await _dash(client, auth_headers, vin))["fleet"]
        await _snooze(
            client, auth_headers, vin, reminder["id"], household_today() + timedelta(days=30)
        )
        after = (await _dash(client, auth_headers, vin))["fleet"]

        assert after["upcoming_30d_count"] == before["upcoming_30d_count"] - 1
        next_due = after["next_due"]
        assert next_due is None or next_due.get("reminder_id") != reminder["id"]

    async def test_family_summary_skips_a_snoozed_reminder(
        self, client, auth_headers, own_vehicle, db_session
    ):
        from app.models.vehicle import Vehicle
        from app.services.family_dashboard_service import FamilyDashboardService

        vin = own_vehicle.vin
        reminder = await _reminder(client, auth_headers, vin, title="Snooze family", due_in_days=-5)
        vehicle = await db_session.scalar(select(Vehicle).where(Vehicle.vin == vin))
        service = FamilyDashboardService(db_session)
        before = await service._build_vehicle_summary(vehicle)
        await _snooze(
            client, auth_headers, vin, reminder["id"], household_today() + timedelta(days=7)
        )
        db_session.expire_all()
        # Re-fetch: the expired instance would sync-refresh on attribute
        # access inside the service and MissingGreenlet.
        vehicle = await db_session.scalar(select(Vehicle).where(Vehicle.vin == vin))
        after = await service._build_vehicle_summary(vehicle)
        assert after.overdue_maintenance == before.overdue_maintenance - 1

    async def test_scheduled_notifications_skip_snoozed_and_resume_after_expiry(
        self, client, auth_headers, own_vehicle, db_session, monkeypatch
    ):
        from app.services.reminder_service import check_due_reminders

        sent: list[str] = []

        class _StubDispatcher:
            def __init__(self, db):
                pass

            async def dispatch(self, event_type, title, message):
                sent.append(title)
                return {"ntfy": True}

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            _StubDispatcher,
        )

        vin = own_vehicle.vin
        reminder = await _reminder(
            client, auth_headers, vin, title="Snooze scheduler", due_in_days=-5
        )
        until = household_today() + timedelta(days=7)
        await _snooze(client, auth_headers, vin, reminder["id"], until)

        await check_due_reminders(db_session)
        assert not any("Snooze scheduler" in t for t in sent), sent

        # The day the snooze expires (today == snoozed_until), it counts again.
        expired = household_today() + timedelta(days=7)
        monkeypatch.setattr("app.services.reminder_service.household_today", lambda: expired)
        await check_due_reminders(db_session)
        assert any("Snooze scheduler" in t for t in sent), sent

    async def test_the_calendar_still_shows_a_snoozed_reminder(
        self, client, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        reminder = await _reminder(
            client, auth_headers, vin, title="Snooze calendar", due_in_days=3
        )
        await _snooze(
            client, auth_headers, vin, reminder["id"], household_today() + timedelta(days=30)
        )
        start = household_today() - timedelta(days=1)
        end = household_today() + timedelta(days=10)
        r = await client.get(
            "/api/calendar",
            headers=auth_headers,
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
        assert r.status_code == 200, r.text
        titles = [e["title"] for e in r.json()["events"]]
        assert any("Snooze calendar" in t for t in titles), titles
        event = next(e for e in r.json()["events"] if "Snooze calendar" in e["title"])
        # Still on its due date, and labelled snoozed rather than due soon.
        assert event["status"] == "snoozed"
        assert event["urgency"] == "low"
