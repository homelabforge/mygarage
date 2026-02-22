"""Unit tests for telemetry value validation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.telemetry_validator import (
    PARAM_CLASS_RANGES,
    RATE_CHECK_MAX_AGE_SECONDS,
    RATE_OF_CHANGE_LIMITS,
    TelemetryValidator,
)


def _mock_param(param_class: str | None = None):
    """Create a mock LiveLinkParameter with the given class."""
    param = MagicMock()
    param.param_class = param_class
    return param


def _mock_latest(value: float, timestamp: datetime):
    """Create a mock VehicleTelemetryLatest row."""
    latest = MagicMock()
    latest.value = value
    latest.timestamp = timestamp
    return latest


class TestValidateRange:
    """Test range validation per parameter class."""

    @pytest.fixture
    def validator(self):
        db = AsyncMock()
        return TelemetryValidator(db)

    @pytest.mark.parametrize(
        "param_class, value",
        [
            ("temperature", 25.0),
            ("temperature", -50.0),  # lower bound
            ("temperature", 250.0),  # upper bound
            ("speed", 0.0),
            ("speed", 120.5),
            ("speed", 350.0),
            ("frequency", 750.0),
            ("frequency", 0.0),
            ("frequency", 15000.0),
            ("percentage", 0.0),
            ("percentage", 50.0),
            ("percentage", 100.0),
            ("voltage", 12.6),
            ("voltage", 0.0),
            ("voltage", 500.0),
            ("pressure", 101.3),
            ("pressure", 0.0),
            ("pressure", 10000.0),
            ("distance", 50000.0),
            ("distance", 0.0),
            ("distance", 2000000.0),
            ("battery", 12.6),
            ("power_factor", 45.0),
        ],
    )
    def test_valid_values_pass(self, validator, param_class, value):
        """Values within class range should pass."""
        is_valid, reason = validator.validate_range(param_class, value)
        assert is_valid is True
        assert reason is None

    @pytest.mark.parametrize(
        "param_class, value",
        [
            ("temperature", -51.0),
            ("temperature", 251.0),
            ("speed", -1.0),
            ("speed", 351.0),
            ("frequency", -1.0),
            ("frequency", 15001.0),
            ("percentage", -0.1),
            ("percentage", 100.1),
            ("voltage", -1.0),
            ("voltage", 501.0),
            ("pressure", -1.0),
            ("pressure", 10001.0),
            ("distance", -1.0),
            ("distance", 2000001.0),
            ("battery", -1.0),
            ("power_factor", 101.0),
        ],
    )
    def test_invalid_values_rejected(self, validator, param_class, value):
        """Values outside class range should be rejected."""
        is_valid, reason = validator.validate_range(param_class, value)
        assert is_valid is False
        assert reason is not None
        assert param_class in reason

    def test_unknown_class_passes(self, validator):
        """Unknown parameter class should bypass validation."""
        is_valid, reason = validator.validate_range("custom_sensor", 99999.0)
        assert is_valid is True
        assert reason is None

    def test_none_class_passes(self, validator):
        """None parameter class should bypass validation."""
        is_valid, reason = validator.validate_range(None, -99999.0)
        assert is_valid is True
        assert reason is None

    def test_garbage_speed_rejected(self, validator):
        """Garbage value like 999 km/h from partial ECU wake should be rejected."""
        is_valid, _ = validator.validate_range("speed", 999.0)
        assert is_valid is False

    def test_garbage_rpm_rejected(self, validator):
        """Garbage RPM like 65535 (0xFFFF) from partial ECU wake should be rejected."""
        is_valid, _ = validator.validate_range("frequency", 65535.0)
        assert is_valid is False


class TestValidateRateOfChange:
    """Test rate-of-change validation."""

    @pytest.fixture
    def validator(self):
        db = AsyncMock()
        return TelemetryValidator(db)

    @pytest.mark.asyncio
    async def test_normal_rate_passes(self, validator):
        """Normal rate of change should pass."""
        # Previous value: 60 km/h 2 seconds ago
        prev_time = datetime.now(UTC) - timedelta(seconds=2)
        latest = _mock_latest(60.0, prev_time)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = latest
        validator.db.execute = AsyncMock(return_value=mock_result)

        # New value: 70 km/h — delta 10 in 2s = 5/s, limit is 15/s
        is_valid, reason = await validator.validate_rate_of_change(
            "VIN123",
            "0D-VehicleSpeed",
            "speed",
            70.0,
        )
        assert is_valid is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_excessive_rate_rejected(self, validator):
        """Excessive rate of change should be rejected."""
        # Previous value: 60 km/h 1 second ago
        prev_time = datetime.now(UTC) - timedelta(seconds=1)
        latest = _mock_latest(60.0, prev_time)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = latest
        validator.db.execute = AsyncMock(return_value=mock_result)

        # New value: 200 km/h — delta 140 in 1s = 140/s, limit is 15/s
        is_valid, reason = await validator.validate_rate_of_change(
            "VIN123",
            "0D-VehicleSpeed",
            "speed",
            200.0,
        )
        assert is_valid is False
        assert reason is not None
        assert "rate of change" in reason

    @pytest.mark.asyncio
    async def test_stale_previous_value_skips_check(self, validator):
        """Previous value older than RATE_CHECK_MAX_AGE_SECONDS should skip check."""
        # Previous value: way beyond the max age
        prev_time = datetime.now(UTC) - timedelta(seconds=RATE_CHECK_MAX_AGE_SECONDS + 10)
        latest = _mock_latest(60.0, prev_time)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = latest
        validator.db.execute = AsyncMock(return_value=mock_result)

        # Even a huge jump should pass when previous is stale
        is_valid, _ = await validator.validate_rate_of_change(
            "VIN123",
            "0D-VehicleSpeed",
            "speed",
            350.0,
        )
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_no_previous_value_passes(self, validator):
        """No previous value in DB should pass (first reading)."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        validator.db.execute = AsyncMock(return_value=mock_result)

        is_valid, _ = await validator.validate_rate_of_change(
            "VIN123",
            "0C-EngineRPM",
            "frequency",
            5000.0,
        )
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_unknown_class_skips_rate_check(self, validator):
        """Unknown parameter class should skip rate-of-change check."""
        is_valid, _ = await validator.validate_rate_of_change(
            "VIN123",
            "CUSTOM_SENSOR",
            "custom_sensor",
            99999.0,
        )
        assert is_valid is True
        validator.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_class_skips_rate_check(self, validator):
        """None parameter class should skip rate-of-change check."""
        is_valid, _ = await validator.validate_rate_of_change(
            "VIN123",
            "UNKNOWN_PID",
            None,
            99999.0,
        )
        assert is_valid is True
        validator.db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_temperature_rate_limit(self, validator):
        """Temperature rate limit should catch rapid spikes."""
        # Previous: 80°C 1 second ago
        prev_time = datetime.now(UTC) - timedelta(seconds=1)
        latest = _mock_latest(80.0, prev_time)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = latest
        validator.db.execute = AsyncMock(return_value=mock_result)

        # New: 200°C — delta 120 in 1s = 120/s, limit is 5/s
        is_valid, _ = await validator.validate_rate_of_change(
            "VIN123",
            "05-EngineCoolantTemp",
            "temperature",
            200.0,
        )
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_naive_timestamp_handled(self, validator):
        """Naive (no tzinfo) timestamps in DB should be handled gracefully."""
        # Simulate a naive datetime (no timezone) from the DB
        prev_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
        latest = _mock_latest(60.0, prev_time)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = latest
        validator.db.execute = AsyncMock(return_value=mock_result)

        # Normal change — should pass without crashing
        is_valid, _ = await validator.validate_rate_of_change(
            "VIN123",
            "0D-VehicleSpeed",
            "speed",
            65.0,
        )
        assert is_valid is True


