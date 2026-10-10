"""Unit tests for WiCAN payload schema validation."""

from datetime import datetime

import pytest

from app.schemas.livelink_ingest import WiCANPayload


class TestAutopidDataValidation:
    """Test autopid_data field validation and normalization."""

    def test_numeric_values_pass_through(self):
        """Numeric values should be preserved as float."""
        payload = WiCANPayload(autopid_data={"0C-EngineRPM": 2150, "0D-VehicleSpeed": 65})
        assert payload.autopid_data["0C-EngineRPM"] == 2150.0
        assert payload.autopid_data["0D-VehicleSpeed"] == 65.0

    def test_none_values_preserved(self):
        """None values should be preserved."""
        payload = WiCANPayload(autopid_data={"0C-EngineRPM": None})
        assert payload.autopid_data["0C-EngineRPM"] is None

    def test_dtc_string_value_preserved(self):
        """DIAGNOSTIC_TROUBLE_CODES string value should be preserved."""
        payload = WiCANPayload(
            autopid_data={
                "0C-EngineRPM": 750,
                "DIAGNOSTIC_TROUBLE_CODES": "P0300,P0420",
            }
        )
        assert payload.autopid_data["DIAGNOSTIC_TROUBLE_CODES"] == "P0300,P0420"
        assert payload.autopid_data["0C-EngineRPM"] == 750.0

    def test_random_string_values_dropped(self):
        """Non-allowlisted string values should be silently dropped."""
        payload = WiCANPayload(
            autopid_data={
                "0C-EngineRPM": 750,
                "STATUS": "running",
                "LABEL": "test",
            }
        )
        assert "STATUS" not in payload.autopid_data
        assert "LABEL" not in payload.autopid_data
        assert payload.autopid_data["0C-EngineRPM"] == 750.0

    def test_integer_values_preserved(self):
        """Integer values should be preserved as-is."""
        payload = WiCANPayload(autopid_data={"0D-VehicleSpeed": 65})
        assert payload.autopid_data["0D-VehicleSpeed"] == 65
        assert isinstance(payload.autopid_data["0D-VehicleSpeed"], int)

    def test_empty_autopid_data(self):
        """Empty autopid_data should be accepted."""
        payload = WiCANPayload(autopid_data={})
        assert payload.autopid_data == {}

    def test_mixed_valid_and_invalid(self):
        """Mixed valid and invalid values should keep only valid ones."""
        payload = WiCANPayload(
            autopid_data={
                "RPM": 750,
                "SPEED": 0,
                "BAD_STRING": "not_allowed",
                "DIAGNOSTIC_TROUBLE_CODES": "P0171",
                "NONE_VAL": None,
            }
        )
        assert len(payload.autopid_data) == 4  # RPM, SPEED, DTC, NONE_VAL
        assert payload.autopid_data["RPM"] == 750.0
        assert payload.autopid_data["DIAGNOSTIC_TROUBLE_CODES"] == "P0171"
        assert payload.autopid_data["NONE_VAL"] is None


class TestTimestampNormalization:
    """The device timestamp lands as naive UTC, whatever offset it carries."""

    @staticmethod
    def _timestamp(sent: str | None) -> datetime | None:
        return WiCANPayload.model_validate(
            {"autopid_data": {"ENGINE_RPM": 800}, "timestamp": sent}
        ).timestamp

    def test_an_offset_is_converted_to_utc(self) -> None:
        """12:00+02:00 is 10:00 UTC. Kept aware, SQLite dropped the offset and
        stored 12:00, and asyncpg refused it and rolled the batch back."""
        stamp = self._timestamp("2026-10-10T12:00:00+02:00")

        assert stamp == datetime(2026, 10, 10, 10, 0)
        assert stamp is not None and stamp.tzinfo is None

    @pytest.mark.usefixtures("local_clock_off_utc")
    def test_a_naive_timestamp_is_read_as_utc(self) -> None:
        """What most WiCANs send: no offset means UTC, not server local time."""
        stamp = self._timestamp("2026-10-10T10:00:00")

        assert stamp == datetime(2026, 10, 10, 10)
        assert stamp is not None and stamp.tzinfo is None

    def test_z_keeps_the_wall_clock(self) -> None:
        stamp = self._timestamp("2026-10-10T10:00:00Z")

        assert stamp == datetime(2026, 10, 10, 10)
        assert stamp is not None and stamp.tzinfo is None

    def test_an_explicit_null_stays_none(self) -> None:
        """Null means "use server time"; it must not reach the converter."""
        assert self._timestamp(None) is None
