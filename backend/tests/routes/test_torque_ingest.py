"""Route tests for the Torque Pro ingest endpoint (Task 9):
GET|POST /api/v1/torque/{token}/upload.

Integration keystone — composes T4 parse_torque_query, T5
TorqueService.resolve_by_token, T6 TelemetryService.store_torque_telemetry, T7
SessionService.resolve_torque_session, T8 LocationService.record_point, and T3
Vehicle.location_tracking_enabled. See task-9-brief.md.

Fixtures: ``client`` / ``db_session`` from tests/conftest.py (base conftest).
No auth headers — the device path token IS the auth.
"""

import itertools
import logging
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.location_point import LocationPoint
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry
from app.routes.torque import TorqueTokenRedactionFilter, redact_torque_path
from app.services import declared_units
from app.services.torque_service import TorqueService

# Uploads store nothing while LiveLink's master switch is off (it gates the
# ingest pipeline). Explicit, not inherited from whatever an earlier test left
# in the shared database.
pytestmark = pytest.mark.usefixtures("livelink_enabled")

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


async def _make_torque_source(
    db_session: AsyncSession, location_tracking_enabled: bool = True
) -> tuple[str, LiveLinkDevice, str]:
    """Create a user + vehicle + kind='torque' device, return (vin, device, raw_token)."""
    n = next(_SEQ)
    user = User(
        username=f"torque_route_user_{n}",
        email=f"torque_route_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"TORQROUTETST{n:05d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Torque Route Car {n}",
        vehicle_type="Car",
        location_tracking_enabled=location_tracking_enabled,
    )
    db_session.add(vehicle)
    await db_session.flush()

    device, raw_token = await TorqueService(db_session).create_source(vin)
    await db_session.commit()
    return vin, device, raw_token


def _epoch_ms(dt: datetime) -> str:
    """Format a datetime as a Torque-style millisecond epoch query value."""
    return str(int(dt.timestamp() * 1000))


async def _telemetry_rows(db_session: AsyncSession, vin: str) -> list[VehicleTelemetry]:
    return list(
        (await db_session.execute(select(VehicleTelemetry).where(VehicleTelemetry.vin == vin)))
        .scalars()
        .all()
    )


async def _location_rows(db_session: AsyncSession, vin: str) -> list[LocationPoint]:
    return list(
        (await db_session.execute(select(LocationPoint).where(LocationPoint.vin == vin)))
        .scalars()
        .all()
    )


async def _get_session(
    db_session: AsyncSession, device_id: str, external_session_id: str
) -> DriveSession:
    return (
        await db_session.execute(
            select(DriveSession).where(
                DriveSession.device_id == device_id,
                DriveSession.external_session_id == external_session_id,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_get_ingest_stores_telemetry_and_session(
    client: AsyncClient, db_session: AsyncSession
):
    """A GET with OBD PIDs + a session id: 200 OK!, telemetry stored, session created."""
    vin, device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(seconds=5)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S1", "id": "abc", "time": _epoch_ms(t), "k0c": "1800", "k0d": "60"},
    )

    assert r.status_code == 200
    assert r.text == "OK!"
    assert r.headers["content-type"].startswith("text/plain")

    rows = await _telemetry_rows(db_session, vin)
    param_keys = {row.param_key for row in rows}
    assert "ENGINE_RPM" in param_keys
    assert "SPEED" in param_keys

    session = await _get_session(db_session, device.device_id, "S1")
    assert session.vin == vin


@pytest.mark.asyncio
async def test_unpadded_pids_are_stored_under_canonical_keys(
    client: AsyncClient, db_session: AsyncSession
):
    """#223: `kc`/`kd` from Torque Pro 1.12 land as ENGINE_RPM/SPEED, not as raw `KC`/`KD`."""
    vin, _device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(seconds=5)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S223", "id": "abc", "time": _epoch_ms(t), "kc": "2549", "kd": "48"},
    )

    assert r.status_code == 200
    param_keys = {row.param_key for row in await _telemetry_rows(db_session, vin)}
    assert param_keys == {"ENGINE_RPM", "SPEED"}


@pytest.mark.asyncio
async def test_minimal_test_request_returns_ok_with_no_pids(
    client: AsyncClient, db_session: AsyncSession
):
    """Torque's connectivity/settings-test GET (eml + v, no PIDs, no session) is a no-crash 200."""
    vin, _device, token = await _make_torque_source(db_session)

    r = await client.get(f"/api/v1/torque/{token}/upload", params={"eml": "x", "v": "3"})

    assert r.status_code == 200
    assert r.text == "OK!"
    assert await _telemetry_rows(db_session, vin) == []


@pytest.mark.asyncio
async def test_gps_pids_write_location_point_when_tracking_enabled(
    client: AsyncClient, db_session: AsyncSession
):
    """GPS PIDs + location_tracking_enabled=True write a location_points row
    attached to the session, and never leak into VehicleTelemetry."""
    vin, device, token = await _make_torque_source(db_session, location_tracking_enabled=True)
    t = datetime.now(UTC) - timedelta(seconds=5)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={
            "session": "S1",
            "time": _epoch_ms(t),
            "kff1006": "40.712800",
            "kff1005": "-74.006000",
        },
    )

    assert r.status_code == 200
    assert r.text == "OK!"

    points = await _location_rows(db_session, vin)
    assert len(points) == 1

    session = await _get_session(db_session, device.device_id, "S1")
    assert points[0].drive_session_id == session.id

    assert await _telemetry_rows(db_session, vin) == []


@pytest.mark.asyncio
async def test_tracking_disabled_stores_obd_but_skips_location(
    client: AsyncClient, db_session: AsyncSession
):
    """location_tracking_enabled=False: OBD telemetry still stored, no location_points row."""
    vin, _device, token = await _make_torque_source(db_session, location_tracking_enabled=False)
    t = datetime.now(UTC) - timedelta(seconds=5)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={
            "session": "S1",
            "time": _epoch_ms(t),
            "k0c": "1800",
            "kff1006": "40.712800",
            "kff1005": "-74.006000",
        },
    )

    assert r.status_code == 200
    assert r.text == "OK!"

    rows = await _telemetry_rows(db_session, vin)
    assert any(row.param_key == "ENGINE_RPM" for row in rows)
    assert await _location_rows(db_session, vin) == []


