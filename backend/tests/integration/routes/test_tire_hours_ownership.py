"""The hour meter rows a tire published move and go with it (#217).

The period editor moves its own row when a mount's date or hours change, a
deleted tire takes its rows with it, and a deleted reading withdraws its row,
all by marker, exactly the way the odometer rows behave. On an hours-only
vehicle nothing here may grow an odometer row.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.tire import TireMountPeriod, TireReading
from app.models.vehicle import Vehicle
from app.utils.odometer_sync import auto_sync_marker

DAY = date(2026, 6, 21)


@pytest_asyncio.fixture
async def vin(db_session, test_user):
    made = f"HRO{uuid.uuid4().hex[:14].upper()}"
    db_session.add(
        Vehicle(
            vin=made,
            user_id=test_user["id"],
            nickname="Hours ownership",
            vehicle_type="ATV",
            year=2022,
            make="Can-Am",
            model="Outlander",
            usage_unit="hours",
        )
    )
    await db_session.commit()
    yield made
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


async def _rows(db_session, vin):
    db_session.expire_all()
    rows = (
        (
            await db_session.execute(
                select(HoursRecord)
                .where(HoursRecord.vin == vin)
                .order_by(HoursRecord.date, HoursRecord.id)
            )
        )
        .scalars()
        .all()
    )
    return [(r.date, r.engine_hours, r.notes) for r in rows]


async def _tire(client, headers, vin, position="FL", **figures):
    made = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount",
        headers=headers,
        json={"vin": vin, "position": position, "mounted_on": DAY.isoformat(), **figures},
    )
    assert made.status_code == 201, made.text
    return made.json()


async def _edit(client, headers, vin, tire, **fields):
    period_id = tire["mount_periods"][0]["id"]
    return await client.put(
        f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
        headers=headers,
        json=fields,
    )


async def _reading(client, headers, vin, tire_id, day, hours):
    made = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings",
        headers=headers,
        json={"recorded_at": day.isoformat(), "tread_depth_mm": "7.0", "engine_hours": hours},
    )
    assert made.status_code == 201, made.text
    return made.json()


@pytest.mark.asyncio
class TestThePeriodEditor:
    async def test_new_hours_update_the_owned_row(self, client, auth_headers, db_session, vin):
        tire = await _tire(client, auth_headers, vin, mounted_hours="100.0")
        marker = auto_sync_marker("tire_mount", tire["mount_periods"][0]["id"])
        edited = await _edit(client, auth_headers, vin, tire, mounted_hours="105.0")
        assert edited.status_code == 200, edited.text
        assert await _rows(db_session, vin) == [(DAY, Decimal("105.0"), marker)]

    async def test_a_new_date_moves_the_owned_row(self, client, auth_headers, db_session, vin):
        tire = await _tire(client, auth_headers, vin, mounted_hours="100.0")
        marker = auto_sync_marker("tire_mount", tire["mount_periods"][0]["id"])
        earlier = DAY - timedelta(days=5)
        assert (
            await _edit(client, auth_headers, vin, tire, mounted_on=earlier.isoformat())
        ).status_code == 200
        assert await _rows(db_session, vin) == [(earlier, Decimal("100.0"), marker)]

    async def test_clearing_the_hours_withdraws_the_row(
        self, client, auth_headers, db_session, vin
    ):
        tire = await _tire(client, auth_headers, vin, mounted_hours="100.0")
        assert (await _edit(client, auth_headers, vin, tire, mounted_hours=None)).status_code == 200
        assert await _rows(db_session, vin) == []

    async def test_a_higher_row_on_the_new_day_keeps_its_place(
        self, client, auth_headers, db_session, vin
    ):
        earlier = DAY - timedelta(days=5)
        manual = await client.post(
            f"/api/vehicles/{vin}/hours",
            headers=auth_headers,
            json={"vin": vin, "date": earlier.isoformat(), "engine_hours": "120.0"},
        )
        assert manual.status_code == 201, manual.text
        tire = await _tire(client, auth_headers, vin, mounted_hours="100.0")
        assert (
            await _edit(client, auth_headers, vin, tire, mounted_on=earlier.isoformat())
        ).status_code == 200
        assert [(d, v) for d, v, _ in await _rows(db_session, vin)] == [(earlier, Decimal("120.0"))]

    async def test_editing_a_junk_period_date_publishes_no_odometer(
        self, client, auth_headers, db_session, vin
    ):
        # An hour figure typed into the odometer before the fix, with no odometer row left.
        tire = await _tire(client, auth_headers, vin)
        period = await db_session.get(TireMountPeriod, tire["mount_periods"][0]["id"])
        period.mounted_odometer_km = Decimal("170.00")
        await db_session.commit()
        moved = await _edit(
            client, auth_headers, vin, tire, mounted_on=(DAY - timedelta(days=3)).isoformat()
        )
        assert moved.status_code == 200, moved.text
        db_session.expire_all()
        odometers = (
            await db_session.execute(
                select(func.count()).select_from(OdometerRecord).where(OdometerRecord.vin == vin)
            )
        ).scalar_one()
        assert odometers == 0


@pytest.mark.asyncio
class TestDeletes:
    async def test_a_deleted_tire_takes_its_rows_and_leaves_the_manual_one(
        self, client, auth_headers, db_session, vin
    ):
        manual = await client.post(
            f"/api/vehicles/{vin}/hours",
            headers=auth_headers,
            json={
                "vin": vin,
                "date": (DAY - timedelta(days=10)).isoformat(),
                "engine_hours": "50.0",
            },
        )
        assert manual.status_code == 201, manual.text
        tire = await _tire(client, auth_headers, vin, mounted_hours="100.0")
        await _reading(client, auth_headers, vin, tire["id"], DAY, "120.0")
        off = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={
                "dismounted_on": (DAY + timedelta(days=1)).isoformat(),
                "dismounted_hours": "130.0",
            },
        )
        assert off.status_code == 200, off.text
        assert len(await _rows(db_session, vin)) == 4
        gone = await client.delete(f"/api/vehicles/{vin}/tires/{tire['id']}", headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert [v for _, v, _ in await _rows(db_session, vin)] == [Decimal("50.0")]

    async def test_a_deleted_reading_withdraws_its_row(self, client, auth_headers, db_session, vin):
        tire = await _tire(client, auth_headers, vin)
        logged = await _reading(client, auth_headers, vin, tire["id"], DAY, "120.0")
        assert len(await _rows(db_session, vin)) == 1
        reading_id = logged["readings"][0]["id"]
        gone = await client.delete(
            f"/api/vehicles/{vin}/tires/{tire['id']}/readings/{reading_id}", headers=auth_headers
        )
        assert gone.status_code == 204, gone.text
        assert await _rows(db_session, vin) == []

    async def test_deleting_a_junk_reading_leaves_its_odometer_alone(
        self, client, auth_headers, db_session, vin
    ):
        # A reading and its odometer row from before the fix: an hour figure typed as kilometres.
        tire = await _tire(client, auth_headers, vin)
        logged = await _reading(client, auth_headers, vin, tire["id"], DAY, "120.0")
        reading_id = logged["readings"][0]["id"]
        marker = auto_sync_marker("tire", tire["id"])
        reading = await db_session.get(TireReading, reading_id)
        reading.odometer_km = Decimal("170.00")
        db_session.add(
            OdometerRecord(
                vin=vin, date=DAY, odometer_km=Decimal("170.00"), notes=marker, source="tire"
            )
        )
        await db_session.commit()
        gone = await client.delete(
            f"/api/vehicles/{vin}/tires/{tire['id']}/readings/{reading_id}", headers=auth_headers
        )
        assert gone.status_code == 204, gone.text
        assert await _rows(db_session, vin) == []
        odometers = (
            (await db_session.execute(select(OdometerRecord).where(OdometerRecord.vin == vin)))
            .scalars()
            .all()
        )
        assert [(r.date, r.odometer_km, r.notes) for r in odometers] == [
            (DAY, Decimal("170.00"), marker)
        ]

    async def test_a_same_day_reading_of_another_tire_backs_the_row(
        self, client, auth_headers, db_session, vin
    ):
        first = await _tire(client, auth_headers, vin, "FL")
        second = await _tire(client, auth_headers, vin, "FR")
        logged = await _reading(client, auth_headers, vin, first["id"], DAY, "120.0")
        await _reading(client, auth_headers, vin, second["id"], DAY, "120.0")
        assert [n for _, _, n in await _rows(db_session, vin)] == [
            auto_sync_marker("tire", first["id"])
        ]
        gone = await client.delete(
            f"/api/vehicles/{vin}/tires/{first['id']}/readings/{logged['readings'][0]['id']}",
            headers=auth_headers,
        )
        assert gone.status_code == 204, gone.text
        assert await _rows(db_session, vin) == [
            (DAY, Decimal("120.0"), auto_sync_marker("tire", second["id"]))
        ]
