"""A tire event owns only the odometer records it created.

A service visit, a fuel-up or a LiveLink device may already have recorded the
vehicle's odometer on the day a tire is mounted, read or fitted. The tire paths
used to treat any automatic record on that day as theirs: they overwrote its
value, re-marked it with the tire event's own marker, and from then on the
period editor moved it and a tire delete removed it. A service visit's reading
could end up two days later than the visit, and the vehicle's odometer history
then ran backwards.

The rule these tests pin: a tire event never touches a record without its own
marker. It updates a record carrying that marker; otherwise it publishes
nothing onto a day that already has a reading at or above its figure (within
the same-reading tolerance), and creates its own record when the day has no
record or only lower ones, so the vehicle's latest reading never falls behind
the tire's. Fuel, DEF and service visits update their own record first and
otherwise keep their same-day take-over, which never claims a tire's record.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.odometer import OdometerRecord
from app.models.tire import Tire, TireMountPeriod
from app.models.vehicle import Vehicle
from app.services.odometer_service import latest_odometer_km_and_date
from app.services.tire_service import (
    ODOMETER_SOURCE_ROTATION,
    ODOMETER_SOURCE_SET,
    ODOMETER_SOURCE_TIRE,
    ODOMETER_SOURCE_TIRE_DISMOUNT,
    ODOMETER_SOURCE_TIRE_MOUNT,
)
from app.utils.odometer_sync import auto_sync_marker

DAY = date(2026, 6, 21)
EARLIER = DAY - timedelta(days=30)
TIRE_SOURCES = {
    ODOMETER_SOURCE_TIRE,
    ODOMETER_SOURCE_TIRE_MOUNT,
    ODOMETER_SOURCE_TIRE_DISMOUNT,
    ODOMETER_SOURCE_ROTATION,
    ODOMETER_SOURCE_SET,
}

Row = tuple[date, Decimal, str | None, str | None]


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle for one test: these assertions list every odometer record it has."""
    vin = f"TYRESYN{uuid.uuid4().hex[:10].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Odometer ownership",
            vehicle_type="Car",
            year=2018,
            make="Mazda",
            model="CX-5",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _records(db_session, vin: str) -> list[OdometerRecord]:
    db_session.expire_all()
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


async def _rows(db_session, vin: str) -> list[Row]:
    return [(r.date, r.odometer_km, r.notes, r.source) for r in await _records(db_session, vin)]


async def _service_visit(client: AsyncClient, headers, vin: str, day: date, km: str) -> int:
    made = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        headers=headers,
        json={
            "date": day.isoformat(),
            "odometer_km": km,
            "line_items": [{"description": "Replace tires", "cost": 640.0}],
        },
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def _fuel(client: AsyncClient, headers, vin: str, day: date, km: str) -> int:
    made = await client.post(
        f"/api/vehicles/{vin}/fuel",
        headers=headers,
        json={
            "vin": vin,
            "date": day.isoformat(),
            "odometer_km": km,
            "liters": 45.0,
            "cost": 70.0,
            "price_per_unit": 1.55,
            "is_full_tank": True,
        },
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def _create_and_mount(client: AsyncClient, headers, vin: str, position: str, **body) -> int:
    made = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount",
        headers=headers,
        json={"vin": vin, "position": position, **body},
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def _service_row(visit_id: int, km: str) -> Row:
    marker = auto_sync_marker("service_visit", visit_id)
    return (DAY, Decimal(km), marker, "service_visit")


async def _mount_on_day(client: AsyncClient, headers, vin: str, km: str) -> str:
    await _create_and_mount(
        client, headers, vin, "FL", mounted_on=DAY.isoformat(), mounted_odometer_km=km
    )
    return ODOMETER_SOURCE_TIRE_MOUNT


async def _mount_existing_on_day(client: AsyncClient, headers, vin: str, km: str) -> str:
    made = await client.post(f"/api/vehicles/{vin}/tires", headers=headers, json={"vin": vin})
    assert made.status_code == 201, made.text
    mounted = await client.post(
        f"/api/vehicles/{vin}/tires/{made.json()['id']}/mount",
        headers=headers,
        json={"position": "FR", "mounted_on": DAY.isoformat(), "mounted_odometer_km": km},
    )
    assert mounted.status_code == 200, mounted.text
    return ODOMETER_SOURCE_TIRE_MOUNT


async def _dismount_on_day(client: AsyncClient, headers, vin: str, km: str) -> str:
    tire_id = await _create_and_mount(client, headers, vin, "RL", mounted_on=EARLIER.isoformat())
    off = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/dismount",
        headers=headers,
        json={"dismounted_on": DAY.isoformat(), "dismounted_odometer_km": km},
    )
    assert off.status_code == 200, off.text
    return ODOMETER_SOURCE_TIRE_DISMOUNT


