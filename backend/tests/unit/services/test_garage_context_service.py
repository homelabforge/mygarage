"""Unit tests for Ask My Garage DTC code extraction."""

from app.services.garage_context_service import extract_dtc_codes


def test_extract_dtc_codes_normalizes_and_dedupes():
    assert extract_dtc_codes("What does p0420 and B0001 mean?") == ["P0420", "B0001"]
    assert extract_dtc_codes("P0420 then p0420 again") == ["P0420"]


def test_extract_dtc_codes_ignores_non_codes():
    assert extract_dtc_codes("no codes here") == []
    assert extract_dtc_codes("") == []
    assert extract_dtc_codes("P42 is too short") == []
