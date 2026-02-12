"""
Unit tests for odometer sync utility.

Tests auto-syncing of odometer records from service/fuel records.
"""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OdometerRecord
from app.utils.odometer_sync import sync_odometer_from_record


@pytest_asyncio.fixture
async def clean_odometer_records(db_session: AsyncSession, test_vehicle):
    """Clean up odometer records for test vehicle before each test.

    This ensures test isolation when running with other tests that may
    create odometer records for the same test vehicle.
    """
    # Delete any existing odometer records for the test vehicle
    await db_session.execute(
        delete(OdometerRecord).where(OdometerRecord.vin == test_vehicle["vin"])
    )
    await db_session.commit()
    yield
    # Cleanup after test as well
    await db_session.execute(
        delete(OdometerRecord).where(OdometerRecord.vin == test_vehicle["vin"])
    )
    await db_session.commit()


@pytest.mark.unit
@pytest.mark.asyncio
class TestOdometerSync:
    """Test odometer sync utility function."""

    async def test_sync_creates_record_when_none_exists(
        self, db_session: AsyncSession, test_vehicle, clean_odometer_records
    ):
        """Test that sync creates a new odometer record when none exists."""
        test_date = date(2024, 1, 15)
        mileage = 50000

        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=mileage,
            source_type="service",
            source_id=1,
        )

        assert result is not None
        assert result.mileage == mileage
        assert result.vin == test_vehicle["vin"]
        assert result.date == test_date
        assert result.notes is not None
        assert "[AUTO-SYNC from service #1]" in result.notes
        assert result.source == "service"

    async def test_sync_skips_when_mileage_is_none(self, db_session: AsyncSession, test_vehicle):
        """Test that sync does nothing when mileage is None."""
        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 2, 1),
            mileage=None,
            source_type="fuel",
            source_id=1,
        )

        assert result is None

    async def test_sync_updates_auto_synced_record(
        self, db_session: AsyncSession, test_vehicle, clean_odometer_records
    ):
        """Test that sync updates existing auto-synced record."""
        test_date = date(2024, 3, 1)

        # Create initial auto-synced record
        initial = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=51000,
            source_type="service",
            source_id=1,
        )
        assert initial is not None
        initial_id = initial.id

        # Update with new mileage
        updated = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=51500,
            source_type="fuel",
            source_id=2,
        )

        assert updated is not None
        assert updated.id == initial_id  # Same record updated
        assert updated.mileage == 51500
        assert updated.notes is not None
        assert "[AUTO-SYNC from fuel #2]" in updated.notes
        assert updated.source == "fuel"

    async def test_sync_does_not_overwrite_manual_entry(
        self, db_session: AsyncSession, test_vehicle, clean_odometer_records
    ):
        """Test that sync does not overwrite manual odometer entry."""
        test_date = date(2024, 4, 1)

        # Create a manual odometer entry (no AUTO-SYNC marker, source=manual)
        manual_record = OdometerRecord(
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=52000,
            notes="Manual entry from inspection",
            source="manual",
        )
        db_session.add(manual_record)
        await db_session.commit()

        # Try to sync a different mileage
        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=52500,
            source_type="service",
            source_id=1,
        )

        # Should return None (did not update)
        assert result is None

        # Verify original value unchanged
        query = await db_session.execute(
            select(OdometerRecord)
            .where(OdometerRecord.vin == test_vehicle["vin"])
            .where(OdometerRecord.date == test_date)
        )
        record = query.scalar_one()
        assert record.mileage == 52000
        assert record.notes is not None
        assert "Manual entry" in record.notes

    async def test_sync_overwrites_livelink_record(
        self, db_session: AsyncSession, test_vehicle, clean_odometer_records
    ):
        """Test that fuel/service sync overwrites a LiveLink odometer record.

        User-entered data from fuel fill-ups or service visits is more
        authoritative than auto-recorded LiveLink telemetry.
        """
        test_date = date(2024, 4, 15)

        # Create a LiveLink odometer record (as the telemetry service would)
        livelink_record = OdometerRecord(
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=7924,  # km stored as miles (the bug this fixes)
            source="livelink",
            notes="Auto-updated from LiveLink (A6-Odometer)",
        )
        db_session.add(livelink_record)
        await db_session.commit()
        await db_session.refresh(livelink_record)
        record_id = livelink_record.id

        # Fuel fill-up sync should overwrite the LiveLink record
        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=4908,
            source_type="fuel",
            source_id=42,
        )

        assert result is not None
        assert result.id == record_id  # Same record updated, not a new one
        assert result.mileage == 4908
        assert result.source == "fuel"
        assert result.notes is not None
        assert "[AUTO-SYNC from fuel #42]" in result.notes

    async def test_sync_from_service_record(
        self, db_session: AsyncSession, test_vehicle, clean_odometer_records
    ):
        """Test sync creates correct notes and source for service source."""
        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 5, 1),
            mileage=53000,
            source_type="service",
            source_id=42,
        )

        assert result is not None
        assert result.notes is not None
        assert "[AUTO-SYNC from service #42]" in result.notes
        assert result.source == "service"

    async def test_sync_from_fuel_record(self, db_session: AsyncSession, test_vehicle):
        """Test sync creates correct notes and source for fuel source."""
        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 5, 15),
            mileage=53500,
            source_type="fuel",
            source_id=99,
        )

        assert result is not None
        assert result.notes is not None
        assert "[AUTO-SYNC from fuel #99]" in result.notes
        assert result.source == "fuel"

    async def test_sync_preserves_manual_entry_with_empty_notes(
        self, db_session: AsyncSession, test_vehicle, clean_odometer_records
    ):
        """Test that sync does not overwrite manual entry with empty notes."""
        test_date = date(2024, 6, 1)

        # Create a manual odometer entry with no notes
        manual_record = OdometerRecord(
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=54000,
            notes=None,  # No notes = manual entry
            source="manual",
        )
        db_session.add(manual_record)
        await db_session.commit()

        # Try to sync
        result = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=test_date,
            mileage=54500,
            source_type="service",
            source_id=1,
        )

        # Should return None (did not update)
        assert result is None

    async def test_sync_different_dates_create_separate_records(
        self, db_session: AsyncSession, test_vehicle
    ):
        """Test that syncs on different dates create separate records."""
        date1 = date(2024, 7, 1)
        date2 = date(2024, 7, 15)

        result1 = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date1,
            mileage=55000,
            source_type="service",
            source_id=1,
        )

        result2 = await sync_odometer_from_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date2,
            mileage=55500,
            source_type="fuel",
            source_id=2,
        )

        assert result1 is not None
        assert result2 is not None
        assert result1.id != result2.id
        assert result1.date == date1
        assert result2.date == date2
