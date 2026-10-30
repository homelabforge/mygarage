"""`repair_wican_odometer_unit.py`: fix a WiCAN odometer read in the wrong unit (FB-3, B6-10).

Two ways a unit-less WiCAN ends up wrong, and only the owner knows which:

- `--to km`: its bare `ODOMETER` really is km, but main read it as miles, so
  migration 133 kept that (legacy row) and everything stored is 1.609x high.
- `--to mi`: it really reports miles, but 3.10 reads a bare `ODOMETER` as km
  from its first frame, so everything stored is 1.609x low, and the 409 on a
  unit change left no way out.

Each test builds the real schema with `create_all`, on SQLite and on PG (its
own schema, so the shared test database isn't touched). `plan_repair` and
`apply_repair` take a connection, so both dialects run the tool's own SQL;
`main` is driven on SQLite for the CLI half.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TypedDict

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.database import Base
from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_device_unit import LiveLinkDeviceUnit
from app.models.odometer import OdometerRecord
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.utils.pg_session import create_utc_async_engine, create_utc_engine

CREATED = datetime(2026, 6, 1, 0, 0, 0)
T0 = datetime(2026, 9, 1, 10, 0, 0)

#: Migration 133 as the runner records it.
_MIGRATION = "133_record_wican_legacy_odometer_unit"


def _pg_url() -> str | None:
    raw = os.getenv("TEST_DATABASE_URL", "").strip()
    if not raw:
        return None
    return raw.replace("postgresql+asyncpg", "postgresql+psycopg2").replace(
        "postgresql://", "postgresql+psycopg2://", 1
    )


@pytest.fixture(params=["sqlite", "pg"])
def engine(request, tmp_path) -> Generator[Engine]:
    """The whole schema, plus `schema_migrations` with 133 applied."""
    schema: str | None = None
    if request.param == "sqlite":
        eng = create_engine(f"sqlite:///{tmp_path / 'mygarage.db'}")
    else:
        url = _pg_url()
        if url is None:
            pytest.skip("TEST_DATABASE_URL not set: PG runs in the docker-compose.test.yml stack")
        schema = f"repair_{uuid.uuid4().hex[:12]}"
        with create_utc_engine(url).begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        eng = create_utc_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE schema_migrations (migration_name VARCHAR(255))"))
        conn.execute(text("INSERT INTO schema_migrations VALUES (:n)"), {"n": _MIGRATION})
    try:
        yield eng
    finally:
        eng.dispose()
        if schema is not None:
            url = _pg_url()
            assert url is not None
            cleanup = create_utc_engine(url)
            with cleanup.begin() as conn:
                conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            cleanup.dispose()


_n = 0


def _vehicle(s: Session, vin: str) -> None:
    global _n
    _n += 1
    user = User(
        username=f"rep_{_n}", email=f"rep_{_n}@example.com", hashed_password="x", is_active=True
    )
    s.add(user)
    s.flush()
    s.add(Vehicle(vin=vin, user_id=user.id, nickname=vin, vehicle_type="Car"))
    s.flush()


def _seed(
    engine: Engine,
    device_id: str,
    vin: str,
    values: list[float],
    *,
    legacy: str | None,
    key: str = "ODOMETER",
    **device: object,
) -> None:
    """One linked WiCAN with raw ODOMETER rows, its latest row, two livelink
    records and two sessions, plus a manual record and an A6-free VIN."""
    with Session(engine) as s:
        _vehicle(s, vin)
        device.setdefault("kind", "wican")
        device.setdefault("created_at", CREATED)
        s.add(LiveLinkDevice(device_id=device_id, vin=vin, enabled=True, **device))
        s.flush()
        for i, value in enumerate(values):
            at = T0 + timedelta(minutes=i)
            s.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key=key,
                    value=value,
                    timestamp=at,
                    received_at=at,
                )
            )
        s.add(
            VehicleTelemetryLatest(
                vin=vin,
                param_key=key,
                value=values[-1],
                timestamp=T0 + timedelta(minutes=len(values) - 1),
                received_at=T0,
            )
        )
        s.add_all(
            [
                OdometerRecord(
                    vin=vin,
                    date=date(2026, 9, 1),
                    odometer_km=values[0],
                    source="livelink",
                    notes=f"Auto-recorded from LiveLink ({key})",
                    created_at=T0,
                ),
                OdometerRecord(
                    vin=vin,
                    date=date(2026, 9, 2),
                    odometer_km=values[-1],
                    source="livelink",
                    notes=f"Auto-updated from LiveLink ({key})",
                    created_at=T0,
                ),
                # A human's number is never touched.
                OdometerRecord(
                    vin=vin,
                    date=date(2026, 8, 1),
                    odometer_km=12345,
                    source="manual",
                    created_at=T0,
                ),
            ]
        )
        s.add_all(
            [
                # Distance from the odometer delta: scales with it.
                DriveSession(
                    vin=vin,
                    device_id=device_id,
                    started_at=T0,
                    ended_at=T0 + timedelta(hours=1),
                    start_odometer=values[0],
                    end_odometer=values[-1],
                    distance_km=values[-1] - values[0],
                ),
                # Distance from a finer counter, not the odometer: left alone.
                DriveSession(
                    vin=vin,
                    device_id=device_id,
                    started_at=T0 + timedelta(hours=2),
                    ended_at=T0 + timedelta(hours=3),
                    start_odometer=values[-1],
                    end_odometer=values[-1],
                    distance_km=0.4,
                ),
            ]
        )
        if legacy:
            s.add(
                LiveLinkDeviceUnit(
                    device_id=device_id,
                    param_key=key,
                    unit=legacy,
                    param_class="distance",
                    source="legacy",
                )
            )
        s.commit()


class _Snapshot(TypedDict):
    raw: list[float]
    latest: float | None
    records: list[tuple[str, float]]
    sessions: list[tuple[float | None, ...]]
    units: list[tuple[object, ...]]


def _snapshot(engine: Engine, device_id: str, vin: str) -> _Snapshot:
    with Session(engine) as s:
        raw = s.scalars(
            select(VehicleTelemetry.value)
            .where(VehicleTelemetry.device_id == device_id)
            .order_by(VehicleTelemetry.timestamp)
        ).all()
        latest = s.scalar(
            select(VehicleTelemetryLatest.value).where(VehicleTelemetryLatest.vin == vin)
        )
        records = s.execute(
            select(OdometerRecord.source, OdometerRecord.odometer_km)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date)
        ).all()
        sessions = s.execute(
            select(DriveSession.start_odometer, DriveSession.end_odometer, DriveSession.distance_km)
            .where(DriveSession.device_id == device_id)
            .order_by(DriveSession.started_at)
        ).all()
        units = s.execute(
            select(
                LiveLinkDeviceUnit.param_key, LiveLinkDeviceUnit.unit, LiveLinkDeviceUnit.source
            ).where(LiveLinkDeviceUnit.device_id == device_id)
        ).all()
    return {
        "raw": [float(v) for v in raw],
        "latest": float(latest) if latest is not None else None,
        "records": [(src, float(km)) for src, km in records],
        "sessions": [tuple(None if v is None else float(v) for v in row) for row in sessions],
        "units": sorted(tuple(u) for u in units),
    }


def _plan(engine: Engine, device_id: str, to: str, key: str = "ODOMETER", **kw: object):
    from tools.repair_wican_odometer_unit import plan_repair

    with engine.connect() as conn:
        return plan_repair(conn, device_id, key, to, **kw)


def _apply(engine: Engine, device_id: str, to: str, key: str = "ODOMETER", **kw: object) -> None:
    from tools.repair_wican_odometer_unit import apply_repair, plan_repair

    with engine.begin() as conn:
        apply_repair(conn, plan_repair(conn, device_id, key, to, **kw))


MILES = Decimal("1.609344")


def _up(km: float) -> float:
    """What a device on `mi` stored for a true km reading, as ingest writes it."""
    return float(Decimal(str(km)) * MILES)


def _down(value: float) -> float:
    """A reading stored 1.609x high, back in km, unrounded."""
    return float(Decimal(str(value)) / MILES)


# --- --to km: really km, read as miles (B6-10) ---------------------------------

#: 50,000 and 50,020.4 km read as miles: what main stored.
INFLATED = [80467.0, 80500.0]


def test_to_km_plans_exactly_the_deflation(engine):
    _seed(engine, "legacykm", "REPAIRVINKM000001", INFLATED, legacy="mi")
    before = _snapshot(engine, "legacykm", "REPAIRVINKM000001")

    plan = _plan(engine, "legacykm", "km")

    assert plan.unit_action == ("drop", None)
    assert plan.raw == [(80467.0, _down(80467.0)), (80500.0, _down(80500.0))]
    assert plan.latest == (80500.0, _down(80500.0))
    # Records alone are whole km, as ingest writes them.
    assert [(old, new) for _id, old, new in plan.records] == [
        (80467.0, 50000.0),
        (80500.0, 50020.0),
    ]
    starts_ends = [(s.start, s.end) for s in plan.sessions]
    assert starts_ends == [
        ((80467.0, _down(80467.0)), (80500.0, _down(80500.0))),
        ((80500.0, _down(80500.0)), (80500.0, _down(80500.0))),
    ]
    assert plan.sessions[0].distance == (33.0, pytest.approx(33 / 1.609344))
    assert plan.sessions[1].distance is None  # a counter's distance, not the odometer's
    # A plan writes nothing.
    assert _snapshot(engine, "legacykm", "REPAIRVINKM000001") == before


def test_to_km_applies_it_and_a_second_run_refuses(engine):
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "legacykm", "REPAIRVINKM000001", INFLATED, legacy="mi")

    _apply(engine, "legacykm", "km")

    after = _snapshot(engine, "legacykm", "REPAIRVINKM000001")
    assert after["raw"] == [_down(80467.0), _down(80500.0)]
    assert after["latest"] == _down(80500.0)
    assert after["records"] == [("manual", 12345.0), ("livelink", 50000.0), ("livelink", 50020.0)]
    assert after["sessions"][0][:2] == (_down(80467.0), _down(80500.0))
    assert after["sessions"][0][2] == pytest.approx(33 / 1.609344)
    assert after["sessions"][1] == (_down(80500.0), _down(80500.0), 0.4)
    # No row left: bare ODOMETER reads km by the key rule.
    assert after["units"] == []

    with pytest.raises(RepairRefusedError, match="already reads km"):
        _plan(engine, "legacykm", "km")
    assert _snapshot(engine, "legacykm", "REPAIRVINKM000001") == after


# --- --to mi: really miles, read as km (FB-3) -----------------------------------

#: 50,000 and 50,020 mi read as km: what 3.10 stored for a fresh device.
DEFLATED = [50000.0, 50020.0]


def test_to_mi_plans_exactly_the_inflation(engine):
    _seed(engine, "freshmi", "REPAIRVINMI000001", DEFLATED, legacy=None)
    before = _snapshot(engine, "freshmi", "REPAIRVINMI000001")

    plan = _plan(engine, "freshmi", "mi")

    assert plan.unit_action == ("hold", "mi")
    assert plan.raw == [(50000.0, _up(50000.0)), (50020.0, _up(50020.0))]
    assert plan.latest == (50020.0, _up(50020.0))
    assert [(old, new) for _id, old, new in plan.records] == [
        (50000.0, 80467.0),
        (50020.0, 80499.0),
    ]
    assert plan.sessions[0].distance == (20.0, pytest.approx(20 * 1.609344))
    assert _snapshot(engine, "freshmi", "REPAIRVINMI000001") == before


def test_to_mi_applies_it_and_a_second_run_refuses(engine):
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "freshmi", "REPAIRVINMI000001", DEFLATED, legacy=None)

    _apply(engine, "freshmi", "mi")

    after = _snapshot(engine, "freshmi", "REPAIRVINMI000001")
    assert after["raw"] == [_up(50000.0), _up(50020.0)]
    assert after["latest"] == _up(50020.0)
    assert after["records"] == [("manual", 12345.0), ("livelink", 80467.0), ("livelink", 80499.0)]
    assert after["sessions"][0][:2] == (_up(50000.0), _up(50020.0))
    assert after["sessions"][0][2] == pytest.approx(20 * 1.609344)
    assert after["sessions"][1] == (_up(50020.0), _up(50020.0), 0.4)
    # Held as legacy, so a km boot config can't flip it back while it has history.
    assert after["units"] == [("ODOMETER", "mi", "legacy")]

    with pytest.raises(RepairRefusedError, match="already reads mi"):
        _plan(engine, "freshmi", "mi")


def test_to_mi_replaces_a_wire_km_declaration(engine):
    """A device that declared km in its boot config but sends miles: the
    owner's word wins, as a legacy row."""
    _seed(engine, "wiredkm", "REPAIRVINWIRE0001", DEFLATED, legacy=None)
    with Session(engine) as s:
        s.add(
            LiveLinkDeviceUnit(
                device_id="wiredkm",
                param_key="ODOMETER",
                unit="km",
                param_class="distance",
                source="wire",
            )
        )
        s.commit()

    _apply(engine, "wiredkm", "mi")

    assert _snapshot(engine, "wiredkm", "REPAIRVINWIRE0001")["units"] == [
        ("ODOMETER", "mi", "legacy")
    ]