async def _retire_on_day(client: AsyncClient, headers, vin: str, km: str) -> str:
    tire_id = await _create_and_mount(client, headers, vin, "RR", mounted_on=EARLIER.isoformat())
    retired = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/retire",
        headers=headers,
        json={"dismounted_on": DAY.isoformat(), "dismounted_odometer_km": km},
    )
    assert retired.status_code == 200, retired.text
    return ODOMETER_SOURCE_TIRE_DISMOUNT


async def _rotate_on_day(client: AsyncClient, headers, vin: str, km: str) -> str:
    left = await _create_and_mount(client, headers, vin, "FL", mounted_on=EARLIER.isoformat())
    right = await _create_and_mount(client, headers, vin, "FR", mounted_on=EARLIER.isoformat())
    rotated = await client.post(
        f"/api/vehicles/{vin}/tires/rotate",
        headers=headers,
        json={
            "rotated_on": DAY.isoformat(),
            "odometer_km": km,
            "moves": [
                {"tire_id": left, "position": "FR"},
                {"tire_id": right, "position": "FL"},
            ],
        },
    )
    assert rotated.status_code == 200, rotated.text
    return ODOMETER_SOURCE_ROTATION


def _own_row(rows: list[Row], km: str, source: str) -> None:
    """Assert `rows` ends with one record the tire event created for itself."""
    (day, odometer, notes, row_source) = rows[-1]
    assert (day, odometer, row_source) == (DAY, Decimal(km), source)
    assert notes is not None and notes.startswith(f"[AUTO-SYNC from {source} #")


async def _read_odometer(client: AsyncClient, headers, vin: str, tire_id: int, km: str) -> dict:
    logged = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings",
        headers=headers,
        json={"recorded_at": DAY.isoformat(), "odometer_km": km, "tread_depth_mm": "7.0"},
    )
    assert logged.status_code == 201, logged.text
    return logged.json()


