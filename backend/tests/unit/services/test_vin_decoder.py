"""`vin_decoder`: NHTSA's answer completed from the VIN's own structure (#211).

The NHTSA payloads are what vPIC really returns (captured 2026-10-07): a
Renault answers with the manufacturer only, a check-digit error and a
model year read off a position Renault does not use for it; a Volkswagen
answers with a make and a plant, no model.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import vin_decoder

RENAULT_VIN = "VF1RFB00X56123456"
VW_VIN = "WVWZZZAUZLW123456"
US_VIN = "1HGBH41JXMN109186"

RENAULT_NHTSA: dict[str, Any] = {
    "vin": RENAULT_VIN,
    "year": 2005,
    "manufacturer": "RENAULT GROUP",
    "vehicle_type": "PASSENGER CAR",
    "error_code": "1,8",
    "error_text": "1 - Check Digit (9th position) does not calculate properly; 8 - No detailed data available currently",
}
VW_NHTSA: dict[str, Any] = {
    "vin": VW_VIN,
    "year": 2020,
    "make": "VOLKSWAGEN",
    "manufacturer": "VOLKSWAGEN AG",
    "plant_country": "GERMANY",
    "error_code": "8",
}
US_NHTSA: dict[str, Any] = {
    "vin": US_VIN,
    "year": 2021,
    "make": "HONDA",
    "model": "Accord",
    "manufacturer": "HONDA OF AMERICA MFG., INC.",
    "plant_country": "UNITED STATES (USA)",
    "error_code": "0",
}


class TestEnrich:
    def test_renault_gets_its_make_from_the_wmi_and_loses_the_year(self):
        result = vin_decoder.enrich(RENAULT_VIN, RENAULT_NHTSA)
        assert result["make"] == "Renault"
        assert result["manufacturer"] == "RENAULT GROUP"  # NHTSA's own wording is kept
        assert result["year"] is None
        assert result["region"] == "EU"
        assert result["wmi_country"] == "FR"
        assert result["decode_quality"] == "partial"
        assert result["notes"] == [
            vin_decoder.NOTE_YEAR_UNRELIABLE,
            vin_decoder.NOTE_CHECK_DIGIT_NOT_APPLICABLE,
            vin_decoder.NOTE_EU_VIN_NO_MODEL,
        ]
        # Everything NHTSA said is still there.
        assert result["error_code"] == "1,8"
        assert result["vehicle_type"] == "PASSENGER CAR"

    def test_volkswagen_keeps_its_model_year(self):
        result = vin_decoder.enrich(VW_VIN, VW_NHTSA)
        assert result["make"] == "VOLKSWAGEN"
        assert result["year"] == 2020
        assert result["decode_quality"] == "partial"
        assert result["region"] == "EU" and result["wmi_country"] == "DE"
        assert vin_decoder.NOTE_YEAR_UNRELIABLE not in result["notes"]
        assert vin_decoder.NOTE_EU_VIN_NO_MODEL in result["notes"]

    def test_north_american_vin_is_untouched_and_full(self):
        result = vin_decoder.enrich(US_VIN, US_NHTSA)
        assert result["year"] == 2021
        assert result["make"] == "HONDA"
        assert result["decode_quality"] == "full"
        assert result["region"] == "NA" and result["wmi_country"] == "US"
        assert result["notes"] == []

    def test_unknown_maker_outside_north_america(self):
        vin = "ZAZ12345678901234"  # ZA–ZR is Italy; ZAZ names no maker in the table
        result = vin_decoder.enrich(vin, {"vin": vin, "year": 2019})
        assert "make" not in result
        assert result["year"] is None
        assert result["decode_quality"] == "none"
        assert result["wmi_country"] == "IT"
        assert vin_decoder.NOTE_YEAR_UNRELIABLE in result["notes"]
        # An unassigned prefix has no country either.
        assert vin_decoder.enrich("ZZZ12345678901234", {})["wmi_country"] is None

    def test_wmi_only_when_nhtsa_names_nothing(self):
        result = vin_decoder.enrich(RENAULT_VIN, {"vin": RENAULT_VIN})
        assert result["make"] == "Renault"
        assert result["manufacturer"] == "Renault"
        # The make came from the table, so the answer is "partial" (a make,
        # no model); "wmi_only" is reserved for a table hit with no make at all.
        assert result["decode_quality"] == "partial"

    def test_quality_vocabulary(self):
        assert vin_decoder.quality_of({"make": "A", "model": "B"}, None) == "full"
        assert vin_decoder.quality_of({"make": "A"}, None) == "partial"
        assert vin_decoder.quality_of({}, MagicMock()) == "wmi_only"
        assert vin_decoder.quality_of({}, None) == "none"


@pytest.mark.asyncio
class TestDecode:
    async def test_validates_before_asking_nhtsa(self):
        nhtsa = MagicMock()
        nhtsa.decode_vin = AsyncMock()
        with pytest.raises(ValueError):
            await vin_decoder.decode("TOO-SHORT", nhtsa)
        nhtsa.decode_vin.assert_not_awaited()

    async def test_enriches_what_nhtsa_returns(self):
        nhtsa = MagicMock()
        nhtsa.decode_vin = AsyncMock(return_value=dict(RENAULT_NHTSA))
        result = await vin_decoder.decode(RENAULT_VIN.lower(), nhtsa)
        nhtsa.decode_vin.assert_awaited_once_with(RENAULT_VIN)
        assert result["make"] == "Renault"
        assert result["year"] is None

    async def test_transport_errors_propagate_unchanged(self):
        nhtsa = MagicMock()
        nhtsa.decode_vin = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        with pytest.raises(httpx.TimeoutException):
            await vin_decoder.decode(VW_VIN, nhtsa)
