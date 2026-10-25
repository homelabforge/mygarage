"""Migration 133: record main's miles reading of a WiCAN's bare ODOMETER (D6a, R12).

T7 reads a bare `ODOMETER` as km, as upstream defines it. A WiCAN with no unit
set that has already reported one was read as miles on main, so its odometer
records are in that scale; 133 stores a `legacy` R12 row so it keeps reading
the same. `odometer_unit` isn't touched, so an `A6-` key keeps km.

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
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.migrations as _m
import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.database import Base, is_sqlite
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_device_unit import LiveLinkDeviceUnit
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


# --- The rows it writes --------------------------------------------------------


def test_133_is_fatal():
    """A failure must not boot with the new km default (Codex R1-H4)."""
    assert _load().FATAL is True


def test_133_records_a_bare_odometer_device_and_nothing_else(db):
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

    assert _rows(engine) == {("bare", "ODOMETER"): LEGACY, ("both", "ODOMETER"): LEGACY}
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


def test_133_ignores_a_latest_row_from_before_the_device(db):
    """A replacement dongle with raw rows of its own isn't stamped from a dead
    device's latest row (Fable F4-2). Red against the plain VIN-scope check."""
    _dialect, engine, _url = db
    with Session(engine) as s:
        _vehicle(s, "M133VINREPLACE001")
        _device(s, "replaced", "M133VINREPLACE001")
        _raw(s, "replaced", "M133VINREPLACE001", "A6-ODOMETER", 80000)
        _latest(s, "M133VINREPLACE001", "ODOMETER", 50000, BEFORE)
        s.commit()

    _load().upgrade(engine)

    assert _rows(engine) == {}


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
    assert await _held(db, "pidonly") == {}
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
async def test_an_sd_backfill_stores_what_live_ingest_would(migrated: AsyncSession):
    """The SD path resolves through the same step: the legacy `ODOMETER` reads
    miles and an R12 mph `SPEED` becomes km/h (R12, R4). The speed is red on
    main; the odometer is red against a T7 that fixed the live path only.

    Live ingest rounds an odometer (`_sanitize_odometer_value`), the SD path
    never has, hence the half-km tolerance on that one.
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
    assert stored["ODOMETER"] == pytest.approx(live_odometer, abs=0.5)
    assert stored["SPEED"] == pytest.approx(live_speed)
    assert live_speed == pytest.approx(50 * 1.609344)