# --- What it refuses -------------------------------------------------------------


def test_it_refuses_a_device_with_a_device_wide_unit(engine):
    """`odometer_unit` beats every per-key row, so a per-key repair can't
    change how the device reads."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "unitset", "REPAIRVINUNIT0001", INFLATED, legacy=None, odometer_unit="mi")

    with pytest.raises(RepairRefusedError, match="odometer_unit"):
        _plan(engine, "unitset", "km")


def test_it_refuses_a_key_another_device_on_the_vehicle_also_reports(engine):
    """Records and the latest row are per vehicle, so they can't be split
    between two devices reporting one key."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "first", "REPAIRVINSHARED01", INFLATED, legacy="mi")
    with Session(engine) as s:
        s.add(
            LiveLinkDevice(device_id="second", vin="REPAIRVINSHARED01", kind="wican", enabled=True)
        )
        s.add(
            VehicleTelemetry(
                vin="REPAIRVINSHARED01",
                device_id="second",
                param_key="ODOMETER",
                value=50000.0,
                timestamp=T0,
                received_at=T0,
            )
        )
        s.commit()

    with pytest.raises(RepairRefusedError, match="second"):
        _plan(engine, "first", "km")


def test_it_refuses_a_device_with_a_second_odometer_key(engine):
    """A session's odometer may have come from either key, so which ones to
    scale can't be told apart."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "twokeys", "REPAIRVINTWOKEYS1", INFLATED, legacy="mi")
    with Session(engine) as s:
        s.add(
            VehicleTelemetry(
                vin="REPAIRVINTWOKEYS1",
                device_id="twokeys",
                param_key="A6-ODOMETER",
                value=50000.0,
                timestamp=T0,
                received_at=T0,
            )
        )
        s.commit()

    with pytest.raises(RepairRefusedError, match="A6-ODOMETER"):
        _plan(engine, "twokeys", "km")


def test_it_refuses_a_series_that_mixes_units(engine):
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "mixed", "REPAIRVINMIXED001", [50000.0, 80467.0], legacy="mi")

    with pytest.raises(RepairRefusedError, match="mixes"):
        _plan(engine, "mixed", "km")


def test_it_refuses_before_migration_133_has_run(engine):
    """133 would write a legacy row after the repair and undo it."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "early", "REPAIRVINEARLY001", INFLATED, legacy=None)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM schema_migrations"))

    with pytest.raises(RepairRefusedError, match="133"):
        _plan(engine, "early", "mi")


# --- Fix round 1 -----------------------------------------------------------------


def test_it_repairs_a_key_main_matched_by_substring(engine):
    """I1: `ODOMETER_KM` was converted and recorded as an odometer on main and
    still is, so it's one the tool repairs. Its key rule reads miles, so km is
    held as a legacy row. Red on 5a013d2e ("isn't this device's odometer")."""
    _seed(engine, "odokm", "REPAIRVINODOKM001", INFLATED, legacy="mi", key="ODOMETER_KM")

    _apply(engine, "odokm", "km", key="ODOMETER_KM")

    after = _snapshot(engine, "odokm", "REPAIRVINODOKM001")
    assert after["raw"] == [_down(80467.0), _down(80500.0)]
    assert after["units"] == [("ODOMETER_KM", "km", "legacy")]


def test_to_km_holds_a_mileage_key_in_km(engine):
    """Regression guard (M4): a bare key whose rule is miles can't just lose
    its row, so km is held. Kills a plan that always drops."""
    _seed(engine, "mileage", "REPAIRVINMILEAGE1", INFLATED, legacy="mi", key="MILEAGE")

    plan = _plan(engine, "mileage", "km", key="MILEAGE")

    assert plan.unit_action == ("hold", "km")
    _apply(engine, "mileage", "km", key="MILEAGE")
    assert _snapshot(engine, "mileage", "REPAIRVINMILEAGE1")["units"] == [
        ("MILEAGE", "km", "legacy")
    ]


def test_to_km_over_a_wire_declaration_survives_the_next_boot(engine):
    """I2: the device's own config says mi but it really sends km. Dropping
    the `wire` row let the next boot put it back, so new readings landed 1.609x
    above the repaired history. A legacy km row is held against the boot's
    re-declaration instead. Red on 5a013d2e."""
    import asyncio

    from app.database import is_sqlite

    if is_sqlite != (engine.dialect.name == "sqlite"):
        pytest.skip("ingest runs on the dialect the app was imported for")
    _seed(engine, "wiredmi", "REPAIRVINWIREDMI1", INFLATED, legacy=None)
    with Session(engine) as s:
        s.add(
            LiveLinkDeviceUnit(
                device_id="wiredmi",
                param_key="ODOMETER",
                unit="mi",
                param_class="distance",
                source="wire",
            )
        )
        s.add(Setting(key="livelink_enabled", value="true"))
        s.commit()

    _apply(engine, "wiredmi", "km")
    asyncio.run(_boot(engine, "wiredmi", {"ODOMETER": {"class": "distance", "unit": "mi"}}, 50030))

    after = _snapshot(engine, "wiredmi", "REPAIRVINWIREDMI1")
    assert after["units"] == [("ODOMETER", "km", "legacy")]
    assert after["raw"][-1] == 50030.0