@pytest.mark.asyncio
class TestAnotherSourcesReadingIsNeverTakenOver:
    @pytest.mark.parametrize(
        "writer",
        [
            _mount_on_day,
            _mount_existing_on_day,
            _dismount_on_day,
            _retire_on_day,
            _rotate_on_day,
        ],
        ids=["create_and_mount", "mount", "dismount", "retire", "rotate"],
    )
    async def test_a_tire_write_leaves_a_service_visits_reading_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session, writer
    ):
        """The service visit that replaced the tires recorded the odometer that
        day. Mounting them at a higher figure used to overwrite the visit's
        value and re-mark the record as the mount's own. The visit's record now
        stays as it was, and the tire event's figure, being higher, is recorded
        beside it as the event's own."""
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")
        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "50000")]

        source = await writer(client, auth_headers, vehicle, "50012")

        rows = await _rows(db_session, vehicle)
        assert rows[0] == _service_row(visit_id, "50000")
        assert len(rows) == 2
        _own_row(rows, "50012", source)

    @pytest.mark.parametrize(
        "writer",
        [
            _mount_on_day,
            _mount_existing_on_day,
            _dismount_on_day,
            _retire_on_day,
            _rotate_on_day,
        ],
        ids=["create_and_mount", "mount", "dismount", "retire", "rotate"],
    )
    async def test_a_tire_write_at_the_days_figure_publishes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session, writer
    ):
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")

        await writer(client, auth_headers, vehicle, "50000")

        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "50000")]

    async def test_the_period_editor_neither_takes_over_nor_moves_a_service_visits_reading(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A legacy period given the service visit's own date and odometer (what
        the editor's Use button fills in), then moved two days later. The
        visit's record used to become the period's, and the move carried it to
        the new date."""
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "143302.07")
        tire = Tire(vin=vehicle, position="FL", brand="Legacy")
        db_session.add(tire)
        await db_session.flush()
        tire_id = tire.id
        period = TireMountPeriod(
            tire_id=tire_id,
            position="FL",
            mounted_on=None,
            mounted_odometer_km=None,
            is_assumed=True,
            observed_active_on=date(2026, 9, 4),
        )
        db_session.add(period)
        await db_session.commit()
        period_id = period.id
        url = f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period_id}"

        used = await client.put(
            url,
            headers=auth_headers,
            json={"mounted_on": DAY.isoformat(), "mounted_odometer_km": "143302.07"},
        )
        assert used.status_code == 200, used.text
        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "143302.07")]

        later = DAY + timedelta(days=2)
        moved = await client.put(
            url,
            headers=auth_headers,
            json={"mounted_on": later.isoformat(), "mounted_odometer_km": "143302.07"},
        )
        assert moved.status_code == 200, moved.text
        assert await _rows(db_session, vehicle) == [
            _service_row(visit_id, "143302.07"),
            (
                later,
                Decimal("143302.07"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id),
                ODOMETER_SOURCE_TIRE_MOUNT,
            ),
        ]

    async def test_a_past_period_leaves_a_fuel_ups_reading_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Add past period with a mount date that matches an older fill-up. The
        mount's figure is higher, so it is recorded beside the fill-up's."""
        tire_id = await _create_and_mount(
            client, auth_headers, vehicle, "FL", mounted_on=DAY.isoformat()
        )
        fuel_day = date(2026, 1, 10)
        fuel_id = await _fuel(client, auth_headers, vehicle, fuel_day, "31000")
        (fuel_record,) = await _records(db_session, vehicle)
        fuel_row = (
            fuel_record.date,
            fuel_record.odometer_km,
            fuel_record.notes,
            fuel_record.source,
            fuel_record.fuel_record_id,
        )
        assert fuel_row == (
            fuel_day,
            Decimal("31000"),
            auto_sync_marker("fuel", fuel_id),
            "fuel",
            fuel_id,
        )

        added = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods",
            headers=auth_headers,
            json={
                "position": "FR",
                "mounted_on": fuel_day.isoformat(),
                "mounted_odometer_km": "31020",
                "dismounted_on": "2026-03-01",
                "dismounted_odometer_km": "36000",
            },
        )
        assert added.status_code == 201, added.text
        new_period_id = next(
            p["id"] for p in added.json()["mount_periods"] if p["position"] == "FR"
        )

        records = await _records(db_session, vehicle)
        assert [(r.date, r.odometer_km, r.notes, r.source, r.fuel_record_id) for r in records] == [
            fuel_row,
            (
                fuel_day,
                Decimal("31020"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, new_period_id),
                ODOMETER_SOURCE_TIRE_MOUNT,
                None,
            ),
            (
                date(2026, 3, 1),
                Decimal("36000"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, new_period_id),
                ODOMETER_SOURCE_TIRE_DISMOUNT,
                None,
            ),
        ]

    async def test_a_reading_leaves_a_livelink_reading_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        db_session.add(
            OdometerRecord(
                vin=vehicle,
                date=DAY,
                odometer_km=Decimal("61000.40"),
                source="livelink",
                notes="Auto-recorded from LiveLink (A6-Odometer)",
            )
        )
        await db_session.commit()
        stored = await client.post(
            f"/api/vehicles/{vehicle}/tires", headers=auth_headers, json={"vin": vehicle}
        )
        assert stored.status_code == 201, stored.text

        read = await client.post(
            f"/api/vehicles/{vehicle}/tires/{stored.json()['id']}/readings",
            headers=auth_headers,
            json={"recorded_at": DAY.isoformat(), "odometer_km": "61050", "tread_depth_mm": "6.5"},
        )
        assert read.status_code == 201, read.text

        assert await _rows(db_session, vehicle) == [
            (DAY, Decimal("61000.40"), "Auto-recorded from LiveLink (A6-Odometer)", "livelink"),
            (
                DAY,
                Decimal("61050"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE, stored.json()["id"]),
                ODOMETER_SOURCE_TIRE,
            ),
        ]

    async def test_a_set_fit_leaves_a_service_visits_reading_alone(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _create_and_mount(
            client, auth_headers, vehicle, "FL", mounted_on="2025-11-01"
        )
        off = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/dismount",
            headers=auth_headers,
            json={"dismounted_on": "2026-04-01"},
        )
        assert off.status_code == 200, off.text
        winter = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets", headers=auth_headers, json={"name": "Winter"}
        )
        assert winter.status_code == 201, winter.text
        set_id = winter.json()["id"]
        assigned = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}",
            headers=auth_headers,
            json={"set_id": set_id},
        )
        assert assigned.status_code == 200, assigned.text
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")

        fitted = await client.post(
            f"/api/vehicles/{vehicle}/tire-sets/{set_id}/mount",
            headers=auth_headers,
            json={"mounted_on": DAY.isoformat(), "odometer_km": "50012"},
        )
        assert fitted.status_code == 200, fitted.text

        assert await _rows(db_session, vehicle) == [
            _service_row(visit_id, "50000"),
            (
                DAY,
                Decimal("50012"),
                auto_sync_marker(ODOMETER_SOURCE_SET, set_id),
                ODOMETER_SOURCE_SET,
            ),
        ]

    async def test_a_tire_delete_leaves_the_reading_it_did_not_create(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The last step of the chain: a record a tire had taken over went with
        the tire when it was deleted."""
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )

        gone = await client.delete(f"/api/vehicles/{vehicle}/tires/{tire_id}", headers=auth_headers)
        assert gone.status_code == 204, gone.text

        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "50000")]


async def _tire_json(client: AsyncClient, headers, vin: str, tire_id: int) -> dict:
    listed = await client.get(f"/api/vehicles/{vin}/tires", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(t for t in listed.json()["tires"] if t["id"] == tire_id)


@pytest.mark.asyncio
class TestTheVehiclesLatestReadingKeepsUpWithTheTire:
    """A service visit and the mount it did, on one day: the vehicle's latest
    reading must not stay below the mount odometer, or the new tire's distance
    reads as the odometer running backwards until some later reading."""

    async def test_a_mount_above_the_days_reading_is_recorded_beside_it(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        (period_id,) = (
            (
                await db_session.execute(
                    select(TireMountPeriod.id).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        )

        assert await _rows(db_session, vehicle) == [
            _service_row(visit_id, "50000"),
            (
                DAY,
                Decimal("50012"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id),
                ODOMETER_SOURCE_TIRE_MOUNT,
            ),
        ]
        tire = await _tire_json(client, auth_headers, vehicle, tire_id)
        assert tire["distance_status"] == "complete"
        assert Decimal(tire["distance_km"]) == Decimal("0")

    async def test_a_mount_within_the_tolerance_of_the_days_reading_publishes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """50,000.1 km is within 3 ppm plus 0.01 km of 50,000: the same reading,
        so no near-duplicate record, and the distance is not a rollback."""
        assert Decimal("0.1") < Decimal("50000") * Decimal("3e-6") + Decimal("0.01")
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50000.1",
        )

        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "50000")]
        tire = await _tire_json(client, auth_headers, vehicle, tire_id)
        assert tire["distance_status"] == "complete"

    async def test_a_mount_below_the_days_reading_publishes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")
        await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="49990",
        )

        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "50000")]
        assert await latest_odometer_km_and_date(db_session, vehicle) == (Decimal("50000"), DAY)

    async def test_a_moved_period_drops_its_record_on_a_day_that_already_reads_higher(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The period owns its mount record on D. Moved to D+1, where LiveLink
        already read higher, the record is deleted rather than carried there;
        the LiveLink record is untouched. Moved again to D+2, a day with no
        record, the period owns nothing any more, so a new record is created
        there."""
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        (owned,) = await _records(db_session, vehicle)
        owned_id, marker = owned.id, owned.notes
        assert marker is not None and marker.startswith("[AUTO-SYNC from tire_mount #")
        next_day, day_after = DAY + timedelta(days=1), DAY + timedelta(days=2)
        livelink = (
            next_day,
            Decimal("50100"),
            "Auto-recorded from LiveLink (A6-Odometer)",
            "livelink",
        )
        db_session.add(
            OdometerRecord(
                vin=vehicle,
                date=next_day,
                odometer_km=Decimal("50100"),
                source="livelink",
                notes="Auto-recorded from LiveLink (A6-Odometer)",
            )
        )
        await db_session.commit()
        (period,) = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        )
        url = f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period.id}"

        moved = await client.put(
            url,
            headers=auth_headers,
            json={"mounted_on": next_day.isoformat(), "mounted_odometer_km": "50012"},
        )
        assert moved.status_code == 200, moved.text
        assert await _rows(db_session, vehicle) == [livelink]

        again = await client.put(
            url,
            headers=auth_headers,
            json={"mounted_on": day_after.isoformat(), "mounted_odometer_km": "50012"},
        )
        assert again.status_code == 200, again.text
        records = await _records(db_session, vehicle)
        assert [(r.date, r.odometer_km, r.notes, r.source) for r in records] == [
            livelink,
            (day_after, Decimal("50012"), marker, ODOMETER_SOURCE_TIRE_MOUNT),
        ]
        assert records[1].id != owned_id

    async def test_a_moved_period_is_the_latest_reading_beside_a_newer_lower_record(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The target day holds a lower record entered after the period's own.
        The period's record is created there again under its marker; being the
        day's highest reading, it is the vehicle's current one, so the open
        period's distance is not a rollback. The lower record is untouched."""
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        (owned,) = await _records(db_session, vehicle)
        owned_id, marker = owned.id, owned.notes
        next_day = DAY + timedelta(days=1)
        visit_id = await _service_visit(client, auth_headers, vehicle, next_day, "50000")
        (period,) = (
            (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        )

        moved = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period.id}",
            headers=auth_headers,
            json={"mounted_on": next_day.isoformat(), "mounted_odometer_km": "50012"},
        )
        assert moved.status_code == 200, moved.text

        records = await _records(db_session, vehicle)
        assert [(r.date, r.odometer_km, r.notes, r.source) for r in records] == [
            (
                next_day,
                Decimal("50000"),
                auto_sync_marker("service_visit", visit_id),
                "service_visit",
            ),
            (next_day, Decimal("50012"), marker, ODOMETER_SOURCE_TIRE_MOUNT),
        ]
        assert records[1].id != owned_id
        assert await latest_odometer_km_and_date(db_session, vehicle) == (
            Decimal("50012"),
            next_day,
        )
        tire = await _tire_json(client, auth_headers, vehicle, tire_id)
        assert tire["distance_status"] == "complete"

    async def test_an_edited_mount_stays_the_days_latest_beside_a_newer_lower_record(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Same day, no move: a lower manual entry was added after the mount, and
        the mount odometer is then corrected upwards. The period's record is
        created again under its marker, and the vehicle's current reading, the
        day's highest, follows the correction."""
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        (owned,) = await _records(db_session, vehicle)
        marker = owned.notes
        manual = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": DAY.isoformat(), "odometer_km": "50000", "notes": "hand"},
        )
        assert manual.status_code == 201, manual.text
        (period_id,) = (
            (
                await db_session.execute(
                    select(TireMountPeriod.id).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        )

        edited = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": DAY.isoformat(), "mounted_odometer_km": "50020"},
        )
        assert edited.status_code == 200, edited.text

        assert await _rows(db_session, vehicle) == [
            (DAY, Decimal("50000"), "hand", "manual"),
            (DAY, Decimal("50020"), marker, ODOMETER_SOURCE_TIRE_MOUNT),
        ]
        assert await latest_odometer_km_and_date(db_session, vehicle) == (Decimal("50020"), DAY)


@pytest.mark.asyncio
class TestATireEventStillKeepsItsOwnRecord:
    async def test_a_mount_on_a_free_day_creates_its_record_and_an_edit_updates_it_in_place(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50000",
        )
        (period_id,) = [
            p.id
            for p in (
                await db_session.execute(
                    select(TireMountPeriod).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        ]
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id)
        (created,) = await _records(db_session, vehicle)
        created_id = created.id
        assert (created.date, created.odometer_km, created.notes) == (DAY, Decimal("50000"), marker)
        # A later row on another day, so a delete and recreate of the mount's
        # record could not reuse its id (SQLite hands out the highest plus one).
        later = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": "2026-07-01", "odometer_km": "50900", "notes": "hand"},
        )
        assert later.status_code == 201, later.text

        edited = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": DAY.isoformat(), "mounted_odometer_km": "50040"},
        )
        assert edited.status_code == 200, edited.text

        updated, _hand = await _records(db_session, vehicle)
        assert (updated.id, updated.date, updated.odometer_km, updated.notes) == (
            created_id,
            DAY,
            Decimal("50040"),
            marker,
        )

    async def test_a_second_reading_updates_its_own_record_beside_a_newer_one(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The tire's own record is found by its marker, not by being the day's
        newest: a manual entry added after the first reading does not stop the
        tire's own figure from being corrected."""
        stored = await client.post(
            f"/api/vehicles/{vehicle}/tires", headers=auth_headers, json={"vin": vehicle}
        )
        assert stored.status_code == 201, stored.text
        tire_id = stored.json()["id"]
        readings = f"/api/vehicles/{vehicle}/tires/{tire_id}/readings"
        first = await client.post(
            readings,
            headers=auth_headers,
            json={"recorded_at": DAY.isoformat(), "odometer_km": "50000", "tread_depth_mm": "7.0"},
        )
        assert first.status_code == 201, first.text
        manual = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": DAY.isoformat(), "odometer_km": "50100", "notes": "hand"},
        )
        assert manual.status_code == 201, manual.text

        second = await client.post(
            readings,
            headers=auth_headers,
            json={"recorded_at": DAY.isoformat(), "odometer_km": "50060", "pressure_kpa": "230"},
        )
        assert second.status_code == 201, second.text

        assert await _rows(db_session, vehicle) == [
            (
                DAY,
                Decimal("50060"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id),
                ODOMETER_SOURCE_TIRE,
            ),
            (DAY, Decimal("50100"), "hand", "manual"),
        ]


