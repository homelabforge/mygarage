"""Tests for SdBackfillService and TelemetryService.bulk_backfill."""

import itertools
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.sd_backfill_service import SdBackfillService

# LiveLink's master switch gates the ingest pipeline and SD backfill, and it is
# off by default. Explicit, not inherited from whatever an earlier test left in
# the shared database.
pytestmark = pytest.mark.usefixtures("livelink_enabled")

# Module-level counter — persists for the entire test session so that each
# make_vehicle_and_device call gets globally unique usernames/VINs/device IDs
# even though the underlying DB session outlives individual test functions.
_VD_SEQ = itertools.count()


def _fixture_db(rows: list[tuple[str, int, float]]) -> bytes:
    """Build a minimal WiCAN SD log SQLite DB and return its bytes.

    rows: list of (param_name, timestamp_epoch_sec, value)
    Cleans up the temp file before returning.
    """
    fd = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    fd.close()
    try:
        c = sqlite3.connect(fd.name)
        c.execute(
            "CREATE TABLE param_info "
            "(Id INTEGER PRIMARY KEY, Name VARCHAR, Type VARCHAR, Data TEXT)"
        )
        c.execute("CREATE TABLE param_data (timestamp INTEGER, param_id INTEGER, value REAL)")
        ids: dict[str, int] = {}
        for name, ts, val in rows:
            if name not in ids:
                ids[name] = c.execute(
                    "INSERT INTO param_info (Name,Type) VALUES (?, 'NUMERIC')", (name,)
                ).lastrowid
            c.execute("INSERT INTO param_data VALUES (?,?,?)", (ts, ids[name], val))
        c.commit()
        c.close()
        return Path(fd.name).read_bytes()
    finally:
        Path(fd.name).unlink(missing_ok=True)


class _FakeClient:
    """Fake SdLogClient that serves pre-built file bytes from a dict."""

    def __init__(self, files: dict[str, tuple[str, bytes]]) -> None:
        # files: {filename: (status, bytes)}
        self._files = files

    async def list_logs(self) -> list[dict]:
        return [{"filename": f, "status": s, "size": 1} for f, (s, _) in self._files.items()]

    async def download_log(self, filename: str) -> bytes:
        return self._files[filename][1]


@pytest_asyncio.fixture
async def make_vehicle_and_device(db_session: AsyncSession):
    """Async factory: creates a minimal user, vehicle, and LiveLinkDevice.

    Returns an async callable accepting (session, *, device_address, sd_backfill_enabled).
    Uses _VD_SEQ (module-level) to produce globally unique identifiers across
    all tests that share the same session-scoped DB.
    """

    async def _factory(
        session: AsyncSession,
        *,
        device_address: str | None = None,
        sd_backfill_enabled: bool = False,
        kind: str | None = None,
    ) -> tuple[str, str]:
        n = next(_VD_SEQ)

        user = User(
            username=f"backfill_user_{n}",
            email=f"backfill_{n}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        session.add(user)
        await session.flush()

        vin = f"BACKFILLTEST{n:05d}"  # 17 chars
        vehicle = Vehicle(
            vin=vin,
            user_id=user.id,
            nickname=f"Backfill Car {n}",
            vehicle_type="Car",
        )
        session.add(vehicle)
        await session.flush()

        device_id = f"bbfill{n:08d}"  # unique, <=20 chars
        device = LiveLinkDevice(
            device_id=device_id,
            vin=vin,
            enabled=True,
            device_address=device_address,
            sd_backfill_enabled=sd_backfill_enabled,
        )
        if kind is not None:
            device.kind = kind
        session.add(device)
        await session.flush()

        return vin, device_id

    return _factory


@pytest.mark.asyncio
async def test_backfill_ingests_and_dedups(db_session, make_vehicle_and_device, monkeypatch):
    """First backfill ingests 2 rows; re-pull of the same active file ingests 0 (deduped)."""
    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://10.0.0.5", sd_backfill_enabled=True
    )
    db = _fixture_db([("0C-EngineRPM", 1781967506, 957.0), ("0D-VehicleSpeed", 1781967506, 60.0)])
    client = _FakeClient({"active.db": ("active", db)})
    svc = SdBackfillService(db_session)
    monkeypatch.setattr(svc, "_client_for", lambda addr: client)

    r1 = await svc.backfill_device(device_id)
    assert r1.rows_ingested == 2, f"expected 2 rows inserted, got {r1.rows_ingested}"
    assert r1.errors == [], f"unexpected errors: {r1.errors}"

    r2 = await svc.backfill_device(device_id)  # re-pull the active file
    assert r2.rows_ingested == 0, f"expected 0 rows on re-pull, got {r2.rows_ingested}"


