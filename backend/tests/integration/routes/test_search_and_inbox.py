"""Global search and the notification inbox.

Both were added in PR #149. Two bugs are pinned here:

- search filtered the needle in Python AFTER a SQL LIMIT, so a matching reminder
  outside the newest N rows reported "no results";
- the inbox gave the upcoming and overdue forms of a reminder the same id, and
  the bell keys its persisted dismissals on that id, so dismissing the early
  warning permanently suppressed the critical escalation.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.reminder_service import (
    count_pending_reminders,
    get_current_hours,
    get_current_mileage,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Every VIN this module creates, so the cleanup below can find them.
_CREATED_VINS: set[str] = set()


@pytest.fixture(autouse=True)
async def _delete_our_vehicles(db_session):
    """Delete this module's vehicles after each test; their rows cascade.

    The suite shares one database, and an overdue "Hydraulic service" left
    here showed up in another module's global reminder run.
    """
    yield
    if _CREATED_VINS:
        await db_session.rollback()
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_(_CREATED_VINS)))
        await db_session.commit()
        _CREATED_VINS.clear()


async def _vehicle(db_session, test_user, vin: str, distance_unit: str | None = None) -> None:
    _CREATED_VINS.add(vin)
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Search",
            distance_unit=distance_unit,
        )
    )
    await db_session.commit()


class TestGlobalSearch:
    async def test_finds_a_match_older_than_the_result_limit(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """The match is created FIRST, so it sorts last by created_at."""
        vin = "SEARCHLIMIT000001"
        await _vehicle(db_session, test_user, vin)

        db_session.add(
            Reminder(vin=vin, title="Timing belt", reminder_type="date", status="pending")
        )
        await db_session.commit()
        # 25 newer reminders push it past the default limit of 20.
        for i in range(25):
            db_session.add(
                Reminder(vin=vin, title=f"Filler {i}", reminder_type="date", status="pending")
            )
        await db_session.commit()

        response = await client.get("/api/search?q=timing belt", headers=auth_headers)

        assert response.status_code == 200
        titles = [hit["title"] for hit in response.json()["results"]]
        assert "Timing belt" in titles

    @pytest.mark.parametrize(
        "needle,should_match,should_not_match",
        [
            ("50%", "Coolant 50% mix", "Coolant 5050 mix"),
            ("a_b", "Filter a_b spec", "Filter axb spec"),
        ],
    )
    async def test_like_wildcards_in_the_query_are_literal(
        self,
        client: AsyncClient,
        auth_headers,
        test_user,
        db_session,
        needle,
        should_match,
        should_not_match,
    ):
        """A % or _ typed by the user is text, not a wildcard."""
        vin = f"SEARCHWILD{abs(hash(needle)) % 10**7:07d}"
        await _vehicle(db_session, test_user, vin)
        db_session.add_all(
            [
                Reminder(vin=vin, title=should_match, reminder_type="date", status="pending"),
                Reminder(vin=vin, title=should_not_match, reminder_type="date", status="pending"),
            ]
        )
        await db_session.commit()

        response = await client.get(f"/api/search?q={needle}", headers=auth_headers)

        assert response.status_code == 200
        titles = [hit["title"] for hit in response.json()["results"]]
        assert should_match in titles
        assert should_not_match not in titles


def _own_items(response, vin: str) -> dict:
    """The inbox items for ``vin``, by title. The inbox spans every vehicle the
    user has, and other tests' reminders persist on PostgreSQL (one titled
    "Tire rotation" among them), so a lookup by title alone picks whichever
    row the database returns last."""
    return {item["title"]: item for item in response.json()["items"] if item["vin"] == vin}


class TestNotificationInbox:
    async def test_upcoming_and_overdue_have_distinct_ids(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """The bell dismisses by id, so the two forms cannot share one.

        Sharing it meant dismissing "due in 10 days" also suppressed the same
        reminder's overdue alert two weeks later, permanently.
        """
        vin = "INBOXIDS000000001"
        await _vehicle(db_session, test_user, vin)
        today = date.today()
        db_session.add_all(
            [
                Reminder(
                    vin=vin,
                    title="Brake fluid",
                    reminder_type="date",
                    status="pending",
                    due_date=today + timedelta(days=10),
                ),
                Reminder(
                    vin=vin,
                    title="Oil change",
                    reminder_type="date",
                    status="pending",
                    due_date=today - timedelta(days=3),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        assert items["Brake fluid"]["kind"] == "reminder_upcoming"
        assert items["Oil change"]["kind"] == "reminder_overdue"
        # The id must carry the kind, not just the reminder's row id.
        assert items["Brake fluid"]["id"].startswith("reminder-reminder_upcoming-")
        assert items["Oil change"]["id"].startswith("reminder-reminder_overdue-")
        assert items["Brake fluid"]["id"] != items["Oil change"]["id"]

    async def test_a_mileage_reminder_still_uses_the_canonical_latest_reading(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Batching must not become MAX(odometer_km).

        The canonical current reading is the LAST row by (date, id), which is not
        the largest value: a correction logged later can be lower. A grouped MAX
        would fire this reminder; the canonical reading must not.
        """

        vin = "INBOXODO000000001"
        await _vehicle(db_session, test_user, vin)
        today = date.today()
        db_session.add_all(
            [
                # Mistyped high reading, then the correction the next day.
                OdometerRecord(
                    vin=vin, date=today - timedelta(days=2), odometer_km=Decimal("9999")
                ),
                OdometerRecord(
                    vin=vin, date=today - timedelta(days=1), odometer_km=Decimal("1000")
                ),
                Reminder(
                    vin=vin,
                    title="Tyre rotation",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("5000"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        # Not overdue: the canonical reading is 1000, not the mistyped 9999. It
        # may still be listed as upcoming, because the same correction makes the
        # 90-day rate enormous and the projection lands today; that is the
        # rate's business (calculate_driving_rate), not this test's.
        kinds = {item["title"]: item["kind"] for item in response.json()["items"]}
        assert kinds.get("Tyre rotation") != "reminder_overdue"

    async def test_a_mileage_reminder_projected_due_soon_is_upcoming(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """The bell uses the same expected date as the card badge and the
        reminders list: a usage projection at the vehicle's recent rate, not
        only a calendar date, so a mileage-only reminder warns before it is
        overdue."""

        vin = "INBOXPRJ000000001"
        await _vehicle(db_session, test_user, vin)
        today = date.today()
        db_session.add_all(
            [
                # 100 km/day over the last 60 days.
                OdometerRecord(
                    vin=vin, date=today - timedelta(days=60), odometer_km=Decimal("50000")
                ),
                OdometerRecord(vin=vin, date=today, odometer_km=Decimal("56000")),
                Reminder(
                    vin=vin,
                    title="Oil in 1,000 km",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("57000"),
                ),  # ~10 days out: upcoming
                Reminder(
                    vin=vin,
                    title="Belt in 14,000 km",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("70000"),
                ),  # ~140 days out: not in the inbox
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        assert items["Oil in 1,000 km"]["kind"] == "reminder_upcoming"
        assert "Belt in 14,000 km" not in items

    async def test_overdue_by_mileage_body_names_the_mileage_not_just_the_date(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """#195: a reminder overdue by mileage with a FUTURE hard date showed
        only 'due <future date>' under an OVERDUE label. The body must state
        the dimension that actually fired: the mileage target and the current
        reading, in the vehicle's own distance unit."""

        vin = "INBOXBODY00000001"
        await _vehicle(db_session, test_user, vin, distance_unit="km")
        today = date.today()
        future = today + timedelta(days=90)
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=today, odometer_km=Decimal("51200")),
                Reminder(
                    vin=vin,
                    title="Brake inspection",
                    reminder_type="smart",
                    status="pending",
                    due_date=future,
                    due_mileage_km=Decimal("50000"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        item = items["Brake inspection"]
        assert item["kind"] == "reminder_overdue"
        assert f"due {future.isoformat()}" in item["body"]
        assert "due at 50,000 km (now 51,200 km)" in item["body"]

    async def test_mileage_only_overdue_body_shows_the_target(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """#195: a mileage-only overdue reminder had NO due information in its
        body at all (the old code only ever printed due_date)."""

        vin = "INBOXBODY00000002"
        await _vehicle(db_session, test_user, vin, distance_unit="km")
        today = date.today()
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=today, odometer_km=Decimal("6100")),
                Reminder(
                    vin=vin,
                    title="Tire rotation",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("5000"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        item = items["Tire rotation"]
        assert item["kind"] == "reminder_overdue"
        assert "due at 5,000 km (now 6,100 km)" in item["body"]

    async def test_overdue_by_hours_body_uses_the_one_hours_formatter(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """The hours bit renders through hours_formatting.format_hours, the
        same string the push notification and the vehicle PDF print, so one
        stored value cannot drift into two spellings across surfaces."""
        vin = "INBOXBODY00000003"
        await _vehicle(db_session, test_user, vin)
        db_session.add_all(
            [
                HoursRecord(vin=vin, date=date.today(), engine_hours=Decimal("520")),
                Reminder(
                    vin=vin,
                    title="Hydraulic service",
                    reminder_type="hours",
                    status="pending",
                    due_hours=Decimal("512"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        item = items["Hydraulic service"]
        assert item["kind"] == "reminder_overdue"
        assert "due at 512.0 hr (now 520.0 hr)" in item["body"]

    async def test_a_reminder_expected_in_twenty_days_is_upcoming(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """RD-3: the bell lists what the reminders list calls due soon, which
        is expected within 30 days. It used its own 14-day window."""
        vin = "INBOXSOON00000001"
        await _vehicle(db_session, test_user, vin)
        db_session.add(
            Reminder(
                vin=vin,
                title="Coolant flush",
                reminder_type="date",
                status="pending",
                due_date=date.today() + timedelta(days=20),
            )
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        assert items["Coolant flush"]["kind"] == "reminder_upcoming"

    async def test_a_mileage_reminder_most_of_the_way_with_no_rate_is_upcoming(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """RD-3: one reading gives no rate, so nothing projects; 92% of the
        span is due soon by the 90% fallback, as the list and the hero say."""
        vin = "INBOXFALL00000001"
        await _vehicle(db_session, test_user, vin, distance_unit="km")
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=date.today(), odometer_km=Decimal("19200")),
                Reminder(
                    vin=vin,
                    title="Spark plugs",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("20000"),
                    start_odometer_km=Decimal("10000"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        item = _own_items(response, vin)["Spark plugs"]
        assert item["kind"] == "reminder_upcoming"
        assert item["body"] == f"{vin} · due at 20,000 km"

    async def test_a_low_tread_body_carries_the_tread(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """D7a: a low-tread item names the tread and its minimum, in the
        caller's tread unit, like the push message does. The unit is pinned
        here: the shared test user's preferences carry over between tests."""
        user = (
            await db_session.execute(select(User).where(User.id == test_user["id"]))
        ).scalar_one()
        saved = (user.unit_tread, user.show_both_units)
        user.unit_tread = "in32"
        user.show_both_units = False
        await db_session.commit()
        try:
            vin = "INBOXTREAD0000001"
            await _vehicle(db_session, test_user, vin)
            db_session.add(
                Reminder(
                    vin=vin,
                    title="Tire tread low (FL)",
                    reminder_type="date",
                    status="pending",
                    source="low_tread",
                    due_date=date.today(),
                    tread_depth_mm=Decimal("1.5"),
                    tread_threshold_mm=Decimal("3.0"),
                )
            )
            await db_session.commit()

            response = await client.get("/api/notifications/inbox", headers=auth_headers)

            assert response.status_code == 200
            item = _own_items(response, vin)["Tire tread low (FL)"]
            assert item["kind"] == "reminder_overdue"
            assert item["body"] == (
                f"{vin} · due {date.today().isoformat()} · tread 2/32 in, minimum 4/32 in"
            )
        finally:
            await db_session.rollback()
            user = (
                await db_session.execute(select(User).where(User.id == test_user["id"]))
            ).scalar_one()
            user.unit_tread, user.show_both_units = saved
            await db_session.commit()

    async def test_one_vehicles_bell_items_equal_its_hero_counts(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """F-12: the bell lists exactly what the hero counts as overdue plus
        due soon, for the same readings (odometer and hours). Snoozed and
        on-track rows are in neither."""
        vin = "INBOXCOUNT0000001"
        await _vehicle(db_session, test_user, vin)
        today = date.today()
        db_session.add_all(
            [
                OdometerRecord(vin=vin, date=today, odometer_km=Decimal("19200")),
                HoursRecord(vin=vin, date=today, engine_hours=Decimal("960")),
                Reminder(
                    vin=vin,
                    title="Count overdue",
                    reminder_type="date",
                    status="pending",
                    due_date=today - timedelta(days=3),
                ),
                Reminder(
                    vin=vin,
                    title="Count soon by date",
                    reminder_type="date",
                    status="pending",
                    due_date=today + timedelta(days=20),
                ),
                Reminder(
                    vin=vin,
                    title="Count on track by date",
                    reminder_type="date",
                    status="pending",
                    due_date=today + timedelta(days=90),
                ),
                Reminder(
                    vin=vin,
                    title="Count snoozed",
                    reminder_type="date",
                    status="pending",
                    due_date=today - timedelta(days=1),
                    snoozed_until=today + timedelta(days=5),
                ),
                Reminder(
                    vin=vin,
                    title="Count soon by share",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("20000"),
                    start_odometer_km=Decimal("10000"),
                ),
                Reminder(
                    vin=vin,
                    title="Count soon by hours share",
                    reminder_type="hours",
                    status="pending",
                    due_hours=Decimal("1000"),
                    start_hours=Decimal("500"),
                ),
                Reminder(
                    vin=vin,
                    title="Count on track by share",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal("50000"),
                    start_odometer_km=Decimal("10000"),
                ),
            ]
        )
        await db_session.commit()

        response = await client.get("/api/notifications/inbox", headers=auth_headers)

        assert response.status_code == 200
        items = _own_items(response, vin)
        counts = await count_pending_reminders(
            db_session,
            vin,
            await get_current_mileage(vin, db_session),
            await get_current_hours(vin, db_session),
        )
        kinds = [item["kind"] for item in items.values()]
        assert kinds.count("reminder_overdue") == counts.overdue == 1
        assert kinds.count("reminder_upcoming") == counts.due_soon == 3
        assert set(items) == {
            "Count overdue",
            "Count soon by date",
            "Count soon by share",
            "Count soon by hours share",
        }
