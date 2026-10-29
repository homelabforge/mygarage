"""DTCs in the JSON backup: every column, code + first seen, one active row per code (batch 3b task 11)."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_dtc import VehicleDTC
from app.routes.import_data._matching import _DuplicateMatcher
from app.routes.import_data.json_dtcs import import_dtcs
from app.services.dtc_service import DTCService
from tests.integration.routes._json_backup import V9, export_json, import_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NewVehicle = Callable[..., Awaitable[str]]


def _v9(*dtcs: dict[str, Any]) -> dict[str, Any]:
    return {**V9, "dtcs": list(dtcs)}


def _dtc(code: str, first_seen: str, *, active: bool = True, **fields: Any) -> dict[str, Any]:
    return {
        "device_id": "a1b2c3d4e5f6",
        "code": code,
        "first_seen": first_seen,
        "last_seen": first_seen,
        "is_active": active,
        **fields,
    }


async def _dtcs(sessionmaker: Any, vin: str) -> list[tuple[Any, ...]]:
    """The vehicle's DTC rows as plain tuples, oldest first, through a fresh session."""
    async with sessionmaker() as fresh:
        rows = (
            (
                await fresh.execute(
                    select(VehicleDTC).where(VehicleDTC.vin == vin).order_by(VehicleDTC.id)
                )
            )
            .scalars()
            .all()
        )
    return [
        (
            d.device_id,
            d.code,
            d.description,
            d.severity,
            d.user_notes,
            d.first_seen,
            d.last_seen,
            d.cleared_at,
            d.is_active,
        )
        for d in rows
    ]


_SOURCE_ROWS = [
    (
        "a1b2c3d4e5f6",
        "P0420",
        "Catalyst System Efficiency Below Threshold (Bank 1)",
        "warning",
        "Cleared: new cat",
        datetime(2026, 1, 5, 8, 0, 0),
        datetime(2026, 1, 20, 17, 45, 0),
        datetime(2026, 1, 21, 9, 0, 0),
        False,
    ),
    (
        "a1b2c3d4e5f6",
        "P0420",
        "My own description",
        "critical",
        None,
        datetime(2026, 4, 2, 7, 30, 0),
        datetime(2026, 4, 9, 18, 0, 0),
        None,
        True,
    ),
]


async def test_a_backup_round_trip_restores_every_dtc_column(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    source = await new_vehicle()
    target = await new_vehicle()
    for row in _SOURCE_ROWS:
        db_session.add(
            VehicleDTC(
                vin=source,
                device_id=row[0],
                code=row[1],
                description=row[2],
                severity=row[3],
                user_notes=row[4],
                first_seen=row[5],
                last_seen=row[6],
                cleared_at=row[7],
                is_active=row[8],
            )
        )
    await db_session.commit()

    exported = await export_json(client, auth_headers, source)
    data = await import_json(client, auth_headers, target, exported)
    # main: KeyError, the import has no dtcs bucket
    assert data["dtcs"]["success_count"] == 2, data
    assert data["errors"] == [] and data["warnings"] == [], data
    assert await _dtcs(test_sessionmaker, target) == _SOURCE_ROWS

    # A re-import into the same vehicle adds nothing (R5).
    again = await import_json(client, auth_headers, target, exported)
    assert again["dtcs"]["skipped_count"] == 2, again
    assert again["warnings"] == [], again
    assert await _dtcs(test_sessionmaker, target) == _SOURCE_ROWS


async def test_a_code_already_active_here_keeps_one_active_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    """A second active row of a code makes the next telemetry report raise (K11)."""
    vin = await new_vehicle()
    db_session.add(
        VehicleDTC(
            vin=vin,
            device_id="a1b2c3d4e5f6",
            code="P0300",
            first_seen=datetime(2026, 6, 1, 8, 0, 0),
            last_seen=datetime(2026, 6, 2, 8, 0, 0),
            is_active=True,
        )
    )
    await db_session.commit()

    # Not skipping duplicates: the rule holds anyway.
    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            _dtc("P0300", "2026-05-01T08:00:00"),
            _dtc("P0300", "2026-03-01T08:00:00", active=False, cleared_at="2026-03-02T08:00:00"),
            _dtc("P0171", "2026-05-10T08:00:00"),
            _dtc("P0171", "2026-05-11T08:00:00"),
        ),
        skip_duplicates=False,
    )
    # main: KeyError, no section read
    counts = data["dtcs"]
    assert (counts["success_count"], counts["skipped_count"], counts["error_count"]) == (2, 2, 0)
    assert data["errors"] == [], data
    assert data["warnings"] == [
        "DTC 0: P0300 is already active on this vehicle, so this copy wasn't imported",
        "DTC 3: P0171 is already active on this vehicle, so this copy wasn't imported",
    ], data
    stored = await _dtcs(test_sessionmaker, vin)
    assert sorted((d[1], d[8]) for d in stored) == [
        ("P0171", True),
        ("P0300", False),
        ("P0300", True),
    ]

    # The next report from the device bumps the one active row instead of raising.
    processed = await DTCService(db_session).process_dtcs(vin, "a1b2c3d4e5f6", ["P0300", "P0171"])
    assert [d.code for d in processed] == ["P0300", "P0171"]


