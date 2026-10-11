"""Tire writes on the hour meter (#217).

An hours-only ATV's tires used to take only odometers, so the hour meter typed
there became hidden odometer rows. These pin the write side: hours store and
publish the way odometers do, a figure for an axis the vehicle doesn't track
is a 422 before anything is written, and a dual vehicle takes both.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.tire import Tire
from app.models.vehicle import Vehicle
from app.services.hours_service import latest_engine_hours_and_date
from app.services.tire_service import UNTRACKED_DISTANCE, UNTRACKED_HOURS
from app.utils.odometer_sync import auto_sync_marker

DAY = date(2026, 6, 21)


@pytest_asyncio.fixture
async def make_vehicle(db_session, test_user):
    made: list[str] = []

    async def _make(usage_unit: str = "hours", secondary: bool = False) -> str:
        vin = f"HRS{uuid.uuid4().hex[:14].upper()}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="Hours tires",
                vehicle_type="ATV",
                year=2021,
                make="Polaris",
                model="Sportsman",
                usage_unit=usage_unit,
                secondary_usage_enabled=secondary,
            )
        )
        await db_session.commit()
        made.append(vin)
        return vin

    yield _make
    for vin in made:
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _hours_rows(db_session, vin):
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
    return [
        (r.date, r.engine_hours, r.notes, r.source, r.fuel_record_id, r.service_visit_id)
        for r in rows
    ]


async def _odometer_count(db_session, vin) -> int:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(func.count()).select_from(OdometerRecord).where(OdometerRecord.vin == vin)
        )
    ).scalar_one()


async def _create_and_mount(client, headers, vin, position="FL", **figures):
    return await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount",
        headers=headers,
        json={
            "vin": vin,
            "position": position,
            "brand": "Maxxis",
            "mounted_on": DAY.isoformat(),
            **figures,
        },
    )


async def _manual_hours(client, headers, vin, value: str) -> None:
    made = await client.post(
        f"/api/vehicles/{vin}/hours",
        headers=headers,
        json={"vin": vin, "date": DAY.isoformat(), "engine_hours": value},
    )
    assert made.status_code == 201, made.text


async def _log_hours(client, headers, vin, tire_id, hours: str) -> dict:
    logged = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings",
        headers=headers,
        json={"recorded_at": DAY.isoformat(), "tread_depth_mm": "7.0", "engine_hours": hours},
    )
    assert logged.status_code == 201, logged.text
    return logged.json()


@pytest.mark.asyncio
class TestTheHoursVehicle:
    async def test_create_and_mount_takes_the_hour_meter(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        made = await _create_and_mount(client, auth_headers, vin, mounted_hours="100.0")
        assert made.status_code == 201, made.text  # main: 422 extra_forbidden
        [period] = made.json()["mount_periods"]
        assert Decimal(period["mounted_hours"]) == Decimal("100.0")
        assert await _hours_rows(db_session, vin) == [
            (
                DAY,
                Decimal("100.0"),
                auto_sync_marker("tire_mount", period["id"]),
                "tire_mount",
                None,
                None,
            )
        ]
        assert await _odometer_count(db_session, vin) == 0

    async def test_an_odometer_is_refused_and_nothing_is_written(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        made = await _create_and_mount(client, auth_headers, vin, mounted_odometer_km="170")
        assert made.status_code == 422, made.text  # main: 201 and an odometer row
        assert made.json()["detail"] == UNTRACKED_DISTANCE
        assert await _odometer_count(db_session, vin) == 0
        db_session.expire_all()
        tires = (
            await db_session.execute(select(func.count()).select_from(Tire).where(Tire.vin == vin))
        ).scalar_one()
        assert tires == 0

    async def test_a_mount_at_zero_hours_is_a_real_bound(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        made = await _create_and_mount(client, auth_headers, vin, mounted_hours="0")
        assert made.status_code == 201, made.text
        [period] = made.json()["mount_periods"]
        assert Decimal(period["mounted_hours"]) == Decimal("0")
        assert [row[1] for row in await _hours_rows(db_session, vin)] == [Decimal("0.0")]

    async def test_a_dismount_below_its_mount_hours_is_refused(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin, mounted_hours="150.0")).json()
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": DAY.isoformat(), "dismounted_hours": "120.0"},
        )
        assert refused.status_code == 409, refused.text
        assert "below its mount hours of 150.0 hr" in refused.json()["detail"]
        assert len(await _hours_rows(db_session, vin)) == 1

    async def test_mount_echoes_the_stored_tenth_and_refuses_a_lower_dismount(
        self, client, auth_headers, db_session, make_vehicle
    ):
        # The mount echoes the tenth it stored (100.2), and a dismount below that is
        # refused. The rounding inside one write is pinned by the next test.
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin, mounted_hours="100.15")).json()
        assert tire["mount_periods"][0]["mounted_hours"] == "100.2"
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": DAY.isoformat(), "dismounted_hours": "100.10"},
        )
        assert refused.status_code == 409, refused.text
        listed = (await client.get(f"/api/vehicles/{vin}/tires", headers=auth_headers)).json()
        [period] = listed["tires"][0]["mount_periods"]
        assert (period["mounted_hours"], period["dismounted_on"]) == ("100.2", None)

    async def test_one_write_is_checked_at_the_stored_tenth(
        self, client, auth_headers, db_session, make_vehicle
    ):
        # Across writes the mount comes back from the column already rounded, so
        # only a write carrying both bounds shows the rounding. Unrounded, this
        # one passed and stored 100.2 -> 100.1.
        vin = await make_vehicle("hours")
        stored = (
            await client.post(
                f"/api/vehicles/{vin}/tires",
                headers=auth_headers,
                json={"vin": vin, "brand": "Spare"},
            )
        ).json()
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/{stored['id']}/mount-periods",
            headers=auth_headers,
            json={
                "position": "RL",
                "mounted_on": "2025-05-01",
                "mounted_hours": "100.15",
                "dismounted_on": "2025-09-01",
                "dismounted_hours": "100.10",
            },
        )
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert "dismounted at 100.1 hr, below its mount hours of 100.2 hr" in detail
        assert await _hours_rows(db_session, vin) == []

    async def test_a_reading_publishes_the_tenth_it_stores(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin)).json()
        logged = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/readings",
            headers=auth_headers,
            json={"recorded_at": DAY.isoformat(), "tread_depth_mm": "7.0", "engine_hours": "30.05"},
        )
        assert logged.status_code == 201, logged.text
        assert logged.json()["readings"][0]["engine_hours"] == "30.1"
        assert [row[1] for row in await _hours_rows(db_session, vin)] == [Decimal("30.1")]


@pytest.mark.asyncio
class TestPublishing:
    async def test_a_higher_reading_that_day_wins(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        await _manual_hours(client, auth_headers, vin, "120.0")
        made = await _create_and_mount(client, auth_headers, vin, mounted_hours="110.0")
        assert made.status_code == 201, made.text
        assert [row[1] for row in await _hours_rows(db_session, vin)] == [Decimal("120.0")]
        assert Decimal(made.json()["mount_periods"][0]["mounted_hours"]) == Decimal("110.0")

    async def test_a_lower_reading_that_day_gets_a_tire_row_beside_it(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        await _manual_hours(client, auth_headers, vin, "100.0")
        await _create_and_mount(client, auth_headers, vin, mounted_hours="110.0")
        assert [row[1] for row in await _hours_rows(db_session, vin)] == [
            Decimal("100.0"),
            Decimal("110.0"),
        ]
        assert (await latest_engine_hours_and_date(db_session, vin))[0] == Decimal("110.0")

    async def test_a_same_day_reading_within_the_band_is_one_reading(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        await _manual_hours(client, auth_headers, vin, "120.0")
        made = await _create_and_mount(client, auth_headers, vin, mounted_hours="120.04")
        assert made.status_code == 201, made.text
        assert [row[1] for row in await _hours_rows(db_session, vin)] == [Decimal("120.0")]
        assert Decimal(made.json()["mount_periods"][0]["mounted_hours"]) == Decimal("120.0")

    async def test_a_rotation_publishes_one_row(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        left = (await _create_and_mount(client, auth_headers, vin, "FL")).json()
        right = (await _create_and_mount(client, auth_headers, vin, "FR")).json()
        rotated = await client.post(
            f"/api/vehicles/{vin}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": left["id"], "position": "FR"},
                    {"tire_id": right["id"], "position": "FL"},
                ],
                "rotated_on": DAY.isoformat(),
                "engine_hours": "200.0",
            },
        )
        assert rotated.status_code == 200, rotated.text
        marker = auto_sync_marker("tire_rotation", min(left["id"], right["id"]))
        assert [(r[1], r[2], r[3]) for r in await _hours_rows(db_session, vin)] == [
            (Decimal("200.0"), marker, "tire_rotation")
        ]

    async def test_a_set_fit_publishes_one_row(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin)).json()
        tire_set = (
            await client.post(
                f"/api/vehicles/{vin}/tire-sets", headers=auth_headers, json={"name": "Mud"}
            )
        ).json()
        filed = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}",
            headers=auth_headers,
            json={"set_id": tire_set["id"]},
        )
        assert filed.status_code == 200, filed.text
        off = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={"dismounted_on": DAY.isoformat(), "dismounted_hours": "10.0"},
        )
        assert off.status_code == 200, off.text
        fitted = await client.post(
            f"/api/vehicles/{vin}/tire-sets/{tire_set['id']}/mount",
            headers=auth_headers,
            json={"mounted_on": DAY.isoformat(), "engine_hours": "20.0"},
        )
        assert fitted.status_code == 200, fitted.text
        rows = await _hours_rows(db_session, vin)
        assert (
            DAY,
            Decimal("20.0"),
            auto_sync_marker("tire_set", tire_set["id"]),
            "tire_set",
            None,
            None,
        ) in rows

    async def test_a_reading_publishes_under_the_tire(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin)).json()
        logged = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/readings",
            headers=auth_headers,
            json={"recorded_at": DAY.isoformat(), "tread_depth_mm": "7.0", "engine_hours": "30.0"},
        )
        assert logged.status_code == 201, logged.text
        assert [(r[1], r[2]) for r in await _hours_rows(db_session, vin)] == [
            (Decimal("30.0"), auto_sync_marker("tire", tire["id"]))
        ]

    async def test_a_lower_reading_of_the_tire_that_day_leaves_its_row(
        self, client, auth_headers, db_session, make_vehicle
    ):
        # Logged out of order. Both readings stay, and the day keeps the higher one (#224).
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin)).json()
        await _log_hours(client, auth_headers, vin, tire["id"], "105.0")
        logged = await _log_hours(client, auth_headers, vin, tire["id"], "100.0")
        assert sorted(Decimal(r["engine_hours"]) for r in logged["readings"]) == [
            Decimal("100.0"),
            Decimal("105.0"),
        ]
        assert [(r[1], r[2]) for r in await _hours_rows(db_session, vin)] == [
            (Decimal("105.0"), auto_sync_marker("tire", tire["id"]))
        ]
        assert await latest_engine_hours_and_date(db_session, vin) == (Decimal("105.0"), DAY)

    async def test_a_higher_reading_of_the_tire_that_day_raises_its_row(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire = (await _create_and_mount(client, auth_headers, vin)).json()
        await _log_hours(client, auth_headers, vin, tire["id"], "105.0")
        await _log_hours(client, auth_headers, vin, tire["id"], "110.0")
        assert [(r[1], r[2]) for r in await _hours_rows(db_session, vin)] == [
            (Decimal("110.0"), auto_sync_marker("tire", tire["id"]))
        ]
        assert await latest_engine_hours_and_date(db_session, vin) == (Decimal("110.0"), DAY)


@pytest.mark.asyncio
class TestTheDualVehicle:
    async def test_it_takes_both_and_publishes_both(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours", secondary=True)
        made = await _create_and_mount(
            client, auth_headers, vin, mounted_odometer_km="1000", mounted_hours="50.0"
        )
        assert made.status_code == 201, made.text
        [period] = made.json()["mount_periods"]
        assert (Decimal(period["mounted_odometer_km"]), Decimal(period["mounted_hours"])) == (
            Decimal("1000"),
            Decimal("50.0"),
        )
        assert await _odometer_count(db_session, vin) == 1
        assert len(await _hours_rows(db_session, vin)) == 1

    async def test_the_secondary_reading_is_optional(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours", secondary=True)
        made = await _create_and_mount(client, auth_headers, vin, mounted_hours="50.0")
        assert made.status_code == 201, made.text
        assert await _odometer_count(db_session, vin) == 0
        assert len(await _hours_rows(db_session, vin)) == 1

    async def test_a_contradiction_on_hours_alone_is_refused(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours", secondary=True)
        tire = (
            await _create_and_mount(
                client, auth_headers, vin, mounted_odometer_km="1000", mounted_hours="150.0"
            )
        ).json()
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/dismount",
            headers=auth_headers,
            json={
                "dismounted_on": DAY.isoformat(),
                "dismounted_odometer_km": "2000",
                "dismounted_hours": "120.0",
            },
        )
        assert refused.status_code == 409, refused.text
        assert "hr" in refused.json()["detail"]

    async def test_a_reading_echoes_at_the_columns_scale(self, client, auth_headers, make_vehicle):
        vin = await make_vehicle("hours", secondary=True)
        tire = (await _create_and_mount(client, auth_headers, vin)).json()
        logged = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/readings",
            headers=auth_headers,
            json={
                "recorded_at": DAY.isoformat(),
                "tread_depth_mm": "7",
                "odometer_km": "170",
                "engine_hours": "100",
            },
        )
        assert logged.status_code == 201, logged.text
        newest = logged.json()["readings"][0]
        # main echoed "170" beside stored readings' "121.00".
        assert (newest["odometer_km"], newest["engine_hours"]) == ("170.00", "100.0")


WRITERS = [
    "mount",
    "dismount",
    "retire",
    "rotate",
    "reading",
    "past_period",
    "period_edit",
    "set_fit",
]


def _figure(field: str, value: str, odometer_key: str, hours_key: str) -> dict[str, str]:
    return {odometer_key: value} if field == "odometer" else {hours_key: value}


async def _attempt(client, headers, vin, writer, field, value, mounted, stored, tire_set):
    base = f"/api/vehicles/{vin}"
    day = DAY.isoformat()
    if writer == "mount":
        body = {
            "position": "FR",
            "mounted_on": day,
            **_figure(field, value, "mounted_odometer_km", "mounted_hours"),
        }
        return await client.post(f"{base}/tires/{stored['id']}/mount", headers=headers, json=body)
    if writer in ("dismount", "retire"):
        body = {
            "dismounted_on": day,
            **_figure(field, value, "dismounted_odometer_km", "dismounted_hours"),
        }
        return await client.post(
            f"{base}/tires/{mounted['id']}/{writer}", headers=headers, json=body
        )
    if writer == "rotate":
        body = {
            "moves": [{"tire_id": mounted["id"], "position": "FR"}],
            "rotated_on": day,
            **_figure(field, value, "odometer_km", "engine_hours"),
        }
        return await client.post(f"{base}/tires/rotate", headers=headers, json=body)
    if writer == "reading":
        body = {
            "recorded_at": day,
            "tread_depth_mm": "7.0",
            **_figure(field, value, "odometer_km", "engine_hours"),
        }
        return await client.post(
            f"{base}/tires/{mounted['id']}/readings", headers=headers, json=body
        )
    if writer == "past_period":
        body = {
            "position": "RL",
            "mounted_on": "2025-05-01",
            "dismounted_on": "2025-09-01",
            **_figure(field, value, "mounted_odometer_km", "mounted_hours"),
        }
        return await client.post(
            f"{base}/tires/{stored['id']}/mount-periods", headers=headers, json=body
        )
    if writer == "period_edit":
        period_id = mounted["mount_periods"][0]["id"]
        body = _figure(field, value, "mounted_odometer_km", "mounted_hours")
        return await client.put(
            f"{base}/tires/{mounted['id']}/mount-periods/{period_id}", headers=headers, json=body
        )
    body = {"mounted_on": day, **_figure(field, value, "odometer_km", "engine_hours")}
    return await client.post(f"{base}/tire-sets/{tire_set['id']}/mount", headers=headers, json=body)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize(
    ("usage_unit", "field", "value", "detail"),
    [
        ("hours", "odometer", "170", UNTRACKED_DISTANCE),
        ("distance", "hours", "120.0", UNTRACKED_HOURS),
    ],
    ids=["odometer_on_hours", "hours_on_distance"],
)
async def test_every_writer_refuses_an_untracked_axis(
    writer, usage_unit, field, value, detail, client, auth_headers, db_session, make_vehicle
):
    vin = await make_vehicle(usage_unit)
    mounted = (await _create_and_mount(client, auth_headers, vin)).json()
    stored = (
        await client.post(
            f"/api/vehicles/{vin}/tires", headers=auth_headers, json={"vin": vin, "brand": "Spare"}
        )
    ).json()
    tire_set = (
        await client.post(
            f"/api/vehicles/{vin}/tire-sets", headers=auth_headers, json={"name": "Winter"}
        )
    ).json()
    odometers, hours = (
        await _odometer_count(db_session, vin),
        len(await _hours_rows(db_session, vin)),
    )

    response = await _attempt(
        client, auth_headers, vin, writer, field, value, mounted, stored, tire_set
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == detail
    assert await _odometer_count(db_session, vin) == odometers
    assert len(await _hours_rows(db_session, vin)) == hours
