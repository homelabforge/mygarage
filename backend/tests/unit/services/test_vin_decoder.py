"""`vin_decoder`: NHTSA's answer completed from the VIN's own structure (#211).

The NHTSA payloads are what vPIC really returns (captured 2026-10-07): a
Renault answers with the manufacturer only, a check-digit error and a
model year read off a position Renault does not use for it; a Volkswagen
answers with a make and a plant, no model.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import vin_decoder

RENAULT_VIN = "VF1RFB00X56123456"
MERCEDES_VIN = "WDDGF8AB7DA123456"
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
        # NHTSA named no make: only the table did, so the answer is wmi_only.
        assert result["decode_quality"] == "wmi_only"
        assert result["make_source"] == "wmi"
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
        assert result["make_source"] == "nhtsa"
        assert result["region"] == "EU" and result["wmi_country"] == "DE"
        assert vin_decoder.NOTE_YEAR_UNRELIABLE not in result["notes"]
        assert vin_decoder.NOTE_EU_VIN_NO_MODEL in result["notes"]

    def test_north_american_vin_is_untouched_and_full(self):
        result = vin_decoder.enrich(US_VIN, US_NHTSA)
        assert result["year"] == 2021
        assert result["make"] == "HONDA"
        assert result["decode_quality"] == "full"
        assert result["make_source"] == "nhtsa"
        assert result["region"] == "NA" and result["wmi_country"] == "US"
        assert result["notes"] == []

    def test_unknown_maker_outside_north_america(self):
        vin = "ZAZ12345678901234"  # ZA–ZR is Italy; ZAZ names no maker in the table
        result = vin_decoder.enrich(vin, {"vin": vin, "year": 2019})
        assert "make" not in result
        assert result["year"] is None
        assert result["decode_quality"] == "none"
        assert result["make_source"] is None
        assert result["wmi_country"] == "IT"
        assert vin_decoder.NOTE_YEAR_UNRELIABLE in result["notes"]
        # An unassigned prefix has no country either.
        assert vin_decoder.enrich("ZZZ12345678901234", {})["wmi_country"] is None

    def test_wmi_only_when_nhtsa_names_nothing(self):
        result = vin_decoder.enrich(RENAULT_VIN, {"vin": RENAULT_VIN})
        assert result["make"] == "Renault"
        assert result["manufacturer"] == "Renault"
        # The quality is NHTSA's own answer, judged before the table fills
        # the make: the table's make never turns "wmi_only" into "partial".
        assert result["decode_quality"] == "wmi_only"
        assert result["make_source"] == "wmi"

    def test_a_clean_nhtsa_decode_keeps_its_year(self):
        # Mercedes is flagged as not using position 10, but vPIC decoded this
        # one cleanly (ErrorCode "0"): its year is NHTSA's answer, not a guess.
        info = {
            "vin": MERCEDES_VIN,
            "year": 2013,
            "make": "MERCEDES-BENZ",
            "model": "ML-Class",
            "error_code": "0",
        }
        result = vin_decoder.enrich(MERCEDES_VIN, info)
        assert result["year"] == 2013
        assert vin_decoder.NOTE_YEAR_UNRELIABLE not in result["notes"]
        assert result["decode_quality"] == "full"
        assert result["make_source"] == "nhtsa"

    def test_an_unclean_decode_still_drops_the_year(self):
        info = {"vin": MERCEDES_VIN, "year": 2013, "make": "MERCEDES-BENZ", "error_code": "8"}
        result = vin_decoder.enrich(MERCEDES_VIN, info)
        assert result["year"] is None
        assert vin_decoder.NOTE_YEAR_UNRELIABLE in result["notes"]

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

    async def test_mercedes_keeps_2013_through_vpic(self):
        """Regression: the real NHTSA client on a mocked vPIC answer."""
        from app.services.nhtsa import NHTSAService

        payload = {
            "Count": 1,
            "Results": [
                {
                    "VIN": MERCEDES_VIN,
                    "ModelYear": "2013",
                    "Make": "MERCEDES-BENZ",
                    "Model": "ML-Class",
                    "Manufacturer": "DAIMLER AG",
                    "PlantCountry": "UNITED STATES (USA)",
                    "VehicleType": "MULTIPURPOSE PASSENGER VEHICLE (MPV)",
                    "ErrorCode": "0",
                    "ErrorText": "0 - VIN decoded clean. Check Digit (9th position) is correct",
                }
            ],
        }
        real_client = httpx.AsyncClient

        def _client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            )
            return real_client(*args, **kwargs)

        with patch("app.services.nhtsa.httpx.AsyncClient", _client):
            result = await vin_decoder.decode(MERCEDES_VIN, NHTSAService())
        assert result["year"] == 2013
        assert result["make"] == "MERCEDES-BENZ"
        assert result["decode_quality"] == "full"
        assert result["make_source"] == "nhtsa"

    async def test_transport_errors_propagate_unchanged(self):
        nhtsa = MagicMock()
        nhtsa.decode_vin = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        with pytest.raises(httpx.TimeoutException):
            await vin_decoder.decode(VW_VIN, nhtsa)
