"""The reminders list in due order, each row saying where it stands (#192).

A row's colour and the hero's counts come from one function
(reminder_service.reminder_due_status), so they can't disagree. The invariant
test below is the property D1 exists for.
"""

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HoursRecord, OdometerRecord, Reminder, Vehicle
from app.utils.household_time import household_today, household_zone

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _created_on_day(day: date) -> datetime:
    """A naive-UTC ``created_at`` that falls on ``day`` in the household zone (local noon)."""
    return (
        datetime.combine(day, time(12), tzinfo=household_zone())
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


async def _seed_vehicle(db_session: AsyncSession, owner_id, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname="Due Rig",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Rig",
        )
    )
    await db_session.commit()
    return vin


async def _list(client: AsyncClient, headers: dict, vin: str, status: str = "pending") -> list:
    r = await client.get(
        f"/api/vehicles/{vin}/reminders", params={"status": status}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_rows_come_in_due_order_with_their_status(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH192001")
    today = household_today()
    # Inserted in an order that is neither the expected one nor its reverse.
    db_session.add_all(
        [
            Reminder(
                vin=vin,
                title="On track",
                reminder_type="date",
                status="pending",
                due_date=today + timedelta(days=90),
            ),
            Reminder(
                vin=vin,
                title="Snoozed",
                reminder_type="date",
                status="pending",
                due_date=today - timedelta(days=1),
                snoozed_until=today + timedelta(days=5),
            ),
            Reminder(
                vin=vin,
                title="Overdue",
                reminder_type="date",
                status="pending",
                due_date=today - timedelta(days=3),
            ),
            Reminder(
                vin=vin,
                title="Due soon",
                reminder_type="date",
                status="pending",
                due_date=today + timedelta(days=10),
            ),
            Reminder(
                vin=vin,
                title="Done",
                reminder_type="date",
                status="done",
                due_date=today - timedelta(days=30),
                completed_date=today - timedelta(days=2),
            ),
        ]
    )
    await db_session.commit()

    rows = await _list(client, non_admin_headers, vin)
    assert [r["title"] for r in rows] == ["Overdue", "Due soon", "On track", "Snoozed"]
    assert [r["due_status"] for r in rows] == ["overdue", "due_soon", "on_track", "snoozed"]
    assert [r["days_until_due"] for r in rows] == [-3, 10, 90, -1]

    every = await _list(client, non_admin_headers, vin, "all")
    assert [r["title"] for r in every] == ["Overdue", "Due soon", "On track", "Snoozed", "Done"]

    (done,) = await _list(client, non_admin_headers, vin, "done")
    for key in (
        "due_status",
        "progress",
        "progress_basis",
        "days_until_due",
        "km_until_due",
        "hours_until_due",
    ):
        assert done[key] is None, key


async def test_the_list_and_the_hero_count_the_same_reminders(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH192002")
    today = household_today()
    db_session.add_all(
        [
            OdometerRecord(vin=vin, date=today - timedelta(days=100), odometer_km=Decimal("50000")),
            OdometerRecord(vin=vin, date=today, odometer_km=Decimal("59500")),
            HoursRecord(vin=vin, date=today, engine_hours=Decimal("150.0"), source="manual"),
            Reminder(
                vin=vin,
                title="Overdue",
                reminder_type="date",
                status="pending",
                due_date=today - timedelta(days=3),
            ),
            Reminder(
                vin=vin,
                title="Due soon by date",
                reminder_type="date",
                status="pending",
                due_date=today + timedelta(days=10),
            ),
            Reminder(
                vin=vin,
                title="On track",
                reminder_type="date",
                status="pending",
                due_date=today + timedelta(days=90),
            ),
            Reminder(
                vin=vin,
                title="Snoozed",
                reminder_type="date",
                status="pending",
                due_date=today - timedelta(days=1),
                snoozed_until=today + timedelta(days=5),
            ),
            # D2: 95% of the way by mileage, and one reading in 90 days means no rate.
            Reminder(
                vin=vin,
                title="Timing belt",
                reminder_type="mileage",
                status="pending",
                due_mileage_km=Decimal("60000"),
                created_at=_created_on_day(today - timedelta(days=100)),
            ),
            # Anchored, half way by hours, no hours rate: on track.
            Reminder(
                vin=vin,
                title="Hydraulics",
                reminder_type="hours",
                status="pending",
                due_hours=Decimal("200.0"),
                anchor_kind="baseline",
                anchor_date=today - timedelta(days=30),
                anchor_hours=Decimal("100.0"),
            ),
            Reminder(
                vin=vin,
                title="Done",
                reminder_type="date",
                status="done",
                due_date=today - timedelta(days=30),
            ),
        ]
    )
    await db_session.commit()

    r = await client.get(f"/api/vehicles/{vin}/detail-stats", headers=non_admin_headers)
    assert r.status_code == 200, r.text
    stats = r.json()
    rows = await _list(client, non_admin_headers, vin)
    by_status = Counter(row["due_status"] for row in rows)

    assert stats["overdue_count"] == by_status["overdue"] == 1
    assert stats["due_soon_count"] == by_status["due_soon"] == 2
    assert stats["upcoming_count"] == by_status["due_soon"] + by_status["on_track"] == 4

    belt = next(row for row in rows if row["title"] == "Timing belt")
    assert belt["due_status"] == "due_soon"
    assert belt["progress_basis"] == "distance"
    assert belt["progress"] == pytest.approx(0.95)
    assert Decimal(belt["km_until_due"]) == Decimal("500")
