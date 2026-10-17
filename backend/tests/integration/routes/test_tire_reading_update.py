"""Correcting a tire reading in place (#225), instead of deleting it and logging it again.

The report: a gauge's 0.346 in typed as 32nds stored 0.27 mm, the tire read
bald, and Delete was the only repair. An edit carries along what the reading
left behind (the tire's tread and pressure, its usage rows, the low-tread
reminder) and is judged against the mount history on each axis the vehicle tracks.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, func, select

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.tire import Tire, TireReading
from app.models.vehicle import Vehicle
from app.services.tire_service import ODOMETER_SOURCE_TIRE
from app.utils.odometer_sync import auto_sync_marker

MakeVehicle = Callable[..., Awaitable[str]]


@pytest_asyncio.fixture
async def make_vehicle(db_session, test_user) -> AsyncIterator[MakeVehicle]:
    """Vehicles for one test: corners are claimable once, and the suite shares one database."""
    made: list[str] = []

    async def _make(usage_unit: str = "distance", secondary: bool = False) -> str:
        vin = f"TRU{uuid.uuid4().hex[:14].upper()}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="Reading update",
                vehicle_type="Car",
                year=2020,
                make="Honda",
                model="Fit",
                usage_unit=usage_unit,
                secondary_usage_enabled=secondary,
            )
        )
        await db_session.commit()
        made.append(vin)
        return vin

    yield _make
    # A failed test can leave the session mid-transaction.
    await db_session.rollback()
    for vin in made:
        await db_session.execute(delete(Reminder).where(Reminder.vin == vin))
        await db_session.execute(delete(OdometerRecord).where(OdometerRecord.vin == vin))
        await db_session.execute(delete(HoursRecord).where(HoursRecord.vin == vin))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest_asyncio.fixture
async def vehicle(make_vehicle: MakeVehicle) -> str:
    """A distance-only vehicle."""
    return await make_vehicle()


async def _tire(
    client: AsyncClient, headers, vin: str, position: str | None = "FL", **extra
) -> int:
    """A tire mounted on 2026-01-01 at 10,000 km unless `extra` says otherwise, or a stored one."""
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


async def _tire_body(client: AsyncClient, headers, vin: str, tire_id: int) -> dict:
    listed = await client.get(f"/api/vehicles/{vin}/tires", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(t for t in listed.json()["tires"] if t["id"] == tire_id)


async def _reading(client: AsyncClient, headers, vin: str, tire_id: int, **body) -> int:
    """Log a reading and return its id: the one the tire didn't have before."""
    before = {r["id"] for r in (await _tire_body(client, headers, vin, tire_id))["readings"]}
    logged = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings", headers=headers, json=body
    )
    assert logged.status_code == 201, logged.text
    (new_id,) = {r["id"] for r in logged.json()["readings"]} - before
    return new_id


def _url(vin: str, tire_id: int, reading_id: int) -> str:
    return f"/api/vehicles/{vin}/tires/{tire_id}/readings/{reading_id}"


async def _put(
    client: AsyncClient, headers, vin: str, tire_id: int, reading_id: int, **body
) -> Response:
    return await client.put(_url(vin, tire_id, reading_id), headers=headers, json=body)


async def _set_tire(client: AsyncClient, headers, vin: str, tire_id: int, **body) -> None:
    """A value set on the tire by hand, through Edit Tire."""
    edited = await client.put(f"/api/vehicles/{vin}/tires/{tire_id}", headers=headers, json=body)
    assert edited.status_code == 200, edited.text


def _dec(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _reading_in(body: dict, reading_id: int) -> dict:
    return next(r for r in body["readings"] if r["id"] == reading_id)


async def _low_tread_statuses(db_session, tire_id: int) -> list[str]:
    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(Reminder.status).where(
                Reminder.tire_id == tire_id, Reminder.source == "low_tread"
            )
        )
    ).all()
    return [status for (status,) in rows]


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


async def _hours_rows(db_session, vin: str) -> list[tuple[date, Decimal, str | None]]:
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


async def _odometer_count(db_session, vin: str) -> int:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(func.count()).select_from(OdometerRecord).where(OdometerRecord.vin == vin)
        )
    ).scalar_one()


