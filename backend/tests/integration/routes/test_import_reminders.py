"""Legacy JSON import reminders: a real due point and a stored start (2.3)."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder, Vehicle
from app.utils.household_time import household_date, household_today

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed_vehicle(db_session: AsyncSession, owner_id, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname="Import Rig",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Rig",
        )
    )
    await db_session.commit()
    return vin


async def _list(client: AsyncClient, headers: dict, vin: str) -> list:
    r = await client.get(
        f"/api/vehicles/{vin}/reminders", params={"status": "pending"}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _import(client: AsyncClient, headers: dict, vin: str, payload: dict) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _reminders(db_session: AsyncSession, vin: str) -> list[Reminder]:
    await db_session.rollback()
    result = await db_session.execute(
        select(Reminder).where(Reminder.vin == vin).order_by(Reminder.id)
    )
    return list(result.scalars().all())


async def test_a_legacy_mileage_interval_counts_from_the_odometer_after_the_import(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """40 days ago at 50,000 km, an interval of 1,000 km, 51,200 km today: 1.2 of the way."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216101")
    today = household_today()
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "odometer_records": [
                {"date": (today - timedelta(days=40)).isoformat(), "reading": 31068.56}
            ],
            "reminders": [
                {"description": "Oil change", "is_recurring": True, "recurrence_miles": 621.37}
            ],
        },
    )
    assert data["reminders"]["success_count"] == 1, data
    now = await client.post(
        f"/api/vehicles/{vin}/odometer",
        headers=non_admin_headers,
        json={"vin": vin, "date": today.isoformat(), "odometer_km": "51200.00"},
    )
    assert now.status_code == 201, now.text
    (row,) = await _list(client, non_admin_headers, vin)
    assert Decimal(row["due_mileage_km"]) == Decimal("51000.00")  # main: 621.37
    assert row["progress_basis"] == "distance"
    assert row["progress"] == pytest.approx(1.2, abs=1e-3)  # main and PR head: None


async def test_a_miles_only_interval_with_no_odometer_reading_is_refused(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216102")
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {"reminders": [{"description": "Oil", "is_recurring": True, "recurrence_miles": 5000}]},
    )
    assert data["reminders"]["success_count"] == 0, data
    assert data["reminders"]["error_count"] == 1, data
    assert "Reminder 0: no odometer reading to count from" in data["errors"], data
    assert await _reminders(db_session, vin) == []


async def test_a_date_and_mileage_interval_with_no_reading_keeps_the_date_side(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216103")
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "reminders": [
                {
                    "description": "Service",
                    "is_recurring": True,
                    "recurrence_days": 180,
                    "recurrence_miles": 5000,
                }
            ]
        },
    )
    assert data["reminders"]["success_count"] == 1, data
    assert data["errors"] == []
    (reminder,) = await _reminders(db_session, vin)
    assert reminder.reminder_type == "date"
    assert reminder.due_mileage_km is None
    assert reminder.due_date == household_today() + timedelta(days=180)


async def test_an_imported_reminder_stores_both_readings(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216104")
    yesterday = (household_today() - timedelta(days=1)).isoformat()
    await _import(
        client,
        non_admin_headers,
        vin,
        {
            "export_version": "3",
            "units": "metric",
            "odometer_records": [{"date": yesterday, "odometer_km": 20000}],
            "hours_records": [{"date": yesterday, "engine_hours": 75.5}],
            "reminders": [
                {"description": "Inspection", "is_recurring": True, "recurrence_days": 365}
            ],
        },
    )
    (reminder,) = await _reminders(db_session, vin)
    assert (reminder.start_odometer_km, reminder.start_hours) == (
        Decimal("20000.00"),
        Decimal("75.5"),
    )


async def test_a_one_time_legacy_reminder_keeps_its_due_date_and_mileage(  # D7
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216105")
    due = (household_today() + timedelta(days=30)).isoformat()
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "odometer_records": [
                {
                    "date": (household_today() - timedelta(days=10)).isoformat(),
                    "reading": 31068.56,
                }
            ],
            "reminders": [
                {
                    "description": "Registration",
                    "due_date": due,
                    "due_mileage": 32000,
                    "is_recurring": False,
                },
                {"description": "Nothing due", "is_recurring": False},
            ],
        },
    )
    assert data["reminders"]["success_count"] == 1, data
    assert "Reminder 1: no due date or mileage to import" in data["errors"], data
    (reminder,) = await _reminders(db_session, vin)
    assert reminder.reminder_type == "both"
    assert reminder.due_date.isoformat() == due
    assert reminder.due_mileage_km == Decimal("51499.01")  # 32,000 mi; main: None


