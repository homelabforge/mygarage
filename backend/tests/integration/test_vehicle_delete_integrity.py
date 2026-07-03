"""Vehicle-delete integrity tests (audit findings F1 + F15).

F1: ``VehicleService.delete_vehicle`` issues a bulk ``DELETE`` statement,
which bypasses ORM relationship cascades. On PostgreSQL the DB-level
``ON DELETE CASCADE`` clauses cover it; on SQLite they only fire when
``PRAGMA foreign_keys=ON`` is set per-connection. The production engine
must therefore enable the pragma, and deleting a vehicle must remove
every child row on BOTH engines — including tables like
``vehicle_telemetry`` and ``drive_sessions`` that have no ORM
relationship on ``Vehicle`` and rely purely on the FK cascade.

F15: deleting a vehicle must also remove its VIN-keyed upload
directories (photos/documents/attachments); the DB cascade does not
touch the filesystem. Production evidence: an orphaned photo directory
for a long-deleted test vehicle.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.def_record import DEFRecord
from app.models.drive_session import DriveSession
from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.vehicle_service import VehicleService
from app.utils.datetime_utils import utc_now

# One row per child table. VehicleTelemetry / VehicleTelemetryLatest /
# DriveSession deliberately included: they have NO ORM relationship on
# Vehicle, so only a DB-level cascade can clean them.
CHILD_MODELS = [
    (FuelRecord, "vin"),
    (DEFRecord, "vin"),
    (OdometerRecord, "vin"),
    (Reminder, "vin"),
    (VehicleTelemetry, "vin"),
    (VehicleTelemetryLatest, "vin"),
    (DriveSession, "vin"),
]


async def _seed_vehicle_with_children(db_session: AsyncSession, user_id: int, vin: str) -> None:
    """Create a throwaway vehicle with one row in every child table."""
    today = date.today()
    now = utc_now()

    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname="Delete Integrity",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Cascade",
        )
    )
    await db_session.flush()

    db_session.add_all(
        [
            FuelRecord(
                vin=vin,
                date=today,
                odometer_km=Decimal("1000.00"),
                liters=Decimal("40.000"),
                is_full_tank=True,
            ),
            DEFRecord(vin=vin, date=today, fill_level=Decimal("0.75")),
            OdometerRecord(vin=vin, date=today, odometer_km=Decimal("1000.00")),
            Reminder(
                vin=vin,
                title="Oil change",
                reminder_type="date",
                due_date=today + timedelta(days=30),
            ),
            VehicleTelemetry(
                vin=vin,
                device_id="deadbeef0001",
                param_key="ENGINE_RPM",
                value=800.0,
                timestamp=now,
            ),
            VehicleTelemetryLatest(
                vin=vin,
                param_key="ENGINE_RPM",
                value=800.0,
                timestamp=now,
            ),
            DriveSession(vin=vin, device_id="deadbeef0001", started_at=now),
        ]
    )
    await db_session.commit()


async def _count(db_session: AsyncSession, model: type, vin: str) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(model).where(getattr(model, "vin") == vin)
    )
    return int(result.scalar() or 0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sqlite_connections_enforce_foreign_keys(db_session: AsyncSession) -> None:
    """F1 guard: every SQLite connection must run with foreign_keys=ON.

    Without this pragma the ``ON DELETE CASCADE`` clauses declared on the
    models are decorative and bulk deletes silently orphan child rows.
    """
    if db_session.get_bind().dialect.name != "sqlite":
        pytest.skip("PRAGMA foreign_keys is SQLite-specific; PG always enforces FKs")

    result = await db_session.execute(text("PRAGMA foreign_keys"))
    assert result.scalar() == 1, (
        "SQLite connection has foreign_keys=OFF - declared FK cascades do not "
        "fire and vehicle deletes orphan child rows (audit finding F1)"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_vehicle_removes_all_child_rows(
    db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """F1: delete_vehicle must leave zero child rows on the live engine.

    Regression scenario: delete a vehicle, later re-add the same VIN -
    orphaned history from the old vehicle silently reattaches.
    """
    vin = "DELINTEG000000001"
    await _seed_vehicle_with_children(db_session, int(test_user["id"]), vin)  # type: ignore[arg-type]

    for model, _ in CHILD_MODELS:
        assert await _count(db_session, model, vin) == 1, f"seed failed for {model.__name__}"

    user = await db_session.get(User, test_user["id"])
    assert user is not None
    await VehicleService(db_session).delete_vehicle(vin, user)

    vehicle_gone = (
        await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
    ).scalar_one_or_none()
    assert vehicle_gone is None, "vehicle row survived delete_vehicle"

    for model, _ in CHILD_MODELS:
        orphans = await _count(db_session, model, vin)
        assert orphans == 0, (
            f"{model.__name__}: {orphans} orphaned row(s) survived vehicle delete "
            "(audit finding F1 - bulk delete without enforced FK cascades)"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_vehicle_removes_vin_keyed_files(
    db_session: AsyncSession,
    test_user: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F15: delete_vehicle must remove the VIN's upload directories.

    Production evidence for the gap: /data/photos/<deleted test VIN>/ with
    32 orphaned files, carried into every backup since.
    """
    vin = "DELINTEG000000002"

    photos_dir = tmp_path / "photos"
    documents_dir = tmp_path / "documents"
    attachments_dir = tmp_path / "attachments"
    monkeypatch.setattr(settings, "photos_dir", photos_dir)
    monkeypatch.setattr(settings, "documents_dir", documents_dir)
    monkeypatch.setattr(settings, "attachments_dir", attachments_dir)

    for base in (photos_dir, documents_dir, attachments_dir):
        vin_dir = base / vin
        vin_dir.mkdir(parents=True)
        (vin_dir / "orphan-candidate.bin").write_bytes(b"data")

    await _seed_vehicle_with_children(db_session, int(test_user["id"]), vin)  # type: ignore[arg-type]

    # Attachments are polymorphic (record_type/record_id, NOT VIN-keyed) and
    # live outside the VIN directories - production evidence: 26 service-visit
    # attachment files that no VIN-dir sweep would ever reach.
    from app.models.attachment import Attachment
    from app.models.service_visit import ServiceVisit

    visit = ServiceVisit(vin=vin, date=date.today(), service_category="Maintenance")
    db_session.add(visit)
    await db_session.flush()
    visit_file = attachments_dir / "service_visit" / str(visit.id) / "invoice.pdf"
    visit_file.parent.mkdir(parents=True)
    visit_file.write_bytes(b"pdf")
    db_session.add(
        Attachment(
            record_type="service_visit",
            record_id=visit.id,
            file_path=str(visit_file),
            file_type="pdf",
            file_size=3,
        )
    )
    await db_session.commit()

    user = await db_session.get(User, test_user["id"])
    assert user is not None
    await VehicleService(db_session).delete_vehicle(vin, user)

    for base in (photos_dir, documents_dir, attachments_dir):
        assert not (base / vin).exists(), (
            f"{base.name}/{vin} survived vehicle delete (audit finding F15 - "
            "DB cascade does not clean the filesystem)"
        )
    assert not visit_file.exists(), (
        "service-visit attachment file survived vehicle delete (audit finding "
        "F15 - polymorphic attachments are not covered by VIN-dir cleanup)"
    )
    orphan_attachments = (
        await db_session.execute(
            select(func.count()).select_from(Attachment).where(Attachment.record_id == visit.id)
        )
    ).scalar()
    assert orphan_attachments == 0, "attachment row survived vehicle delete"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_vehicle_survives_file_cleanup_failure(
    db_session: AsyncSession,
    test_user: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filesystem error during post-commit cleanup must not fail the delete.

    The DB delete is already committed when file cleanup runs; an unlink or
    rmtree error must degrade to a logged warning, never a 500 for a delete
    that already happened (codex review R1-H1).
    """
    import shutil as shutil_module

    vin = "DELINTEG000000003"
    photos_dir = tmp_path / "photos"
    monkeypatch.setattr(settings, "photos_dir", photos_dir)
    monkeypatch.setattr(settings, "documents_dir", tmp_path / "documents")
    monkeypatch.setattr(settings, "attachments_dir", tmp_path / "attachments")
    (photos_dir / vin).mkdir(parents=True)

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr(shutil_module, "rmtree", _boom)

    await _seed_vehicle_with_children(db_session, int(test_user["id"]), vin)  # type: ignore[arg-type]
    user = await db_session.get(User, test_user["id"])
    assert user is not None

    # Must not raise despite rmtree failing.
    await VehicleService(db_session).delete_vehicle(vin, user)

    vehicle_gone = (
        await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
    ).scalar_one_or_none()
    assert vehicle_gone is None, "DB delete must succeed even when file cleanup fails"