async def _boot(engine: Engine, device_id: str, config: dict, odometer: float) -> None:
    """A WiCAN boot POST through real ingest, on the test's own database."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import configure_sqlite_engine
    from app.schemas.livelink_ingest import WiCANPayload
    from app.services.livelink_ingest import ingest
    from app.services.livelink_sources.base import WicanHttpsEnvelope
    from app.services.livelink_sources.wican import WicanModule

    url = engine.url.render_as_string(hide_password=False)
    if engine.dialect.name == "sqlite":
        async_engine = create_async_engine(url.replace("sqlite://", "sqlite+aiosqlite://", 1))
        configure_sqlite_engine(async_engine)
    else:
        # The fixture's own schema, which the sync engine reaches by search_path.
        with engine.connect() as conn:
            schema = conn.execute(text("SELECT current_schema()")).scalar_one()
        async_engine = create_utc_async_engine(
            url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1),
            connect_args={"server_settings": {"search_path": schema}},
        )
    payload = WiCANPayload.model_validate(
        {
            "autopid_data": {"ODOMETER": odometer},
            "config": config,
            "status": {"device_id": device_id, "ecu_status": "online"},
        }
    )
    try:
        async with async_sessionmaker(async_engine, expire_on_commit=False)() as db:
            await ingest(WicanModule(), WicanHttpsEnvelope(device_id, payload), db)
            await db.commit()
    finally:
        await async_engine.dispose()


def test_it_leaves_an_earlier_dongles_records_and_another_vins_rows_alone(engine):
    """M1: records are the vehicle's, so only those dated in this device's
    window on it are rescaled; an earlier dongle's true km stay. Raw rows on
    a car this device was linked to before belong to that car's history. Red
    on 5a013d2e, which rescaled both."""
    _seed(engine, "newdongle", "REPAIRVINWINDOW01", INFLATED, legacy="mi")
    with Session(engine) as s:
        s.add(
            OdometerRecord(
                vin="REPAIRVINWINDOW01",
                date=date(2026, 3, 1),
                odometer_km=40000,
                source="livelink",
                notes="Auto-recorded from LiveLink (ODOMETER)",
                created_at=datetime(2026, 3, 1),
            )
        )
        _vehicle(s, "REPAIRVINOLDCAR01")
        s.add(
            VehicleTelemetry(
                vin="REPAIRVINOLDCAR01",
                device_id="newdongle",
                param_key="ODOMETER",
                value=12345.0,
                timestamp=datetime(2026, 7, 1),
                received_at=datetime(2026, 7, 1),
            )
        )
        s.commit()

    _apply(engine, "newdongle", "km")

    after = _snapshot(engine, "newdongle", "REPAIRVINWINDOW01")
    assert after["records"] == [
        ("livelink", 40000.0),
        ("manual", 12345.0),
        ("livelink", 50000.0),
        ("livelink", 50020.0),
    ]
    assert sorted(after["raw"]) == [12345.0, _down(80467.0), _down(80500.0)]


def test_it_refuses_a_device_that_went_back_and_forth_between_vehicles(engine):
    """Regression guard (wave A re-review T1): it reported on this vehicle,
    then on another one after that, so its window here has a hole in it and
    which records it wrote can't be told. Kills dropping the check (the
    reviewer's `if False and ...` mutant left this file green)."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "bandf", "REPAIRVINBANDF001", INFLATED, legacy="mi")
    with Session(engine) as s:
        _vehicle(s, "REPAIRVINFORMER02")
        s.add(
            VehicleTelemetry(
                vin="REPAIRVINFORMER02",
                device_id="bandf",
                param_key="COOLANT",
                value=90.0,
                timestamp=T0 + timedelta(days=3),
                received_at=T0 + timedelta(days=3),
            )
        )
        s.commit()

    with pytest.raises(RepairRefusedError, match="another vehicle after"):
        _plan(engine, "bandf", "km")


def test_it_refuses_when_another_device_on_the_vehicle_recorded_in_its_window(engine):
    """M1: raw rows prune at 90 days, so a second WiCAN on the car is found by
    what doesn't: its link and its sessions with odometers. Red on 5a013d2e,
    which looked at raw rows only."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "firstdev", "REPAIRVINTWINS001", INFLATED, legacy="mi")
    with Session(engine) as s:
        s.add(
            LiveLinkDevice(device_id="twindev", vin="REPAIRVINTWINS001", kind="wican", enabled=True)
        )
        s.add(
            DriveSession(
                vin="REPAIRVINTWINS001",
                device_id="twindev",
                started_at=T0 + timedelta(days=1),
                ended_at=T0 + timedelta(days=1, hours=1),
                start_odometer=80600.0,
                end_odometer=80650.0,
            )
        )
        s.commit()

    with pytest.raises(RepairRefusedError, match="twindev"):
        _plan(engine, "firstdev", "km")


def test_it_refuses_a_device_that_is_not_a_wican_or_a_torque_phone(engine):
    """Regression guard (M4): a per-key row changes nothing for another kind.
    Kills dropping the kind check. A Torque phone has its own path now (R10),
    so a generic sensor stands in for "another kind"."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "gendev", "REPAIRVINGENKIND1", INFLATED, legacy=None, kind="generic_mqtt")

    with pytest.raises(RepairRefusedError, match="WiCANs and Torque phones only"):
        _plan(engine, "gendev", "mi")


def test_it_refuses_an_unlinked_device(engine):
    """Regression guard (M4): records and the latest value are a vehicle's.
    Kills dropping the link check."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    with Session(engine) as s:
        s.add(LiveLinkDevice(device_id="loosedev", vin=None, kind="wican", enabled=True))
        s.commit()

    with pytest.raises(RepairRefusedError, match="isn't linked"):
        _plan(engine, "loosedev", "mi")


def test_it_refuses_a_key_that_is_not_an_odometer(engine):
    """Regression guard (M4): kills dropping the odometer-key check."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "coolant", "REPAIRVINCOOLANT1", [90.0, 91.0], legacy=None, key="COOLANT")

    with pytest.raises(RepairRefusedError, match="isn't this device's odometer"):
        _plan(engine, "coolant", "mi", key="COOLANT")


# --- Fix round 3 (N3) -------------------------------------------------------------


def test_the_window_starts_when_the_device_reached_this_vehicle(engine):
    """A device relinked from another car didn't record on this one before it
    left that one. So the window starts at its last reading elsewhere, not at
    its device-wide `created_at`, and an earlier dongle's record in between
    stays. Red on 4e32c6eb, which rescaled it."""
    _seed(
        engine,
        "relinked",
        "REPAIRVINARRIVED1",
        INFLATED,
        legacy="mi",
        created_at=datetime(2026, 1, 1),
    )
    with Session(engine) as s:
        _vehicle(s, "REPAIRVINFORMER01")
        s.add(
            VehicleTelemetry(
                vin="REPAIRVINFORMER01",
                device_id="relinked",
                param_key="COOLANT",
                value=90.0,
                timestamp=datetime(2026, 7, 1),
                received_at=datetime(2026, 7, 1),
            )
        )
        s.add(
            OdometerRecord(
                vin="REPAIRVINARRIVED1",
                date=date(2026, 5, 1),
                odometer_km=40000,
                source="livelink",
                notes="Auto-recorded from LiveLink (ODOMETER)",
                created_at=datetime(2026, 5, 1),
            )
        )
        s.commit()

    _apply(engine, "relinked", "km")

    records = _snapshot(engine, "relinked", "REPAIRVINARRIVED1")["records"]
    assert ("livelink", 40000.0) in records
    assert ("livelink", 50000.0) in records


def test_it_refuses_over_a_deleted_devices_odometer_sessions(engine):
    """A deleted dongle's drive sessions outlive it (no FK), and an odometer on
    one says it may have recorded the key here. Red on 4e32c6eb, which looked
    only at devices still on file."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "survivor", "REPAIRVINGHOST001", INFLATED, legacy="mi")
    with Session(engine) as s:
        s.add(
            DriveSession(
                vin="REPAIRVINGHOST001",
                device_id="ghostdev",
                started_at=T0 + timedelta(days=1),
                ended_at=T0 + timedelta(days=1, hours=1),
                start_odometer=80600.0,
                end_odometer=80650.0,
            )
        )
        s.commit()

    with pytest.raises(RepairRefusedError, match="ghostdev"):
        _plan(engine, "survivor", "km")


def test_it_refuses_over_a_generic_device_that_declares_the_key(engine):
    """The simple path records a declared key on any kind, so a generic sensor
    on the car that declares ODOMETER may have written its records. Red on
    4e32c6eb, whose `_could_record` said no for any kind but WiCAN and Torque."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "carwican", "REPAIRVINGENERIC1", INFLATED, legacy="mi")
    with Session(engine) as s:
        s.add(
            LiveLinkDevice(
                device_id="gendecl",
                vin="REPAIRVINGENERIC1",
                kind="generic_mqtt",
                enabled=True,
                odometer_param_key="ODOMETER",
            )
        )
        s.commit()

    with pytest.raises(RepairRefusedError, match="gendecl"):
        _plan(engine, "carwican", "km")


# --- The command line (SQLite) ---------------------------------------------------


def test_the_cli_dry_runs_by_default_then_applies_then_refuses(tmp_path, monkeypatch, capsys):
    from tools import repair_wican_odometer_unit as tool

    db = tmp_path / "mygarage.db"
    eng = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE schema_migrations (migration_name VARCHAR(255))"))
        conn.execute(text("INSERT INTO schema_migrations VALUES (:n)"), {"n": _MIGRATION})
    _seed(eng, "clidev", "REPAIRVINCLI00001", INFLATED, legacy="mi")
    before = _snapshot(eng, "clidev", "REPAIRVINCLI00001")

    def run(*extra: str) -> int:
        monkeypatch.setattr(
            "sys.argv", ["repair", "--db", str(db), "--device-id", "clidev", "--to", "km", *extra]
        )
        return tool.main()

    assert run() == 0
    out = capsys.readouterr().out
    assert "Back up" in out and "DRY RUN" in out
    assert "80,467 -> 50,000" in out
    assert _snapshot(eng, "clidev", "REPAIRVINCLI00001") == before

    assert run("--apply") == 0
    assert _snapshot(eng, "clidev", "REPAIRVINCLI00001")["raw"] == [_down(80467.0), _down(80500.0)]
    capsys.readouterr()

    assert run("--apply") == 2
    assert "already reads km" in capsys.readouterr().out
    eng.dispose()


# --- Both paths: precision and daily summaries (R10) ------------------------------


def _summary(
    s: Session, vin: str, day: date, values: list[float], count: int, key: str = "ODOMETER"
) -> None:
    """A daily summary as the 01:00 job writes it, from ``values``."""
    s.add(
        TelemetryDailySummary(
            vin=vin,
            param_key=key,
            date=datetime.combine(day, time()),
            min_value=min(values),
            max_value=max(values),
            avg_value=sum(values) / len(values),
            sample_count=count,
        )
    )


