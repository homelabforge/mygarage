"""Unit tests for WiCAN payload schema validation."""

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