@pytest.mark.asyncio
async def test_invalid_token_returns_403(client: AsyncClient):
    """An unrecognized token: 403, plain-text body that is not the OK! sentinel."""
    r = await client.get("/api/v1/torque/not-a-real-token/upload", params={"eml": "x"})

    assert r.status_code == 403
    assert r.text != "OK!"


@pytest.mark.asyncio
async def test_replay_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    """Replaying the same request twice: still 200 OK!, no duplicate telemetry or location rows."""
    vin, _device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(seconds=5)
    params = {
        "session": "S1",
        "time": _epoch_ms(t),
        "k0c": "1800",
        "kff1006": "40.712800",
        "kff1005": "-74.006000",
    }

    r1 = await client.get(f"/api/v1/torque/{token}/upload", params=params)
    r2 = await client.get(f"/api/v1/torque/{token}/upload", params=params)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.text == "OK!"
    assert r2.text == "OK!"

    rows = await _telemetry_rows(db_session, vin)
    engine_rpm_rows = [row for row in rows if row.param_key == "ENGINE_RPM"]
    assert len(engine_rpm_rows) == 1

    points = await _location_rows(db_session, vin)
    assert len(points) == 1


@pytest.mark.asyncio
async def test_post_variant_accepted(client: AsyncClient, db_session: AsyncSession):
    """POST with a form body is accepted for robustness (Torque itself uses GET)."""
    vin, _device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(seconds=5)

    r = await client.post(
        f"/api/v1/torque/{token}/upload",
        data={"session": "S1", "time": _epoch_ms(t), "k0c": "1800"},
    )

    assert r.status_code == 200
    assert r.text == "OK!"

    rows = await _telemetry_rows(db_session, vin)
    assert any(row.param_key == "ENGINE_RPM" for row in rows)


def test_redact_torque_path_strips_the_token():
    """redact_torque_path replaces the token segment, regardless of surrounding text."""
    raw = 'GET /api/v1/torque/abcdef0123456789/upload?session=S1 HTTP/1.1" 200 3'

    redacted = redact_torque_path(raw)

    assert "abcdef0123456789" not in redacted
    assert "/api/v1/torque/<redacted>/upload" in redacted


def test_redaction_filter_scrubs_the_token_from_a_log_record():
    """R1-H3: a log record whose message contains the raw token in the ingest
    path is rewritten so the raw token is absent from the rendered message."""
    real_token = "super-secret-torque-device-token-000111"
    record = logging.LogRecord(
        name="granian.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            f'1.2.3.4 - - [17/Jul/2026] "GET /api/v1/torque/{real_token}/upload?session=S1 '
            'HTTP/1.1" 200 3'
        ),
        args=(),
        exc_info=None,
    )

    kept = TorqueTokenRedactionFilter().filter(record)

    assert kept is True  # never drops the record
    rendered = record.getMessage()
    assert real_token not in rendered
    assert "/api/v1/torque/<redacted>/upload" in rendered