def _summaries(engine: Engine, vin: str, key: str = "ODOMETER") -> dict[date, tuple]:
    with Session(engine) as s:
        rows = s.execute(
            select(
                TelemetryDailySummary.date,
                TelemetryDailySummary.min_value,
                TelemetryDailySummary.max_value,
                TelemetryDailySummary.avg_value,
                TelemetryDailySummary.sample_count,
            ).where(TelemetryDailySummary.vin == vin, TelemetryDailySummary.param_key == key)
        ).all()
    return {day.date(): (lo, hi, avg, n) for day, lo, hi, avg, n in rows}


def test_readings_keep_their_fraction_and_records_stay_whole_km(engine):
    """R1-H1: raw, latest and session odometers keep their fraction, as ingest
    stores them; only records are whole km. Red on f1986ea5, whose `_reading`
    rounded all four (100000, not 100000.31)."""
    _seed(engine, "fracdev", "REPAIRVINFRAC0001", [160934.9, 160966.0], legacy="mi")

    plan = _plan(engine, "fracdev", "km")

    assert plan.raw[0] == (160934.9, pytest.approx(100000.3107, abs=1e-4))
    assert plan.latest == (160966.0, pytest.approx(100019.6353, abs=1e-4))
    assert plan.sessions[0].start == (160934.9, pytest.approx(100000.3107, abs=1e-4))
    assert [new for _id, _old, new in plan.records] == [100000.0, 100020.0]

    _apply(engine, "fracdev", "km")
    after = _snapshot(engine, "fracdev", "REPAIRVINFRAC0001")
    assert after["raw"][0] == pytest.approx(100000.3107, abs=1e-4)
    assert after["records"][1:] == [("livelink", 100000.0), ("livelink", 100020.0)]


SUMVIN = "REPAIRVINSUMMARY1"


def test_wican_summaries_scale_after_the_window_start_and_rebuild_its_day(engine):
    """R1-M2: a day before the window start is untouched, the days after it
    are scaled, and its own day is rebuilt from the surviving rows: an earlier
    dongle's 08:00 true-km reading stays, this one's are scaled. Red under a
    plain `date >= since.date()` scale, and on f1986ea5, which left summaries
    alone."""
    _seed(engine, "sumdev", SUMVIN, INFLATED, legacy="mi", created_at=datetime(2026, 9, 1, 9))
    with Session(engine) as s:
        s.add(
            VehicleTelemetry(
                vin=SUMVIN,
                device_id="olddongle",
                param_key="ODOMETER",
                value=49990.0,
                timestamp=datetime(2026, 9, 1, 8),
                received_at=datetime(2026, 9, 1, 8),
            )
        )
        _summary(s, SUMVIN, date(2026, 8, 31), [49900.0, 49990.0], 40)
        _summary(s, SUMVIN, date(2026, 9, 1), [49990.0, *INFLATED], 3)
        _summary(s, SUMVIN, date(2026, 9, 2), [80500.0], 1)
        s.commit()

    plan = _plan(engine, "sumdev", "km")
    assert sorted(c.how for c in plan.summaries) == ["rebuilt", "scaled"]
    _apply(engine, "sumdev", "km")

    sums = _summaries(engine, SUMVIN)
    assert sums[date(2026, 8, 31)] == (49900.0, 49990.0, 49945.0, 40)
    mine = [_down(v) for v in INFLATED]
    assert sums[date(2026, 9, 1)] == pytest.approx((49990.0, mine[1], (49990.0 + sum(mine)) / 3, 3))
    assert sums[date(2026, 9, 2)] == pytest.approx((mine[1], mine[1], mine[1], 1))


def _pruned_window_day(engine: Engine, device_id: str) -> None:
    """The window starts on Aug 30, whose raw rows are gone."""
    _seed(engine, device_id, SUMVIN, INFLATED, legacy="mi", created_at=datetime(2026, 8, 30, 12))
    with Session(engine) as s:
        _summary(s, SUMVIN, date(2026, 8, 30), [80000.0, 80400.0], 5)
        _summary(s, SUMVIN, date(2026, 8, 31), [80400.0, 80450.0], 2)
        s.commit()


def test_wican_pruned_window_day_is_left_when_another_device_was_ever_here(engine, capsys):
    """R2-M2: with the raw rows pruned, the day can't be rebuilt, and an
    earlier dongle's odometer session says its readings may be in it, so it's
    left as is and named. Red on f1986ea5 (no summary handling, no report)."""
    from tools.repair_wican_odometer_unit import _report

    _pruned_window_day(engine, "prundev")
    with Session(engine) as s:
        s.add(
            DriveSession(
                vin=SUMVIN,
                device_id="olddongle",
                started_at=datetime(2026, 8, 20, 9),
                ended_at=datetime(2026, 8, 20, 10),
                start_odometer=49000.0,
                end_odometer=49010.0,
            )
        )
        s.commit()

    plan = _plan(engine, "prundev", "km")
    assert plan.summaries_left == [date(2026, 8, 30)]
    _report(plan)
    out = capsys.readouterr().out
    assert "1 scaled, 0 rebuilt, 1 left as is" in out
    assert "2026-08-30: the window-start day" in out

    _apply(engine, "prundev", "km")
    sums = _summaries(engine, SUMVIN)
    assert sums[date(2026, 8, 30)] == (80000.0, 80400.0, 80200.0, 5)
    assert sums[date(2026, 8, 31)] == pytest.approx(
        (_down(80400.0), _down(80450.0), _down(80425.0), 2)
    )


def test_wican_pruned_window_day_is_scaled_on_a_single_device_vehicle(engine):
    """R2-M2: nothing else ever left a trace of the key on the vehicle, so the
    window-start day is all this device's and is scaled. Red on f1986ea5."""
    _pruned_window_day(engine, "solodev")

    _apply(engine, "solodev", "km")

    assert _summaries(engine, SUMVIN)[date(2026, 8, 30)] == pytest.approx(
        (_down(80000.0), _down(80400.0), _down(80200.0), 5)
    )


# --- Torque: TORQUE_ODOMETER stored as miles since the switch (R10) --------------

TQ = "tq_phone01"
TQVIN = "REPAIRVINTORQUE02"
TQKEY = "TORQUE_ODOMETER"
SWITCH = datetime(2026, 7, 1, 12)
PHONE_CREATED = datetime(2026, 1, 1)

#: Undeclared km rows, then the owner declares the key with `mi` on Jul 1.
HISTORY = [
    (datetime(2026, 6, 30, 9), 56950.0),
    (datetime(2026, 7, 1, 8), 56990.0),
    (datetime(2026, 7, 1, 9), 57000.0),
    (SWITCH, _up(57010.0)),
    (datetime(2026, 7, 1, 13), _up(57030.0)),
    (datetime(2026, 7, 2, 9), _up(57080.0)),
    (datetime(2026, 7, 2, 10), _up(57100.0)),
]

_sessions_made = 0


def _phone(s: Session, device_id: str = TQ, vin: str | None = TQVIN, **device: object) -> None:
    device.setdefault("kind", "torque")
    device.setdefault("created_at", PHONE_CREATED)
    device.setdefault("odometer_unit", "mi")
    device.setdefault("odometer_param_key", TQKEY)
    s.add(LiveLinkDevice(device_id=device_id, vin=vin, enabled=True, **device))
    s.flush()


def _rows(
    s: Session,
    rows: list[tuple[datetime, float]],
    device_id: str = TQ,
    vin: str = TQVIN,
    key: str = TQKEY,
) -> None:
    for at, value in rows:
        s.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key=key,
                value=value,
                timestamp=at,
                received_at=at,
            )
        )


def _session(
    s: Session,
    started: datetime,
    ended: datetime,
    start: float | None,
    end: float | None,
    device_id: str = TQ,
    vin: str = TQVIN,
    torque: bool = True,
) -> DriveSession:
    """A drive session; a Torque one carries its upload's session id."""
    global _sessions_made
    _sessions_made += 1
    session = DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=started,
        ended_at=ended,
        start_odometer=start,
        end_odometer=end,
        distance_km=end - start if start is not None and end is not None else None,
        external_session_id=f"tq-{_sessions_made}" if torque else None,
    )
    s.add(session)
    s.flush()
    return session


def _record(s: Session, day: date, km: float, notes: str, created_at: datetime) -> OdometerRecord:
    record = OdometerRecord(
        vin=TQVIN,
        date=day,
        odometer_km=round(km),
        source="livelink",
        notes=f"{notes} ({TQKEY})",
        created_at=created_at,
    )
    s.add(record)
    s.flush()
    return record


