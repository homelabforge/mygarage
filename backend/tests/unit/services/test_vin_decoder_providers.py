"""Two decoders (#219 takeover): which runs first, when AutoRef falls back, what the answer says."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.vin import AutoRefVersionRequest, VINDecodeResponse
from app.services import vin_decoder
from app.services.autoref import (
    NOTE_AUTOREF_BEST_GUESS,
    NOTE_AUTOREF_PICK_VERSION,
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
    BOTH: list[vin_decoder.Provider] = ["nhtsa", "autoref"]

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


YARIS_VIN = "VNKKH963X0A127993"  # Toyota by its WMI; AutoRef also matched a Daihatsu
GOLF_VIN = "WVWZZZAUZFW806653"


def _candidate(record_id: str, label: str, kw: int) -> dict[str, Any]:
    return {
        "record_type": "TG",
        "id": record_id,
        "label": label,
        "model_full": label,
        "fuel_type": "gasoline",
        "kw": kw,
        "transmission": "Manual",
        "gearbox_code": "M",
        "grouped": False,
    }


CANDIDATES = [_candidate("311017", "Golf VII GTE", 110), _candidate("310899", "Golf VII R 5T", 221)]
AGREEMENT: dict[str, Any] = {
    "vin": YARIS_VIN,
    "year": None,
    "make": None,
    "model": None,
    "trim": None,
    "engine": {"kw": None, "hp": None},
    "transmission": {"type": "Manual", "speeds": None},
    "notes": [NOTE_AUTOREF_PICK_VERSION],
    "candidates": CANDIDATES,
}
PICKED: dict[str, Any] = {
    "vin": GOLF_VIN,
    "year": None,
    "make": "Volkswagen",
    "model": "Golf",
    "trim": "VII GTE",
    "engine": {"kw": 110, "hp": 148, "fuel_type_normalized": "hybrid"},
    "notes": [],
}


def _pick(**overrides: Any) -> AutoRefVersionRequest:
    fields: dict[str, Any] = {
        "vin": GOLF_VIN,
        "record_type": "TG",
        "id": "311017",
        "gearbox_code": "M",
        "expect_model": "Golf VII GTE",
        "expect_kw": 110,
        "grouped": False,
    }
    return AutoRefVersionRequest(**{**fields, **overrides})


def _version_service(answer: Any = None, error: Exception | None = None) -> MagicMock:
    service = MagicMock()
    if error is not None:
        service.decode_version = AsyncMock(side_effect=error)
    else:
        service.decode_version = AsyncMock(return_value=answer)
    return service


@pytest.mark.unit
@pytest.mark.asyncio
class TestSeveralVersions:
    async def test_decode_passes_candidates_through_enrich(self):
        result = await vin_decoder.decode(
            YARIS_VIN, _nhtsa(), provider="autoref", autoref=_autoref(dict(AGREEMENT))
        )
        assert result["candidates"] == CANDIDATES
        assert result["make"] == "Toyota"
        assert result["make_source"] == "wmi"
        assert NOTE_AUTOREF_PICK_VERSION in result["notes"]

    async def test_the_response_keeps_candidates(self):
        result = await vin_decoder.decode(
            YARIS_VIN, _nhtsa(), provider="autoref", autoref=_autoref(dict(AGREEMENT))
        )
        response = VINDecodeResponse(**result)
        assert response.candidates is not None
        assert response.candidates[0].id == "311017"
        assert response.candidates[0].gearbox_code == "M"

    async def test_decode_version_enriches(self):
        service = _version_service(dict(PICKED))
        result = await vin_decoder.decode_version(GOLF_VIN, service, _pick())
        service.decode_version.assert_awaited_once_with(
            GOLF_VIN,
            "TG",
            "311017",
            gearbox_code="M",
            expect_model="Golf VII GTE",
            expect_kw=110,
            grouped=False,
        )
        assert result["decoded_by"] == "autoref"
        assert result["make_source"] == "autoref"
        assert result["region"] == "EU"
        assert vin_decoder.NOTE_CHECK_DIGIT_NOT_APPLICABLE in result["notes"]
        assert vin_decoder.NOTE_EU_VIN_NO_MODEL not in result["notes"]

    async def test_decode_version_none_is_no_match(self):
        with pytest.raises(vin_decoder.AutoRefNoMatchError):
            await vin_decoder.decode_version(GOLF_VIN, _version_service(None), _pick())

    async def test_decode_version_errors_stay_visible(self):
        with pytest.raises(AutoRefQuotaError):
            await vin_decoder.decode_version(
                GOLF_VIN, _version_service(error=AutoRefQuotaError()), _pick()
            )

    async def test_decode_version_without_a_client_is_not_configured(self):
        with pytest.raises(vin_decoder.AutoRefNotConfiguredError):
            await vin_decoder.decode_version(GOLF_VIN, None, _pick())


@pytest.mark.unit
class TestVersionNotes:
    def test_a_version_list_replaces_the_no_model_note(self):
        # F-2: the picker is the way to the model, not typing it.
        with_versions = vin_decoder.enrich(GOLF_VIN, dict(AGREEMENT, vin=GOLF_VIN), "autoref")
        assert vin_decoder.NOTE_EU_VIN_NO_MODEL not in with_versions["notes"]
        without = {k: v for k, v in AGREEMENT.items() if k != "candidates"}
        plain = vin_decoder.enrich(GOLF_VIN, dict(without, vin=GOLF_VIN), "autoref")
        assert vin_decoder.NOTE_EU_VIN_NO_MODEL in plain["notes"]

    def test_a_pick_needs_something_to_check(self):
        with pytest.raises(ValueError):
            _pick(expect_model=None, expect_kw=None)
