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
from datetime import date, datetime, timedelta

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
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
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


def _snapshot(engine: Engine, device_id: str, vin: str) -> dict[str, object]:
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


def _plan(engine: Engine, device_id: str, to: str, key: str = "ODOMETER"):
    from tools.repair_wican_odometer_unit import plan_repair

    with engine.connect() as conn:
        return plan_repair(conn, device_id, key, to)


def _apply(engine: Engine, device_id: str, to: str, key: str = "ODOMETER") -> None:
    from tools.repair_wican_odometer_unit import apply_repair, plan_repair

    with engine.begin() as conn:
        apply_repair(conn, plan_repair(conn, device_id, key, to))


# --- --to km: really km, read as miles (B6-10) ---------------------------------

#: 50,000 and 50,020.4 km read as miles: what main stored.
INFLATED = [80467.0, 80500.0]


def test_to_km_plans_exactly_the_deflation(engine):
    _seed(engine, "legacykm", "REPAIRVINKM000001", INFLATED, legacy="mi")
    before = _snapshot(engine, "legacykm", "REPAIRVINKM000001")

    plan = _plan(engine, "legacykm", "km")

    assert plan.unit_action == ("drop", None)
    assert plan.raw == [(80467.0, 50000.0), (80500.0, 50020.0)]
    assert plan.latest == (80500.0, 50020.0)
    assert [(old, new) for _id, old, new in plan.records] == [
        (80467.0, 50000.0),
        (80500.0, 50020.0),
    ]
    starts_ends = [(s.start, s.end) for s in plan.sessions]
    assert starts_ends == [
        ((80467.0, 50000.0), (80500.0, 50020.0)),
        ((80500.0, 50020.0), (80500.0, 50020.0)),
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
    assert after["raw"] == [50000.0, 50020.0]
    assert after["latest"] == 50020.0
    assert after["records"] == [("manual", 12345.0), ("livelink", 50000.0), ("livelink", 50020.0)]
    assert after["sessions"][0][:2] == (50000.0, 50020.0)
    assert after["sessions"][0][2] == pytest.approx(33 / 1.609344)
    assert after["sessions"][1] == (50020.0, 50020.0, 0.4)
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
    assert plan.raw == [(50000.0, 80467.0), (50020.0, 80499.0)]
    assert plan.latest == (50020.0, 80499.0)
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
    assert after["raw"] == [80467.0, 80499.0]
    assert after["latest"] == 80499.0
    assert after["records"] == [("manual", 12345.0), ("livelink", 80467.0), ("livelink", 80499.0)]
    assert after["sessions"][0][:2] == (80467.0, 80499.0)
    assert after["sessions"][0][2] == pytest.approx(20 * 1.609344)
    assert after["sessions"][1] == (80499.0, 80499.0, 0.4)
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
    assert after["raw"] == [50000.0, 50020.0]
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
    assert sorted(after["raw"]) == [12345.0, 50000.0, 50020.0]


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


def test_it_refuses_a_device_that_is_not_a_wican(engine):
    """Regression guard (M4): a per-key row changes nothing for another kind.
    Kills dropping the kind check."""
    from tools.repair_wican_odometer_unit import RepairRefusedError

    _seed(engine, "torquedev", "REPAIRVINTORQUE01", INFLATED, legacy=None, kind="torque")

    with pytest.raises(RepairRefusedError, match="WiCANs only"):
        _plan(engine, "torquedev", "mi")


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
    assert _snapshot(eng, "clidev", "REPAIRVINCLI00001")["raw"] == [50000.0, 50020.0]
    capsys.readouterr()

    assert run("--apply") == 2
    assert "already reads km" in capsys.readouterr().out
    eng.dispose()