def _torque_history(
    engine: Engine,
    rows: list[tuple[datetime, float]] = HISTORY,
    *,
    records: bool = True,
    sessions: bool = True,
) -> None:
    """A phone on the car since January, declared with `mi` on Jul 1."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s)
        _rows(s, rows)
        last_at, last = rows[-1]
        s.add(
            VehicleTelemetryLatest(
                vin=TQVIN, param_key=TQKEY, value=last, timestamp=last_at, received_at=last_at
            )
        )
        _summary(s, TQVIN, date(2026, 3, 15), [40000.0, 40100.0], 50, key=TQKEY)
        for day in sorted({at.date() for at, _v in rows}):
            values = [v for at, v in rows if at.date() == day]
            _summary(s, TQVIN, day, values, len(values), key=TQKEY)
        s.add(
            OdometerRecord(
                vin=TQVIN,
                date=date(2026, 6, 1),
                odometer_km=56000,
                source="manual",
                created_at=datetime(2026, 6, 1),
            )
        )
        if records:
            _record(s, date(2026, 7, 1), _up(57030.0), "Auto-updated from LiveLink", SWITCH)
            _record(s, date(2026, 7, 2), _up(57100.0), "Auto-updated from LiveLink", rows[-2][0])
        if sessions:
            _session(
                s, datetime(2026, 6, 30, 8, 30), datetime(2026, 6, 30, 9, 30), 56950.0, 56950.0
            )
            # Spans the switch: its low is a km row, its high an inflated one.
            _session(s, datetime(2026, 7, 1, 8), datetime(2026, 7, 1, 13), 56990.0, _up(57030.0))
            _session(
                s, datetime(2026, 7, 2, 9), datetime(2026, 7, 2, 10), _up(57080.0), _up(57100.0)
            )
        s.commit()


def _device_unit(engine: Engine, device_id: str = TQ) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT odometer_unit FROM livelink_devices WHERE device_id = :d"),
            {"d": device_id},
        ).scalar()


def test_torque_repairs_from_the_step_and_leaves_the_km_history(engine):
    """R10: only rows, sessions and summary days from the switch on are
    scaled; Jan-Jun stay, the switch day is rebuilt, a spanning session keeps
    its km low and loses its inflated high. Apply clears `odometer_unit` and
    writes no unit-store row, and a second run has nothing to repair. Red on
    f1986ea5 ("WiCANs only")."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _torque_history(engine)

    plan = _plan(engine, TQ, "km", key=TQKEY)
    assert plan.boundary == SWITCH
    assert plan.unit_action == ("clear_device_unit", None)
    _apply(engine, TQ, "km", key=TQKEY)

    after = _snapshot(engine, TQ, TQVIN)
    assert after["raw"] == pytest.approx(
        [56950.0, 56990.0, 57000.0, 57010.0, 57030.0, 57080.0, 57100.0]
    )
    assert after["raw"][:3] == [56950.0, 56990.0, 57000.0]
    assert after["latest"] == pytest.approx(57100.0)
    assert after["records"] == [("manual", 56000.0), ("livelink", 57030.0), ("livelink", 57100.0)]
    jun, span, jul2 = after["sessions"]
    assert jun == (56950.0, 56950.0, 0.0)
    assert span == pytest.approx((56990.0, 57030.0, 40.0))
    assert span[0] == 56990.0
    assert jul2 == pytest.approx((57080.0, 57100.0, 20.0))

    sums = _summaries(engine, TQVIN, TQKEY)
    assert sums[date(2026, 3, 15)] == (40000.0, 40100.0, 40050.0, 50)
    assert sums[date(2026, 6, 30)] == (56950.0, 56950.0, 56950.0, 1)
    assert sums[date(2026, 7, 1)] == pytest.approx((56990.0, 57030.0, 57007.5, 4))
    assert sums[date(2026, 7, 2)] == pytest.approx((57080.0, 57100.0, 57090.0, 2))

    assert _device_unit(engine) is None
    assert after["units"] == []
    with pytest.raises(RepairRefusedError, match="nothing to repair"):
        _plan(engine, TQ, "km", key=TQKEY)


def test_torque_dry_run_shows_the_switch_its_source_and_the_rows_around_it(engine, capsys):
    from tools.repair_wican_odometer_unit import _report

    _torque_history(engine)

    _report(_plan(engine, TQ, "km", key=TQKEY))

    out = capsys.readouterr().out
    assert "2026-07-01 12:00:00" in out
    assert "the step 57,000 -> 91,749" in out
    for reading in ("56,950", "56,990", "57,000", "91,749", "91,781", "91,861"):
        assert reading in out
    assert "x1.610" in out
    assert "clear odometer_unit" in out
    assert "1 scaled, 1 rebuilt, 0 left as is" in out


#: A Torque profile correction at the switch: 57,000 -> 96,561 is x1.694,
#: outside the step band, and the jump guard held back the first record.
BAND_MISS = [
    (datetime(2026, 6, 30, 9), 56950.0),
    (datetime(2026, 7, 1, 9), 57000.0),
    (SWITCH, 96561.0),
    (datetime(2026, 7, 1, 13), 96600.0),
]


def test_torque_refuses_a_switch_it_cannot_place_and_takes_switch_at(engine):
    """F2-1: no step and no record, so nothing places the switch: refused,
    nothing written (red against "earliest raw row" placement). With
    --switch-at it scales exactly from there."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _torque_history(engine, BAND_MISS, records=False, sessions=False)
    before = _snapshot(engine, TQ, TQVIN)

    with pytest.raises(RepairRefusedError, match="can't be placed from what survives"):
        _apply(engine, TQ, "km", key=TQKEY)
    assert _snapshot(engine, TQ, TQVIN) == before
    assert _device_unit(engine) == "mi"

    _apply(engine, TQ, "km", key=TQKEY, switch_at=SWITCH)
    assert _snapshot(engine, TQ, TQVIN)["raw"] == [
        56950.0,
        57000.0,
        _down(96561.0),
        _down(96600.0),
    ]


def test_switch_at_keeps_a_no_row_session_across_it_whole(engine):
    """F4-2: with no rows inside, which of its columns is km can't be told,
    and a mixed pair would recompute a negative distance."""
    _torque_history(engine, BAND_MISS, records=False, sessions=False)
    with Session(engine) as s:
        kept = _session(s, datetime(2026, 7, 1, 10), datetime(2026, 7, 1, 11, 30), 57010.0, 92000.0)
        s.commit()
        kept_id = kept.id
    switch_at = datetime(2026, 7, 1, 11)

    plan = _plan(engine, TQ, "km", key=TQKEY, switch_at=switch_at)

    assert [k[0] for k in plan.sessions_kept] == [kept_id]
    assert plan.sessions == []
    _apply(engine, TQ, "km", key=TQKEY, switch_at=switch_at)
    assert _snapshot(engine, TQ, TQVIN)["sessions"] == [(57010.0, 92000.0, 92000.0 - 57010.0)]


def test_switch_at_reports_the_step_it_disagrees_with(engine, capsys):
    from tools.repair_wican_odometer_unit import RepairRefusedError, _report

    _torque_history(engine)

    plan = _plan(engine, TQ, "km", key=TQKEY, switch_at=datetime(2026, 7, 1, 13))
    _report(plan)

    out = capsys.readouterr().out
    assert "--switch-at" in out
    assert "disagrees" in out and "2026-07-01 12:00:00" in out
    # Outside the window is no switch at all.
    with pytest.raises(RepairRefusedError, match="before"):
        _plan(engine, TQ, "km", key=TQKEY, switch_at=datetime(2025, 12, 1))


def test_torque_places_the_switch_on_this_vin_only(engine):
    """F2-3: the phone was on another car first. Its last reading there and
    its first here sit x1.624 apart, a false step if the series weren't
    scoped to this VIN (two steps, refused)."""
    with Session(engine) as s:
        _vehicle(s, "REPAIRVINFORMER03")
        _vehicle(s, TQVIN)
        _phone(s)
        _rows(
            s,
            [(datetime(2026, 6, 1), 35000.0), (datetime(2026, 6, 2), 35100.0)],
            vin="REPAIRVINFORMER03",
        )
        _rows(
            s,
            [
                (datetime(2026, 6, 10), 57000.0),
                (datetime(2026, 6, 20), 57050.0),
                (SWITCH, _up(57100.0)),
            ],
        )
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == SWITCH
    assert [new for _old, new in plan.raw] == [pytest.approx(57100.0)]


def test_torque_refuses_an_up_down_up_series(engine):
    """F2-4: a phone that flushed its queue after the switch stored inflated
    values under pre-switch times, so no single switch exists."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _torque_history(
        engine,
        [
            (datetime(2026, 7, 1, 9), 57000.0),
            (datetime(2026, 7, 1, 9, 30), _up(57005.0)),
            (datetime(2026, 7, 1, 10), 57020.0),
            (SWITCH, _up(57030.0)),
        ],
        records=False,
        sessions=False,
    )

    with pytest.raises(RepairRefusedError, match="--switch-at"):
        _plan(engine, TQ, "km", key=TQKEY)


def test_torque_scales_records_by_created_at_not_date(engine):
    """F2-5: the phone was re-added under a new id on Jul 1. The old id's
    record dated that day was written before the new one existed and stays; a
    backfilled record made later from a km row was inflated once and is
    scaled. A `date`-based filter would scale both."""
    readded = datetime(2026, 7, 1, 12)
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s, created_at=readded)
        _rows(s, [(datetime(2026, 7, 2, 9), 57050.0), (datetime(2026, 7, 5, 12), _up(57100.0))])
        old = _record(
            s, date(2026, 7, 1), 56990.0, "Auto-updated from LiveLink", datetime(2026, 7, 1, 9)
        )
        backfilled = _record(
            s,
            date(2026, 7, 2),
            _up(57050.0),
            "Backfilled from LiveLink telemetry",
            datetime(2026, 7, 6),
        )
        s.commit()
        old_id, backfilled_id = old.id, backfilled.id

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == datetime(2026, 7, 5, 12)
    assert [(i, new) for i, _old, new in plan.records] == [(backfilled_id, 57050.0)]
    assert old_id not in plan.flagged_records


def test_torque_session_columns_follow_the_rows_inside_it(engine):
    """F2-2: a Torque session's odometers are the low and high of the key's
    rows inside it, not its edge frames. This one starts two minutes before
    the switch on a frame with no odometer, so both columns are inflated. A
    `started_at` rule leaves the start alone."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s)
        _rows(
            s,
            [
                (datetime(2026, 7, 1, 9), 57000.0),
                (SWITCH, _up(57010.0)),
                (datetime(2026, 7, 1, 12, 55), _up(57040.0)),
            ],
        )
        _session(
            s, datetime(2026, 7, 1, 11, 58), datetime(2026, 7, 1, 13), _up(57010.0), _up(57040.0)
        )
        s.commit()

    _apply(engine, TQ, "km", key=TQKEY)

    assert _snapshot(engine, TQ, TQVIN)["sessions"] == [pytest.approx((57010.0, 57040.0, 30.0))]


def test_torque_flags_a_double_converted_backfilled_record(engine, capsys):
    """F3-5: backfill converted a post-switch row with the device's `mi`, so
    that record is 2.59x high and still 1.609x high after the scale. One built
    from a km row comes out right and isn't flagged."""
    from tools.repair_wican_odometer_unit import _report

    _torque_history(engine)
    with Session(engine) as s:
        good = _record(
            s,
            date(2026, 6, 30),
            _up(56950.0),
            "Backfilled from LiveLink telemetry",
            datetime(2026, 7, 3),
        )
        twice = _record(
            s,
            date(2026, 7, 2),
            _up(_up(57100.0)),
            "Backfilled from LiveLink telemetry",
            datetime(2026, 7, 3),
        )
        s.commit()
        good_id, twice_id = good.id, twice.id

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.flagged_records == [twice_id]
    assert (good_id, round(_up(56950.0)), 56950.0) in plan.records
    _report(plan)
    out = capsys.readouterr().out
    assert f"record {twice_id}: " in out and "converted it twice" in out