@pytest.mark.asyncio
class TestTheReportedTypo:
    async def test_a_bald_reading_corrected_to_its_real_depth_fixes_the_tire_and_its_reminder(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """0.346/32 in (0.27 mm) corrected to 11/32 in (8.73 mm), in place."""
        tire_id = await _tire(client, auth_headers, vehicle, min_tread_mm="1.6")
        typo = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-10-11",
            tread_depth_mm="0.27",
            pressure_kpa="448",
        )
        tire = await _tire_body(client, auth_headers, vehicle, tire_id)
        assert _dec(tire["tread_depth_mm"]) == Decimal("0.27")
        assert await _low_tread_statuses(db_session, tire_id) == ["pending"]

        fixed = await _put(client, auth_headers, vehicle, tire_id, typo, tread_depth_mm="8.73")

        assert fixed.status_code == 200, fixed.text
        body = fixed.json()
        assert [r["id"] for r in body["readings"]] == [typo]
        assert _dec(_reading_in(body, typo)["tread_depth_mm"]) == Decimal("8.73")
        # Untouched by a body that didn't name it.
        assert _dec(_reading_in(body, typo)["pressure_kpa"]) == Decimal("448")
        assert _dec(body["tread_depth_mm"]) == Decimal("8.73")
        assert body["below_threshold"] is False
        assert await _low_tread_statuses(db_session, tire_id) == ["done"]