@pytest.mark.asyncio
async def test_backfill_noop_without_address(db_session, make_vehicle_and_device, monkeypatch):
    """Device with no device_address → backfill returns empty result without hitting client."""
    vin, device_id = await make_vehicle_and_device(
        db_session, device_address=None, sd_backfill_enabled=True
    )
    svc = SdBackfillService(db_session)
    r = await svc.backfill_device(device_id)
    assert r.files_seen == 0 and r.rows_ingested == 0


@pytest.mark.asyncio
async def test_backfill_noop_sd_disabled(db_session, make_vehicle_and_device, monkeypatch):
    """Device with sd_backfill_enabled=False → backfill returns empty result."""
    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://10.0.0.6", sd_backfill_enabled=False
    )
    client = _FakeClient({"active.db": ("active", b"")})
    svc = SdBackfillService(db_session)
    monkeypatch.setattr(svc, "_client_for", lambda addr: client)
    r = await svc.backfill_device(device_id)
    assert r.files_seen == 0 and r.rows_ingested == 0


@pytest.mark.asyncio
async def test_backfill_skips_a_source_without_sd_backfill(
    db_session, make_vehicle_and_device, monkeypatch
):
    """Fable I1: the manual route and the queued worker both land here, so a
    generic device with a stray address and the switch on is never pulled."""
    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://10.0.0.7", sd_backfill_enabled=True, kind="generic_mqtt"
    )
    svc = SdBackfillService(db_session)
    calls: list[str] = []

    def _record(addr: str) -> _FakeClient:
        calls.append(addr)
        return _FakeClient({})

    monkeypatch.setattr(svc, "_client_for", _record)

    r = await svc.backfill_device(device_id)

    assert calls == []
    assert r.files_seen == 0 and r.rows_ingested == 0 and r.errors == []


@pytest.mark.asyncio
async def test_backfill_completed_file_skipped_on_re_pull(
    db_session, make_vehicle_and_device, monkeypatch
):
    """A completed (non-active) file should be skipped on subsequent polls."""
    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://10.0.0.7", sd_backfill_enabled=True
    )
    db = _fixture_db([("0C-EngineRPM", 1781967506, 957.0)])
    client = _FakeClient({"done.db": ("inactive", db)})
    svc = SdBackfillService(db_session)
    monkeypatch.setattr(svc, "_client_for", lambda addr: client)

    r1 = await svc.backfill_device(device_id)
    assert r1.rows_ingested == 1

    # Second poll: same file still listed — should be skipped (completed=True now)
    r2 = await svc.backfill_device(device_id)
    assert r2.rows_ingested == 0


@pytest.mark.asyncio
async def test_backfill_dedups_against_live_row(db_session, make_vehicle_and_device, monkeypatch):
    """Backfill must not duplicate a row already stored by the live ingest path.

    The live path stores naive UTC datetimes (via utc_now()).  SdLogParser
    produces tz-aware UTC datetimes (datetime.fromtimestamp(ts, UTC)).
    Before the fix, these were DISTINCT keys in the unique index so
    on_conflict_do_nothing silently let the duplicate through.  After the fix,
    bulk_backfill strips tzinfo before inserting, so the keys collide and the
    conflict clause skips the row.
    """
    epoch_t = 1781967506  # fixed epoch for reproducibility
    # Live path stores naive UTC — replicate exactly
    live_ts = datetime.fromtimestamp(epoch_t, UTC).replace(tzinfo=None)

    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://10.0.0.8", sd_backfill_enabled=True
    )

    # Seed a live telemetry row with naive UTC timestamp (as the live path would)
    live_row = VehicleTelemetry(
        vin=vin,
        device_id=device_id,
        param_key="0C-ENGINERPM",
        value=957.0,
        timestamp=live_ts,
    )
    db_session.add(live_row)
    await db_session.flush()

    # SD fixture contains the same PID at the same epoch; param name canonicalises
    # to "0C-ENGINERPM" inside bulk_backfill
    sd_db = _fixture_db([("0C-EngineRPM", epoch_t, 957.0)])
    client = _FakeClient({"active.db": ("active", sd_db)})
    svc = SdBackfillService(db_session)
    monkeypatch.setattr(svc, "_client_for", lambda addr: client)

    result = await svc.backfill_device(device_id)

    # Backfill row must have been skipped (conflict fired), not inserted
    assert result.rows_ingested == 0, (
        f"expected 0 rows_ingested (dedup with live row), got {result.rows_ingested}"
    )

    # Exactly one row must exist for this (device_id, param_key) — not two
    count_result = await db_session.execute(
        select(func.count(VehicleTelemetry.id)).where(
            VehicleTelemetry.device_id == device_id,
            VehicleTelemetry.param_key == "0C-ENGINERPM",
        )
    )
    row_count = count_result.scalar()
    assert row_count == 1, f"expected exactly 1 telemetry row (merged), found {row_count}"