# --- Torque: a second sender (F3-1, F4-1, F4-3, F4-4) ---------------------------


def test_torque_refuses_another_phone_linked_to_the_vehicle(engine):
    """F3-1: every Torque phone sends TORQUE_ODOMETER undeclared, and latest
    and summaries take it from any device on the VIN. Linked with no raw rows
    left still counts."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _torque_history(engine)
    with Session(engine) as s:
        _phone(s, "tq_phone02", odometer_unit=None, odometer_param_key=None)
        s.commit()

    with pytest.raises(RepairRefusedError, match=r"tq_phone02.*unlink"):
        _plan(engine, TQ, "km", key=TQKEY)


def test_torque_allows_an_unlinked_phone_whose_activity_predates_the_switch_day(engine):
    """F4-3: scope binds at the switch day, not the window start, so a second
    phone's rows and sessions from June don't block, and a summary day after
    the switch is still scaled."""
    _torque_history(engine)
    with Session(engine) as s:
        _phone(s, "tq_phone02", vin=None, odometer_unit=None, odometer_param_key=None)
        _rows(s, [(datetime(2026, 6, 29, 9), 56900.0)], device_id="tq_phone02")
        _session(
            s, datetime(2026, 6, 29, 8), datetime(2026, 6, 29, 10), 56890.0, 56900.0, "tq_phone02"
        )
        s.commit()

    _apply(engine, TQ, "km", key=TQKEY)

    assert _summaries(engine, TQVIN, TQKEY)[date(2026, 7, 2)] == pytest.approx(
        (57080.0, 57100.0, 57090.0, 2)
    )


def test_torque_allows_a_speed_only_wican_on_the_same_car(engine):
    """F4-1: a WiCAN beside the phone is a supported setup and never sends the
    phone's key."""
    _torque_history(engine)
    with Session(engine) as s:
        s.add(LiveLinkDevice(device_id="carwican", vin=TQVIN, kind="wican", enabled=True))
        _rows(s, [(datetime(2026, 7, 2, 14), 60.0)], device_id="carwican", key="SPEED")
        _session(
            s,
            datetime(2026, 7, 2, 14),
            datetime(2026, 7, 2, 15),
            None,
            None,
            "carwican",
            torque=False,
        )
        s.commit()

    assert _plan(engine, TQ, "km", key=TQKEY).boundary == SWITCH