@pytest.mark.asyncio
class TestTheTiresTreadAndPressure:
    async def test_a_reading_moved_past_the_newest_takes_over_the_tire(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        older = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-03-10", tread_depth_mm="6.0"
        )
        tire = await _tire_body(client, auth_headers, vehicle, tire_id)
        assert _dec(tire["tread_depth_mm"]) == Decimal("6.0")

        moved = await _put(client, auth_headers, vehicle, tire_id, older, recorded_at="2026-04-10")

        assert moved.status_code == 200, moved.text
        assert _dec(moved.json()["tread_depth_mm"]) == Decimal("8.0")

    async def test_the_newest_reading_moved_back_hands_the_tire_to_the_one_now_newest(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-10", tread_depth_mm="8.0"
        )
        newest = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-03-10", tread_depth_mm="6.0"
        )

        moved = await _put(client, auth_headers, vehicle, tire_id, newest, recorded_at="2026-01-10")

        assert moved.status_code == 200, moved.text
        assert _dec(moved.json()["tread_depth_mm"]) == Decimal("8.0")

    async def test_a_value_set_on_the_tire_survives_an_edit_that_changes_no_measure(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        await _set_tire(client, auth_headers, vehicle, tire_id, tread_depth_mm="7.5")

        # The editor resends every field; only the notes differ.
        notes_only = await _put(
            client,
            auth_headers,
            vehicle,
            tire_id,
            reading,
            recorded_at="2026-01-10",
            tread_depth_mm="8.00",
            notes="front left",
        )

        assert notes_only.status_code == 200, notes_only.text
        assert _dec(notes_only.json()["tread_depth_mm"]) == Decimal("7.5")
        assert _reading_in(notes_only.json(), reading)["notes"] == "front left"

    async def test_a_corrected_newest_reading_replaces_a_value_set_on_the_tire(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """What logging the corrected reading fresh would have done."""
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        await _set_tire(client, auth_headers, vehicle, tire_id, tread_depth_mm="7.5")

        corrected = await _put(
            client, auth_headers, vehicle, tire_id, reading, tread_depth_mm="6.5"
        )

        assert corrected.status_code == 200, corrected.text
        assert _dec(corrected.json()["tread_depth_mm"]) == Decimal("6.5")

    async def test_the_older_of_two_same_day_readings_does_not_take_over_a_value_set_on_the_tire(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """Newest is (recorded_at, id): a later same-day reading still outranks this one."""
        tire_id = await _tire(client, auth_headers, vehicle, None)
        older = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="7.0"
        )
        await _set_tire(client, auth_headers, vehicle, tire_id, tread_depth_mm="6.5")

        corrected = await _put(client, auth_headers, vehicle, tire_id, older, tread_depth_mm="7.5")

        assert corrected.status_code == 200, corrected.text
        assert _dec(_reading_in(corrected.json(), older)["tread_depth_mm"]) == Decimal("7.5")
        assert _dec(corrected.json()["tread_depth_mm"]) == Decimal("6.5")

    async def test_a_pressure_cleared_from_the_only_reading_that_had_one_leaves_it_unknown(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-01-10",
            tread_depth_mm="8.0",
            pressure_kpa="230",
        )
        tire = await _tire_body(client, auth_headers, vehicle, tire_id)
        assert _dec(tire["pressure_kpa"]) == Decimal("230")

        cleared = await _put(client, auth_headers, vehicle, tire_id, reading, pressure_kpa=None)

        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["pressure_kpa"] is None
        assert _dec(cleared.json()["tread_depth_mm"]) == Decimal("8.0")

    async def test_a_tread_added_to_a_pressure_only_reading_sets_a_tire_with_none(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", pressure_kpa="230"
        )
        tire = await _tire_body(client, auth_headers, vehicle, tire_id)
        assert tire["tread_depth_mm"] is None

        added = await _put(client, auth_headers, vehicle, tire_id, reading, tread_depth_mm="7.0")

        assert added.status_code == 200, added.text
        assert _dec(added.json()["tread_depth_mm"]) == Decimal("7.0")
        assert _dec(added.json()["pressure_kpa"]) == Decimal("230")

    async def test_an_edit_echoes_at_the_columns_scale(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """#224 Ruling 14 for the edit: 170.00 beside the other readings' 121.00, not 170."""
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )

        edited = await _put(
            client, auth_headers, vehicle, tire_id, reading, odometer_km="170", tread_depth_mm="7"
        )

        assert edited.status_code == 200, edited.text
        echoed = _reading_in(edited.json(), reading)
        assert (echoed["odometer_km"], echoed["tread_depth_mm"]) == ("170.00", "7.00")
        assert edited.json()["tread_depth_mm"] == "7.00"


@pytest.mark.asyncio
class TestWhatTheEditRefuses:
    async def test_a_reading_left_measuring_nothing_is_refused(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )

        refused = await _put(client, auth_headers, vehicle, tire_id, reading, tread_depth_mm=None)

        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == "A reading needs a tread depth, a pressure, or both"
        db_session.expire_all()
        stored = await db_session.get(TireReading, reading)
        assert stored is not None and stored.tread_depth_mm == Decimal("7.0")

    async def test_a_cleared_date_and_an_unknown_key_are_refused(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )

        no_date = await _put(client, auth_headers, vehicle, tire_id, reading, recorded_at=None)
        assert no_date.status_code == 422, no_date.text
        misspelt = await _put(client, auth_headers, vehicle, tire_id, reading, tread_mm="7.0")
        assert misspelt.status_code == 422, misspelt.text

    async def test_a_reading_of_another_tire_or_none_at_all_is_not_found(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        mine = await _tire(client, auth_headers, vehicle, None)
        theirs = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, theirs, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )

        wrong_tire = await _put(client, auth_headers, vehicle, mine, reading, tread_depth_mm="5.0")
        assert wrong_tire.status_code == 404, wrong_tire.text
        missing = await _put(client, auth_headers, vehicle, mine, 99_999_999, tread_depth_mm="5.0")
        assert missing.status_code == 404, missing.text
        db_session.expire_all()
        stored = await db_session.get(TireReading, reading)
        assert stored is not None and stored.tread_depth_mm == Decimal("7.0")

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
            refused = await _put(
                client, reader_headers, vin, tire_id, reading, tread_depth_mm="5.0"
            )
            assert refused.status_code == 403, refused.text
            allowed = await _put(
                client, writer_headers, vin, tire_id, reading, tread_depth_mm="5.0"
            )
            assert allowed.status_code == 200, allowed.text
            assert _dec(_reading_in(allowed.json(), reading)["tread_depth_mm"]) == Decimal("5.0")
        finally:
            await db_session.execute(delete(Tire).where(Tire.id == tire_id))
            await db_session.commit()


@pytest.mark.asyncio
class TestTheUntrackedAxis:
    async def test_a_stored_junk_odometer_does_not_block_an_edit_and_null_clears_it(
        self, client: AsyncClient, auth_headers, make_vehicle, db_session
    ):
        """An hour figure typed as kilometres before #217 still sits on the reading."""
        vin = await make_vehicle("hours")
        tire_id = await _tire(
            client, auth_headers, vin, mounted_odometer_km=None, mounted_hours="100.0"
        )
        reading = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-03-01",
            tread_depth_mm="7.0",
            engine_hours="150.0",
        )
        stored = await db_session.get(TireReading, reading)
        assert stored is not None
        stored.odometer_km = Decimal("170.00")
        await db_session.commit()

        tread = await _put(client, auth_headers, vin, tire_id, reading, tread_depth_mm="6.5")
        assert tread.status_code == 200, tread.text
        assert _reading_in(tread.json(), reading)["odometer_km"] == "170.00"

        cleared = await _put(client, auth_headers, vin, tire_id, reading, odometer_km=None)
        assert cleared.status_code == 200, cleared.text
        assert _reading_in(cleared.json(), reading)["odometer_km"] is None


@pytest.mark.asyncio
class TestTheRowsTheReadingPublished:
    DAY = date(2026, 2, 1)
    SESSION = date(2026, 3, 1)

    async def _day(self, db_session, vin: str) -> list[tuple[date, Decimal, str | None]]:
        return [row for row in await _records(db_session, vin) if row[0] == self.SESSION]

    async def _four_on_one_day(self, client, headers, vin: str) -> dict[str, tuple[int, int]]:
        """Four tires read at 15,000 km on one day: one record, under the first one's marker."""
        out: dict[str, tuple[int, int]] = {}
        for pos in ("FL", "FR", "RL", "RR"):
            tire_id = await _tire(client, headers, vin, pos)
            out[pos] = (
                tire_id,
                await _reading(
                    client,
                    headers,
                    vin,
                    tire_id,
                    recorded_at=self.SESSION.isoformat(),
                    odometer_km="15000",
                    tread_depth_mm="7.0",
                ),
            )
        return out

    async def test_an_odometer_added_later_is_published(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )
        assert await _records(db_session, vehicle) == []

        added = await _put(client, auth_headers, vehicle, tire_id, reading, odometer_km="11000")

        assert added.status_code == 200, added.text
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), marker)]

    async def test_a_typo_corrected_down_replaces_the_record(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Down on purpose: a higher figure raises the tire's own row anyway, a lower one needs the withdraw."""
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-02-01",
            odometer_km="150000",
            tread_depth_mm="7.0",
        )
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("150000"), marker)]

        fixed = await _put(client, auth_headers, vehicle, tire_id, reading, odometer_km="15000")

        assert fixed.status_code == 200, fixed.text
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("15000"), marker)]

    async def test_a_reading_moved_to_another_day_takes_its_record_along(
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

        moved = await _put(
            client, auth_headers, vehicle, tire_id, reading, recorded_at="2026-02-03"
        )

        assert moved.status_code == 200, moved.text
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(date(2026, 2, 3), Decimal("11000"), marker)]

    async def test_a_manual_record_at_the_same_figure_on_the_old_day_survives(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        db_session.add(
            OdometerRecord(vin=vehicle, date=self.DAY, odometer_km=Decimal("11000"), notes="hand")
        )
        await db_session.commit()
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
        # The day already read 11,000 km, so the reading published nothing.
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), "hand")]

        moved = await _put(
            client, auth_headers, vehicle, tire_id, reading, recorded_at="2026-02-03"
        )

        assert moved.status_code == 200, moved.text
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [
            (self.DAY, Decimal("11000"), "hand"),
            (date(2026, 2, 3), Decimal("11000"), marker),
        ]

    async def test_a_tread_only_edit_leaves_the_days_record_where_it_is(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        ids = await self._four_on_one_day(client, auth_headers, vehicle)
        fl_tire, fl_reading = ids["FL"]
        before = await self._day(db_session, vehicle)
        assert [n for _, _, n in before] == [auto_sync_marker(ODOMETER_SOURCE_TIRE, fl_tire)]

        # The editor resends the odometer it was seeded with.
        edited = await _put(
            client,
            auth_headers,
            vehicle,
            fl_tire,
            fl_reading,
            tread_depth_mm="6.5",
            odometer_km="15000.00",
        )

        assert edited.status_code == 200, edited.text
        assert await self._day(db_session, vehicle) == before

    async def test_the_first_tire_corrected_down_leaves_the_day_at_the_others_figure(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        ids = await self._four_on_one_day(client, auth_headers, vehicle)
        fl_tire, fl_reading = ids["FL"]

        fixed = await _put(client, auth_headers, vehicle, fl_tire, fl_reading, odometer_km="14990")

        assert fixed.status_code == 200, fixed.text
        # RR's reading was logged last: the highest figure that day, newest on the tie.
        assert await self._day(db_session, vehicle) == [
            (self.SESSION, Decimal("15000"), auto_sync_marker(ODOMETER_SOURCE_TIRE, ids["RR"][0]))
        ]

    async def test_the_first_tire_corrected_up_sits_beside_the_others(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        ids = await self._four_on_one_day(client, auth_headers, vehicle)
        fl_tire, fl_reading = ids["FL"]

        fixed = await _put(client, auth_headers, vehicle, fl_tire, fl_reading, odometer_km="15010")

        assert fixed.status_code == 200, fixed.text
        assert await self._day(db_session, vehicle) == [
            (self.SESSION, Decimal("15000"), auto_sync_marker(ODOMETER_SOURCE_TIRE, ids["RR"][0])),
            (self.SESSION, Decimal("15010"), auto_sync_marker(ODOMETER_SOURCE_TIRE, fl_tire)),
        ]

    async def test_an_hours_figure_corrected_moves_its_row_and_grows_no_odometer(
        self, client: AsyncClient, auth_headers, make_vehicle, db_session
    ):
        vin = await make_vehicle("hours")
        tire_id = await _tire(client, auth_headers, vin, None)
        reading = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-02-01",
            tread_depth_mm="7.0",
            engine_hours="150.0",
        )
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _hours_rows(db_session, vin) == [(self.DAY, Decimal("150.0"), marker)]

        fixed = await _put(client, auth_headers, vin, tire_id, reading, engine_hours="140.0")

        assert fixed.status_code == 200, fixed.text
        assert await _hours_rows(db_session, vin) == [(self.DAY, Decimal("140.0"), marker)]
        assert await _odometer_count(db_session, vin) == 0

    async def test_a_junk_odometer_row_stays_put_on_an_hours_vehicle(
        self, client: AsyncClient, auth_headers, make_vehicle, db_session
    ):
        vin = await make_vehicle("hours")
        tire_id = await _tire(client, auth_headers, vin, None)
        reading = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-02-01",
            tread_depth_mm="7.0",
            engine_hours="150.0",
        )
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        # An hour figure typed as kilometres before #217, and the row it published.
        stored = await db_session.get(TireReading, reading)
        assert stored is not None
        stored.odometer_km = Decimal("170.00")
        db_session.add(
            OdometerRecord(
                vin=vin, date=self.DAY, odometer_km=Decimal("170.00"), notes=marker, source="tire"
            )
        )
        await db_session.commit()
        junk = [(self.DAY, Decimal("170.00"), marker)]

        moved = await _put(client, auth_headers, vin, tire_id, reading, recorded_at="2026-02-03")
        assert moved.status_code == 200, moved.text
        assert await _hours_rows(db_session, vin) == [(date(2026, 2, 3), Decimal("150.0"), marker)]
        assert await _records(db_session, vin) == junk

        cleared = await _put(client, auth_headers, vin, tire_id, reading, odometer_km=None)
        assert cleared.status_code == 200, cleared.text
        assert await _records(db_session, vin) == junk

    async def test_a_dual_vehicle_moves_both_rows(
        self, client: AsyncClient, auth_headers, make_vehicle, db_session
    ):
        vin = await make_vehicle("distance", secondary=True)
        tire_id = await _tire(client, auth_headers, vin, None)
        reading = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-02-01",
            odometer_km="11000",
            engine_hours="150.0",
            tread_depth_mm="7.0",
        )

        moved = await _put(client, auth_headers, vin, tire_id, reading, recorded_at="2026-02-03")

        assert moved.status_code == 200, moved.text
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vin) == [(date(2026, 2, 3), Decimal("11000"), marker)]
        assert await _hours_rows(db_session, vin) == [(date(2026, 2, 3), Decimal("150.0"), marker)]


