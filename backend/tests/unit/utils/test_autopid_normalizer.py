"""Unit tests for autopid_data normalizer."""

from app.utils.autopid_normalizer import normalize_autopid_data


class TestFlatFormat:
    """Test flat format passthrough."""

    def test_flat_numeric_passes_through(self):
        """Flat numeric dict should pass through unchanged."""
        data = {"0C-EngineRPM": 2150, "0D-VehicleSpeed": 65}
        result = normalize_autopid_data(data)
        assert result == {"0C-EngineRPM": 2150, "0D-VehicleSpeed": 65}

    def test_flat_none_preserved(self):
        """None values in flat format should be preserved."""
        data = {"0C-EngineRPM": None}
        result = normalize_autopid_data(data)
        assert result == {"0C-EngineRPM": None}

    def test_flat_filters_non_numeric(self):
        """Non-numeric, non-allowlisted values should be dropped."""
        data = {"RPM": 2150, "STATUS": "ok", "LABEL": "test"}
        result = normalize_autopid_data(data)
        assert result == {"RPM": 2150}

    def test_flat_preserves_dtc_string(self):
        """DIAGNOSTIC_TROUBLE_CODES string should be preserved."""
        data = {"RPM": 750, "DIAGNOSTIC_TROUBLE_CODES": "P0300,P0420"}
        result = normalize_autopid_data(data)
        assert result["DIAGNOSTIC_TROUBLE_CODES"] == "P0300,P0420"
        assert result["RPM"] == 750

    def test_empty_dict(self):
        """Empty dict should return empty dict."""
        assert normalize_autopid_data({}) == {}


class TestGroupedFormat:
    """Test grouped format flattening."""

    def test_grouped_format_flattens(self):
        """Grouped dict should be flattened to key-value pairs."""
        data = {
            "Engine": {"0C-EngineRPM": 2150, "05-EngineCoolantTemp": 85},
            "Transmission": {"0D-VehicleSpeed": 65},
        }
        result = normalize_autopid_data(data)
        assert result == {
            "0C-EngineRPM": 2150,
            "05-EngineCoolantTemp": 85,
            "0D-VehicleSpeed": 65,
        }

    def test_grouped_multiple_pids_per_group(self):
        """Each group can have multiple PIDs."""
        data = {"Engine": {"RPM": 2150, "COOLANT": 85, "LOAD": 45}}
        result = normalize_autopid_data(data)
        assert len(result) == 3

    def test_grouped_filters_non_numeric_in_groups(self):
        """Non-numeric values within groups should be filtered."""
        data = {"Engine": {"RPM": 2150, "STATUS": "running"}}
        result = normalize_autopid_data(data)
        assert result == {"RPM": 2150}

    def test_grouped_preserves_none_in_groups(self):
        """None values within groups should be preserved."""
        data = {"Engine": {"RPM": None}}
        result = normalize_autopid_data(data)
        assert result == {"RPM": None}

    def test_mixed_grouped_and_flat(self):
        """Mix of grouped and flat values should work."""
        data = {
            "Engine": {"RPM": 2150},
            "BATTERY_VOLTAGE": 12.6,
        }
        result = normalize_autopid_data(data)
        assert result == {"RPM": 2150, "BATTERY_VOLTAGE": 12.6}


class TestArrayFormat:
    """Test array-grouped format flattening."""

    def test_array_format_flattens(self):
        """Array-grouped format should be flattened."""
        data = [
            {"group": "Engine", "pids": {"0C-EngineRPM": 2150}},
            {"group": "Trans", "pids": {"0D-VehicleSpeed": 65}},
        ]
        result = normalize_autopid_data(data)
        assert result == {"0C-EngineRPM": 2150, "0D-VehicleSpeed": 65}

    def test_array_format_multiple_pids(self):
        """Array group with multiple PIDs should flatten all."""
        data = [{"group": "Engine", "pids": {"RPM": 2150, "COOLANT": 85}}]
        result = normalize_autopid_data(data)
        assert result == {"RPM": 2150, "COOLANT": 85}

    def test_empty_list(self):
        """Empty list should return empty dict."""
        assert normalize_autopid_data([]) == {}

    def test_array_skips_non_dict_items(self):
        """Non-dict items in array should be skipped."""
        data = [{"group": "Engine", "pids": {"RPM": 2150}}, "garbage", 42]
        result = normalize_autopid_data(data)
        assert result == {"RPM": 2150}

    def test_array_missing_pids_key(self):
        """Array items without 'pids' key should be skipped."""
        data = [{"group": "Engine", "data": {"RPM": 2150}}]
        result = normalize_autopid_data(data)
        assert result == {}
