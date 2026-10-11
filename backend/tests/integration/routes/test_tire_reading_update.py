"""Correcting a tread reading in place, instead of deleting it and logging it again.

The report that asked for it: a gauge's 0.346 in typed into the 32nds field
stored 0.346/32 in, a tire reading as bald, and the only repair was Delete. A
reading logged without an odometer could never be given one either.

A reading leaves three things behind, and each has to follow the corrected
values: the tread and pressure it may have copied onto the tire, the vehicle
odometer record it published, and the low-tread reminder that tread may have
raised. And because a correction can change a reading's date and odometer, it
is judged against the mount history the way the period editor's writes are.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.tire import Tire, TireReading
from app.models.vehicle import Vehicle
from app.services.tire_service import ODOMETER_SOURCE_TIRE
from app.utils.odometer_sync import auto_sync_marker


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
    """A vehicle for this test alone: corners are claimable once per vehicle,
    and the suite shares one database."""
    vin = f"TIREUPD{uuid.uuid4().hex[:10].upper()}"[:17]
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Reading update",
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


async def _tire_body(client: AsyncClient, headers, vin: str, tire_id: int) -> dict:
    listed = await client.get(f"/api/vehicles/{vin}/tires", headers=headers)
    assert listed.status_code == 200, listed.text
    return next(t for t in listed.json()["tires"] if t["id"] == tire_id)


async def _reading(client: AsyncClient, headers, vin: str, tire_id: int, **body) -> int:
    """Log a reading and return its id: the one the response did not have before."""
    before = {r["id"] for r in (await _tire_body(client, headers, vin, tire_id))["readings"]}
    logged = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings", headers=headers, json=body
    )
    assert logged.status_code == 201, logged.text
    (new_id,) = {r["id"] for r in logged.json()["readings"]} - before
    return new_id


async def _tire_value(
    client: AsyncClient, headers, vin: str, tire_id: int, field: str
) -> Decimal | None:
    value = (await _tire_body(client, headers, vin, tire_id))[field]
    return None if value is None else Decimal(str(value))


def _url(vin: str, tire_id: int, reading_id: int) -> str:
    return f"/api/vehicles/{vin}/tires/{tire_id}/readings/{reading_id}"


def _dec(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _reading_in(body: dict, reading_id: int) -> dict:
    return next(r for r in body["readings"] if r["id"] == reading_id)


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
        assert await _tire_value(
            client, auth_headers, vehicle, tire_id, "tread_depth_mm"
        ) == Decimal("0.27")
        assert await _low_tread_statuses(db_session, tire_id) == ["pending"]

        fixed = await client.put(
            _url(vehicle, tire_id, typo), headers=auth_headers, json={"tread_depth_mm": "8.73"}
        )

        assert fixed.status_code == 200, fixed.text
        body = fixed.json()
        assert [r["id"] for r in body["readings"]] == [typo]
        assert _dec(_reading_in(body, typo)["tread_depth_mm"]) == Decimal("8.73")
        # Untouched by a body that did not name it.
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
        assert await _tire_value(
            client, auth_headers, vehicle, tire_id, "tread_depth_mm"
        ) == Decimal("6.0")

        moved = await client.put(
            _url(vehicle, tire_id, older), headers=auth_headers, json={"recorded_at": "2026-04-10"}
        )

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

        moved = await client.put(
            _url(vehicle, tire_id, newest), headers=auth_headers, json={"recorded_at": "2026-01-10"}
        )

        assert moved.status_code == 200, moved.text
        assert _dec(moved.json()["tread_depth_mm"]) == Decimal("8.0")

    async def test_a_value_set_on_the_tire_survives_an_edit_that_changes_no_measure(
        self, client: AsyncClient, auth_headers, vehicle
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-01-10", tread_depth_mm="8.0"
        )
        edited = await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}",
            headers=auth_headers,
            json={"tread_depth_mm": "7.5"},
        )
        assert edited.status_code == 200, edited.text
        assert _dec(edited.json()["tread_depth_mm"]) == Decimal("7.5")

        # The editor resends every field; only the notes differ.
        notes_only = await client.put(
            _url(vehicle, tire_id, reading),
            headers=auth_headers,
            json={"recorded_at": "2026-01-10", "tread_depth_mm": "8.00", "notes": "front left"},
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
        await client.put(
            f"/api/vehicles/{vehicle}/tires/{tire_id}",
            headers=auth_headers,
            json={"tread_depth_mm": "7.5"},
        )

        corrected = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"tread_depth_mm": "6.5"}
        )

        assert corrected.status_code == 200, corrected.text
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
        assert await _tire_value(client, auth_headers, vehicle, tire_id, "pressure_kpa") == Decimal(
            "230"
        )

        cleared = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"pressure_kpa": None}
        )

        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["pressure_kpa"] is None
        assert _dec(cleared.json()["tread_depth_mm"]) == Decimal("8.0")


@pytest.mark.asyncio
class TestTheOdometerRecordTheReadingPublished:
    DAY = date(2026, 2, 1)

    async def test_an_odometer_added_later_is_published(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )
        assert await _records(db_session, vehicle) == []

        added = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"odometer_km": "11000"}
        )

        assert added.status_code == 200, added.text
        assert _dec(_reading_in(added.json(), reading)["odometer_km"]) == Decimal("11000")
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11000"), marker)]

    async def test_a_corrected_odometer_replaces_the_mistyped_one(
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

        corrected = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"odometer_km": "11500"}
        )

        assert corrected.status_code == 200, corrected.text
        assert await _records(db_session, vehicle) == [(self.DAY, Decimal("11500"), marker)]

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

        moved = await client.put(
            _url(vehicle, tire_id, reading),
            headers=auth_headers,
            json={"recorded_at": "2026-02-03"},
        )

        assert moved.status_code == 200, moved.text
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [(date(2026, 2, 3), Decimal("11000"), marker)]

    async def test_a_manual_record_on_the_old_day_survives(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        db_session.add(
            OdometerRecord(vin=vehicle, date=self.DAY, odometer_km=Decimal("10900"), notes="hand")
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

        moved = await client.put(
            _url(vehicle, tire_id, reading),
            headers=auth_headers,
            json={"recorded_at": "2026-02-03"},
        )

        assert moved.status_code == 200, moved.text
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        assert await _records(db_session, vehicle) == [
            (self.DAY, Decimal("10900"), "hand"),
            (date(2026, 2, 3), Decimal("11000"), marker),
        ]


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
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        records_before = await _records(db_session, vehicle)
        assert (date(2026, 3, 1), Decimal("11000"), marker) in records_before

        # Mounted at 10,000 km on 2026-01-01, so two months later the odometer
        # cannot read 9,000 km.
        refused = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"odometer_km": "9000"}
        )

        assert refused.status_code == 409, refused.text
        assert "contradicts the reading dated 2026-03-01" in refused.json()["detail"]
        db_session.expire_all()
        stored = await db_session.get(TireReading, reading)
        assert stored is not None and stored.odometer_km == Decimal("11000")
        assert await _records(db_session, vehicle) == records_before

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

        fixed = await client.put(
            _url(vehicle, tire_id, typo), headers=auth_headers, json={"odometer_km": "15000"}
        )
        assert fixed.status_code == 200, fixed.text

        again = await client.post(f"{base}/dismount", headers=auth_headers, json=dismount)
        assert again.status_code == 200, again.text
        assert [r["id"] for r in again.json()["readings"]] == [typo]


@pytest.mark.asyncio
class TestWhatTheEditRefuses:
    async def test_a_reading_left_measuring_nothing_is_refused(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        tire_id = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, tire_id, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )

        refused = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"tread_depth_mm": None}
        )

        assert refused.status_code == 422, refused.text
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

        no_date = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"recorded_at": None}
        )
        assert no_date.status_code == 422, no_date.text
        misspelt = await client.put(
            _url(vehicle, tire_id, reading), headers=auth_headers, json={"tread_mm": "7.0"}
        )
        assert misspelt.status_code == 422, misspelt.text

    async def test_a_reading_of_another_tire_or_none_at_all_is_not_found(
        self, client: AsyncClient, auth_headers, vehicle, db_session
    ):
        mine = await _tire(client, auth_headers, vehicle, None)
        theirs = await _tire(client, auth_headers, vehicle, None)
        reading = await _reading(
            client, auth_headers, vehicle, theirs, recorded_at="2026-02-01", tread_depth_mm="7.0"
        )

        wrong_tire = await client.put(
            _url(vehicle, mine, reading), headers=auth_headers, json={"tread_depth_mm": "5.0"}
        )
        assert wrong_tire.status_code == 404, wrong_tire.text
        missing = await client.put(
            _url(vehicle, mine, 99_999_999), headers=auth_headers, json={"tread_depth_mm": "5.0"}
        )
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
            refused = await client.put(
                _url(vin, tire_id, reading), headers=reader_headers, json={"tread_depth_mm": "5.0"}
            )
            assert refused.status_code == 403, refused.text
            allowed = await client.put(
                _url(vin, tire_id, reading), headers=writer_headers, json={"tread_depth_mm": "5.0"}
            )
            assert allowed.status_code == 200, allowed.text
            assert _dec(_reading_in(allowed.json(), reading)["tread_depth_mm"]) == Decimal("5.0")
        finally:
            await db_session.execute(delete(Tire).where(Tire.id == tire_id))
            await db_session.commit()