@pytest.mark.asyncio
class TestTheMountHistory:
    async def test_a_correction_that_contradicts_the_mount_is_refused_and_changes_nothing(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle)
        reading = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-03-01",
            odometer_km="11000",
            tread_depth_mm="7.0",
        )
        records_before = await _records(db_session, vehicle)

        # Mounted at 10,000 km on 2026-01-01, so two months on it can't read 9,000 km.
        refused = await _put(client, auth_headers, vehicle, tire_id, reading, odometer_km="9000")

        assert refused.status_code == 409, refused.text
        # The default test user reads miles: 9,000 km / 1.609344, to one decimal.
        assert refused.json()["detail"] == (
            "The FL period mounted 2026-01-01 contradicts the reading dated 2026-03-01 at "
            "5,592.3 mi: the vehicle's odometer would have to run backwards. If that reading "
            "is wrong, correct or delete it in the tire's history."
        )
        db_session.expire_all()
        stored = await db_session.get(TireReading, reading)
        assert stored is not None and stored.odometer_km == Decimal("11000")
        assert await _records(db_session, vehicle) == records_before

    async def test_a_new_contradiction_is_refused_beside_an_old_one_on_the_same_period(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        """Rule 5 flags each period once, so an old bad reading mustn't hide a new one."""
        tire_id = await _tire(client, auth_headers, vehicle)
        # Log Reading doesn't validate, so a legacy contradiction can exist.
        await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-03-01",
            odometer_km="9000",
            tread_depth_mm="7.0",
        )
        healthy = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-04-01",
            odometer_km="12000",
            tread_depth_mm="6.8",
        )

        refused = await _put(client, auth_headers, vehicle, tire_id, healthy, odometer_km="9500")

        assert refused.status_code == 409, refused.text
        assert "contradicts the reading dated 2026-04-01" in refused.json()["detail"]
        db_session.expire_all()
        stored = await db_session.get(TireReading, healthy)
        assert stored is not None and stored.odometer_km == Decimal("12000")

    async def test_a_reading_that_already_contradicted_a_period_can_still_be_edited(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        """An old contradiction never blocks an edit, so a repair can go one field at a time."""
        tire_id = await _tire(client, auth_headers, vehicle)
        legacy = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-03-01",
            odometer_km="9000",
            tread_depth_mm="7.0",
        )

        notes = await _put(client, auth_headers, vehicle, tire_id, legacy, notes="check this")

        assert notes.status_code == 200, notes.text
        assert _reading_in(notes.json(), legacy)["notes"] == "check this"

    async def test_correcting_a_typo_that_blocked_a_dismount_unblocks_it(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle)
        typo = await _reading(
            client,
            auth_headers,
            vehicle,
            tire_id,
            recorded_at="2026-03-01",
            odometer_km="150000",
            tread_depth_mm="7.0",
        )
        dismount = {"dismounted_on": "2026-06-01", "dismounted_odometer_km": "20000"}
        base = f"/api/vehicles/{vehicle}/tires/{tire_id}"
        refused = await client.post(f"{base}/dismount", headers=auth_headers, json=dismount)
        assert refused.status_code == 409, refused.text

        fixed = await _put(client, auth_headers, vehicle, tire_id, typo, odometer_km="15000")
        assert fixed.status_code == 200, fixed.text

        again = await client.post(f"{base}/dismount", headers=auth_headers, json=dismount)
        assert again.status_code == 200, again.text
        assert [r["id"] for r in again.json()["readings"]] == [typo]

    async def test_an_hour_meter_run_backwards_is_refused_in_hours(
        self, client: AsyncClient, auth_headers, make_vehicle, db_session
    ):
        vin = await make_vehicle("hours")
        tire_id = await _tire(
            client, auth_headers, vin, mounted_odometer_km=None, mounted_hours="100.0"
        )
        reading = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-03-01",
            tread_depth_mm="7.0",
            engine_hours="150.0",
        )
        rows_before = await _hours_rows(db_session, vin)

        refused = await _put(client, auth_headers, vin, tire_id, reading, engine_hours="90.0")

        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == (
            "The FL period mounted 2026-01-01 contradicts the reading dated 2026-03-01 at 90.0 hr: "
            "the vehicle's hour meter would have to run backwards. If that reading is wrong, "
            "correct or delete it in the tire's history."
        )
        assert await _hours_rows(db_session, vin) == rows_before

    async def test_a_new_hours_contradiction_is_refused_beside_an_old_one(
        self, client: AsyncClient, auth_headers, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire_id = await _tire(
            client, auth_headers, vin, mounted_odometer_km=None, mounted_hours="100.0"
        )
        await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-03-01",
            tread_depth_mm="7.0",
            engine_hours="90.0",
        )
        healthy = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-04-01",
            tread_depth_mm="6.8",
            engine_hours="160.0",
        )

        refused = await _put(client, auth_headers, vin, tire_id, healthy, engine_hours="95.0")

        assert refused.status_code == 409, refused.text
        assert "contradicts the reading dated 2026-04-01 at 95.0 hr" in refused.json()["detail"]

    async def test_a_dual_vehicle_refuses_an_hours_contradiction_its_odometer_doesnt_have(
        self, client: AsyncClient, auth_headers, make_vehicle
    ):
        vin = await make_vehicle("distance", secondary=True)
        tire_id = await _tire(client, auth_headers, vin, mounted_hours="100.0")
        reading = await _reading(
            client,
            auth_headers,
            vin,
            tire_id,
            recorded_at="2026-03-01",
            odometer_km="11000",
            engine_hours="150.0",
            tread_depth_mm="7.0",
        )

        refused = await _put(client, auth_headers, vin, tire_id, reading, engine_hours="90.0")

        assert refused.status_code == 409, refused.text
        assert "the vehicle's hour meter would have to run backwards" in refused.json()["detail"]
