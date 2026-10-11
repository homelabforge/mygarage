"""Deleting a tread reading: the way out of a reading logged with the wrong odometer.

Log Reading does not validate against the mount history, and the writers that
do (mount, dismount, retire, rotate, set fit, the period editor) refuse any
write that leaves a period contradicting a reading. So one mistyped odometer
made every honest write to that tire a 409 with nothing able to remove the
reading. The refusal now names the reading, and this route removes it.

A reading leaves three things behind that the delete has to account for: the
tread and pressure it may have copied onto the tire, the vehicle odometer
record it published, and the low-tread reminder the copied tread may have
raised.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.tire import Tire, TireReading
from app.models.vehicle import Vehicle
from app.schemas.tire import TireCreate, TireCreateAndMountRequest, TireReadingCreate
from app.services.tire_service import ODOMETER_SOURCE_TIRE, TireService
from app.utils.odometer_sync import auto_sync_marker


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle for this test alone: corners are claimable once per vehicle,
    and the suite shares one database."""
    vin = f"TIREDEL{uuid.uuid4().hex[:10].upper()}"[:17]
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Reading delete",
            vehicle_type="Car",
            year=2020,
            make="Honda",
            model="Fit",
        )
    )
    await db_session.commit()
    yield vin
    await db_session.execute(delete(Reminder).where(Reminder.vin == vin))
    await db_session.execute(delete(OdometerRecord).where(OdometerRecord.vin == vin))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _tire(
    client: AsyncClient, headers, vin: str, position: str | None = "FL", **extra
) -> int:
    """Create a tire at a corner (mounted 2026-01-01 at 10,000 km) or in storage."""
    if position is None:
        made = await client.post(
            f"/api/vehicles/{vin}/tires", headers=headers, json={"vin": vin, **extra}
        )
    else:
        made = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=headers,
            json={
                "vin": vin,
                "position": position,
                "mounted_on": "2026-01-01",
                "mounted_odometer_km": "10000",
                **extra,
            },
        )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def _reading(client: AsyncClient, headers, vin: str, tire_id: int, **body) -> int:
    """Log a reading and return its id: the one the response did not have before."""
    before = await _reading_ids(client, headers, vin, tire_id)
    logged = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings", headers=headers, json=body
    )
    assert logged.status_code == 201, logged.text
    (new_id,) = {r["id"] for r in logged.json()["readings"]} - before
    return new_id


