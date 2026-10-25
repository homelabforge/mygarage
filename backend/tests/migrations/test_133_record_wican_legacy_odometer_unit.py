"""Migration 133: record main's reading of a WiCAN's odometer keys (D6a, R12, R1-H1).

T7 reads a bare `ODOMETER` as km, as upstream defines it, and R12 honours a
unit the device declares for any key. Main ignored both: a PID key read km and
any bare key read miles. So 133 stores a `legacy` R12 row with main's unit for
every odometer key a unit-less WiCAN has history under, and its records keep
their scale whatever the next boot config says. `odometer_unit` isn't touched.

Asserted on stored VALUES after the migration plus a fresh ingest, not just on
the row (Codex R1-H4). Each test builds its own schema with `create_all`, on
SQLite and PG. The ingest half runs on the dialect the app was imported for
(`app.database.is_sqlite` picks the insert dialect at import), so the SQLite
case runs in the host suite and the PG case under the sidecar.

`created_at` is set explicitly everywhere: SQLite's `CURRENT_TIMESTAMP` is
second-resolution text, so insert order alone flakes (Fable F5-4).
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.migrations as _m
import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.database import Base, is_sqlite
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_device_unit import LiveLinkDeviceUnit
from app.models.odometer import OdometerRecord
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.utils.datetime_utils import utc_now

_NAME = "133_record_wican_legacy_odometer_unit"

#: Well clear of the second-resolution trap on both sides.
CREATED = (utc_now() - timedelta(days=200)).replace(microsecond=0)
BEFORE = CREATED - timedelta(days=30)
AFTER = CREATED + timedelta(days=30)

#: 50,000 mi in km, as live ingest stores an odometer (rounded).
KM_50000_MI = 80467.0


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db(engine_for_migration) -> tuple[str, Engine, str]:
    """A whole schema, as `create_all` builds it before the runner."""
    dialect, engine, url = engine_for_migration
    Base.metadata.create_all(engine)
    return dialect, engine, url


_n = 0


def _vehicle(s: Session, vin: str) -> None:
    global _n
    _n += 1
    user = User(
        username=f"m133_{_n}", email=f"m133_{_n}@example.com", hashed_password="x", is_active=True
    )
    s.add(user)
    s.flush()
    s.add(Vehicle(vin=vin, user_id=user.id, nickname=vin, vehicle_type="Car"))
    s.flush()


def _device(s: Session, device_id: str, vin: str | None, **fields: object) -> None:
    fields.setdefault("kind", "wican")
    fields.setdefault("created_at", CREATED)
    s.add(LiveLinkDevice(device_id=device_id, vin=vin, enabled=True, **fields))
    s.flush()


def _raw(s: Session, device_id: str, vin: str, key: str, value: float, at: datetime = AFTER):
    s.add(
        VehicleTelemetry(
            vin=vin, device_id=device_id, param_key=key, value=value, timestamp=at, received_at=at
        )
    )


def _latest(s: Session, vin: str, key: str, value: float, at: datetime):
    s.add(VehicleTelemetryLatest(vin=vin, param_key=key, value=value, timestamp=at, received_at=at))


def _rows(engine: Engine) -> dict[tuple[str, str], tuple[str | None, str | None, str]]:
    with engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT device_id, param_key, unit, param_class, source FROM livelink_device_units"
            )
        ).all()
    return {(d, k): (u, c, src) for d, k, u, c, src in found}


LEGACY = ("mi", "distance", "legacy")
LEGACY_KM = ("km", "distance", "legacy")


# --- The rows it writes --------------------------------------------------------


def test_133_is_fatal():
    """A failure must not boot with the new km default (Codex R1-H4)."""
    assert _load().FATAL is True


def test_133_records_every_odometer_key_in_mains_unit(db):
    """A PID key read km on main and a bare one miles; each keeps that (R1-H1).
    The A6- rows are red against a 133 that only knew bare ODOMETER."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        for vin in ("M133VINBARE000001", "M133VINPID0000001", "M133VINBOTH000001"):
            _vehicle(s, vin)
        _vehicle(s, "M133VINUNIT000001")
        _vehicle(s, "M133VINTORQ000001")
        _device(s, "bare", "M133VINBARE000001")
        _raw(s, "bare", "M133VINBARE000001", "ODOMETER", 50000)
        _device(s, "pid", "M133VINPID0000001")
        _raw(s, "pid", "M133VINPID0000001", "A6-ODOMETER", 80000)
        _device(s, "both", "M133VINBOTH000001")
        _raw(s, "both", "M133VINBOTH000001", "A6-ODOMETER", 80000)
        _raw(s, "both", "M133VINBOTH000001", "ODOMETER", 50000)
        _device(s, "unitset", "M133VINUNIT000001", odometer_unit="km")
        _raw(s, "unitset", "M133VINUNIT000001", "ODOMETER", 80000)
        _device(s, "torque", "M133VINTORQ000001", kind="torque")
        _raw(s, "torque", "M133VINTORQ000001", "ODOMETER", 80000)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {
        ("bare", "ODOMETER"): LEGACY,
        ("pid", "A6-ODOMETER"): LEGACY_KM,
        ("both", "A6-ODOMETER"): LEGACY_KM,
        ("both", "ODOMETER"): LEGACY,
    }
    with engine.connect() as conn:
        found = conn.execute(text("SELECT device_id, odometer_unit FROM livelink_devices"))
        units = {device_id: unit for device_id, unit in found.all()}
    assert units == {"bare": None, "pid": None, "both": None, "unitset": "km", "torque": None}