async def test_a_recurring_row_with_no_interval_is_refused(  # Codex R1-M2
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216106")
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "reminders": [
                {"description": "No interval", "is_recurring": True, "recurrence_days": 0},
                {"description": "Plates", "is_recurring": True, "recurrence_days": 365},
            ]
        },
    )
    assert data["reminders"]["success_count"] == 1, data
    assert "Reminder 0: no due date or mileage to import" in data["errors"], data
    (reminder,) = await _reminders(db_session, vin)
    assert reminder.title == "Plates"  # main: 2 rows, one never due


async def test_a_completed_legacy_reminder_imports_as_done(  # D8
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216107")
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "reminders": [
                {
                    "description": "Old oil",
                    "is_completed": True,
                    "completed_at": "2025-11-02T15:30:00",
                    "due_date": "2025-11-01",
                    "is_recurring": True,
                    "recurrence_days": 90,
                }
            ]
        },
    )
    assert data["reminders"]["success_count"] == 1, data
    (reminder,) = await _reminders(db_session, vin)
    assert reminder.status == "done"  # main: pending
    assert reminder.completed_at == datetime(2025, 11, 2, 15, 30)
    assert reminder.completed_date == household_date(datetime(2025, 11, 2, 15, 30))
    assert (reminder.reminder_type, reminder.due_date) == ("date", date(2025, 11, 1))
    assert await _list(client, non_admin_headers, vin) == []


async def test_a_completed_at_reads_as_utc_and_a_bad_one_is_refused(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """A zoned time lands as naive UTC, a missing one stays empty, junk is refused."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216108")
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "reminders": [
                {"description": "Garbled", "is_completed": True, "completed_at": "last tuesday"},
                {"description": "Numbered", "is_completed": True, "completed_at": 20251102},
                {
                    "description": "Zoned",
                    "is_completed": True,
                    "completed_at": "2025-11-02T10:30:00-05:00",
                    "due_mileage": 30000,
                },
                {"description": "Undated", "is_completed": True},
            ]
        },
    )
    assert data["reminders"]["success_count"] == 2, data
    assert "Reminder 0: completed_at is not a valid date and time" in data["errors"], data
    assert "Reminder 1: completed_at is not a valid date and time" in data["errors"], data
    zoned, undated = await _reminders(db_session, vin)
    assert zoned.completed_at == datetime(2025, 11, 2, 15, 30)
    assert (zoned.reminder_type, zoned.due_mileage_km) == ("mileage", Decimal("48280.32"))
    assert (undated.status, undated.completed_at, undated.completed_date) == ("done", None, None)
    assert (undated.reminder_type, undated.due_date, undated.due_mileage_km) == (
        "date",
        None,
        None,
    )


async def test_a_due_point_the_api_refuses_fails(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """A one-time row's own mileage and an interval added to the odometer both get bounds."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216109")
    yesterday = (household_today() - timedelta(days=1)).isoformat()
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "export_version": "3",
            "units": "metric",
            "odometer_records": [{"date": yesterday, "odometer_km": 1000}],
            "reminders": [
                {"description": "Negative", "due_mileage": -5, "is_recurring": False},
                {"description": "Past the cap", "is_recurring": True, "recurrence_miles": 99999999},
                {"description": "Endless", "due_mileage": float("inf"), "is_recurring": False},
            ],
        },
    )
    assert data["reminders"]["success_count"] == 0, data
    # Rounded before the check, so it reads like the interval's message.
    assert "Reminder 0: due_mileage_km must be more than 0, not -5.00" in data["errors"], data
    assert (
        "Reminder 1: due_mileage_km must be at most 99999999.99, not 100000999.00" in data["errors"]
    ), data
    assert "Reminder 2: due_mileage_km must be a number" in data["errors"], data
    assert await _reminders(db_session, vin) == []


