"""Tires in the JSON backup: sets, tires, mount periods and readings (task 5, J1, N-4, N-6)."""

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading, TireSet
from app.routes.import_data import json_tires, vehicle_json
from tests.integration.routes._json_backup import V9, export_json, import_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _seed(db_session: AsyncSession, vin: str) -> None:
    """A set, a mounted tire with a closed and an open period, and a stored tire."""
    winter = TireSet(vin=vin, name="Winter", notes="studded")
    db_session.add(winter)
    await db_session.flush()
    mounted = Tire(
        vin=vin,
        position="FL",
        brand="Nokian",
        model_name="Hakka 10",
        size="225/45R17",
        dot_code="2324",
        set_id=winter.id,
        tread_depth_mm=Decimal("7.50"),
        pressure_kpa=Decimal("240.00"),
        min_tread_mm=Decimal("3.00"),
        notes="quiet",
    )
    stored = Tire(
        vin=vin,
        brand="Michelin",
        tread_depth_mm=Decimal("5.00"),
        min_tread_mm=Decimal("2.00"),
        storage_location="Shed",
        retired_on=date(2026, 5, 1),
    )
    db_session.add_all([mounted, stored])
    await db_session.flush()
    closed = TireMountPeriod(
        tire_id=mounted.id,
        position="FR",
        mounted_on=date(2025, 11, 1),
        dismounted_on=date(2026, 4, 1),
        mounted_odometer_km=Decimal("10000.00"),
        dismounted_odometer_km=Decimal("14000.00"),
        mounted_hours=Decimal("100.0"),
        dismounted_hours=Decimal("140.0"),
        notes="first winter",
    )
    open_ = TireMountPeriod(
        tire_id=mounted.id,
        position="FL",
        mounted_on=date(2026, 10, 1),
        mounted_odometer_km=Decimal("18000.00"),
        is_assumed=True,
        observed_active_on=date(2026, 10, 2),
    )
    db_session.add_all([closed, open_])
    await db_session.flush()
    db_session.add_all(
        [
            # An old reading with no period (N-6), one in the closed period, one in the open one.
            TireReading(
                tire_id=mounted.id,
                vin=vin,
                position=None,
                recorded_at=date(2025, 10, 1),
                tread_depth_mm=Decimal("8.00"),
            ),
            TireReading(
                tire_id=mounted.id,
                vin=vin,
                position="FR",
                mount_period_id=closed.id,
                recorded_at=date(2026, 3, 1),
                odometer_km=Decimal("13000.00"),
                engine_hours=Decimal("130.0"),
                tread_depth_mm=Decimal("7.80"),
                pressure_kpa=Decimal("235.00"),
                notes="cold",
            ),
            TireReading(
                tire_id=mounted.id,
                vin=vin,
                position="FL",
                mount_period_id=open_.id,
                recorded_at=date(2026, 10, 5),
                pressure_kpa=Decimal("240.00"),
            ),
            TireReading(
                tire_id=stored.id,
                vin=vin,
                recorded_at=date(2026, 4, 20),
                tread_depth_mm=Decimal("5"),
            ),
        ]
    )
    await db_session.commit()


_TIRE_SKIP = {"id", "vin", "set_id", "created_at", "updated_at"}
_PERIOD_SKIP = {"id", "tire_id", "created_at"}
_READING_SKIP = {"id", "tire_id", "vin", "mount_period_id", "created_at"}


def _columns(row: Any, skip: set[str]) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key not in skip}


