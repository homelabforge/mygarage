"""A one-off stores its start when it's made (PR #216).

Before, its start was the reading nearest the day it was made, looked up on
every read, so a reading added or corrected that day moved the start with it.
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vehicle
from app.utils.household_time import household_today

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed_vehicle(db_session: AsyncSession, owner_id, vin: str, **fields) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname="Start Rig",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Rig",
            **fields,
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


async def _fill_up(client: AsyncClient, headers: dict, vin: str, km: str) -> None:
    r = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json={
            "vin": vin,
            "date": household_today().isoformat(),
            "liters": 40.0,
            "cost": 60.0,
            "odometer_km": km,
            "is_full_tank": True,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text


async def _create(client: AsyncClient, headers: dict, vin: str, body: dict) -> dict:
    r = await client.post(f"/api/vehicles/{vin}/reminders", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_same_day_fill_up_moves_the_bar(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """Both fill-ups write the day's odometer row; the second takes it over in place."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216001")
    await _fill_up(client, non_admin_headers, vin, "115388.00")
    await _create(
        client,
        non_admin_headers,
        vin,
        {"title": "Oil", "reminder_type": "mileage", "due_mileage_km": "116000.00"},
    )
    await _fill_up(client, non_admin_headers, vin, "115450.00")
    (row,) = await _list(client, non_admin_headers, vin)
    assert row["progress_basis"] == "distance"
    assert row["progress"] == pytest.approx(62 / 612)


async def test_a_sparse_history_keeps_the_bar_past_due(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """The first reading after creation is nearer and already past due."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216002")
    today = household_today()
    old = await client.post(
        f"/api/vehicles/{vin}/odometer",
        headers=non_admin_headers,
        json={
            "vin": vin,
            "date": (today - timedelta(days=60)).isoformat(),
            "odometer_km": "10000.00",
        },
    )
    assert old.status_code == 201, old.text
    await _create(
        client,
        non_admin_headers,
        vin,
        {"title": "Belt", "reminder_type": "mileage", "due_mileage_km": "11000.00"},
    )
    new = await client.post(
        f"/api/vehicles/{vin}/odometer",
        headers=non_admin_headers,
        json={"vin": vin, "date": today.isoformat(), "odometer_km": "11500.00"},
    )
    assert new.status_code == 201, new.text
    (row,) = await _list(client, non_admin_headers, vin)
    assert row["due_status"] == "overdue"
    assert row["progress_basis"] == "distance"
    assert row["progress"] == pytest.approx(1.5)


async def test_a_same_day_hours_update_moves_the_bar(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """The vehicle's current hours upsert today's manual row in place."""
    vin = await _seed_vehicle(
        db_session, non_admin_user["id"], "5NPE24AF0FH216003", usage_unit="hours"
    )
    first = await client.put(
        f"/api/vehicles/{vin}", json={"current_hours": 100.0}, headers=non_admin_headers
    )
    assert first.status_code == 200, first.text
    await _create(
        client,
        non_admin_headers,
        vin,
        {"title": "Hydraulics", "reminder_type": "hours", "due_hours": "150.0"},
    )
    second = await client.put(
        f"/api/vehicles/{vin}", json={"current_hours": 110.0}, headers=non_admin_headers
    )
    assert second.status_code == 200, second.text
    (row,) = await _list(client, non_admin_headers, vin)
    assert row["progress_basis"] == "hours"
    assert row["progress"] == pytest.approx(0.2)


async def test_a_mileage_target_added_later_counts_from_creation(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """A date-only one-off stores the odometer too, so a target added by PUT counts from creation."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216004")
    await _fill_up(client, non_admin_headers, vin, "115388.00")
    created = await _create(
        client,
        non_admin_headers,
        vin,
        {
            "title": "Inspection",
            "reminder_type": "date",
            "due_date": (household_today() + timedelta(days=100)).isoformat(),
        },
    )
    put = await client.put(
        f"/api/vehicles/{vin}/reminders/{created['id']}",
        headers=non_admin_headers,
        json={"reminder_type": "both", "due_mileage_km": "116000.00"},
    )
    assert put.status_code == 200, put.text
    await _fill_up(client, non_admin_headers, vin, "115450.00")
    (row,) = await _list(client, non_admin_headers, vin)
    assert row["progress_basis"] == "distance"
    assert row["progress"] == pytest.approx(62 / 612)


async def test_a_typo_fixed_later_brings_the_bar_back(
    client: AsyncClient, non_admin_headers, non_admin_user, db_session: AsyncSession
):
    """A typo on file when the reminder is made, fixed later, counts from the nearest reading again."""
    vin = await _seed_vehicle(db_session, non_admin_user["id"], "5NPE24AF0FH216005")
    typo = await client.post(
        f"/api/vehicles/{vin}/odometer",
        headers=non_admin_headers,
        json={"vin": vin, "date": household_today().isoformat(), "odometer_km": "101000.00"},
    )
    assert typo.status_code == 201, typo.text
    await _create(
        client,
        non_admin_headers,
        vin,
        {"title": "Oil", "reminder_type": "mileage", "due_mileage_km": "11000.00"},
    )
    fixed = await client.put(
        f"/api/vehicles/{vin}/odometer/{typo.json()['id']}",
        headers=non_admin_headers,
        json={"odometer_km": "10100.00"},
    )
    assert fixed.status_code == 200, fixed.text
    (row,) = await _list(client, non_admin_headers, vin)
    # The stored 101,000 is above the fixed reading, so it's ignored and the bar shows as on main.
    assert row["progress_basis"] == "distance"
    assert row["progress"] == pytest.approx(0.0)