class TestValidateBatch:
    """Test batch validation of telemetry values."""

    @pytest.fixture
    def validator(self):
        db = AsyncMock()
        return TelemetryValidator(db)

    @pytest.mark.asyncio
    async def test_all_valid_values(self, validator):
        """All valid values should pass through."""
        params = {
            "0D-VehicleSpeed": _mock_param("speed"),
            "0C-EngineRPM": _mock_param("frequency"),
        }
        data = {"0D-VehicleSpeed": 65, "0C-EngineRPM": 2150}

        # No previous values in DB
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        validator.db.execute = AsyncMock(return_value=mock_result)

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert len(valid) == 2
        assert len(rejected) == 0
        assert valid["0D-VehicleSpeed"] == 65
        assert valid["0C-EngineRPM"] == 2150

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid(self, validator):
        """Mix of valid and invalid values should separate correctly."""
        params = {
            "0D-VehicleSpeed": _mock_param("speed"),
            "0C-EngineRPM": _mock_param("frequency"),
            "05-EngineCoolantTemp": _mock_param("temperature"),
        }
        data = {
            "0D-VehicleSpeed": 65,  # Valid
            "0C-EngineRPM": 65535,  # Invalid (0xFFFF garbage)
            "05-EngineCoolantTemp": 90,  # Valid
        }

        # No previous values
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        validator.db.execute = AsyncMock(return_value=mock_result)

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert len(valid) == 2
        assert len(rejected) == 1
        assert "0D-VehicleSpeed" in valid
        assert "05-EngineCoolantTemp" in valid
        assert rejected[0]["param_key"] == "0C-EngineRPM"

    @pytest.mark.asyncio
    async def test_none_values_pass_through(self, validator):
        """None values should pass through without validation."""
        params = {"0D-VehicleSpeed": _mock_param("speed")}
        data = {"0D-VehicleSpeed": None}

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert valid == {"0D-VehicleSpeed": None}
        assert len(rejected) == 0

    @pytest.mark.asyncio
    async def test_string_values_pass_through(self, validator):
        """String values (like DTCs) should pass through without validation."""
        params = {
            "DIAGNOSTIC_TROUBLE_CODES": _mock_param(None),
            "0C-EngineRPM": _mock_param("frequency"),
        }
        data = {
            "DIAGNOSTIC_TROUBLE_CODES": "P0300,P0420",
            "0C-EngineRPM": 750,
        }

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        validator.db.execute = AsyncMock(return_value=mock_result)

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert valid["DIAGNOSTIC_TROUBLE_CODES"] == "P0300,P0420"
        assert valid["0C-EngineRPM"] == 750
        assert len(rejected) == 0

    @pytest.mark.asyncio
    async def test_unknown_class_bypasses_validation(self, validator):
        """Parameters with unknown class should bypass all validation."""
        params = {"CUSTOM_SENSOR": _mock_param("custom_class")}
        data = {"CUSTOM_SENSOR": 99999}

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert valid["CUSTOM_SENSOR"] == 99999
        assert len(rejected) == 0

    @pytest.mark.asyncio
    async def test_no_param_in_cache_bypasses(self, validator):
        """Parameters not found in cache should bypass validation."""
        params = {}  # Empty cache
        data = {"MYSTERY_PID": 42}

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert valid["MYSTERY_PID"] == 42
        assert len(rejected) == 0

    @pytest.mark.asyncio
    async def test_empty_batch(self, validator):
        """Empty batch should return empty results."""
        valid, rejected = await validator.validate_batch("VIN123", {}, {})
        assert valid == {}
        assert rejected == []

    @pytest.mark.asyncio
    async def test_all_values_rejected(self, validator):
        """All garbage values should be rejected."""
        params = {
            "0D-VehicleSpeed": _mock_param("speed"),
            "0C-EngineRPM": _mock_param("frequency"),
        }
        data = {
            "0D-VehicleSpeed": 999,  # Above 350 max
            "0C-EngineRPM": 65535,  # Above 15000 max
        }

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        validator.db.execute = AsyncMock(return_value=mock_result)

        valid, rejected = await validator.validate_batch("VIN123", data, params)
        assert len(valid) == 0
        assert len(rejected) == 2


class TestRangeCompleteness:
    """Verify all documented classes have ranges and rate limits."""

    def test_all_range_classes_have_rate_limits(self):
        """Every class with a range should have a rate limit (except distance)."""
        for cls in PARAM_CLASS_RANGES:
            if cls == "distance":
                continue  # Distance doesn't have rate-of-change limits
            assert cls in RATE_OF_CHANGE_LIMITS, f"Class '{cls}' has range but no rate limit"

    def test_all_rate_classes_have_ranges(self):
        """Every class with a rate limit should have a range."""
        for cls in RATE_OF_CHANGE_LIMITS:
            assert cls in PARAM_CLASS_RANGES, f"Class '{cls}' has rate limit but no range"
