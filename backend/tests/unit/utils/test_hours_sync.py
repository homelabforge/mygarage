"""
Unit tests for engine-hours sync utility.

Tests auto-syncing of hours_records from service/fuel records. Unlike
odometer_sync (which locates a synced row by (vin, date)), hours_sync locates
by SOURCE IDENTITY (fuel_record_id / service_visit_id) — never (vin, date)
and never note-parsing. See the hours-usage-model plan §3/§5 (R1-H2).
"""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelRecord, HoursRecord, ServiceVisit
from app.utils.hours_sync import remove_synced_hours, sync_hours_from_record


@pytest_asyncio.fixture
async def fuel_record(
    db_session: AsyncSession, test_vehicle, clean_hours_records
) -> AsyncIterator[FuelRecord]:
    """A minimal fuel record — the FK parent for fuel-sourced hours rows."""
    record = FuelRecord(vin=test_vehicle["vin"], date=date(2024, 1, 15))
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    record_id = record.id
    yield record
    await db_session.execute(delete(FuelRecord).where(FuelRecord.id == record_id))
    await db_session.commit()


@pytest_asyncio.fixture
async def service_visit(
    db_session: AsyncSession, test_vehicle, clean_hours_records
) -> AsyncIterator[ServiceVisit]:
    """A minimal service visit — the FK parent for service-sourced hours rows."""
    visit = ServiceVisit(vin=test_vehicle["vin"], date=date(2024, 2, 1))
    db_session.add(visit)
    await db_session.commit()
    await db_session.refresh(visit)
    visit_id = visit.id
    yield visit
    await db_session.execute(delete(ServiceVisit).where(ServiceVisit.id == visit_id))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestSyncHoursFromRecord:
    """Test sync_hours_from_record — located by source identity."""

    async def test_creates_record_from_fuel_source(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """Fuel-sourced sync sets fuel_record_id, leaves service_visit_id null."""
        result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("100.5"),
            source_type="fuel",
            source_id=fuel_record.id,
        )

        assert result is not None
        assert result.engine_hours == Decimal("100.5")
        assert result.vin == test_vehicle["vin"]
        assert result.date == date(2024, 1, 15)
        assert result.source == "fuel"
        assert result.fuel_record_id == fuel_record.id
        assert result.service_visit_id is None
        assert result.notes is not None
        assert f"[AUTO-SYNC from fuel #{fuel_record.id}]" in result.notes

    async def test_second_call_same_fuel_id_updates_same_row(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """Calling again with the same fuel id updates the SAME row (no dupe)."""
        first = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("100.5"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        assert first is not None
        first_id = first.id

        second = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 22),
            engine_hours=Decimal("108.2"),
            source_type="fuel",
            source_id=fuel_record.id,
        )

        assert second is not None
        assert second.id == first_id
        assert second.engine_hours == Decimal("108.2")
        assert second.date == date(2024, 1, 22)

        # Confirm only ONE row exists for this fuel source (no duplicate).
        rows = (
            (
                await db_session.execute(
                    select(HoursRecord).where(HoursRecord.fuel_record_id == fuel_record.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_engine_hours_none_deletes_synced_row(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """engine_hours=None deletes the existing synced row and returns None."""
        created = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("100.5"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        assert created is not None

        result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=None,
            source_type="fuel",
            source_id=fuel_record.id,
        )

        assert result is None
        remaining = (
            await db_session.execute(
                select(HoursRecord).where(HoursRecord.fuel_record_id == fuel_record.id)
            )
        ).scalar_one_or_none()
        assert remaining is None

    async def test_engine_hours_none_when_no_row_exists_is_noop(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """engine_hours=None with no existing synced row is a safe no-op."""
        result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=None,
            source_type="fuel",
            source_id=fuel_record.id,
        )
        assert result is None

    async def test_manual_row_never_touched_by_sync(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """A source='manual' row at the SAME vin/date is never modified or deleted."""
        manual = HoursRecord(
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("999.9"),
            notes="Manual reading from dash photo",
            source="manual",
        )
        db_session.add(manual)
        await db_session.commit()
        await db_session.refresh(manual)
        manual_id = manual.id

        # Create, then update, then clear a fuel-sourced sync at the SAME
        # (vin, date) as the manual row — none of these steps may touch it.
        await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("100.5"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("108.2"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=None,
            source_type="fuel",
            source_id=fuel_record.id,
        )

        untouched = (
            await db_session.execute(select(HoursRecord).where(HoursRecord.id == manual_id))
        ).scalar_one()
        assert untouched.engine_hours == Decimal("999.9")
        assert untouched.source == "manual"
        assert untouched.notes == "Manual reading from dash photo"
        assert untouched.fuel_record_id is None
        assert untouched.service_visit_id is None

    async def test_service_visit_source_sets_service_visit_id(
        self, db_session: AsyncSession, test_vehicle, service_visit
    ):
        """service_visit source sets service_visit_id, not fuel_record_id."""
        result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 2, 1),
            engine_hours=Decimal("250.3"),
            source_type="service_visit",
            source_id=service_visit.id,
        )

        assert result is not None
        assert result.source == "service_visit"
        assert result.service_visit_id == service_visit.id
        assert result.fuel_record_id is None
        assert result.notes is not None
        assert f"[AUTO-SYNC from service_visit #{service_visit.id}]" in result.notes

    async def test_fuel_and_service_visit_sources_are_independent_identities(
        self, db_session: AsyncSession, test_vehicle, fuel_record, service_visit
    ):
        """A fuel sync and a service_visit sync never collide, even sharing a date."""
        fuel_result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 2, 1),
            engine_hours=Decimal("100.0"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        service_result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 2, 1),
            engine_hours=Decimal("101.0"),
            source_type="service_visit",
            source_id=service_visit.id,
        )

        assert fuel_result is not None
        assert service_result is not None
        assert fuel_result.id != service_result.id

    async def test_commit_false_flushes_without_committing(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """commit=False flushes (row visible, id assigned) but never commits."""
        fuel_record_id = fuel_record.id  # capture before rollback expires attrs

        result = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 3, 1),
            engine_hours=Decimal("120.5"),
            source_type="fuel",
            source_id=fuel_record_id,
            commit=False,
        )

        assert result is not None
        assert result.id is not None  # flush assigned an id

        # Visible within the same session/transaction (flushed, not committed).
        visible = (
            await db_session.execute(
                select(HoursRecord).where(HoursRecord.fuel_record_id == fuel_record_id)
            )
        ).scalar_one_or_none()
        assert visible is not None

        # Rolling back discards it — proves it was never committed.
        await db_session.rollback()
        after_rollback = (
            await db_session.execute(
                select(HoursRecord).where(HoursRecord.fuel_record_id == fuel_record_id)
            )
        ).scalar_one_or_none()
        assert after_rollback is None

    async def test_unknown_source_type_raises(self, db_session: AsyncSession, test_vehicle):
        """An unrecognized source_type must fail loudly, not silently default
        to the service_visit_id column (which would filter on the wrong FK,
        miss any existing synced row for the real source, and — on create —
        insert a row with BOTH FK columns null)."""
        with pytest.raises(ValueError, match="livelink"):
            await sync_hours_from_record(
                db=db_session,
                vin=test_vehicle["vin"],
                date=date(2024, 1, 15),
                engine_hours=Decimal("100.5"),
                source_type="livelink",
                source_id=1,
            )


@pytest.mark.integration
@pytest.mark.asyncio
class TestRemoveSyncedHours:
    """Test remove_synced_hours — explicit cleanup by source identity."""

    async def test_deletes_identified_synced_row(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        created = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("100.5"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        assert created is not None

        await remove_synced_hours(db_session, "fuel", fuel_record.id)

        remaining = (
            await db_session.execute(
                select(HoursRecord).where(HoursRecord.fuel_record_id == fuel_record.id)
            )
        ).scalar_one_or_none()
        assert remaining is None

    async def test_leaves_manual_and_other_source_rows(
        self,
        db_session: AsyncSession,
        test_vehicle,
        fuel_record,
        service_visit,
    ):
        # A second, distinct fuel record — used only here, so created inline
        # rather than as a shared fixture.
        other_fuel_record = FuelRecord(vin=test_vehicle["vin"], date=date(2024, 1, 20))
        db_session.add(other_fuel_record)
        await db_session.commit()
        await db_session.refresh(other_fuel_record)

        manual = HoursRecord(
            vin=test_vehicle["vin"],
            date=date(2024, 1, 10),
            engine_hours=Decimal("50.0"),
            source="manual",
        )
        db_session.add(manual)
        await db_session.commit()
        await db_session.refresh(manual)

        target = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 15),
            engine_hours=Decimal("100.5"),
            source_type="fuel",
            source_id=fuel_record.id,
        )
        other_fuel_synced = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 1, 20),
            engine_hours=Decimal("110.0"),
            source_type="fuel",
            source_id=other_fuel_record.id,
        )
        service_synced = await sync_hours_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 2, 1),
            engine_hours=Decimal("250.3"),
            source_type="service_visit",
            source_id=service_visit.id,
        )
        assert target is not None
        assert other_fuel_synced is not None
        assert service_synced is not None

        await remove_synced_hours(db_session, "fuel", fuel_record.id)

        remaining_ids = {
            row.id
            for row in (
                await db_session.execute(
                    select(HoursRecord).where(HoursRecord.vin == test_vehicle["vin"])
                )
            )
            .scalars()
            .all()
        }
        assert manual.id in remaining_ids
        assert other_fuel_synced.id in remaining_ids
        assert service_synced.id in remaining_ids
        assert target.id not in remaining_ids

        await db_session.execute(delete(FuelRecord).where(FuelRecord.id == other_fuel_record.id))
        await db_session.commit()

    async def test_noop_when_no_matching_row(
        self, db_session: AsyncSession, test_vehicle, fuel_record
    ):
        """Removing a source identity with no synced row is a safe no-op."""
        await remove_synced_hours(db_session, "fuel", fuel_record.id)
        # No exception; nothing to assert beyond "did not raise."

    async def test_unknown_source_type_raises(self, db_session: AsyncSession):
        """Same exhaustive-dispatch guarantee as sync_hours_from_record."""
        with pytest.raises(ValueError, match="livelink"):
            await remove_synced_hours(db_session, "livelink", 1)