def test_133_leaves_a_declared_row_alone_and_a_rerun_changes_nothing(db):
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINWIRE000001")
        _vehicle(s, "M133VINBARE000002")
        _device(s, "wired", "M133VINWIRE000001")
        _raw(s, "wired", "M133VINWIRE000001", "ODOMETER", 80000)
        s.add(
            LiveLinkDeviceUnit(
                device_id="wired",
                param_key="ODOMETER",
                unit="km",
                param_class="distance",
                source="wire",
            )
        )
        _device(s, "bare2", "M133VINBARE000002")
        _raw(s, "bare2", "M133VINBARE000002", "ODOMETER", 50000)
        s.commit()

    _load().upgrade(engine)
    first = _rows(engine)
    with engine.connect() as conn:
        stamps = conn.execute(
            text("SELECT id, created_at FROM livelink_device_units ORDER BY id")
        ).all()
    _load().upgrade(engine)

    assert first == {
        ("wired", "ODOMETER"): ("km", "distance", "wire"),
        ("bare2", "ODOMETER"): LEGACY,
    }
    assert _rows(engine) == first
    with engine.connect() as conn:
        again = conn.execute(
            text("SELECT id, created_at FROM livelink_device_units ORDER BY id")
        ).all()
    assert again == stamps


def test_133_reads_the_latest_row_for_a_pruned_device(db):
    """A vehicle parked past the 90-day retention has no raw rows at upgrade,
    and would come back reading its miles as km below its own floor (Fable
    F3-1). Red against a telemetry-only evidence query."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINPRUNED0001")
        _device(s, "pruned", "M133VINPRUNED0001")
        # Its other keys are still there; only ODOMETER is gone.
        _raw(s, "pruned", "M133VINPRUNED0001", "COOLANT", 90)
        _latest(s, "M133VINPRUNED0001", "ODOMETER", 50000, AFTER)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("pruned", "ODOMETER"): LEGACY}


def test_133_reads_the_vin_for_a_device_that_reported_other_keys_first(db):
    """Re-discovered, it has sent COOLANT but no ODOMETER yet, and its VIN's
    last bare ODOMETER predates it. Raw rows of OTHER keys don't show it has
    reported the odometer since, so the unbounded VIN check still applies, or
    its first km reading lands below the floor its earlier self wrote (Fable
    FB-2). Red against the any-key raw check."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINOTHER00001")
        _device(s, "otherfirst", "M133VINOTHER00001")
        _raw(s, "otherfirst", "M133VINOTHER00001", "COOLANT", 90)
        _latest(s, "M133VINOTHER00001", "ODOMETER", 50000, BEFORE)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("otherfirst", "ODOMETER"): LEGACY}