@pytest.mark.asyncio
async def test_backfill_does_nothing_while_livelink_is_off(
    db_session, make_vehicle_and_device, monkeypatch
):
    """A backfill queued before the master switch went off still runs through
    here afterwards (run_sd_backfill), so the check lives in the service, not
    only in the route. The device is fully configured: only the switch stops it."""
    from app.models.settings import Setting

    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://10.0.0.5", sd_backfill_enabled=True
    )
    contacted: list[str] = []
    svc = SdBackfillService(db_session)
    monkeypatch.setattr(svc, "_client_for", lambda addr: contacted.append(addr))
    row = await db_session.get(Setting, "livelink_enabled")
    row.value = "false"  # the module's fixture put it on, and puts it back
    await db_session.commit()

    result = await svc.backfill_device(device_id)

    assert contacted == []
    assert (result.files_seen, result.rows_ingested) == (0, 0)


@pytest.mark.asyncio
async def test_backfill_refuses_an_address_that_no_longer_resolves_private(
    db_session, make_vehicle_and_device, monkeypatch, caplog
):
    """FB-7: the address was checked when it was saved, and a LAN hostname can
    resolve somewhere public later. A public literal stands in for that here.
    Logged and skipped, never connected to."""
    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://8.8.8.8", sd_backfill_enabled=True
    )
    svc = SdBackfillService(db_session)
    calls: list[str] = []

    def _record(addr: str) -> _FakeClient:
        calls.append(addr)
        return _FakeClient({})

    monkeypatch.setattr(svc, "_client_for", _record)

    with caplog.at_level("WARNING", logger="app.services.sd_backfill_service"):
        r = await svc.backfill_device(device_id)

    assert calls == []
    assert r.files_seen == 0 and r.rows_ingested == 0
    assert len(r.errors) == 1 and "private" in r.errors[0]
    assert any("8.8.8.8" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_a_queued_backfill_logs_a_refused_address_and_carries_on(
    db_session, make_vehicle_and_device, monkeypatch, caplog
):
    """The sweep's path (a device coming online queues one): the refusal is a
    log line, not an exception out of the background task."""
    import contextlib

    from app.tasks import livelink_tasks

    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://8.8.4.4", sd_backfill_enabled=True
    )
    await db_session.commit()
    connected: list[str] = []
    monkeypatch.setattr(
        SdBackfillService,
        "_client_for",
        lambda self, addr: connected.append(addr) or _FakeClient({}),
    )
    monkeypatch.setattr(
        livelink_tasks, "AsyncSessionLocal", lambda: contextlib.nullcontext(db_session)
    )

    with caplog.at_level("WARNING"):
        await livelink_tasks.run_sd_backfill(device_id)

    assert connected == []
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("8.8.4.4" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_backfill_says_so_when_the_address_does_not_resolve_at_all(
    db_session, make_vehicle_and_device, monkeypatch, caplog
):
    """Wave B review M-6: a DNS outage logged "doesn't resolve to a private
    address", which reads like a rebind. It's a lookup that failed, and the log
    says that. Still skipped. Red on f3a8b81c (the private wording)."""
    import socket

    vin, device_id = await make_vehicle_and_device(
        db_session, device_address="http://wican.invalid", sd_backfill_enabled=True
    )

    def _no_answer(*_args: object, **_kwargs: object) -> list:
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _no_answer)
    svc = SdBackfillService(db_session)
    calls: list[str] = []
    monkeypatch.setattr(svc, "_client_for", lambda addr: calls.append(addr) or _FakeClient({}))

    with caplog.at_level("WARNING", logger="app.services.sd_backfill_service"):
        r = await svc.backfill_device(device_id)

    assert calls == []
    assert len(r.errors) == 1 and "look up" in r.errors[0] and "private" not in r.errors[0]
    messages = [rec.getMessage() for rec in caplog.records]
    assert any("look up" in m and "wican.invalid" in m for m in messages)