def test_torque_refuses_a_deleted_phone_on_the_switch_day_until_ignored(engine):
    """F4-4: a re-added phone gets a new id, so the old one turns up with a
    Torque session on the switch day and nothing to unlink. The owner who
    knows it was the same phone passes --ignore-device; an id still on file
    can't be ignored."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _torque_history(engine)
    with Session(engine) as s:
        _session(
            s, datetime(2026, 7, 1, 7), datetime(2026, 7, 1, 7, 30), 56980.0, 56985.0, "tq_oldphone"
        )
        _phone(s, "tq_phone02", vin=None, odometer_unit=None, odometer_param_key=None)
        s.commit()

    with pytest.raises(RepairRefusedError, match=r"tq_oldphone.*2026-07-01.*--ignore-device"):
        _plan(engine, TQ, "km", key=TQKEY)
    assert _plan(engine, TQ, "km", key=TQKEY, ignore_devices=["tq_oldphone"]).boundary == SWITCH
    with pytest.raises(RepairRefusedError, match=r"tq_phone02.*on file"):
        _plan(engine, TQ, "km", key=TQKEY, ignore_devices=["tq_phone02"])


# --- Torque: the switch from the first record (F3-2, F3-4, F5-1) ----------------

RECORD_SWITCH = datetime(2026, 7, 1, 12, 0, 5)


def _record_case(engine: Engine, *, rows: bool = True) -> dict[str, int]:
    """The km rows and the switch day's rows are pruned; the first record the
    phone wrote under the declaration survives, as `Auto-updated`."""
    ids: dict[str, int] = {}
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s)
        if rows:
            _rows(
                s,
                [(datetime(2026, 7, 3, 8), _up(57200.0)), (datetime(2026, 7, 3, 9), _up(57220.0))],
            )
        # Hand-built, before the switch: ingest can't leave one there.
        s.add(
            VehicleTelemetryLatest(
                vin=TQVIN,
                param_key=TQKEY,
                value=56950.0,
                timestamp=datetime(2026, 6, 30, 9),
                received_at=datetime(2026, 6, 30, 9),
            )
        )
        _summary(s, TQVIN, date(2026, 6, 30), [56950.0], 1, key=TQKEY)
        _summary(s, TQVIN, date(2026, 7, 1), [57000.0, _up(57040.0)], 6, key=TQKEY)
        _summary(s, TQVIN, date(2026, 7, 2), [_up(57100.0), _up(57150.0)], 4, key=TQKEY)
        _summary(s, TQVIN, date(2026, 7, 3), [_up(57200.0), _up(57220.0)], 2, key=TQKEY)
        ids["first"] = _record(
            s, date(2026, 7, 1), _up(57030.0), "Auto-updated from LiveLink", RECORD_SWITCH
        ).id
        ids["jul3"] = _record(
            s,
            date(2026, 7, 3),
            _up(57220.0),
            "Auto-recorded from LiveLink",
            datetime(2026, 7, 3, 8, 0, 1),
        ).id
        ids["overnight"] = _session(
            s, datetime(2026, 7, 1, 20), datetime(2026, 7, 2, 1), _up(57040.0), _up(57060.0)
        ).id
        ids["jul3_session"] = _session(
            s, datetime(2026, 7, 3, 8), datetime(2026, 7, 3, 9), _up(57200.0), _up(57220.0)
        ).id
        s.commit()
    return ids


def test_torque_places_the_switch_at_the_first_record(engine, capsys):
    """F3-2, F3-4, F5-1: no step survives, but the first record ingest wrote
    under the declaration predates every surviving row, so its `created_at` is
    the switch. That record is `Auto-updated` (the next frame rewrote its
    notes); an `Auto-recorded`-only filter finds Jul 3's, after the first raw
    row, and refuses. The switch day can't be rebuilt and is left; the days
    after are scaled; an overnight session from that day with no rows is kept
    whole; a latest before the switch is named, not scaled."""
    from tools.repair_wican_odometer_unit import _report

    ids = _record_case(engine)

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == RECORD_SWITCH
    assert plan.summaries_left == [date(2026, 7, 1)]
    assert plan.latest is None
    assert plan.stale_latest == (56950.0, datetime(2026, 6, 30, 9))
    assert [k[0] for k in plan.sessions_kept] == [ids["overnight"]]
    _report(plan)
    out = capsys.readouterr().out
    assert f"record {ids['first']}" in out and "2026-07-01 12:00:05" in out
    assert "earliest surviving raw row" in out and "2026-07-03 08:00:00" in out
    assert "gap" in out and "server timestamp" in out
    assert "56,950" in out and "before the switch" in out

    _apply(engine, TQ, "km", key=TQKEY)
    after = _snapshot(engine, TQ, TQVIN)
    assert after["raw"] == pytest.approx([57200.0, 57220.0])
    assert after["latest"] == 56950.0
    assert after["records"] == [("livelink", 57030.0), ("livelink", 57220.0)]
    overnight, jul3 = after["sessions"]
    assert overnight == (_up(57040.0), _up(57060.0), _up(57060.0) - _up(57040.0))
    assert jul3 == pytest.approx((57200.0, 57220.0, 20.0))
    sums = _summaries(engine, TQVIN, TQKEY)
    assert sums[date(2026, 6, 30)] == (56950.0, 56950.0, 56950.0, 1)
    assert sums[date(2026, 7, 1)] == (57000.0, _up(57040.0), (57000.0 + _up(57040.0)) / 2, 6)
    assert sums[date(2026, 7, 2)] == pytest.approx((57100.0, 57150.0, 57125.0, 4))
    assert sums[date(2026, 7, 3)] == pytest.approx((57200.0, 57220.0, 57210.0, 2))


def test_torque_backfills_before_the_switch_go_by_their_days_top(engine, capsys):
    """Parked (b): backfill ran after the owner set mi but before the phone's
    first frame wrote a record, so its records predate B and a created_at rule
    skips them. Backfill writes round(day top x factor), so a record that
    matches its day's top x1.609 was read as miles and is scaled; one that
    matches the top as is stays quietly; one that matches neither (the
    switch day's summary mixes units) or has no day left is named."""
    from tools.repair_wican_odometer_unit import _report

    ids = _record_case(engine)
    early = RECORD_SWITCH - timedelta(hours=2)
    with Session(engine) as s:
        _summary(s, TQVIN, date(2026, 6, 29), [56900.0], 1, key=TQKEY)
        backfilled = "Backfilled from LiveLink telemetry"
        ids["miles"] = _record(s, date(2026, 6, 30), _up(56950.0), backfilled, early).id
        ids["km"] = _record(s, date(2026, 6, 29), 56900.0, backfilled, early).id
        ids["mixed"] = _record(s, date(2026, 7, 1), 57000.0, backfilled, early).id
        ids["no_day"] = _record(s, date(2026, 6, 28), 91500.0, backfilled, early).id
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == RECORD_SWITCH
    assert (ids["miles"], round(_up(56950.0)), 56950.0) in plan.records
    planned = {i for i, _old, _new in plan.records}
    assert not planned & {ids["km"], ids["mixed"], ids["no_day"]}
    assert plan.early_backfills == [ids["miles"]]
    assert sorted(plan.unproven_backfills) == sorted([ids["mixed"], ids["no_day"]])
    _report(plan)
    out = capsys.readouterr().out
    assert (
        f"record {ids['miles']}: {round(_up(56950.0)):,} -> 56,950 km, backfilled before the "
        "switch from its day's top read as miles"
    ) in out
    assert f"record {ids['mixed']}" in out and f"record {ids['no_day']}" in out
    assert f"record {ids['km']}" not in out

    _apply(engine, TQ, "km", key=TQKEY)
    with engine.connect() as conn:
        km = dict(conn.execute(text("SELECT id, odometer_km FROM odometer_records")).all())
    assert float(km[ids["miles"]]) == 56950.0
    assert float(km[ids["km"]]) == 56900.0
    assert float(km[ids["mixed"]]) == 57000.0
    assert float(km[ids["no_day"]]) == 91500.0


def test_torque_refuses_with_no_surviving_rows(engine):
    """F3-4: a record alone can't be checked against anything."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _record_case(engine, rows=False)

    with pytest.raises(RepairRefusedError, match="no surviving"):
        _plan(engine, TQ, "km", key=TQKEY)


def test_torque_allows_a_deleted_odometer_wican_after_the_switch(engine):
    """F5-3: a deleted WiCAN's odometer sessions carry no Torque session id
    and it never sent the phone's key, so it doesn't block. The WiCAN path's
    "deleted with odometer sessions" rule would."""
    _record_case(engine)
    with Session(engine) as s:
        _session(
            s,
            datetime(2026, 7, 5, 9),
            datetime(2026, 7, 5, 10),
            57300.0,
            57320.0,
            "deadwican",
            torque=False,
        )
        s.commit()

    assert _plan(engine, TQ, "km", key=TQKEY).boundary == RECORD_SWITCH


# --- Torque: what it refuses ---------------------------------------------------


@pytest.mark.parametrize(
    ("device", "key", "to", "match"),
    [
        ({}, "ODOMETER", "km", "TORQUE_ODOMETER only"),
        ({}, TQKEY, "mi", "in km"),
        ({"odometer_unit": None}, TQKEY, "km", "nothing to repair"),
        ({"odometer_unit": "km"}, TQKEY, "km", "nothing to repair"),
        ({"odometer_param_key": "KFF1271"}, TQKEY, "km", "nothing to repair"),
    ],
)
def test_torque_refusals(engine, device, key, to, match):
    from tools.repair_wican_odometer_unit import RepairRefusedError

    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s, **device)
        _rows(s, HISTORY)
        s.commit()

    with pytest.raises(RepairRefusedError, match=match):
        _plan(engine, TQ, to, key=key)


def test_the_cli_takes_the_torque_command_the_409_names(tmp_path, monkeypatch, capsys):
    """The 409, the UI hint and migration 139 all name exactly this command."""
    from tools import repair_wican_odometer_unit as tool

    db = tmp_path / "mygarage.db"
    eng = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(eng)
    _torque_history(eng)

    def run(*extra: str) -> int:
        monkeypatch.setattr(
            "sys.argv",
            [
                "tools/repair_wican_odometer_unit.py",
                "--db",
                str(db),
                "--device-id",
                TQ,
                "--key",
                "TORQUE_ODOMETER",
                "--to",
                "km",
                *extra,
            ],
        )
        return tool.main()

    assert run() == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "2026-07-01 12:00:00" in out
    assert _device_unit(eng) == "mi"
    assert run("--apply") == 0
    assert _device_unit(eng) is None
    capsys.readouterr()
    assert run("--apply") == 2
    assert "nothing to repair" in capsys.readouterr().out
    eng.dispose()


def test_the_cli_parses_switch_at_and_ignore_device(monkeypatch):
    from tools import repair_wican_odometer_unit as tool

    monkeypatch.setattr(
        "sys.argv",
        [
            "repair",
            "--device-id",
            TQ,
            "--key",
            TQKEY,
            "--to",
            "km",
            "--switch-at",
            "2026-07-01T14:00:00+02:00",
            "--ignore-device",
            "tq_a",
            "--ignore-device",
            "tq_b",
        ],
    )
    args = tool._parse_args()

    assert args.switch_at == SWITCH
    assert args.ignore_device == ["tq_a", "tq_b"]


# --- Fix round 1 (T5 review) -----------------------------------------------------


def _pruned_head(engine: Engine, rows: list[tuple[datetime, float]], *, record: bool) -> int:
    """A session from 11:00 across the switch whose km rows (11:30) were pruned:
    pruning goes by age, so it cut the session's head."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s)
        _rows(s, rows)
        if record:
            _record(s, date(2026, 7, 1), _up(57010.0), "Auto-updated from LiveLink", RECORD_SWITCH)
        session = _session(
            s, datetime(2026, 7, 1, 11), datetime(2026, 7, 1, 13), 57000.0, _up(57030.0)
        )
        s.commit()
        return session.id


def test_a_spanning_session_with_its_head_pruned_is_kept_whole_in_the_record_case(engine):
    """Review fix 1: its km low came from a row since pruned, so its first
    surviving row is after the switch, and the per-row rule divided a correct
    57,000 by 1.609 (distance 21,612). Kept whole and reported. Red on 861eb1a0."""
    session_id = _pruned_head(
        engine,
        [(datetime(2026, 7, 1, 12, 30), _up(57020.0)), (datetime(2026, 7, 1, 13), _up(57030.0))],
        record=True,
    )

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == RECORD_SWITCH
    assert plan.sessions == []
    assert [k[0] for k in plan.sessions_kept] == [session_id]
    _apply(engine, TQ, "km", key=TQKEY)
    assert _snapshot(engine, TQ, TQVIN)["sessions"] == [
        (57000.0, _up(57030.0), _up(57030.0) - 57000.0)
    ]


def test_a_spanning_session_with_its_head_pruned_is_kept_whole_under_switch_at(engine):
    """Review fix 1, `--switch-at`: same session, no step, no record. Red on 861eb1a0."""
    session_id = _pruned_head(
        engine,
        [(datetime(2026, 7, 1, 12, 30), 96561.0), (datetime(2026, 7, 1, 13), 96600.0)],
        record=False,
    )

    plan = _plan(engine, TQ, "km", key=TQKEY, switch_at=SWITCH)

    assert plan.sessions == []
    assert [k[0] for k in plan.sessions_kept] == [session_id]


def test_a_spanning_session_follows_the_row_its_start_came_from(engine):
    """Final review A: the stored start is the 12:30 row's value, so that row
    is where it came from, and it's after the switch: scaled, under
    `--switch-at`, from an inflated first row after an odometer-less edge
    frame. No older row needed. Red on 5af0f60c, which kept it whole because
    no row older than the session survived."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s)
        _rows(s, [(datetime(2026, 7, 1, 12, 30), 96561.0), (datetime(2026, 7, 1, 13), 96600.0)])
        _session(s, datetime(2026, 7, 1, 11), datetime(2026, 7, 1, 13), 96561.0, 96600.0)
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY, switch_at=SWITCH)

    assert plan.sessions_kept == []
    assert plan.sessions[0].start == (96561.0, _down(96561.0))


def test_switch_at_must_fall_inside_the_window(engine):
    """Review fix 2: after the latest surviving reading (or after now, with
    none) there's nothing left to place the switch by. Red on 861eb1a0, which
    checked only the lower bound."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _torque_history(engine)
    last = HISTORY[-1][0]

    with pytest.raises(RepairRefusedError, match="after the latest surviving reading"):
        _plan(engine, TQ, "km", key=TQKEY, switch_at=last + timedelta(seconds=1))
    assert _plan(engine, TQ, "km", key=TQKEY, switch_at=last).boundary == last


def test_switch_at_with_no_surviving_rows_must_not_be_in_the_future(engine):
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _record_case(engine, rows=False)

    with pytest.raises(RepairRefusedError, match="after now"):
        _plan(engine, TQ, "km", key=TQKEY, switch_at=datetime(2999, 1, 1))
    assert _plan(engine, TQ, "km", key=TQKEY, switch_at=SWITCH).boundary == SWITCH


def test_the_report_names_the_left_day_in_the_owners_words(engine, capsys):
    """Review fix 3: "B's day" is reviewer shorthand."""
    from tools.repair_wican_odometer_unit import _report

    _record_case(engine)

    _report(_plan(engine, TQ, "km", key=TQKEY))

    out = capsys.readouterr().out
    assert "2026-07-01: the switch day" in out
    assert "B's" not in out


# --- Final review (codex R1-H1/H2, Fable F-1/F-2, F3-5) ---------------------------


@pytest.mark.parametrize(
    ("rows", "switch_at"),
    [
        # codex's shape: no step (x1.694), so the owner passes --switch-at.
        ([(datetime(2026, 7, 1, 12, 30), 96561.0), (datetime(2026, 7, 1, 13), 96600.0)], SWITCH),
        # The same with a step at 12:30 off the replayed row.
        (
            [
                (datetime(2026, 7, 1, 12, 30), _up(57020.0)),
                (datetime(2026, 7, 1, 13), _up(57030.0)),
            ],
            None,
        ),
    ],
)
def test_an_older_replayed_row_does_not_prove_a_pruned_head(engine, rows, switch_at):
    """Final review A (codex R1-H1): Torque takes past timestamps, so a 09:00
    reading replayed after the session's 11:30 km row was pruned says nothing
    about that session. Its stored 57,000 matches no row inside it, so it's
    kept whole. Red on 5af0f60c, which divided it into 35,418 and wrote a
    21,612 km distance."""
    session_id = _pruned_head(engine, rows, record=False)
    with Session(engine) as s:
        _rows(s, [(datetime(2026, 7, 1, 9), 57000.0)])
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY, switch_at=switch_at)

    assert plan.sessions == []
    assert [k[0] for k in plan.sessions_kept] == [session_id]
    _apply(engine, TQ, "km", key=TQKEY, switch_at=switch_at)
    assert _snapshot(engine, TQ, TQVIN)["sessions"] == [
        (57000.0, _up(57030.0), _up(57030.0) - 57000.0)
    ]