def test_133_records_a_user_autopid_key_in_miles(db):
    """Codex R1-H1: `MILEAGE` read miles on main, and a km boot config would
    switch it now that R12 honours one. Red against a 133 that only knew bare
    ODOMETER."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINMILEAGE001")
        _device(s, "mileage", "M133VINMILEAGE001")
        _raw(s, "mileage", "M133VINMILEAGE001", "MILEAGE", 128748)
        _vehicle(s, "M133VINODOLAT0001")
        # Pruned: only the latest row says it ever reported ODO.
        _device(s, "odolatest", "M133VINODOLAT0001")
        _latest(s, "M133VINODOLAT0001", "ODO", 128748, AFTER)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("mileage", "MILEAGE"): LEGACY, ("odolatest", "ODO"): LEGACY}


def test_133_follows_a_declared_key_and_nothing_else(db):
    """A declared `odometer_param_key` replaces name matching, as it did on
    main, so a bare ODOMETER beside it was stored raw and gets no miles row
    (Fable FB-4). Red against a 133 that included declared-other devices."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINDECLOTHER1")
        _device(s, "declother", "M133VINDECLOTHER1", odometer_param_key="A6-ODOMETER")
        _raw(s, "declother", "M133VINDECLOTHER1", "ODOMETER", 50000)
        _latest(s, "M133VINDECLOTHER1", "ODOMETER", 50000, AFTER)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {}


def test_133_records_a_declared_key_with_history_in_mains_unit(db):
    """The declared key itself is covered: bare reads miles, as on main."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINDECLMY0001")
        _device(s, "declmy", "M133VINDECLMY0001", odometer_param_key="MY_ODO")
        _raw(s, "declmy", "M133VINDECLMY0001", "MY_ODO", 50000)
        _raw(s, "declmy", "M133VINDECLMY0001", "A6-ODOMETER", 80467)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("declmy", "MY_ODO"): LEGACY}


def test_133_gives_a_rediscovered_device_main_s_reading(db):
    """Deleted and re-discovered (same MAC id, new `created_at`) with no raw
    rows at all: the unbounded VIN check applies, for the migration only, or it
    lands below the floor its earlier incarnation recorded (Fable F5-5). Red
    against the bounded check alone."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINREDISC0001")
        _device(s, "redisc", "M133VINREDISC0001")
        _latest(s, "M133VINREDISC0001", "ODOMETER", 50000, BEFORE)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("redisc", "ODOMETER"): LEGACY}


def test_133_reads_a_declared_odometer_key(db):
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINDECL000001")
        _device(s, "declared", "M133VINDECL000001", odometer_param_key="ODOMETER")
        _raw(s, "declared", "M133VINDECL000001", "COOLANT", 90)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("declared", "ODOMETER"): LEGACY}


def test_133_skips_a_device_with_no_odometer_evidence(db):
    """Regression guard on the scope: nothing reported, nothing recorded."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINQUIET00001")
        _device(s, "quiet", "M133VINQUIET00001")
        _device(s, "unlinked", None)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {}


def test_133_gives_a_second_wican_on_the_vin_the_row_too(db):
    """The latest table is keyed by VIN, so a second unit-less WiCAN on that
    VIN gets the row as well: main's reading for it anyway."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINTWO000001")
        _device(s, "first", "M133VINTWO000001")
        _raw(s, "first", "M133VINTWO000001", "ODOMETER", 50000)
        _device(s, "second", "M133VINTWO000001")
        _raw(s, "second", "M133VINTWO000001", "COOLANT", 90)
        _latest(s, "M133VINTWO000001", "ODOMETER", 50000, AFTER)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {("first", "ODOMETER"): LEGACY, ("second", "ODOMETER"): LEGACY}


