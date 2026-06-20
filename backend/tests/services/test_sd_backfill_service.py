"""Tests for SdBackfillService and TelemetryService.bulk_backfill."""

import itertools
import sqlite3
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.sd_backfill_service import SdBackfillService

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