async def test_a_bad_dtc_row_is_a_row_error_and_the_rest_import(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    no_code = _dtc("P0001", "2026-01-01T00:00:00")
    del no_code["code"]
    no_device = _dtc("P0002", "2026-01-01T00:00:00")
    del no_device["device_id"]
    no_last_seen = _dtc("P0005", "2026-01-01T00:00:00")
    del no_last_seen["last_seen"]
    # Severity and is_active are optional: the columns' defaults fill them in.
    bare = _dtc("P0006", "2026-01-01T00:00:00")
    del bare["is_active"]
    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            no_code,
            no_device,
            _dtc("P0003", "not a time"),
            _dtc("P0004", "2026-01-01T00:00:00", is_active="yes"),
            no_last_seen,
            bare,
        ),
    )
    # main: KeyError, nothing read
    assert data["dtcs"]["success_count"] == 1, data
    assert data["errors"] == [
        "DTC 0: code is missing",
        "DTC 1: device_id is missing",
        "DTC 2: first_seen is not a valid date and time",
        "DTC 3: is_active must be true or false",
        "DTC 4: last_seen is missing",
    ], data
    assert [(d[1], d[3], d[8]) for d in await _dtcs(test_sessionmaker, vin)] == [
        ("P0006", "warning", True)
    ]


async def test_a_dtc_matches_on_its_code_and_first_seen_together(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    """Same code another time, or another code the same time, is a different DTC (S6)."""
    vin = await new_vehicle()
    db_session.add(
        VehicleDTC(
            vin=vin,
            device_id="a1b2c3d4e5f6",
            code="P0420",
            first_seen=datetime(2026, 1, 5, 8, 0, 0),
            last_seen=datetime(2026, 1, 6, 8, 0, 0),
            cleared_at=datetime(2026, 1, 7, 8, 0, 0),
            is_active=False,
        )
    )
    await db_session.commit()

    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            # Neither of these is the stored row, so neither may spend it.
            _dtc("P0420", "2026-02-05T08:00:00", active=False),
            _dtc("P0171", "2026-01-05T08:00:00", active=False),
            _dtc("P0420", "2026-01-05T08:00:00", active=False),
        ),
    )
    # main: KeyError, no dtcs bucket
    assert (data["dtcs"]["success_count"], data["dtcs"]["skipped_count"]) == (2, 1), data
    assert sorted((d[1], d[5]) for d in await _dtcs(test_sessionmaker, vin)) == [
        ("P0171", datetime(2026, 1, 5, 8, 0, 0)),
        ("P0420", datetime(2026, 1, 5, 8, 0, 0)),
        ("P0420", datetime(2026, 2, 5, 8, 0, 0)),
    ]


async def _active_count(session: AsyncSession, vin: str, code: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(VehicleDTC)
        .where(VehicleDTC.vin == vin, VehicleDTC.code == code, VehicleDTC.is_active.is_(True))
    )
    return result.scalar_one()


async def test_ingest_that_loses_the_race_bumps_the_row_that_won(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, new_vehicle: NewVehicle
):
    """The check found nothing, then another writer's row landed first (R1-H5).

    SQLite can't run two writers at once, so the lost race is staged: the
    first look misses a row that's already there.
    """
    vin = await new_vehicle()
    winner = VehicleDTC(
        vin=vin,
        device_id="a1b2c3d4e5f6",
        code="P0420",
        first_seen=datetime(2026, 7, 1, 8, 0, 0),
        last_seen=datetime(2026, 7, 1, 8, 0, 0),
        is_active=True,
    )
    db_session.add(winner)
    await db_session.commit()

    real_lookup = DTCService._get_vehicle_dtc
    looks: list[str] = []

    async def first_look_misses(self: DTCService, vin_: str, code: str) -> VehicleDTC | None:
        looks.append(code)
        return None if len(looks) == 1 else await real_lookup(self, vin_, code)

    monkeypatch.setattr(DTCService, "_get_vehicle_dtc", first_look_misses)

    processed = await DTCService(db_session).process_dtcs(vin, "a1b2c3d4e5f6", ["P0420"])

    # main: a second active row lands beside the winner; with only 137's index, the report raises
    assert [d.id for d in processed] == [winner.id]
    assert await _active_count(db_session, vin, "P0420") == 1
    assert processed[0].last_seen > datetime(2026, 7, 1, 8, 0, 0)


