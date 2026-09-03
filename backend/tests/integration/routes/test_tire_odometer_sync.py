"""The odometer a user types into a tire operation has to count as an odometer.

Every tire write that takes an odometer was recording it on the mount period
and nowhere else. `distance_on_tire` bounds an OPEN period with the vehicle's
latest `OdometerRecord`, so a user who rotated their tires and dutifully
entered the odometer still saw "incomplete": the number they had just typed was
not an odometer reading as far as the rest of the app was concerned.

Fuel records and service visits have synced one since v2.26.2 via
`sync_odometer_from_record`. These tests pin the tire paths onto the same
helper, with the same two refusals: a manual reading is never overwritten, and
the row is cleaned up when its source is deleted.

The one deliberate asymmetry is at the bottom of this file: a ROTATION's
reading survives the deletion of a tire that took part in it.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.odometer import OdometerRecord
from app.models.vehicle import Vehicle

TODAY = date(2026, 3, 14)


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle for this file alone, cleaned up afterwards.

    Its own VIN because these assertions count the vehicle's odometer rows, and
    its own make/model because leaving look-alike vehicles behind has broken
    test_vehicle.py's dashboard assertions twice.
    """
    vin = f"TIREODO{uuid.uuid4().hex[:10].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Odometer Sync",
            vehicle_type="Car",
            year=2019,
            make="Subaru",
            model="Forester",
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