async def _tires(db_session: AsyncSession, vin: str) -> list[dict[str, Any]]:
    """The vehicle's tires as portable content: ids out, links as names and indices."""
    db_session.expire_all()
    tires = (
        (await db_session.execute(select(Tire).where(Tire.vin == vin).order_by(Tire.id)))
        .scalars()
        .all()
    )
    view = []
    for tire in tires:
        periods = (
            (
                await db_session.execute(
                    select(TireMountPeriod)
                    .where(TireMountPeriod.tire_id == tire.id)
                    .order_by(TireMountPeriod.id)
                )
            )
            .scalars()
            .all()
        )
        index = {p.id: i for i, p in enumerate(periods)}
        readings = (
            (
                await db_session.execute(
                    select(TireReading)
                    .where(TireReading.tire_id == tire.id)
                    .order_by(TireReading.id)
                )
            )
            .scalars()
            .all()
        )
        tire_set = await db_session.get(TireSet, tire.set_id) if tire.set_id else None
        view.append(
            {
                **_columns(tire, _TIRE_SKIP),
                "set": (tire_set.name, tire_set.notes) if tire_set else None,
                "periods": [_columns(p, _PERIOD_SKIP) for p in periods],
                "readings": [
                    {
                        **_columns(r, _READING_SKIP),
                        "period": index.get(r.mount_period_id),
                        "vin_matches": r.vin == vin,
                    }
                    for r in readings
                ],
            }
        )
    return view


async def _low_tread(db_session: AsyncSession, vin: str) -> list[Reminder]:
    db_session.expire_all()
    return list(
        (
            await db_session.execute(
                select(Reminder)
                .where(Reminder.vin == vin, Reminder.source == "low_tread")
                .order_by(Reminder.id)
            )
        )
        .scalars()
        .all()
    )


def _period(position: str, mounted_on: str, dismounted_on: str | None = None) -> dict[str, Any]:
    return {"position": position, "mounted_on": mounted_on, "dismounted_on": dismounted_on}


def _mounted(position: str, **over: Any) -> dict[str, Any]:
    return {
        "position": position,
        "min_tread_mm": 2.0,
        "mount_periods": [_period(position, "2026-01-01")],
        **over,
    }


# -- J1 / G4-13: the family comes back whole ------------------------------------


