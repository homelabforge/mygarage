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

import pytest
from httpx import AsyncClient

from app.models.reminder import Reminder
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _vehicle(db_session, test_user, vin: str) -> None:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Search",
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
        items = {item["title"]: item for item in response.json()["items"]}
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
        from decimal import Decimal

        from app.models.odometer import OdometerRecord

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
        titles = [item["title"] for item in response.json()["items"]]
        assert "Tyre rotation" not in titles