def test_a_step_case_spanning_session_still_follows_its_rows(engine):
    """Final review A's limit: the stored start is the 11:30 km row and the
    end the 13:00 inflated one, so the start stays, the end is scaled and the
    distance is recomputed. A fix that kept every spanning session whole
    would leave the end 1.609x high."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s)
        _rows(
            s,
            [
                (datetime(2026, 7, 1, 11, 30), 57000.0),
                (SWITCH, _up(57010.0)),
                (datetime(2026, 7, 1, 13), _up(57030.0)),
            ],
        )
        _session(s, datetime(2026, 7, 1, 11), datetime(2026, 7, 1, 13), 57000.0, _up(57030.0))
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == SWITCH
    assert plan.sessions_kept == []
    _apply(engine, TQ, "km", key=TQKEY)
    assert _snapshot(engine, TQ, TQVIN)["sessions"] == [pytest.approx((57000.0, 57030.0, 30.0))]


@pytest.mark.parametrize(
    "replayed",
    [
        # codex's shape: 08:00 and 09:00 pruned, two older readings replayed.
        [(datetime(2026, 7, 1, 6), 56820.0), (datetime(2026, 7, 1, 7), 56830.0), *HISTORY[3:5]],
        # The same two pruned, replays with the same sum: only the min is off.
        [(datetime(2026, 7, 1, 8, 10), 56980.0), (datetime(2026, 7, 1, 8, 50), 57010.0)]
        + HISTORY[3:5],
        # 12:00 and 13:00 pruned, replays with the same sum: only the max is off.
        [
            *HISTORY[1:3],
            (datetime(2026, 7, 1, 12, 10), _up(57010.0) - 5),
            (datetime(2026, 7, 1, 12, 50), _up(57030.0) + 5),
        ],
        # 09:00 pruned, an 08:30 replay inside the range: only the avg is off.
        [HISTORY[1], (datetime(2026, 7, 1, 8, 30), 56995.0), *HISTORY[3:5]],
    ],
    ids=["codex", "min", "max", "avg"],
)
def test_a_switch_day_summary_its_rows_no_longer_back_is_left(engine, capsys, replayed):
    """Final review B (codex R1-H2): rows were pruned and replays refilled the
    day, so it still counts 4 rows but they aren't the ones it was built
    from. Left and named; the day after is still scaled. Red on 5af0f60c,
    which rebuilt it (codex's shape: avg 56,922.5)."""
    from tools.repair_wican_odometer_unit import _report

    _torque_history(engine, [HISTORY[0], *replayed, *HISTORY[5:]], records=False, sessions=False)
    original = [v for at, v in HISTORY if at.date() == date(2026, 7, 1)]
    with Session(engine) as s:
        day = s.scalars(
            select(TelemetryDailySummary).where(
                TelemetryDailySummary.vin == TQVIN,
                TelemetryDailySummary.date == datetime(2026, 7, 1),
            )
        ).one()
        day.min_value, day.max_value = min(original), max(original)
        day.avg_value = sum(original) / len(original)
        s.commit()
    before = _summaries(engine, TQVIN, TQKEY)[date(2026, 7, 1)]

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary is not None and plan.boundary.date() == date(2026, 7, 1)
    assert plan.summaries_left == [date(2026, 7, 1)]
    _report(plan)
    assert "2026-07-01: the switch day" in capsys.readouterr().out
    _apply(engine, TQ, "km", key=TQKEY)
    sums = _summaries(engine, TQVIN, TQKEY)
    assert sums[date(2026, 7, 1)] == before
    assert sums[date(2026, 7, 2)] == pytest.approx((57080.0, 57100.0, 57090.0, 2))


#: The phone arrived on Jul 1; its clock ran behind, so the first thing it
#: left here is stamped before that.
ARRIVED = datetime(2026, 7, 1)


def _foreign_record(s: Session) -> int:
    """A deleted phone's true-km record from before this one arrived."""
    return _record(
        s, date(2026, 6, 29), 56995.0, "Auto-recorded from LiveLink", datetime(2026, 6, 29, 10)
    ).id


def test_a_foreign_record_from_before_the_phone_arrived_is_left(engine):
    """Final review C (Fable F-1): a skewed first row puts the window start on
    Jun 28, before the phone's `created_at`, and a deleted phone's 56,995 km
    record from Jun 29 sits in between. It isn't this phone's and isn't
    inflated. Red on 5af0f60c, which made it 35,415."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s, created_at=ARRIVED)
        _rows(
            s,
            [
                (datetime(2026, 6, 28, 9), 56990.0),
                (datetime(2026, 7, 1, 9), 57000.0),
                (SWITCH, _up(57010.0)),
                (datetime(2026, 7, 1, 13), _up(57030.0)),
            ],
        )
        foreign = _foreign_record(s)
        own = _record(s, date(2026, 7, 1), _up(57030.0), "Auto-updated from LiveLink", SWITCH).id
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == SWITCH
    assert [(i, new) for i, _old, new in plan.records] == [(own, 57030.0)]
    _apply(engine, TQ, "km", key=TQKEY)
    with Session(engine) as s:
        assert float(s.get_one(OdometerRecord, foreign).odometer_km) == 56995.0


def test_a_foreign_record_from_before_the_phone_arrived_cannot_place_the_switch(engine):
    """Final review C: a session stamped Jun 28 by the phone's slow clock
    puts the window start before its `created_at`, and the km rows are
    pruned. The deleted phone's Jun 29 record isn't the first one this phone
    wrote, so the switch is this phone's own Jul 1 record and Jun 30 stays
    km. Red on 5af0f60c, which placed it on Jun 29 and scaled Jun 30."""
    with Session(engine) as s:
        _vehicle(s, TQVIN)
        _phone(s, created_at=ARRIVED)
        _session(s, datetime(2026, 6, 28, 9), datetime(2026, 6, 28, 9, 30), None, None)
        _rows(
            s,
            [(datetime(2026, 7, 3, 8), _up(57200.0)), (datetime(2026, 7, 3, 9), _up(57220.0))],
        )
        _summary(s, TQVIN, date(2026, 6, 30), [56950.0], 1, key=TQKEY)
        foreign = _foreign_record(s)
        _record(s, date(2026, 7, 1), _up(57030.0), "Auto-updated from LiveLink", RECORD_SWITCH)
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.boundary == RECORD_SWITCH
    assert foreign not in [i for i, _old, _new in plan.records]
    assert date(2026, 6, 30) not in [c.day for c in plan.summaries]


def test_a_record_written_before_switch_at_is_left(engine):
    """Final review C: the rescale set also needs `created_at >= B`. Under a
    later `--switch-at` the Jul 1 record predates the switch the owner named,
    so it's left like the rows before it; Jul 2's is scaled. Red on
    5af0f60c, which scaled every record since the window start."""
    _torque_history(engine)
    switch_at = HISTORY[-2][0]

    plan = _plan(engine, TQ, "km", key=TQKEY, switch_at=switch_at)

    assert [new for _i, _old, new in plan.records] == [57100.0]


def test_the_record_case_says_nothing_before_the_switch_is_touched(engine, capsys):
    """Final review D (Fable F-2): a switch from the first record can be
    late, and the days before it are silently left. The report says so and
    points at --switch-at; the step case doesn't need it. Red on 5af0f60c."""
    from tools.repair_wican_odometer_unit import _report

    _record_case(engine)
    _report(_plan(engine, TQ, "km", key=TQKEY))
    out = capsys.readouterr().out
    assert "nothing before the switch time is touched" in out
    assert "if the unit was set earlier, pass --switch-at" in out


def test_the_step_case_report_has_no_record_case_caveat(engine, capsys):
    from tools.repair_wican_odometer_unit import _report

    _torque_history(engine)
    _report(_plan(engine, TQ, "km", key=TQKEY))
    assert "nothing before the switch time is touched" not in capsys.readouterr().out


def test_a_double_converted_record_on_a_pruned_day_is_flagged_by_its_summary(engine, capsys):
    """Final review 10 (F3-5): Jul 2's raw rows are gone, so the record's day
    top comes from that day's summary, scaled as the plan scales it. One
    built from a km row on pruned Jun 30, whose summary stays km, isn't
    flagged. Red on 5af0f60c, which needed raw rows to flag anything."""
    from tools.repair_wican_odometer_unit import _report

    _record_case(engine)
    with Session(engine) as s:
        good = _record(
            s,
            date(2026, 6, 30),
            _up(56950.0),
            "Backfilled from LiveLink telemetry",
            datetime(2026, 7, 3, 10),
        ).id
        twice = _record(
            s,
            date(2026, 7, 2),
            _up(_up(57150.0)),
            "Backfilled from LiveLink telemetry",
            datetime(2026, 7, 3, 10),
        ).id
        s.commit()

    plan = _plan(engine, TQ, "km", key=TQKEY)

    assert plan.flagged_records == [twice]
    assert (good, round(_up(56950.0)), 56950.0) in plan.records
    _report(plan)
    out = capsys.readouterr().out
    assert f"record {twice}: " in out and "converted it twice" in out