async def test_tires_round_trip_into_an_empty_vehicle(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    source = await new_vehicle()
    target = await new_vehicle()
    await _seed(db_session, source)

    backup = await export_json(client, auth_headers, source)
    data = await import_json(client, auth_headers, target, backup)

    assert data["tire_sets"]["success_count"] == 1
    assert data["tires"]["success_count"] == 2
    assert data["errors"] == []
    # main: the target has no tires, the backup carried none.
    assert await _tires(db_session, target) == await _tires(db_session, source)


async def test_the_export_writes_indices_not_ids(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    await _seed(db_session, vin)
    backup = await export_json(client, auth_headers, vin)
    # main: KeyError, no tire_sets section.
    assert backup["tire_sets"] == [{"name": "Winter", "notes": "studded"}]
    mounted = backup["tires"][0]
    assert mounted["set_index"] == 0
    assert [p["position"] for p in mounted["mount_periods"]] == ["FR", "FL"]
    assert [r["mount_period_index"] for r in mounted["readings"]] == [None, 0, 1]
    assert backup["tires"][1]["set_index"] is None


async def test_the_export_orders_periods_by_id_not_by_date(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    # The relationship sorts periods by mounted_on; an index has to mean the same row every time (S2).
    vin = await new_vehicle()
    tire = Tire(vin=vin)
    db_session.add(tire)
    await db_session.flush()
    later_mount = TireMountPeriod(
        tire_id=tire.id,
        position="RL",
        mounted_on=date(2026, 3, 1),
        dismounted_on=date(2026, 4, 1),
    )
    db_session.add(later_mount)
    await db_session.flush()
    # Entered second, mounted first.
    earlier_mount = TireMountPeriod(
        tire_id=tire.id,
        position="FR",
        mounted_on=date(2025, 1, 1),
        dismounted_on=date(2025, 2, 1),
    )
    db_session.add(earlier_mount)
    await db_session.flush()
    db_session.add(
        TireReading(
            tire_id=tire.id,
            vin=vin,
            position="FR",
            mount_period_id=earlier_mount.id,
            recorded_at=date(2025, 1, 15),
            tread_depth_mm=Decimal("7"),
        )
    )
    await db_session.commit()

    [row] = (await export_json(client, auth_headers, vin))["tires"]
    assert [p["position"] for p in row["mount_periods"]] == ["RL", "FR"]
    assert [r["mount_period_index"] for r in row["readings"]] == [1]


# -- N-2: a mounted tire below its minimum raises the reminder at import ---------


async def test_a_mounted_tire_below_its_minimum_raises_one_reminder(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    payload = {
        **V9,
        "tires": [
            _mounted(
                "FL",
                tread_depth_mm=1.5,
                readings=[
                    {"recorded_at": "2026-06-01", "tread_depth_mm": 1.5, "mount_period_index": 0}
                ],
            ),
            # Off the vehicle: no reminder (D3a).
            {"position": None, "tread_depth_mm": 1.0, "min_tread_mm": 2.0},
        ],
    }
    await import_json(client, auth_headers, vin, payload)
    [fl] = [t for t in await _tires(db_session, vin) if t["position"] == "FL"]
    rows = await _low_tread(db_session, vin)
    # main: no tires, so no reminder.
    assert [(r.title, r.status, r.tread_depth_mm) for r in rows] == [
        ("Tire tread low (FL)", "pending", Decimal("1.50"))
    ]
    stored_fl = (
        await db_session.execute(select(Tire).where(Tire.vin == vin, Tire.position == "FL"))
    ).scalar_one()
    assert rows[0].tire_id == stored_fl.id
    assert fl["readings"][0]["period"] == 0


async def test_a_null_minimum_stays_null_and_raises_nothing(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    # A present null means no threshold. The model's 2.0 default mustn't fill it in (R1-F1).
    source = await new_vehicle()
    target = await new_vehicle()
    payload = {**V9, "tires": [_mounted("FL", min_tread_mm=None, tread_depth_mm=0.5)]}
    await import_json(client, auth_headers, source, payload)
    # main: nothing imported, so nothing to unpack.
    [tire] = await _tires(db_session, source)
    assert tire["min_tread_mm"] is None
    assert await _low_tread(db_session, source) == []

    backup = await export_json(client, auth_headers, source)
    assert backup["tires"][0]["min_tread_mm"] is None
    await import_json(client, auth_headers, target, backup)
    [copy] = await _tires(db_session, target)
    assert copy["min_tread_mm"] is None
    assert await _low_tread(db_session, target) == []


async def test_an_absent_minimum_takes_the_column_default(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    # Only a present null clears it; no key at all is the 2.0 a new tire gets.
    vin = await new_vehicle()
    await import_json(client, auth_headers, vin, {**V9, "tires": [{"brand": "Spare"}]})
    # main: nothing imported, so nothing to unpack.
    [tire] = await _tires(db_session, vin)
    assert tire["min_tread_mm"] == Decimal("2.00")


async def test_a_reimport_into_the_source_skips_its_tires(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    await import_json(
        client, auth_headers, vin, {**V9, "tires": [_mounted("FL", tread_depth_mm=1.5)]}
    )
    before = await _tires(db_session, vin)
    backup = await export_json(client, auth_headers, vin)

    data = await import_json(client, auth_headers, vin, backup)
    # main: KeyError, there is no tires bucket.
    assert data["tires"]["skipped_count"] == 1
    assert data["warnings"] == [
        "Tires: this vehicle already has tires, so the file's tires weren't imported"
    ]
    assert await _tires(db_session, vin) == before
    assert len(await _low_tread(db_session, vin)) == 1


async def test_one_empty_tire_set_on_the_target_skips_the_files_tires(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    db_session.add(TireSet(vin=vin, name="Spare set"))
    await db_session.commit()
    data = await import_json(
        client, auth_headers, vin, {**V9, "tire_sets": [{"name": "A"}], "tires": [_mounted("FL")]}
    )
    # main: no warning; the sections are never read.
    assert data["warnings"] == [
        "Tires: this vehicle already has tires, so the file's tires weren't imported"
    ]
    assert data["tire_sets"]["skipped_count"] == 1
    assert data["tires"]["skipped_count"] == 1
    assert await _tires(db_session, vin) == []


_TWO_LOW = {
    **V9,
    "tires": [
        _mounted("FL", tread_depth_mm=1.5),
        _mounted("FR", tread_depth_mm=1.0),
    ],
}


async def test_a_failed_low_tread_sync_keeps_the_tires(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    async def broken(*_: Any) -> None:
        raise RuntimeError("sync failed")

    monkeypatch.setattr(vehicle_json, "sync_imported_tires", broken)
    caplog.set_level(logging.WARNING)
    vin = await new_vehicle()

    data = await import_json(client, auth_headers, vin, _TWO_LOW)

    assert data["tires"]["success_count"] == 2
    assert [t["position"] for t in await _tires(db_session, vin)] == ["FL", "FR"]
    assert await _low_tread(db_session, vin) == []
    assert any("low-tread sync failed" in r.getMessage() for r in caplog.records)


async def test_one_tire_failing_its_sync_leaves_the_others_reminder(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    real = json_tires.sync_low_tread_reminder
    calls: list[int] = []

    async def first_one_fails(db: AsyncSession, tire: Tire) -> bool:
        # Writes its reminder, then raises: the savepoint has to take the reminder back.
        calls.append(tire.id)
        changed = await real(db, tire)
        if len(calls) == 1:
            raise RuntimeError("sync failed")
        return changed

    monkeypatch.setattr(json_tires, "sync_low_tread_reminder", first_one_fails)
    caplog.set_level(logging.WARNING)
    vin = await new_vehicle()

    await import_json(client, auth_headers, vin, _TWO_LOW)

    assert len(calls) == 2
    assert [t["position"] for t in await _tires(db_session, vin)] == ["FL", "FR"]
    assert [r.title for r in await _low_tread(db_session, vin)] == ["Tire tread low (FR)"]
    assert any("low-tread sync failed" in r.getMessage() for r in caplog.records)


# -- N-4, S4, R6: a bad row refuses the whole family ----------------------------

_ONE_SET: list[dict[str, Any]] = [{"name": "Only"}]

_REFUSED = [
    pytest.param(
        [_mounted("FL", mount_periods=[_period("FL", "2026-01-01"), _period("FR", "2026-02-01")])],
        "Tire 0: has more than one open mount period",
        _ONE_SET,
        id="two-open-periods",
    ),
    pytest.param(
        [_mounted("FL", mount_periods=[_period("FL", "2026-01-01", "2026-02-01")])],
        "Tire 0: is mounted at FL but has no open mount period",
        _ONE_SET,
        id="mounted-no-open-period",
    ),
    pytest.param(
        [_mounted("FL", mount_periods=[_period("RR", "2026-01-01")])],
        "Tire 0: is mounted at FL but its open mount period is at RR",
        _ONE_SET,
        id="open-period-elsewhere",
    ),
    pytest.param(
        [{"position": None, "mount_periods": [_period("FL", "2026-01-01")]}],
        "Tire 0: is off the vehicle but has an open mount period",
        _ONE_SET,
        id="stored-with-open-period",
    ),
    pytest.param(
        [_mounted("FL", retired_on="2026-05-01")],
        "Tire 0: is retired but still mounted",
        _ONE_SET,
        id="retired-but-mounted",
    ),
    pytest.param(
        [_mounted("FL"), {"position": None}, _mounted("FL")],
        "Tire 2: FL is taken by tire 0",
        _ONE_SET,
        id="two-tires-one-corner",
    ),
    pytest.param(
        [_mounted("FL", set_index=1)],
        "Tire 0: set_index must be the index of a tire set in this file",
        _ONE_SET,
        id="set-index-out-of-range",
    ),
    pytest.param(
        [_mounted("FL", set_index=True)],
        "Tire 0: set_index must be the index of a tire set in this file",
        _ONE_SET,
        id="set-index-true",
    ),
    pytest.param(
        [
            _mounted("FL"),
            {
                "position": None,
                "readings": [
                    {"recorded_at": "2026-02-01", "pressure_kpa": 200, "mount_period_index": 0}
                ],
            },
        ],
        "Tire 1, reading 0: mount_period_index must be the index of a mount period of this tire",
        _ONE_SET,
        id="period-index-of-another-tire",
    ),
    pytest.param(
        [_mounted("FL", readings=[{"recorded_at": "2026-02-01", "odometer_km": 100}])],
        "Tire 0, reading 0: a reading needs a tread depth, a pressure, or both",
        _ONE_SET,
        id="reading-measures-nothing",
    ),
    pytest.param(
        [_mounted("FL", readings=[{"recorded_at": "2026-02-01", "tread_depth_mm": 31}])],
        "Tire 0, reading 0: tread_depth_mm must be at most 30, not 31",
        _ONE_SET,
        id="tread-past-the-api-bound",
    ),
    pytest.param(
        [_mounted("FL", mount_periods=[{"position": "XX", "mounted_on": "2026-01-01"}])],
        "Tire 0, mount period 0: position must be one of FL, FR, RL, RR, SPARE",
        _ONE_SET,
        id="period-position-word",
    ),
    pytest.param(
        [_mounted("FL", mount_periods=[{**_period("FL", "2026-01-01"), "is_assumed": "yes"}])],
        "Tire 0, mount period 0: is_assumed must be true or false",
        _ONE_SET,
        id="is-assumed-word",
    ),
    pytest.param(
        [_mounted("FL", readings="none")],
        "Tire 0: readings must be a list",
        _ONE_SET,
        id="readings-not-a-list",
    ),
    pytest.param(
        ["FL"],
        "Tire 0: must be an object",
        _ONE_SET,
        id="tire-not-an-object",
    ),
    pytest.param(
        [_mounted("FL")],
        "Tire set 0: name is missing",
        [{"notes": "no name"}],
        id="set-without-a-name",
    ),
    pytest.param(
        [_mounted("FL", mount_periods=[{"mounted_on": "2026-01-01"}])],
        "Tire 0, mount period 0: position is missing",
        _ONE_SET,
        id="period-without-a-position",
    ),
    pytest.param(
        [_mounted("FL", mount_periods=[{**_period("FL", "2026-01-01"), "mounted_hours": -1}])],
        "Tire 0, mount period 0: mounted_hours must be at least 0, not -1",
        _ONE_SET,
        id="period-hours-below-zero",
    ),
    pytest.param(
        [
            _mounted(
                "FL",
                readings=[{"recorded_at": "2026-02-01", "pressure_kpa": 200, "engine_hours": 1e9}],
            )
        ],
        "Tire 0, reading 0: engine_hours must be at most 999999999.9, not 1000000000.0",
        _ONE_SET,
        id="reading-hours-past-the-bound",
    ),
]


@pytest.mark.parametrize(("tires", "reason", "tire_sets"), _REFUSED)
async def test_a_bad_tire_refuses_the_family_and_writes_nothing(
    tires: list[Any],
    reason: str,
    tire_sets: list[dict[str, Any]],
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    vin = await new_vehicle()
    data = await import_json(
        client, auth_headers, vin, {**V9, "tire_sets": tire_sets, "tires": tires}
    )
    # main: the tires section is never read, so nothing is refused.
    assert data["errors"] == [f"{reason}, so the file's tires weren't imported"]
    assert data["tire_sets"]["error_count"] == 1
    assert data["tires"]["error_count"] == len(tires)
    assert await _tires(db_session, vin) == []
    assert (
        await db_session.execute(select(TireSet).where(TireSet.vin == vin))
    ).scalars().all() == []


async def test_a_retired_tire_restores_with_its_closed_periods(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    # N-7: no future-date or untracked-axis checks; a backup restores whole.
    vin = await new_vehicle(usage_unit="hours")
    payload = {
        **V9,
        "tires": [
            {
                "position": None,
                "retired_on": "2026-05-01",
                "min_tread_mm": 2.0,
                "mount_periods": [
                    {
                        "position": "RL",
                        "mounted_on": "2025-01-01",
                        "dismounted_on": "2026-05-01",
                        "mounted_odometer_km": 5000,
                        "dismounted_odometer_km": 9000,
                    }
                ],
            }
        ],
    }
    data = await import_json(client, auth_headers, vin, payload)
    assert data["errors"] == []
    [tire] = await _tires(db_session, vin)
    # main: nothing imported.
    assert tire["retired_on"] == date(2026, 5, 1)
    assert tire["periods"][0]["dismounted_odometer_km"] == Decimal("9000.00")
