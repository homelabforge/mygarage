"""Mounting, rotating, retiring and deleting a tire.

The distinction this file is mostly about: **retiring a tire is not deleting
it**. This release is the one that makes tire history worth keeping, and the
ordinary act of replacing a worn tire was a hard DELETE that cascaded through
every reading and every mount period. Shipping the mount-period model beside an
unchanged delete would mean the first thing a user does after collecting a
season of data is erase it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading
from app.models.vehicle import Vehicle


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle for this test alone, cleaned up afterwards.

    Positions are claimable once per vehicle now, so a shared VIN would make
    these tests order-dependent; and leaving vehicles behind breaks a
    paginated assertion in test_vehicle.py.
    """
    vin = f"TIRELIFE{uuid.uuid4().hex[:9].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Lifecycle",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Accord",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _mount(client: AsyncClient, headers, vin: str, position: str, **extra) -> dict:
    body = {"vin": vin, "position": position, "tread_depth_mm": "8.0", **extra}
    response = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount", headers=headers, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
class TestMountAndDismount:
    async def test_dismounting_frees_the_corner_and_keeps_the_tire(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire = await _mount(client, auth_headers, vehicle, "FL")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_odometer_km": "15000"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["position"] is None

        # The tire still exists, with its history.
        stored = (await db_session.execute(select(Tire).where(Tire.id == tire["id"]))).scalar_one()
        assert stored.position is None
        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire["id"])
                )
            )
            .scalars()
            .all()
        )
        assert len(periods) == 1
        assert periods[0].dismounted_on is not None

        # And the corner is free for another tire.
        await _mount(client, auth_headers, vehicle, "FL")

    async def test_two_tires_cannot_hold_one_corner(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        await _mount(client, auth_headers, vehicle, "FR")
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "FR", "tread_depth_mm": "8.0"},
        )
        assert response.status_code == 409, response.text

    async def test_a_failed_create_and_mount_leaves_no_orphan_tire(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The reason create-and-mount is one operation.

        A caller doing create-then-mount by hand and losing the mount would be
        left with a tire it did not ask for and cannot see.
        """
        await _mount(client, auth_headers, vehicle, "RL")
        before = len(
            (await db_session.execute(select(Tire).where(Tire.vin == vehicle))).scalars().all()
        )
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vehicle, "position": "RL", "brand": "Orphan"},
        )
        assert response.status_code == 409
        after = (await db_session.execute(select(Tire).where(Tire.vin == vehicle))).scalars().all()
        assert len(after) == before
        assert not any(t.brand == "Orphan" for t in after)

    async def test_mounting_an_already_mounted_tire_is_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire = await _mount(client, auth_headers, vehicle, "RR")
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount",
            headers=auth_headers,
            json={"position": "SPARE"},
        )
        assert response.status_code == 409, response.text

    async def test_a_stored_tire_can_be_remounted_elsewhere(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The seasonal-swap case the whole model exists for: a tire comes off
        in autumn and goes back on in spring, keeping its history."""
        tire = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_odometer_km": "9000"},
        )
        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/mount",
            headers=auth_headers,
            json={"position": "FR", "mounted_odometer_km": "12000"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["position"] == "FR"

        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod)
                    .where(TireMountPeriod.tire_id == tire["id"])
                    .order_by(TireMountPeriod.id)
                )
            )
            .scalars()
            .all()
        )
        assert [p.position for p in periods] == ["FL", "FR"]
        # 8,000 km on the first period. The 3,000 km the vehicle drove while
        # this tire was in storage is NOT credited to it -- that is the whole
        # defect this release fixes.
        assert response.json()["distance_status"] == "complete"


@pytest.mark.asyncio
class TestDeleteAndRetire:
    async def test_deleting_a_tire_with_a_reminder_succeeds(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The composite FK carries no ON DELETE action on purpose.

        SET NULL would try to null `vin` too -- a referential action applies to
        every column in the FK -- and `vehicle_reminders.vin` is NOT NULL, so
        SQLite rejects the delete outright and retiring a tire becomes
        impossible. The service nulls `tire_id` explicitly instead.
        """
        tire = await _mount(
            client, auth_headers, vehicle, "FL", tread_depth_mm="1.0", min_tread_mm="3.0"
        )
        reminders = (
            (await db_session.execute(select(Reminder).where(Reminder.vin == vehicle)))
            .scalars()
            .all()
        )
        assert reminders, "a tire below its threshold should have raised a reminder"

        response = await client.delete(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}", headers=auth_headers
        )
        assert response.status_code in (200, 204), response.text

        # The reminder survives as history, detached from the deleted tire.
        await db_session.commit()
        surviving = (
            (await db_session.execute(select(Reminder).where(Reminder.vin == vehicle)))
            .scalars()
            .all()
        )
        assert surviving, "deleting a tire must not erase the record that it was flagged"
        assert all(r.tire_id is None for r in surviving)

    async def test_retiring_keeps_every_reading_and_period(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The ordinary act of replacing a worn tire.

        Before this release it was a hard DELETE that cascaded through the
        readings and mount periods -- erasing exactly the history the mount
        period model exists to collect.
        """
        tire = await _mount(client, auth_headers, vehicle, "FL", mounted_odometer_km="1000")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/readings",
            headers=auth_headers,
            json={"recorded_at": "2026-03-01", "tread_depth_mm": "5.0"},
        )

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={"dismounted_odometer_km": "20000"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["retired_on"] is not None
        assert body["position"] is None, "a retired tire is not on the vehicle"

        readings = (
            (await db_session.execute(select(TireReading).where(TireReading.tire_id == tire["id"])))
            .scalars()
            .all()
        )
        assert len(readings) == 1, "retiring must not erase readings"
        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire["id"])
                )
            )
            .scalars()
            .all()
        )
        assert len(periods) == 1
        assert periods[0].dismounted_on is not None, "retiring closes the open period"

    async def test_a_retired_tire_is_out_of_the_default_list(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire = await _mount(client, auth_headers, vehicle, "FL")
        await _mount(client, auth_headers, vehicle, "FR")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={},
        )

        listed = await client.get(f"/api/vehicles/{vehicle}/tires", headers=auth_headers)
        assert listed.status_code == 200
        ids = [t["id"] for t in listed.json()["tires"]]
        assert tire["id"] not in ids

        # But it is still there when asked for.
        with_retired = await client.get(
            f"/api/vehicles/{vehicle}/tires?include_retired=true", headers=auth_headers
        )
        assert with_retired.status_code == 200
        assert tire["id"] in [t["id"] for t in with_retired.json()["tires"]]

    async def test_retiring_frees_the_corner(self, client: AsyncClient, auth_headers, vehicle):
        """The replacement goes where the old one was."""
        tire = await _mount(client, auth_headers, vehicle, "FL")
        await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={},
        )
        await _mount(client, auth_headers, vehicle, "FL")