@pytest.mark.asyncio
class TestATiresRowKeepsTheDaysHighest:
    """Every reading of a tire publishes under the tire's marker, so one row stands for all of
    them that day. A lower one logged later leaves it alone (#224). A period's row holds one
    event, and the editor still corrects it down."""

    async def test_a_lower_reading_of_the_tire_that_day_leaves_its_row(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        stored = await client.post(
            f"/api/vehicles/{vehicle}/tires", headers=auth_headers, json={"vin": vehicle}
        )
        assert stored.status_code == 201, stored.text
        tire_id = stored.json()["id"]
        await _read_odometer(client, auth_headers, vehicle, tire_id, "50100")
        logged = await _read_odometer(client, auth_headers, vehicle, tire_id, "50000")

        assert sorted(Decimal(r["odometer_km"]) for r in logged["readings"]) == [
            Decimal("50000"),
            Decimal("50100"),
        ]
        assert await _rows(db_session, vehicle) == [
            (
                DAY,
                Decimal("50100"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id),
                ODOMETER_SOURCE_TIRE,
            )
        ]
        assert await latest_odometer_km_and_date(db_session, vehicle) == (Decimal("50100"), DAY)

    async def test_the_period_editor_still_corrects_a_mount_down(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50100",
        )
        (period_id,) = (
            (
                await db_session.execute(
                    select(TireMountPeriod.id).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        )

        edited = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": DAY.isoformat(), "mounted_odometer_km": "50000"},
        )
        assert edited.status_code == 200, edited.text

        assert await _rows(db_session, vehicle) == [
            (
                DAY,
                Decimal("50000"),
                auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period_id),
                ODOMETER_SOURCE_TIRE_MOUNT,
            )
        ]


@pytest.mark.asyncio
class TestNonTireSourcesKeepOneReadingPerDay:
    async def test_a_second_fill_up_on_a_day_takes_over_the_first_ones_reading(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        first = await _fuel(client, auth_headers, vehicle, DAY, "70000")
        assert [(r.notes, r.fuel_record_id) for r in await _records(db_session, vehicle)] == [
            (auto_sync_marker("fuel", first), first)
        ]

        second = await _fuel(client, auth_headers, vehicle, DAY, "70300")

        records = await _records(db_session, vehicle)
        assert [(r.date, r.odometer_km, r.notes, r.source, r.fuel_record_id) for r in records] == [
            (DAY, Decimal("70300"), auto_sync_marker("fuel", second), "fuel", second)
        ]
        assert not {r.source for r in records} & TIRE_SOURCES

    async def test_a_fill_up_edit_updates_its_own_row_beside_a_newer_manual_one(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """A source's own row is found by its marker first: a manual entry added
        later that day does not stop the fill-up's corrected figure landing."""
        fuel_id = await _fuel(client, auth_headers, vehicle, DAY, "70000")
        manual = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": DAY.isoformat(), "odometer_km": "70100", "notes": "hand"},
        )
        assert manual.status_code == 201, manual.text

        edited = await client.put(
            f"/api/vehicles/{vehicle}/fuel/{fuel_id}",
            headers=auth_headers,
            json={"odometer_km": "70050"},
        )
        assert edited.status_code == 200, edited.text

        assert await _rows(db_session, vehicle) == [
            (DAY, Decimal("70050"), auto_sync_marker("fuel", fuel_id), "fuel"),
            (DAY, Decimal("70100"), "hand", "manual"),
        ]


@pytest.mark.asyncio
class TestNonTireSourcesNeverTakeOverATiresRow:
    """Fuel, DEF and service visits take over the day's automatic row, but not
    one a tire event wrote: that row is moved and deleted by the tire's own
    marker, and a service visit that re-marked it removed the tire's reading."""

    async def test_resaving_a_same_day_service_visit_keeps_the_tires_row(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        before = await _rows(db_session, vehicle)
        assert before[0] == _service_row(visit_id, "50000")
        _own_row(before, "50012", ODOMETER_SOURCE_TIRE_MOUNT)

        saved = await client.put(
            f"/api/vehicles/{vehicle}/service-visits/{visit_id}",
            headers=auth_headers,
            json={"notes": "invoice attached"},
        )
        assert saved.status_code == 200, saved.text

        assert await _rows(db_session, vehicle) == before
        tire = await _tire_json(client, auth_headers, vehicle, tire_id)
        assert tire["distance_status"] == "complete"

    async def test_a_new_service_visit_beside_a_tires_row_creates_its_own(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        (tire_row,) = await _rows(db_session, vehicle)

        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "50000")

        assert await _rows(db_session, vehicle) == [tire_row, _service_row(visit_id, "50000")]


@pytest.mark.asyncio
class TestTheOwnedMoveOntoAnOlderHigherRecord:
    async def test_a_period_moved_onto_an_older_higher_record_drops_its_own(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The LiveLink record on D+1 is older than the mount's own record, so
        only its higher figure, not a newer id, says the day already reads at
        least as high: the owned record is deleted, the LiveLink record kept."""
        next_day = DAY + timedelta(days=1)
        livelink = (
            next_day,
            Decimal("50100"),
            "Auto-recorded from LiveLink (A6-Odometer)",
            "livelink",
        )
        db_session.add(
            OdometerRecord(
                vin=vehicle,
                date=next_day,
                odometer_km=Decimal("50100"),
                source="livelink",
                notes="Auto-recorded from LiveLink (A6-Odometer)",
            )
        )
        await db_session.commit()
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="50012",
        )
        (period_id,) = (
            (
                await db_session.execute(
                    select(TireMountPeriod.id).where(TireMountPeriod.tire_id == tire_id)
                )
            )
            .scalars()
            .all()
        )

        moved = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": next_day.isoformat(), "mounted_odometer_km": "50012"},
        )
        assert moved.status_code == 200, moved.text

        assert await _rows(db_session, vehicle) == [livelink]


@pytest.mark.asyncio
class TestAZeroDistanceKeepsItsScale:
    async def test_a_mount_within_the_tolerance_above_the_days_reading_reads_zero_point_zero_zero(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """89,044 mi as a service visit saved before the exact mile stored it,
        and the mount typed today: one reading, so no tire row, and the clamp
        inside the tolerance is the tire's only contribution. It serialises
        like every other distance, to the hundredth."""
        visit_id = await _service_visit(client, auth_headers, vehicle, DAY, "143302.07")
        tire_id = await _create_and_mount(
            client,
            auth_headers,
            vehicle,
            "FL",
            mounted_on=DAY.isoformat(),
            mounted_odometer_km="143302.43",
        )
        assert await _rows(db_session, vehicle) == [_service_row(visit_id, "143302.07")]

        tire = await _tire_json(client, auth_headers, vehicle, tire_id)
        assert tire["distance_status"] == "complete"
        assert tire["distance_km"] == "0.00"
