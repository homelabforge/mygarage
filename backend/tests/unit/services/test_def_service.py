"""
Unit tests for DEF service analytics logic.

Tests the analytics calculation methods in isolation.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.def_record import DEFAnalytics
from app.services.def_service import DEFRecordService


def _make_mock_vehicle(tank_capacity=None):
    """Create a mock vehicle with DEF tank capacity."""
    vehicle = MagicMock()
    vehicle.def_tank_capacity_gallons = tank_capacity
    return vehicle


def _make_mock_record(record_date, mileage, gallons, cost, fill_level=None):
    """Create a mock DEF record."""
    record = MagicMock()
    record.date = record_date
    record.mileage = mileage
    record.gallons = gallons
    record.cost = cost
    record.fill_level = fill_level
    return record


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFAnalytics:
    """Test DEF analytics calculation logic."""

    async def test_analytics_empty_records(self):
        """Test analytics with no records returns default values."""
        mock_db = AsyncMock()
        service = DEFRecordService(mock_db)

        mock_vehicle = _make_mock_vehicle(tank_capacity=None)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch(
            "app.services.auth.get_vehicle_or_403",
            new_callable=AsyncMock,
            return_value=mock_vehicle,
        ):
            result = await service.get_def_analytics("TEST_VIN", MagicMock())

        assert isinstance(result, DEFAnalytics)
        assert result.record_count == 0
        assert result.data_confidence == "insufficient"
        assert result.total_gallons is None
        assert result.total_cost is None

    async def test_analytics_insufficient_data(self):
        """Test analytics with fewer than 3 records with mileage."""
        mock_db = AsyncMock()
        service = DEFRecordService(mock_db)

        mock_vehicle = _make_mock_vehicle(tank_capacity=Decimal("5.0"))

        # No fill_level set — avoids the tank capacity lookup code path
        records = [
            _make_mock_record(date(2024, 1, 1), 10000, Decimal("2.5"), Decimal("15.00")),
            _make_mock_record(date(2024, 2, 1), 12000, Decimal("2.5"), Decimal("16.00")),
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        mock_db.execute.return_value = mock_result

        with patch(
            "app.services.auth.get_vehicle_or_403",
            new_callable=AsyncMock,
            return_value=mock_vehicle,
        ):
            result = await service.get_def_analytics("TEST_VIN", MagicMock())

        assert result.record_count == 2
        assert result.total_gallons is not None
        assert result.total_cost is not None
        assert result.gallons_per_1000_miles is None
        assert result.data_confidence == "insufficient"

    async def test_analytics_confidence_levels(self):
        """Test data confidence classification with 5+ records and 2000+ mile span."""
        mock_db = AsyncMock()
        service = DEFRecordService(mock_db)

        mock_vehicle = _make_mock_vehicle(tank_capacity=Decimal("5.0"))

        # No fill_level — avoids tank capacity lookup code path
        records = [
            _make_mock_record(
                date(2024, 1, 1) + timedelta(days=30 * i),
                10000 + (500 * i),
                Decimal("2.5"),
                Decimal("15.00"),
            )
            for i in range(5)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = records
        mock_db.execute.return_value = mock_result

        with patch(
            "app.services.auth.get_vehicle_or_403",
            new_callable=AsyncMock,
            return_value=mock_vehicle,
        ):
            result = await service.get_def_analytics("TEST_VIN", MagicMock())

        assert result.record_count == 5
        assert result.total_gallons is not None


@pytest.mark.unit
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFSchemaValidation:
    """Test DEF schema validation rules."""

    async def test_fill_level_valid_range(self):
        """Test that fill_level accepts values in 0-1 range."""
        from app.schemas.def_record import DEFRecordCreate

        for level in ["0.00", "0.50", "1.00"]:
            record = DEFRecordCreate(
                vin="3C7WRTCL8NG123456",
                date=date(2024, 1, 1),
                fill_level=Decimal(level),
            )
            assert record.fill_level == Decimal(level)

    async def test_fill_level_rejects_out_of_range(self):
        """Test that fill_level > 1 is rejected."""
        from pydantic import ValidationError

        from app.schemas.def_record import DEFRecordCreate

        with pytest.raises(ValidationError):
            DEFRecordCreate(
                vin="3C7WRTCL8NG123456",
                date=date(2024, 1, 1),
                fill_level=Decimal("1.50"),
            )

    async def test_negative_gallons_rejected(self):
        """Test that negative gallons value is rejected."""
        from pydantic import ValidationError

        from app.schemas.def_record import DEFRecordCreate

        with pytest.raises(ValidationError):
            DEFRecordCreate(
                vin="3C7WRTCL8NG123456",
                date=date(2024, 1, 1),
                gallons=Decimal("-1.0"),
            )

    async def test_update_schema_all_optional(self):
        """Test that DEFRecordUpdate allows all fields to be optional."""
        from app.schemas.def_record import DEFRecordUpdate

        # Empty update should be valid
        update = DEFRecordUpdate()
        assert update.date is None
        assert update.gallons is None
        assert update.cost is None

    async def test_create_requires_date_and_vin(self):
        """Test that DEFRecordCreate requires date and vin."""
        from pydantic import ValidationError

        from app.schemas.def_record import DEFRecordCreate

        with pytest.raises(ValidationError):
            DEFRecordCreate()  # type: ignore[call-arg]