async def _refuse(*_args: Any, **_kwargs: Any) -> None:
    """A flush the database refused for some reason that isn't the index."""
    raise IntegrityError("INSERT INTO vehicle_dtcs", {}, Exception("refused"))


async def test_a_refused_insert_that_isnt_the_index_is_a_row_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, new_vehicle: NewVehicle
):
    """Only an active copy of a code that's active here is the index saying no."""
    vin = await new_vehicle()
    db_session.add_all(
        [
            VehicleDTC(
                vin=vin,
                device_id="a1b2c3d4e5f6",
                code="P0420",
                first_seen=datetime(2026, 6, 1, 8, 0, 0),
                last_seen=datetime(2026, 6, 2, 8, 0, 0),
                is_active=True,
            ),
            # A cleared P0171 is history; it doesn't make the code active here.
            VehicleDTC(
                vin=vin,
                device_id="a1b2c3d4e5f6",
                code="P0171",
                first_seen=datetime(2026, 1, 1, 8, 0, 0),
                last_seen=datetime(2026, 1, 2, 8, 0, 0),
                cleared_at=datetime(2026, 1, 3, 8, 0, 0),
                is_active=False,
            ),
        ]
    )
    await db_session.commit()
    matcher = await _DuplicateMatcher.before_import(db_session, VehicleDTC)
    monkeypatch.setattr(db_session, "flush", _refuse)
    bucket = {"success": 0, "errors": 0, "skipped": 0}
    errors: list[str] = []
    warnings: list[str] = []

    await import_dtcs(
        db_session,
        vin,
        [
            # P0420 is active here, but a cleared row never meets the index.
            _dtc("P0420", "2026-03-01T08:00:00", active=False),
            # Active, but no P0171 is.
            _dtc("P0171", "2026-03-01T08:00:00"),
        ],
        matcher=matcher,
        skip_duplicates=False,
        bucket=bucket,
        errors=errors,
        warnings=warnings,
    )

    # main: ImportError, no json_dtcs
    assert warnings == []
    assert errors == ["DTC 0: could not be imported", "DTC 1: could not be imported"]
    assert bucket == {"success": 0, "errors": 2, "skipped": 0}


async def test_a_refused_report_with_no_row_that_won_still_raises(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, new_vehicle: NewVehicle
):
    """The recovery only covers a lost race; any other refusal still reaches the caller."""
    vin = await new_vehicle()
    monkeypatch.setattr(db_session, "flush", _refuse)

    # main: raises too, so this pins the recovery's guard rather than going red
    with pytest.raises(IntegrityError):
        await DTCService(db_session).process_dtcs(vin, "a1b2c3d4e5f6", ["P0171"])


async def test_an_import_and_a_report_racing_on_postgresql_leave_one_active_row(
    test_engine: Any, test_sessionmaker: Any, new_vehicle: NewVehicle
):
    """Codex proof case 5: the import's insert and a live report's insert overlap.

    PostgreSQL only: the report's insert waits on the import's uncommitted row
    in the unique index, then fails once the import commits, and recovers.
    """
    if test_engine.dialect.name != "postgresql":
        pytest.skip("SQLite has one writer at a time; the staged test above covers it")

    vin = await new_vehicle()
    imported = asyncio.Event()
    bucket = {"success": 0, "errors": 0, "skipped": 0}
    errors: list[str] = []
    warnings: list[str] = []

    async def restore() -> None:
        async with test_sessionmaker() as a:
            matcher = await _DuplicateMatcher.before_import(a, VehicleDTC)
            await import_dtcs(
                a,
                vin,
                [_dtc("P0455", "2026-07-02T08:00:00")],
                matcher=matcher,
                skip_duplicates=False,
                bucket=bucket,
                errors=errors,
                warnings=warnings,
            )
            imported.set()
            # Hold the row uncommitted while the report's insert queues behind it.
            await asyncio.sleep(0.5)
            await a.commit()

    async def report() -> list[VehicleDTC]:
        async with test_sessionmaker() as b:
            await imported.wait()
            # Read committed: the import's row isn't visible yet, so this inserts too.
            processed = await DTCService(b).process_dtcs(vin, "ffeeddccbbaa", ["P0455"])
            await b.commit()
            return processed

    _, processed = await asyncio.gather(restore(), report())

    # main: two active P0455 rows (no index), and the next report raises
    assert bucket["success"] == 1 and errors == [], (bucket, errors)
    async with test_sessionmaker() as fresh:
        assert await _active_count(fresh, vin, "P0455") == 1
        again = await DTCService(fresh).process_dtcs(vin, "ffeeddccbbaa", ["P0455"])
        assert [d.id for d in again] == [processed[0].id]