async def test_a_due_point_is_rounded_to_the_cent_before_it_is_stored(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """A half cent rounds here, half to even, so SQLite and PostgreSQL store the same cent."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216110")
    yesterday = (household_today() - timedelta(days=1)).isoformat()
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "export_version": "3",
            "units": "metric",
            "odometer_records": [{"date": yesterday, "odometer_km": 1000}],
            "reminders": [
                {"description": "Own mileage", "due_mileage": 1000.015, "is_recurring": False},
                {"description": "Interval", "is_recurring": True, "recurrence_miles": 19000.015},
                {"description": "Own, even tie", "due_mileage": 2000.025, "is_recurring": False},
                {
                    "description": "Interval, even tie",
                    "is_recurring": True,
                    "recurrence_miles": 29000.025,
                },
            ],
        },
    )
    assert data["reminders"]["success_count"] == 4, data
    rows = await _reminders(db_session, vin)
    # Unrounded, SQLite reads the .015s back as .01, and both dialects store the .025s as .03.
    assert [r.due_mileage_km for r in rows] == [
        Decimal("1000.02"),
        Decimal("20000.02"),
        Decimal("2000.02"),
        Decimal("30000.02"),
    ]


async def test_a_legacy_zero_mileage_reads_as_no_mileage(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """The v2 app saved 0 for no mileage, so it isn't a due odometer of zero."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216111")
    due = (household_today() + timedelta(days=30)).isoformat()
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "reminders": [
                {"description": "Plates", "due_date": due, "due_mileage": 0, "is_recurring": False},
                {
                    "description": "Old wash",
                    "is_completed": True,
                    "completed_at": "2025-11-02T15:30:00",
                    "due_date": "2025-11-01",
                    "due_mileage": 0,
                    "is_recurring": False,
                },
                {"description": "Zero only", "due_mileage": 0, "is_recurring": False},
            ]
        },
    )
    assert data["reminders"]["success_count"] == 2, data
    assert data["errors"] == ["Reminder 2: no due date or mileage to import"], data
    plates, wash = await _reminders(db_session, vin)
    assert (plates.status, plates.reminder_type, plates.due_mileage_km) == ("pending", "date", None)
    assert plates.due_date.isoformat() == due
    assert (wash.status, wash.reminder_type, wash.due_mileage_km) == ("done", "date", None)


async def test_a_blank_due_date_imports_on_the_mileage(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """A blank due_date is no date, same as a missing one, so the mileage carries the row."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216112")
    data = await _import(
        client,
        non_admin_headers,
        vin,
        {
            "export_version": "3",
            "units": "metric",
            "reminders": [
                {
                    "description": "Belt",
                    "due_date": "",
                    "due_mileage": 150000,
                    "is_recurring": False,
                },
                {
                    "description": "Coolant",
                    "due_date": " ",
                    "due_mileage": 160000,
                    "is_recurring": False,
                },
            ],
        },
    )
    assert data["reminders"]["success_count"] == 2, data
    belt, coolant = await _reminders(db_session, vin)
    assert (belt.reminder_type, belt.due_date, belt.due_mileage_km) == (
        "mileage",
        None,
        Decimal("150000.00"),
    )
    assert (coolant.reminder_type, coolant.due_date, coolant.due_mileage_km) == (
        "mileage",
        None,
        Decimal("160000.00"),
    )