async def _odometer_rows(db_session, vin: str) -> list[OdometerRecord]:
    return list(
        (
            await db_session.execute(
                select(OdometerRecord)
                .where(OdometerRecord.vin == vin)
                .order_by(OdometerRecord.date, OdometerRecord.id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestTheOdometerIsRecorded:
    """One reading per operation, at the operation's own date."""

    async def test_mounting_records_the_odometer(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=TODAY.isoformat(),
            mounted_odometer_km="20000",
        )

        rows = await _odometer_rows(db_session, vehicle)
        assert [(r.date, r.odometer_km) for r in rows] == [(TODAY, 20000)]
        assert rows[0].source == "tire"

    async def test_mounting_an_existing_tire_records_the_odometer(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """`create-and-mount` and `mount` are separate writers and both count."""
        created = await client.post(
            f"/api/vehicles/{vehicle}/tires",
            headers=auth_headers,
            json={"vin": vehicle, "tread_depth_mm": "8.0"},
        )
        assert created.status_code == 201, created.text

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{created.json()['id']}/mount",
            headers=auth_headers,
            json={
                "position": "FR",
                "mounted_on": TODAY.isoformat(),
                "mounted_odometer_km": "21000",
            },
        )
        assert response.status_code == 200, response.text

        rows = await _odometer_rows(db_session, vehicle)
        assert [(r.date, r.odometer_km) for r in rows] == [(TODAY, 21000)]

    async def test_dismounting_records_the_odometer(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire = await _mount(client, auth_headers, vehicle, "FL")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": TODAY.isoformat(), "dismounted_odometer_km": "25000"},
        )
        assert response.status_code == 200, response.text

        rows = await _odometer_rows(db_session, vehicle)
        assert (TODAY, 25000) in [(r.date, r.odometer_km) for r in rows]

    async def test_retiring_records_the_odometer(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Retire takes the same request body as dismount, so it is the same writer."""
        tire = await _mount(client, auth_headers, vehicle, "RL")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={"dismounted_on": TODAY.isoformat(), "dismounted_odometer_km": "26000"},
        )
        assert response.status_code == 200, response.text

        rows = await _odometer_rows(db_session, vehicle)
        assert (TODAY, 26000) in [(r.date, r.odometer_km) for r in rows]

    async def test_a_reading_records_the_odometer(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A tread reading's odometer is vehicle context by its own schema's words.

        Without this the previous three tests make things WORSE for someone who
        only records readings: mounting publishes an odometer, which becomes the
        open period's upper bound, and the card reports a confident "0 km"
        instead of admitting it does not know.
        """
        tire = await _mount(client, auth_headers, vehicle, "RR", mounted_odometer_km="30000")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/readings",
            headers=auth_headers,
            json={
                "recorded_at": TODAY.isoformat(),
                "odometer_km": "34000",
                "tread_depth_mm": "7.0",
            },
        )
        assert response.status_code == 201, response.text

        rows = await _odometer_rows(db_session, vehicle)
        assert (TODAY, 34000) in [(r.date, r.odometer_km) for r in rows]

    async def test_rotating_records_one_reading_and_completes_the_distance(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The case that started this: the payoff is `complete`, not `incomplete`.

        A rotation writes ONE reading however many tires moved, because the
        odometer is a fact about the vehicle, not about each corner.
        """
        left = await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=date(2026, 1, 1).isoformat(),
            mounted_odometer_km="1000",
        )
        right = await _mount(
            client,
            auth_headers,
            vehicle,
            "FR",
            mounted_on=date(2026, 1, 1).isoformat(),
            mounted_odometer_km="1000",
        )

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": left["id"], "position": "RR"},
                    {"tire_id": right["id"], "position": "RL"},
                ],
                "rotated_on": TODAY.isoformat(),
                "odometer_km": "20000",
            },
        )
        assert response.status_code == 200, response.text

        # Two mounts on 2026-01-01 collapse to ONE reading for that date, and
        # the rotation adds exactly one more. Not three.
        rows = await _odometer_rows(db_session, vehicle)
        assert [(r.date, r.odometer_km) for r in rows] == [
            (date(2026, 1, 1), 1000),
            (TODAY, 20000),
        ]

        for tire in response.json()["tires"]:
            assert tire["distance_status"] == "complete", tire
            assert tire["distance_km"] == "19000.00", tire


@pytest.mark.asyncio
class TestItRefusesToOverwriteAManualReading:
    async def test_a_manual_reading_on_the_same_date_wins(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The user's own entry is authoritative. Same rule as fuel and service."""
        db_session.add(
            OdometerRecord(vin=vehicle, date=TODAY, odometer_km=44000, notes="Read it myself")
        )
        await db_session.commit()

        await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=TODAY.isoformat(),
            mounted_odometer_km="20000",
        )

        rows = await _odometer_rows(db_session, vehicle)
        assert [(r.date, r.odometer_km, r.notes) for r in rows] == [
            (TODAY, 44000, "Read it myself")
        ]


@pytest.mark.asyncio
class TestDeletingTheSourceRemovesTheReading:
    """The other half of the boundary.

    Nothing cascades these rows: `odometer_records` carries a FK for
    fuel-sourced rows only. A tire entered with a typo'd odometer and then
    deleted would otherwise leave the typo behind, poisoning every mileage
    reminder the vehicle has.
    """

    async def test_deleting_a_tire_removes_the_reading_it_synced(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire = await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=TODAY.isoformat(),
            mounted_odometer_km="900000",
        )

        response = await client.delete(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}", headers=auth_headers
        )
        assert response.status_code == 204, response.text

        assert await _odometer_rows(db_session, vehicle) == []

    async def test_deleting_a_tire_leaves_a_manual_reading_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        db_session.add(
            OdometerRecord(
                vin=vehicle, date=date(2026, 2, 1), odometer_km=15000, notes="Read it myself"
            )
        )
        await db_session.commit()

        tire = await _mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=TODAY.isoformat(),
            mounted_odometer_km="20000",
        )
        await client.delete(f"/api/vehicles/{vehicle}/tires/{tire['id']}", headers=auth_headers)

        rows = await _odometer_rows(db_session, vehicle)
        assert [(r.date, r.odometer_km) for r in rows] == [(date(2026, 2, 1), 15000)]

    async def test_deleting_a_rotated_tire_keeps_the_rotations_reading(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The deliberate asymmetry.

        A mount's odometer exists because of ONE tire, so it goes when that
        tire goes. A rotation's odometer is a reading of the vehicle taken
        while several tires were on it; deleting one of them does not make the
        reading untrue, and cascading it would break the distance figure for
        every other tire in the same rotation.
        """
        left = await _mount(client, auth_headers, vehicle, "FL")
        right = await _mount(client, auth_headers, vehicle, "FR")

        response = await client.post(
            f"/api/vehicles/{vehicle}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": left["id"], "position": "RR"},
                    {"tire_id": right["id"], "position": "RL"},
                ],
                "rotated_on": TODAY.isoformat(),
                "odometer_km": "20000",
            },
        )
        assert response.status_code == 200, response.text

        deleted = await client.delete(
            f"/api/vehicles/{vehicle}/tires/{left['id']}", headers=auth_headers
        )
        assert deleted.status_code == 204, deleted.text

        rows = await _odometer_rows(db_session, vehicle)
        assert [(r.date, r.odometer_km) for r in rows] == [(TODAY, 20000)]