@pytest.mark.asyncio
async def test_future_device_time_is_clamped_so_duration_stays_non_negative(
    client: AsyncClient, db_session: AsyncSession
):
    """R2-H2: a device clock 2h in the future must not become started_at. When a
    chronologically-newer session id finalizes the trip, duration_seconds >= 0.
    """
    _vin, device, token = await _make_torque_source(db_session)
    future = datetime.now(UTC) + timedelta(hours=2)

    r1 = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S1", "time": _epoch_ms(future), "k0c": "1800"},
    )
    assert r1.status_code == 200

    # Chronologically-newer session id finalizes S1 at server-now.
    later = datetime.now(UTC) + timedelta(seconds=1)
    r2 = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S2", "time": _epoch_ms(later), "k0c": "1900"},
    )
    assert r2.status_code == 200

    s1 = await _get_session(db_session, device.device_id, "S1")
    assert s1.ended_at is not None
    assert s1.duration_seconds is not None
    assert s1.duration_seconds >= 0


@pytest.mark.asyncio
async def test_garbage_overrange_time_falls_back_to_server_now(
    client: AsyncClient, db_session: AsyncSession
):
    """`time` is only digit-validated upstream (torque_pid_map.parse_torque_query), not
    range-checked. A 20-digit garbage value overflows datetime.fromtimestamp — the route
    must degrade to server-now instead of 500ing (Torque retries on any non-OK! response,
    so an unhandled overflow would wedge a misconfigured device in a retry loop).
    """
    vin, _device, token = await _make_torque_source(db_session)
    before = datetime.now(UTC).replace(tzinfo=None)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S1", "time": "99999999999999999999", "k0c": "1800"},
    )
    after = datetime.now(UTC).replace(tzinfo=None)

    assert r.status_code == 200
    assert r.text == "OK!"

    rows = await _telemetry_rows(db_session, vin)
    engine_rpm = next(row for row in rows if row.param_key == "ENGINE_RPM")
    # Server-now-ish, not the far future the garbage value would have implied.
    assert before <= engine_rpm.timestamp <= after


@pytest.mark.asyncio
async def test_ecu_status_online_after_data_bearing_ingest(
    client: AsyncClient, db_session: AsyncSession
):
    """resolve_torque_session's newer-drive branch can set ecu_status='offline' via
    end_session; a data-bearing ingest must re-assert 'online' so the LiveLink
    status endpoint doesn't show an actively-uploading device as offline.
    """
    _vin, device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(seconds=5)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S1", "time": _epoch_ms(t), "k0c": "1800"},
    )
    assert r.status_code == 200

    refreshed = (
        await db_session.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device.device_id)
        )
    ).scalar_one()
    assert refreshed.ecu_status == "online"


# ---------------------------------------------------------------------------
# Routed through the source pipeline (source-modules plan, Task 9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_runs_through_the_source_pipeline(
    client: AsyncClient, db_session: AsyncSession
):
    """The route must delegate, not keep its own copy of the orchestration.

    A VALID token and EXACTLY one call. `await_count <= 1` would pass when the
    route never delegates at all, which is the regression this exists to catch.
    """
    from unittest.mock import AsyncMock, patch

    _vin, _device, token = await _make_torque_source(db_session)

    with patch("app.routes.torque.ingest", new=AsyncMock()) as ing:
        resp = await client.get(f"/api/v1/torque/{token}/upload", params={"k0c": "900"})

    assert resp.status_code == 200
    assert resp.text == "OK!"
    ing.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unlinked_source_still_answers_ok(client: AsyncClient, db_session: AsyncSession):
    """Torque retries forever on any non-OK response, and the pipeline returns
    early for an unlinked device, so the route must still say OK!."""
    from app.services.livelink_service import LiveLinkService

    n = next(_SEQ)
    token = LiveLinkService.generate_token()
    db_session.add(
        LiveLinkDevice(
            device_id=f"tq_unlinked_{n}",
            kind="torque",
            vin=None,
            torque_device_id=f"{n:032d}",
            device_token_hash=LiveLinkService.hash_token(token),
            enabled=True,
        )
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/torque/{token}/upload", params={"k0c": "900"})

    assert resp.status_code == 200
    assert resp.text == "OK!"


@pytest.mark.asyncio
async def test_an_upload_leaves_device_status_alone(client: AsyncClient, db_session: AsyncSession):
    """The route never wrote device_status, so a Torque source stays 'unknown'.

    Not cosmetic. check_device_offline_status only sweeps devices whose
    device_status is 'online', and notifies for each one it marks offline. A
    phone uploads only while driving, so marking it online on upload would
    send a "device offline" notification after every drive, to users who
    have never had one.
    """
    _vin, device, token = await _make_torque_source(db_session)
    await db_session.refresh(device)
    device_id, before = device.device_id, device.device_status

    resp = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S1", "time": _epoch_ms(datetime.now(UTC)), "k0c": "1800"},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    refreshed = (
        await db_session.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
    ).scalar_one()
    assert refreshed.device_status == before
    assert refreshed.last_seen is not None


