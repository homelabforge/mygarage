"""Two decoders (#219 takeover): which runs first, when AutoRef falls back, what the answer says."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import vin_decoder
from app.services.autoref import (
    NOTE_AUTOREF_BEST_GUESS,
    AutoRefAuthError,
    AutoRefQuotaError,
    AutoRefUnavailableError,
)

EU_VIN = "VF1RFB00X56123456"  # Renault, France
NA_VIN = "1HGCM82633A004352"  # Honda, US

NHTSA_ANSWER: dict[str, Any] = {"vin": EU_VIN, "make": "RENAULT", "manufacturer": "RENAULT S.A."}
AUTOREF_ANSWER: dict[str, Any] = {
    "vin": EU_VIN,
    "year": None,
    "make": "Renault",
    "model": "Clio",
    "trim": "1.0 TCe 90",
    "engine": {"kw": 67, "hp": 90},
    "notes": [NOTE_AUTOREF_BEST_GUESS],
}


def _nhtsa(answer: dict[str, Any] | None = None) -> MagicMock:
    service = MagicMock()
    service.decode_vin = AsyncMock(return_value=dict(answer or NHTSA_ANSWER))
    return service


def _autoref(answer: Any = None, error: Exception | None = None) -> MagicMock:
    service = MagicMock()
    if error is not None:
        service.decode = AsyncMock(side_effect=error)
    else:
        service.decode = AsyncMock(return_value=answer)
    return service


@pytest.mark.unit
class TestPreferredProvider:
    BOTH = ["nhtsa", "autoref"]

    @pytest.mark.parametrize("country", ["FR", "DE", "IT", "GB", "CH", "NO", "IS", "LI"])
    def test_europe_puts_autoref_first(self, country):
        assert vin_decoder.preferred_provider(country, self.BOTH) == "autoref"

    @pytest.mark.parametrize("country", ["US", "CA", "MX", "AU", None])
    def test_elsewhere_puts_nhtsa_first(self, country):
        assert vin_decoder.preferred_provider(country, self.BOTH) == "nhtsa"

    def test_without_autoref_it_is_always_nhtsa(self):
        assert vin_decoder.preferred_provider("FR", ["nhtsa"]) == "nhtsa"

    def test_a_north_american_vin_goes_to_nhtsa_even_in_europe(self):
        # Fable F-5: NHTSA answers those fully and for free.
        assert vin_decoder.preferred_provider("FR", self.BOTH, NA_VIN) == "nhtsa"

    def test_a_european_vin_in_europe_goes_to_autoref(self):
        assert vin_decoder.preferred_provider("FR", self.BOTH, EU_VIN) == "autoref"


@pytest.mark.unit
@pytest.mark.asyncio
class TestDecodeWithAutoRef:
    async def test_autoref_answers(self):
        nhtsa = _nhtsa()
        result = await vin_decoder.decode(
            EU_VIN, nhtsa, provider="autoref", autoref=_autoref(dict(AUTOREF_ANSWER)), fallback=True
        )
        nhtsa.decode_vin.assert_not_awaited()
        assert result["decoded_by"] == "autoref"
        assert result["make_source"] == "autoref"
        assert result["model"] == "Clio"
        assert result["decode_quality"] == "full"
        assert result["region"] == "EU"
        # Codex R1-M3: enrich keeps the provider's notes.
        assert NOTE_AUTOREF_BEST_GUESS in result["notes"]

    async def test_no_match_falls_back_to_nhtsa_with_a_note(self):
        nhtsa = _nhtsa()
        result = await vin_decoder.decode(
            EU_VIN, nhtsa, provider="autoref", autoref=_autoref(None), fallback=True
        )
        nhtsa.decode_vin.assert_awaited_once()
        assert result["decoded_by"] == "nhtsa"
        assert result["make"] == "Renault"
        assert vin_decoder.NOTE_AUTOREF_NO_MATCH in result["notes"]

    @pytest.mark.parametrize(
        "error,note",
        [
            (AutoRefAuthError(403), vin_decoder.NOTE_AUTOREF_KEY_REJECTED),
            (AutoRefQuotaError(), vin_decoder.NOTE_AUTOREF_QUOTA),
            (AutoRefUnavailableError(500), vin_decoder.NOTE_AUTOREF_UNAVAILABLE),
            (AutoRefUnavailableError(timed_out=True), vin_decoder.NOTE_AUTOREF_UNAVAILABLE),
        ],
    )
    async def test_errors_fall_back_to_nhtsa_with_a_note(self, error, note):
        nhtsa = _nhtsa()
        result = await vin_decoder.decode(
            EU_VIN, nhtsa, provider="autoref", autoref=_autoref(error=error), fallback=True
        )
        nhtsa.decode_vin.assert_awaited_once()
        assert result["decoded_by"] == "nhtsa"
        assert note in result["notes"]

    async def test_explicit_autoref_with_no_match_says_so(self):
        # Fable F-10: never a thin enriched answer that would wipe the form.
        nhtsa = _nhtsa()
        with pytest.raises(vin_decoder.AutoRefNoMatchError):
            await vin_decoder.decode(EU_VIN, nhtsa, provider="autoref", autoref=_autoref(None))
        nhtsa.decode_vin.assert_not_awaited()

    async def test_explicit_autoref_errors_stay_visible(self):
        nhtsa = _nhtsa()
        with pytest.raises(AutoRefQuotaError):
            await vin_decoder.decode(
                EU_VIN, nhtsa, provider="autoref", autoref=_autoref(error=AutoRefQuotaError())
            )
        nhtsa.decode_vin.assert_not_awaited()

    async def test_autoref_without_a_service_is_not_configured(self):
        with pytest.raises(vin_decoder.AutoRefNotConfiguredError):
            await vin_decoder.decode(EU_VIN, _nhtsa(), provider="autoref", autoref=None)


@pytest.mark.unit
@pytest.mark.asyncio
class TestDecodeWithNHTSA:
    async def test_nhtsa_make_reads_title_case(self):
        nhtsa = _nhtsa(
            {"vin": NA_VIN, "make": "HONDA", "model": "Accord", "year": 2003, "error_code": "0"}
        )
        result = await vin_decoder.decode(NA_VIN, nhtsa)
        assert result["make"] == "Honda"
        assert result["decoded_by"] == "nhtsa"
        assert result["make_source"] == "nhtsa"

    async def test_an_all_caps_model_reads_title_case(self):
        nhtsa = _nhtsa(
            {"vin": NA_VIN, "make": "MITSUBISHI", "model": "MIRAGE G4", "error_code": "0"}
        )
        result = await vin_decoder.decode(NA_VIN, nhtsa)
        assert (result["make"], result["model"]) == ("Mitsubishi", "Mirage G4")

    async def test_the_make_picks_the_model_spelling(self):
        # Fable fix-wave F-1: a Mini One, not the Mercedes-AMG ONE.
        nhtsa = _nhtsa({"vin": NA_VIN, "make": "MINI", "model": "ONE", "error_code": "0"})
        result = await vin_decoder.decode(NA_VIN, nhtsa)
        assert (result["make"], result["model"]) == ("MINI", "One")

    async def test_nhtsa_never_calls_autoref(self):
        autoref = _autoref(dict(AUTOREF_ANSWER))
        await vin_decoder.decode(EU_VIN, _nhtsa(), provider="nhtsa", autoref=autoref, fallback=True)
        autoref.decode.assert_not_awaited()


@pytest.mark.unit
class TestEnrichNotes:
    def test_provider_notes_come_first_and_are_not_repeated(self):
        info = {
            "vin": EU_VIN,
            "make": "Renault",
            "notes": ["autoref_best_guess", "autoref_best_guess"],
        }
        result = vin_decoder.enrich(EU_VIN, info)
        assert result["notes"][0] == "autoref_best_guess"
        assert result["notes"].count("autoref_best_guess") == 1

    def test_an_answer_without_notes_still_gets_the_vin_notes(self):
        result = vin_decoder.enrich(EU_VIN, {"vin": EU_VIN, "make": "Renault"})
        assert vin_decoder.NOTE_EU_VIN_NO_MODEL in result["notes"]