def test_133_does_not_read_odometer_records(db):
    """Regression guard on ruling T7-a: a `livelink` odometer record names no
    key, so it isn't evidence of a bare ODOMETER (it may well be `A6-`). Kills
    a migration that adds record evidence."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINRECORD0001")
        _device(s, "recorded", "M133VINRECORD0001")
        s.add(
            OdometerRecord(
                vin="M133VINRECORD0001",
                date=AFTER.date(),
                odometer_km=80000,
                source="livelink",
                created_at=AFTER,
            )
        )
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {}


def test_133_skips_an_install_with_no_devices_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)

    assert not inspect(engine).has_table("livelink_device_units")


# --- Stored values after the migration and a fresh ingest ----------------------


@pytest_asyncio.fixture
async def migrated(db) -> AsyncGenerator[AsyncSession]:
    """Four WiCANs seeded as main left them, migrated, with an async session.

    - `legacy`: bare `ODOMETER` history, no unit.
    - `pidonly`: only `A6-ODOMETER` history.
    - `mixed`: both.
    - `unitkm`: bare `ODOMETER` history, `odometer_unit='km'`.
    - `redisc`: re-discovered (F5-5), no raw rows, its VIN's bare `ODOMETER`
      latest row from before it was added.
    - `mileage`: a `MILEAGE` autopid read as miles (Codex R1-H1), with the
      record main wrote from it: 80,000 mi is 128,748 km.
    - `pidkmdev`: `A6-ODOMETER` history in km, with its record.
    """
    dialect, engine, url = db
    if is_sqlite != (dialect == "sqlite"):
        pytest.skip("ingest runs on the dialect the app was imported for")

    with Session(engine) as s:
        s.add(Setting(key="livelink_enabled", value="true"))
        for device_id, vin, keys, fields in (
            ("legacy", "M133INGLEGACY0001", ("ODOMETER",), {}),
            ("pidonly", "M133INGPIDONLY001", ("A6-ODOMETER",), {}),
            ("mixed", "M133INGMIXED00001", ("A6-ODOMETER", "ODOMETER"), {}),
            ("unitkm", "M133INGUNITKM0001", ("ODOMETER",), {"odometer_unit": "km"}),
        ):
            _vehicle(s, vin)
            _device(s, device_id, vin, **fields)
            for key in keys:
                _raw(s, device_id, vin, key, 1000, at=AFTER)
        _vehicle(s, "M133INGREDISC0001")
        _device(s, "redisc", "M133INGREDISC0001")
        _latest(s, "M133INGREDISC0001", "ODOMETER", 50000, BEFORE)
        for device_id, vin, key, km in (
            ("mileage", "M133INGMILEAGE001", "MILEAGE", 128748.0),
            ("pidkmdev", "M133INGPIDKM00001", "A6-ODOMETER", 80000.0),
        ):
            _vehicle(s, vin)
            _device(s, device_id, vin)
            _raw(s, device_id, vin, key, km, at=AFTER)
            _latest(s, vin, key, km, AFTER)
            s.add(
                OdometerRecord(
                    vin=vin,
                    date=AFTER.date(),
                    odometer_km=km,
                    source="livelink",
                    notes=f"Auto-recorded from LiveLink ({key})",
                    created_at=AFTER,
                )
            )
        s.commit()

    _load().upgrade(engine)

    if dialect == "sqlite":
        from app.database import configure_sqlite_engine

        async_engine = create_async_engine(url.replace("sqlite://", "sqlite+aiosqlite://", 1))
        configure_sqlite_engine(async_engine)
    else:
        async_engine = create_async_engine(
            url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        )
    maker = async_sessionmaker(async_engine, expire_on_commit=False, autoflush=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await async_engine.dispose()


async def _rx(db: AsyncSession, device_id: str, **values: float) -> None:
    from app.services.livelink_ingest import ingest
    from app.services.livelink_sources.base import MqttEnvelope
    from app.services.livelink_sources.wican import WicanModule

    env = MqttEnvelope(f"wican/{device_id}/can/rx", json.dumps(values).encode())
    await ingest(WicanModule(), env, db)
    await db.commit()


async def _boot(db: AsyncSession, device_id: str, config: dict, **values: float) -> None:
    from app.schemas.livelink_ingest import WiCANPayload
    from app.services.livelink_ingest import ingest
    from app.services.livelink_sources.base import WicanHttpsEnvelope
    from app.services.livelink_sources.wican import WicanModule

    payload = WiCANPayload.model_validate(
        {
            "autopid_data": values,
            "config": config,
            "status": {"device_id": device_id, "ecu_status": "online"},
        }
    )
    await ingest(WicanModule(), WicanHttpsEnvelope(device_id, payload), db)
    await db.commit()


async def _newest(db: AsyncSession, device_id: str, key: str) -> float:
    row = await db.execute(
        select(VehicleTelemetry.value)
        .where(VehicleTelemetry.device_id == device_id, VehicleTelemetry.param_key == key)
        .order_by(VehicleTelemetry.timestamp.desc())
        .limit(1)
    )
    return row.scalar_one()


async def _held(db: AsyncSession, device_id: str) -> dict[str, tuple[str | None, str]]:
    rows = await db.execute(
        select(
            LiveLinkDeviceUnit.param_key, LiveLinkDeviceUnit.unit, LiveLinkDeviceUnit.source
        ).where(LiveLinkDeviceUnit.device_id == device_id)
    )
    return {k: (u, src) for k, u, src in rows.all()}


@pytest.mark.asyncio
async def test_no_existing_install_reads_differently(migrated: AsyncSession):
    """The same raw frame on each device lands as it did on main."""
    db = migrated
    await _rx(db, "legacy", ODOMETER=50000)
    await _rx(db, "pidonly", **{"A6-ODOMETER": 80467})
    # One car: both keys read the same distance, in their own units.
    await _rx(db, "mixed", **{"A6-ODOMETER": 80467, "ODOMETER": 50000})
    await _rx(db, "unitkm", ODOMETER=80467)

    assert await _newest(db, "legacy", "ODOMETER") == KM_50000_MI
    assert await _newest(db, "pidonly", "A6-ODOMETER") == 80467.0
    assert await _held(db, "pidonly") == {"A6-ODOMETER": ("km", "legacy")}
    assert await _newest(db, "mixed", "A6-ODOMETER") == 80467.0
    assert await _newest(db, "mixed", "ODOMETER") == KM_50000_MI
    assert await _newest(db, "unitkm", "ODOMETER") == 80467.0
    assert await _held(db, "unitkm") == {}


@pytest.mark.asyncio
async def test_a_boot_config_declaring_km_does_not_replace_the_legacy_row(
    migrated: AsyncSession,
):
    """On main this device's upstream-km `ODOMETER` was read as miles, so its
    records are already 1.609x high. Switching to km now would put every later
    reading below that floor (Fable F1-3). Red against a T7 that lets the
    declaration win."""
    db = migrated
    await _boot(db, "legacy", {"ODOMETER": {"class": "distance", "unit": "km"}}, ODOMETER=50000)
    await _rx(db, "legacy", ODOMETER=50001)

    assert await _held(db, "legacy") == {"ODOMETER": ("mi", "legacy")}
    values = await db.execute(
        select(VehicleTelemetry.value)
        .where(VehicleTelemetry.device_id == "legacy", VehicleTelemetry.param_key == "ODOMETER")
        .where(VehicleTelemetry.timestamp > AFTER)
        .order_by(VehicleTelemetry.timestamp)
    )
    assert list(values.scalars().all()) == [KM_50000_MI, 80469.0]


@pytest.mark.asyncio
async def test_a_rediscovered_device_keeps_its_legacy_row_through_a_km_boot(
    migrated: AsyncSession,
):
    """133 gave the F5-5 device its row from the unbounded VIN check. Its
    bounded history is empty, so the R12 exception has to read 133's evidence
    too, or its first boot config swaps the row out and every reading lands
    below the floor its earlier self recorded (F1-3)."""
    db = migrated
    assert await _held(db, "redisc") == {"ODOMETER": ("mi", "legacy")}

    await _boot(db, "redisc", {"ODOMETER": {"class": "distance", "unit": "km"}}, ODOMETER=50001)

    assert await _held(db, "redisc") == {"ODOMETER": ("mi", "legacy")}
    assert await _newest(db, "redisc", "ODOMETER") == 80469.0


async def _record_max(db: AsyncSession, vin: str) -> float:
    found = await db.execute(
        select(func.max(OdometerRecord.odometer_km)).where(OdometerRecord.vin == vin)
    )
    return float(found.scalar_one())


@pytest.mark.asyncio
async def test_a_km_boot_config_keeps_a_mileage_autopid_in_miles(migrated: AsyncSession):
    """Codex R1-H1's reproduction. On main `MILEAGE` read miles whatever the
    config said, so its record floor is 128,748 km. A km declaration switching
    it would store 80,010 km and leave the floor where it was, silently, for
    good. Red against a 133 that only recorded bare ODOMETER."""
    db = migrated
    await _boot(db, "mileage", {"MILEAGE": {"class": "distance", "unit": "km"}}, MILEAGE=80010)

    assert await _held(db, "mileage") == {"MILEAGE": ("mi", "legacy")}
    assert await _newest(db, "mileage", "MILEAGE") == 128764.0
    assert await _record_max(db, "M133INGMILEAGE001") == 128764.0


@pytest.mark.asyncio
async def test_a_miles_boot_config_keeps_a_pid_odometer_in_km(migrated: AsyncSession):
    """The opposite conflict: a standard PID read km on main. A miles
    declaration would put the next reading 1.609x up, past the jump guard, and
    drop it. Red against a 133 that only recorded bare ODOMETER."""
    db = migrated
    await _boot(
        db,
        "pidkmdev",
        {"A6-ODOMETER": {"class": "distance", "unit": "mi"}},
        **{"A6-ODOMETER": 80010},
    )

    assert await _held(db, "pidkmdev") == {"A6-ODOMETER": ("km", "legacy")}
    assert await _newest(db, "pidkmdev", "A6-ODOMETER") == 80010.0
    assert await _record_max(db, "M133INGPIDKM00001") == 80010.0


@pytest.mark.asyncio
async def test_a_rediscovered_device_that_sends_another_key_first_keeps_its_row(
    migrated: AsyncSession,
):
    """Fable FB-2: one COOLANT frame isn't the odometer reporting since
    re-creation. With the any-key raw check the km boot config replaced the
    row and 50,001 stored as km, below the floor. Red on ed8fbef9."""
    db = migrated
    await _rx(db, "redisc", COOLANT=90)
    await _boot(db, "redisc", {"ODOMETER": {"class": "distance", "unit": "km"}}, ODOMETER=50001)

    assert await _held(db, "redisc") == {"ODOMETER": ("mi", "legacy")}
    assert await _newest(db, "redisc", "ODOMETER") == 80469.0


@pytest.mark.asyncio
async def test_an_sd_backfill_stores_what_live_ingest_would(migrated: AsyncSession):
    """The SD path resolves through the same step: the legacy `ODOMETER` reads
    miles and an R12 mph `SPEED` becomes km/h (R12, R4). The speed is red on
    main; the odometer is red against a T7 that fixed the live path only.

    Live ingest rounds an odometer (`_sanitize_odometer_value`), and so does
    the SD path now (B6-11), so the two match exactly.
    """
    from app.services.sd_log_parser import SdRow
    from app.services.telemetry_service import TelemetryService

    db = migrated
    db.add(
        LiveLinkDeviceUnit(
            device_id="legacy", param_key="SPEED", unit="mph", param_class="speed", source="wire"
        )
    )
    await db.commit()
    await _rx(db, "legacy", ODOMETER=50000, SPEED=50)
    live_odometer = await _newest(db, "legacy", "ODOMETER")
    live_speed = await _newest(db, "legacy", "SPEED")

    at = AFTER + timedelta(days=1)
    await TelemetryService(db).bulk_backfill(
        "M133INGLEGACY0001",
        "legacy",
        [SdRow("ODOMETER", 50000.0, at), SdRow("SPEED", 50.0, at)],
    )

    sd = await db.execute(
        select(VehicleTelemetry.param_key, VehicleTelemetry.value).where(
            VehicleTelemetry.device_id == "legacy", VehicleTelemetry.timestamp == at
        )
    )
    stored = {key: value for key, value in sd.all()}
    assert stored["ODOMETER"] == live_odometer
    assert stored["SPEED"] == pytest.approx(live_speed)
    assert live_speed == pytest.approx(50 * 1.609344)
