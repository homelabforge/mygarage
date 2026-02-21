"""
Unit tests for DEF sync utility.

Tests auto-syncing of DEF observation records from fuel records.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.utils.def_sync import delete_def_for_fuel_record, sync_def_from_fuel_record


@pytest_asyncio.fixture
async def clean_def_records(db_session: AsyncSession, test_vehicle):
    """Clean up DEF records for test vehicle before each test."""
    await db_session.execute(delete(DEFRecord).where(DEFRecord.vin == test_vehicle["vin"]))
    await db_session.commit()
    yield
    await db_session.execute(delete(DEFRecord).where(DEFRecord.vin == test_vehicle["vin"]))
    await db_session.commit()


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFSync:
    """Test DEF sync utility functions."""

    async def test_sync_creates_new_record(
        self, db_session: AsyncSession, test_vehicle, clean_def_records
    ):
        """Test that sync creates a new DEF record with correct entry_type."""
        result = await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 6, 15),
            mileage=50000,
            fill_level=Decimal("0.75"),
            fuel_record_id=999,
        )

        assert result is not None
        assert result.vin == test_vehicle["vin"]
        assert result.date == date(2024, 6, 15)
        assert result.mileage == 50000
        assert result.fill_level == Decimal("0.75")
        assert result.entry_type == "auto_fuel_sync"
        assert result.origin_fuel_record_id == 999

    async def test_sync_updates_existing_record(
        self, db_session: AsyncSession, test_vehicle, clean_def_records
    ):
        """Test that sync updates an existing auto-synced record by origin_fuel_record_id."""
        # Create initial
        initial = await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 6, 15),
            mileage=50000,
            fill_level=Decimal("0.75"),
            fuel_record_id=999,
        )
        assert initial is not None
        initial_id = initial.id

        # Update with new values
        updated = await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 6, 20),
            mileage=50500,
            fill_level=Decimal("0.50"),
            fuel_record_id=999,
        )

        assert updated is not None
        assert updated.id == initial_id  # Same record updated
        assert updated.fill_level == Decimal("0.50")
        assert updated.date == date(2024, 6, 20)
        assert updated.mileage == 50500

    async def test_sync_with_none_mileage(
        self, db_session: AsyncSession, test_vehicle, clean_def_records
    ):
        """Test that sync works when mileage is None."""
        result = await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 7, 1),
            mileage=None,
            fill_level=Decimal("0.50"),
            fuel_record_id=1000,
        )

        assert result is not None
        assert result.mileage is None
        assert result.fill_level == Decimal("0.50")

    async def test_sync_different_fuel_records_create_separate(
        self, db_session: AsyncSession, test_vehicle, clean_def_records
    ):
        """Test that syncs for different fuel records create separate DEF records."""
        result1 = await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 6, 1),
            mileage=49000,
            fill_level=Decimal("0.90"),
            fuel_record_id=100,
        )

        result2 = await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 7, 1),
            mileage=51000,
            fill_level=Decimal("0.60"),
            fuel_record_id=101,
        )

        assert result1 is not None
        assert result2 is not None
        assert result1.id != result2.id
        assert result1.origin_fuel_record_id == 100
        assert result2.origin_fuel_record_id == 101


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDeleteDEFForFuelRecord:
    """Test deleting DEF records linked to a fuel record."""

    async def test_delete_returns_count(
        self, db_session: AsyncSession, test_vehicle, clean_def_records
    ):
        """Test that delete returns the number of records deleted."""
        # Create a linked DEF record
        await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 8, 1),
            mileage=55000,
            fill_level=Decimal("0.80"),
            fuel_record_id=200,
        )

        count = await delete_def_for_fuel_record(db=db_session, fuel_record_id=200)
        await db_session.commit()  # Caller must commit

        assert count == 1

        # Verify record is gone
        result = await db_session.execute(
            select(DEFRecord).where(DEFRecord.origin_fuel_record_id == 200)
        )
        assert result.scalar_one_or_none() is None

    async def test_delete_returns_zero_when_no_linked(self, db_session: AsyncSession):
        """Test that delete returns 0 when no linked records exist."""
        count = await delete_def_for_fuel_record(db=db_session, fuel_record_id=99999)
        await db_session.commit()

        assert count == 0

    async def test_delete_does_not_commit(
        self, db_session: AsyncSession, test_vehicle, clean_def_records
    ):
        """Test that delete does NOT commit — caller manages transaction."""
        # Create a linked DEF record
        await sync_def_from_fuel_record(
            db=db_session,
            vin=test_vehicle["vin"],
            date=date(2024, 9, 1),
            mileage=56000,
            fill_level=Decimal("0.65"),
            fuel_record_id=300,
        )

        count = await delete_def_for_fuel_record(db=db_session, fuel_record_id=300)
        assert count == 1

        # Rollback instead of commit — record should still exist
        await db_session.rollback()

        result = await db_session.execute(
            select(DEFRecord).where(DEFRecord.origin_fuel_record_id == 300)
        )
        record = result.scalar_one_or_none()
        assert record is not None, "Record should still exist after rollback"