async def _tire_body(client: AsyncClient, headers, vin: str, tire_id: int) -> dict:
    listed = await client.get(f"/api/vehicles/{vin}/tires", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(t for t in listed.json()["tires"] if t["id"] == tire_id)


async def _reading_ids(client: AsyncClient, headers, vin: str, tire_id: int) -> set[int]:
    return {r["id"] for r in (await _tire_body(client, headers, vin, tire_id))["readings"]}


def _url(vin: str, tire_id: int, reading_id: int) -> str:
    return f"/api/vehicles/{vin}/tires/{tire_id}/readings/{reading_id}"


def _dec(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


async def _records(db_session, vin: str) -> list[tuple[date, Decimal, str | None]]:
    db_session.expire_all()
    rows = (
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
    return [(r.date, r.odometer_km, r.notes) for r in rows]


async def _record_ids(db_session, vin: str) -> list[int]:
    db_session.expire_all()
    rows = await db_session.execute(
        select(OdometerRecord.id).where(OdometerRecord.vin == vin).order_by(OdometerRecord.id)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
class TestTheWayOutOfAMistypedReading:
    async def test_a_dismount_refused_by_a_typo_succeeds_once_the_reading_is_deleted(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        ids = {
            pos: await _tire(client, auth_headers, vehicle, pos) for pos in ("FL", "FR", "RL", "RR")
        }
        typo = await _reading(
            client,
            auth_headers,
            vehicle,
            ids["FL"],
            recorded_at="2026-03-01",
            odometer_km="150000",
            tread_depth_mm="7.0",
        )
        dismount = {"dismounted_on": "2026-06-01", "dismounted_odometer_km": "20000"}
        base = f"/api/vehicles/{vehicle}/tires/{ids['FL']}"

        refused = await client.post(f"{base}/dismount", headers=auth_headers, json=dismount)
        assert refused.status_code == 409, refused.text
        # The default test user is imperial, so the refusal renders in
        # miles: 150,000 km / 1.609344 km per mile, to one decimal place.
        assert refused.json()["detail"] == (
            "The FL period mounted 2026-01-01 contradicts the reading dated 2026-03-01 at "
            "93,205.7 mi: the vehicle's odometer would have to run backwards. If that reading "
            "is wrong, delete it from the tire's history."
        )

        gone = await client.delete(_url(vehicle, ids["FL"], typo), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert gone.content == b""

        again = await client.post(f"{base}/dismount", headers=auth_headers, json=dismount)
        assert again.status_code == 200, again.text
        assert again.json()["readings"] == []
        (period,) = again.json()["mount_periods"]
        assert period["dismounted_on"] == "2026-06-01"


@pytest.mark.asyncio
class TestTheTiresTreadAndPressure:
    async def test_deleting_the_newest_reading_puts_back_the_one_before(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        newest = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-03-10", tread_depth_mm="6.0"
        )
        assert _dec(
            (await _tire_body(client, auth_headers, vehicle, tire_id))["tread_depth_mm"]
        ) == Decimal("6.0")

        gone = await client.delete(_url(vehicle, tire_id, newest), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert _dec(
            (await _tire_body(client, auth_headers, vehicle, tire_id))["tread_depth_mm"]
        ) == Decimal("8.0")

    async def test_deleting_the_only_reading_leaves_no_tread_rather_than_an_old_one(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Add Tire stored 9.0 on the tire and created no reading; the reading
        replaced it. Nothing on file still measures 9.0 as of any date, so the
        honest value is unknown."""
        tire_id = await _tire(client, auth_headers, vehicle, None, tread_depth_mm="9.0")
        only = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )
        gone = await client.delete(_url(vehicle, tire_id, only), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert (await _tire_body(client, auth_headers, vehicle, tire_id))["tread_depth_mm"] is None

    async def test_a_tread_and_pressure_edited_after_the_reading_are_left_alone(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-01-10",
            tread_depth_mm="8.0",
            pressure_kpa="240",
        )
        newest = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-02-01",
            tread_depth_mm="7.0",
            pressure_kpa="230",
        )
        edited = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}",
            headers=auth_headers,
            json={"tread_depth_mm": "6.5", "pressure_kpa": "220"},
        )
        assert edited.status_code == 200, edited.text
        gone = await client.delete(_url(vehicle, tire_id, newest), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        body = await _tire_body(client, auth_headers, vehicle, tire_id)
        assert (_dec(body["tread_depth_mm"]), _dec(body["pressure_kpa"])) == (
            Decimal("6.5"),
            Decimal("220"),
        )

    async def test_a_pressure_only_reading_takes_only_its_pressure_with_it(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        leak = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", pressure_kpa="180"
        )
        gone = await client.delete(_url(vehicle, tire_id, leak), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        body = await _tire_body(client, auth_headers, vehicle, tire_id)
        assert _dec(body["tread_depth_mm"]) == Decimal("8.0")
        assert body["pressure_kpa"] is None


@pytest.mark.asyncio
class TestTheOdometerRecordTheReadingPublished:
    DAY = date(2026, 2, 1)

    async def test_the_readings_own_record_goes_with_it(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-02-01",
            odometer_km="11000",
            tread_depth_mm="7.0",
        )
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), marker)]
        gone = await client.delete(_url(vehicle, tire_id, reading), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await _records(db_session, vehicle) == []

    async def test_a_manual_record_on_the_same_day_survives(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        manual = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": "2026-02-01", "odometer_km": "11000", "notes": "hand"},
        )
        assert manual.status_code == 201, manual.text
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-02-01",
            odometer_km="11000",
            tread_depth_mm="7.0",
        )
        gone = await client.delete(_url(vehicle, tire_id, reading), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), "hand")]

    async def test_a_record_another_reading_of_the_tire_still_backs_survives(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Two readings of one tire on one day at one odometer share one record:
        the second publish updated the first's row in place."""
        tire_id = await _tire(client, auth_headers, vehicle, None)
        body = {"recorded_at": "2026-02-01", "odometer_km": "11000"}
        tread = await _reading(client, auth_headers, vehicle, tire_id, tread_depth_mm="7.0", **body)
        pressure = await _reading(
            client, auth_headers, vehicle, tire_id, pressure_kpa="230", **body
        )
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), marker)]

        first = await client.delete(_url(vehicle, tire_id, tread), headers=auth_headers)
        assert first.status_code == 204, first.text
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), marker)]
        second = await client.delete(_url(vehicle, tire_id, pressure), headers=auth_headers)
        assert second.status_code == 204, second.text
        assert await _records(db_session, vehicle) == []

    async def test_a_record_a_later_reading_on_the_same_day_rewrote_survives(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The same tire read twice on one day at two odometers: the second
        publish rewrote the first's row, so the row holds the second value and
        is not the first reading's to take."""
        tire_id = await _tire(client, auth_headers, vehicle, None)
        morning = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-02-01",
            odometer_km="11000",
            tread_depth_mm="7.0",
        )
        await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-02-01",
            odometer_km="11050",
            pressure_kpa="230",
        )
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11050"), marker)]
        gone = await client.delete(_url(vehicle, tire_id, morning), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11050"), marker)]

    async def test_a_record_another_tires_reading_published_survives(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """The second tire read that day found a record and published nothing,
        so the day's record is the first tire's, at the same date and
        odometer as the reading being deleted, and not that reading's to take."""
        mine = await _tire(client, auth_headers, vehicle, None)
        theirs = await _tire(client, auth_headers, vehicle, None)
        body = {"recorded_at": "2026-02-01", "odometer_km": "11000", "tread_depth_mm": "7.0"}
        await _reading(client, auth_headers, vehicle, theirs, **body)
        reading = await _reading(client, auth_headers, vehicle, mine, **body)
        theirs_marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, theirs)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), theirs_marker)]
        # A later row on another day, so a delete and republish of the day's
        # record cannot hand the new row the old id (SQLite reuses the highest).
        later = await client.post(
            f"/api/vehicles/{vehicle}/odometer",
            headers=auth_headers,
            json={"vin": vehicle, "date": "2026-02-20", "odometer_km": "11800", "notes": "hand"},
        )
        assert later.status_code == 201, later.text
        ids_before = await _record_ids(db_session, vehicle)

        gone = await client.delete(_url(vehicle, mine, reading), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await _records(db_session, vehicle) == [
            (self.DAY, Decimal("11000"), theirs_marker),
            (date(2026, 2, 20), Decimal("11800"), "hand"),
        ]
        # The same row, not a delete followed by a republish that looks alike.
        assert await _record_ids(db_session, vehicle) == ids_before


_SESSION_DAY = date(2026, 3, 1)


@pytest.mark.asyncio
class TestTheDaysRecordOtherReadingsStillSupport:
    """A reading publishes the vehicle's odometer only when no record on its day
    reads at or above it, so after a Log Reading session at one odometer the
    day's one record carries the FIRST reading's marker and value while every
    other reading of that day stands behind the same kilometres. Deleting the reading whose marker it
    carries must leave the day with a record, or the vehicle's latest odometer
    falls back to an older day and every mounted tire reads a confident
    too-low distance.

    On a session that does not autoflush, as every request session is: the
    record's delete has to reach the database before the republish looks for
    a same-day row by SQL.
    """

    @staticmethod
    def _maker(test_engine) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    @staticmethod
    async def _day(
        maker: async_sessionmaker[AsyncSession], vin: str, day: date
    ) -> list[tuple[Decimal, str | None]]:
        async with maker() as db:
            rows = (
                (
                    await db.execute(
                        select(OdometerRecord)
                        .where(OdometerRecord.vin == vin, OdometerRecord.date == day)
                        .order_by(OdometerRecord.id)
                    )
                )
                .scalars()
                .all()
            )
            return [(r.odometer_km, r.notes) for r in rows]

    @staticmethod
    async def _log(maker: async_sessionmaker[AsyncSession], vin: str, tire_id: int, **body) -> int:
        """Log a reading and return its id: ids increase, so it is the tire's highest."""
        async with maker() as db:
            logged = await TireService(db).add_reading(
                vin, tire_id, TireReadingCreate(**body), None
            )
        return max(r.id for r in logged.readings)

    async def test_four_tires_read_on_one_day_keep_the_days_record_when_the_first_is_deleted(
        self, test_engine, vehicle
    ):
        maker = self._maker(test_engine)
        ids: dict[str, int] = {}
        for position in ("FL", "FR", "RL", "RR"):
            async with maker() as db:
                made = await TireService(db).create_and_mount(
                    vehicle,
                    TireCreateAndMountRequest(
                        vin=vehicle,
                        position=position,
                        brand=position,
                        mounted_on=date(2026, 1, 1),
                        mounted_odometer_km=Decimal("10000"),
                    ),
                    None,
                )
            ids[position] = made.id
        readings = {
            position: await self._log(
                maker,
                vehicle,
                ids[position],
                recorded_at=_SESSION_DAY,
                odometer_km=Decimal("15000"),
                tread_depth_mm=Decimal("7.0"),
            )
            for position in ("FL", "FR", "RL", "RR")
        }

        async def fl_distance() -> Decimal | None:
            async with maker() as db:
                listed = await TireService(db).list_tires(vehicle, None)
            return next(t for t in listed.tires if t.id == ids["FL"]).distance_km

        assert await self._day(maker, vehicle, _SESSION_DAY) == [
            (Decimal("15000"), auto_sync_marker(ODOMETER_SOURCE_TIRE, ids["FL"]))
        ]
        assert await fl_distance() == Decimal("5000")

        async with maker() as db:
            await TireService(db).delete_reading(vehicle, ids["FL"], readings["FL"], None)

        (only,) = await self._day(maker, vehicle, _SESSION_DAY)
        assert only[0] == Decimal("15000")
        assert only[1] in {
            auto_sync_marker(ODOMETER_SOURCE_TIRE, ids[position]) for position in ("FR", "RL", "RR")
        }
        assert await fl_distance() == Decimal("5000")

    async def test_deleting_the_later_of_two_same_day_readings_puts_the_earlier_back(
        self, test_engine, vehicle
    ):
        maker = self._maker(test_engine)
        async with maker() as db:
            tire_id = (
                await TireService(db).create_tire(
                    vehicle, TireCreate(vin=vehicle, brand="Twice"), None
                )
            ).id
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        await self._log(
            maker,
            vehicle,
            tire_id,
            recorded_at=_SESSION_DAY,
            odometer_km=Decimal("11000"),
            tread_depth_mm=Decimal("7.0"),
        )
        later = await self._log(
            maker,
            vehicle,
            tire_id,
            recorded_at=_SESSION_DAY,
            odometer_km=Decimal("11050"),
            pressure_kpa=Decimal("230"),
        )
        assert await self._day(maker, vehicle, _SESSION_DAY) == [(Decimal("11050"), marker)]

        async with maker() as db:
            await TireService(db).delete_reading(vehicle, tire_id, later, None)

        assert await self._day(maker, vehicle, _SESSION_DAY) == [(Decimal("11000"), marker)]

    async def test_the_highest_reading_left_that_day_backs_the_record(self, test_engine, vehicle):
        # B and C published nothing under A's 11,050 km. With A's reading gone, B's 11,020
        # is the day's highest, though C's 11,000 was logged last (#224).
        maker = self._maker(test_engine)
        ids: list[int] = []
        for brand in ("A", "B", "C"):
            async with maker() as db:
                made = await TireService(db).create_tire(
                    vehicle, TireCreate(vin=vehicle, brand=brand), None
                )
            ids.append(made.id)
        a, b, c = ids
        readings = [
            await self._log(
                maker,
                vehicle,
                tire_id,
                recorded_at=_SESSION_DAY,
                odometer_km=Decimal(km),
                tread_depth_mm=Decimal("7.0"),
            )
            for tire_id, km in ((a, "11050"), (b, "11020"), (c, "11000"))
        ]
        assert await self._day(maker, vehicle, _SESSION_DAY) == [
            (Decimal("11050"), auto_sync_marker(ODOMETER_SOURCE_TIRE, a))
        ]

        async with maker() as db:
            await TireService(db).delete_reading(vehicle, a, readings[0], None)

        assert await self._day(maker, vehicle, _SESSION_DAY) == [
            (Decimal("11020"), auto_sync_marker(ODOMETER_SOURCE_TIRE, b))
        ]


@pytest.mark.asyncio
class TestTheLowTreadReminder:
    async def test_a_reminder_raised_by_the_deleted_reading_completes(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None, min_tread_mm="2.0")
        await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="7.0"
        )
        low = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-03-10", tread_depth_mm="1.5"
        )

        async def statuses() -> list[str]:
            db_session.expire_all()
            rows = (
                await db_session.execute(
                    select(Reminder.status).where(
                        Reminder.tire_id == tire_id, Reminder.source == "low_tread"
                    )
                )
            ).all()
            return [status for (status,) in rows]

        assert await statuses() == ["pending"]
        gone = await client.delete(_url(vehicle, tire_id, low), headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await statuses() == ["done"]
        assert _dec(
            (await _tire_body(client, auth_headers, vehicle, tire_id))["tread_depth_mm"]
        ) == Decimal("7.0")


@pytest.mark.asyncio
class TestWhoMayDeleteWhich:
    async def test_a_reading_of_another_tire_or_none_at_all_is_not_found(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        mine = await _tire(client, auth_headers, vehicle, None)
        theirs = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, theirs, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )
        wrong_tire = await client.delete(_url(vehicle, mine, reading), headers=auth_headers)
        assert wrong_tire.status_code == 404, wrong_tire.text
        missing = await client.delete(_url(vehicle, mine, 99_999_999), headers=auth_headers)
        assert missing.status_code == 404, missing.text
        db_session.expire_all()
        assert (await db_session.get(TireReading, reading)) is not None

    async def test_a_read_share_is_refused_and_a_write_share_is_not(
        self,
        client: AsyncClient,
        owned_vehicle,
        owner_headers,
        reader_headers,
        writer_headers,
        db_session,
    ):
        vin = owned_vehicle.vin
        tire_id = await _tire(client, owner_headers, vin, None)
        try:
            reading = await _reading(
                client, owner_headers, vin, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
            )
            refused = await client.delete(_url(vin, tire_id, reading), headers=reader_headers)
            assert refused.status_code == 403, refused.text
            assert reading in await _reading_ids(client, owner_headers, vin, tire_id)
            allowed = await client.delete(_url(vin, tire_id, reading), headers=writer_headers)
            assert allowed.status_code == 204, allowed.text
        finally:
            await db_session.execute(delete(Tire).where(Tire.id == tire_id))
            await db_session.commit()