@pytest.mark.asyncio
async def test_an_upload_while_livelink_is_off_answers_ok_and_stores_nothing(
    client: AsyncClient, db_session: AsyncSession
):
    """OK!, because Torque retries forever on anything else; nothing stored,
    because the master switch now gates every ingest path."""
    from app.models.settings import Setting

    vin, _device, token = await _make_torque_source(db_session)
    row = await db_session.get(Setting, "livelink_enabled")
    row.value = "false"  # the module's fixture put it on, and puts it back
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={"session": "S1", "time": _epoch_ms(datetime.now(UTC)), "k0c": "1800"},
    )

    assert resp.status_code == 200
    assert resp.text == "OK!"
    assert await _telemetry_rows(db_session, vin) == []


@pytest.mark.asyncio
async def test_readings_register_with_their_units_and_names(
    client: AsyncClient, db_session: AsyncSession
):
    """#223: INTAKE_PRESSURE registers in kPa and KFF1238 under its readable name."""
    keys = ["INTAKE_PRESSURE", "KFF1238"]
    # The registry is shared by the suite; start these two from nothing.
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys)))
    await db_session.commit()
    _vin, _device, token = await _make_torque_source(db_session)

    r = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={
            "session": "S223U",
            "id": "abc",
            "time": _epoch_ms(datetime.now(UTC) - timedelta(seconds=5)),
            "kb": "62.0",
            "kff1238": "14.1",
        },
    )

    assert r.status_code == 200
    rows = (
        await db_session.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys))
        )
    ).scalars()
    assert {p.param_key: (p.unit, p.display_name) for p in rows} == {
        "INTAKE_PRESSURE": ("kPa", "Intake Pressure"),
        "KFF1238": ("V", "OBD adapter voltage"),
    }


async def _units(db_session: AsyncSession, keys: list[str]) -> dict[str, str | None]:
    rows = (
        await db_session.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys))
        )
    ).scalars()
    return {p.param_key: p.unit for p in rows}


@pytest.mark.asyncio
async def test_a_declared_unit_waits_for_the_pids_first_value(
    client: AsyncClient, db_session: AsyncSession
):
    """F-3: a session-start request registers nothing; a PID's unit lands with its first value."""
    keys = ["K3C", "K23"]
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys)))
    await db_session.commit()
    _vin, _device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(seconds=10)

    start = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={
            "session": "S223D",
            "id": "abc",
            "time": _epoch_ms(t),
            "defaultUnit3c": "°C",
            "defaultUnit23": "kPa",
        },
    )
    assert start.status_code == 200
    assert await _units(db_session, keys) == {}

    value = await client.get(
        f"/api/v1/torque/{token}/upload",
        params={
            "session": "S223D",
            "id": "abc",
            "time": _epoch_ms(t + timedelta(seconds=5)),
            "k3c": "450.0",
        },
    )
    assert value.status_code == 200
    assert await _units(db_session, keys) == {"K3C": "°C"}  # K23 never carried a value


@pytest.mark.asyncio
async def test_a_restart_mid_session_heals_at_the_next_session_start(
    client: AsyncClient, db_session: AsyncSession
):
    """D4: the map is process memory; the next session start fills the unit in."""
    keys = ["K3D"]
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(keys)))
    await db_session.commit()
    _vin, _device, token = await _make_torque_source(db_session)
    t = datetime.now(UTC) - timedelta(minutes=10)

    def _get(session: str, at: datetime, **pids: str):
        return client.get(
            f"/api/v1/torque/{token}/upload",
            params={"session": session, "id": "abc", "time": _epoch_ms(at), **pids},
        )

    assert (await _get("S223R1", t, defaultUnit3d="°C")).status_code == 200
    declared_units._BY_DEVICE.clear()  # what a restart does
    assert (await _get("S223R1", t + timedelta(seconds=5), k3d="430.0")).status_code == 200
    assert await _units(db_session, keys) == {"K3D": None}
    assert (await _get("S223R2", t + timedelta(minutes=5), defaultUnit3d="°C")).status_code == 200
    assert await _units(db_session, keys) == {"K3D": "°C"}
