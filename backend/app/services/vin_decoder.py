"""Decode a VIN: NHTSA's answer, read with what the VIN itself says (#211).

NHTSA's vPIC is the one decoder the app calls. On a North American VIN it
answers everything; on a European one it knows the manufacturer (« RENAULT
GROUP »), leaves the make and the model empty, reports a check-digit error
that is not one (the check digit is a North American rule), and reads a
model year off position 10 that most European makers use for something
else. This wrapper keeps every field NHTSA gives, fills the make and the
manufacturer from the bundled WMI table when NHTSA has none, drops the
year where the position is not a model year (unless NHTSA decoded the VIN
cleanly, ErrorCode "0": then the year is NHTSA's answer, not a guess), and
says how much NHTSA itself decoded (``decode_quality``, judged before the
table fills anything) and where the make came from (``make_source``), with
``notes`` the form can show, so the person types the model instead of
trusting a blank.

Transport failures are NHTSA's own exceptions, raised unchanged: the route
maps them to 503/504 as before.

Since #219 AutoRef (``app.services.autoref``) is a second decoder, for the
European VINs NHTSA can't name. Both run through ``enrich``, so region,
country, year rules and notes stay one code path. With ``fallback`` (the
route's Automatic) an AutoRef miss or error quietly asks NHTSA instead and
says so in a note; a provider the person chose runs alone and its errors
reach them. Makes and ALL-CAPS models come back in Title Case
(``app.utils.vehicle_names``) whichever decoder answered.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.countries import EU_MEMBER_STATES
from app.services.autoref import (
    AutoRefAuthError,
    AutoRefError,
    AutoRefQuotaError,
    AutoRefService,
)
from app.services.nhtsa import NHTSAService
from app.services.settings_service import SecretUnreadableError, SettingsService
from app.utils import wmi as wmi_table
from app.utils.logging_utils import sanitize_for_log
from app.utils.vehicle_names import normalize_make, normalize_model
from app.utils.vin import calculate_check_digit, validate_vin

logger = logging.getLogger(__name__)

DecodeQuality = Literal["full", "partial", "wmi_only", "none"]
Provider = Literal["nhtsa", "autoref"]
MakeSource = Literal["nhtsa", "wmi", "autoref"]

#: Where AutoRef runs first in Automatic: the EU plus the countries whose
#: registries AutoRef also reads or borders (plan D4).
AUTOREF_FIRST_COUNTRIES: frozenset[str] = frozenset(EU_MEMBER_STATES) | {
    "GB",
    "CH",
    "NO",
    "IS",
    "LI",
}

#: The notes the form translates.
NOTE_EU_VIN_NO_MODEL = "eu_vin_no_model"
NOTE_YEAR_UNRELIABLE = "year_unreliable"
NOTE_CHECK_DIGIT_NOT_APPLICABLE = "check_digit_not_applicable"
#: Automatic asked AutoRef first and fell back to NHTSA, and why.
NOTE_AUTOREF_NO_MATCH = "autoref_no_match"
NOTE_AUTOREF_KEY_REJECTED = "autoref_key_rejected"
NOTE_AUTOREF_QUOTA = "autoref_quota"
NOTE_AUTOREF_UNAVAILABLE = "autoref_unavailable"
#: NHTSA's "the check digit does not match" code.
_NHTSA_CHECK_DIGIT_ERROR = "1"
#: NHTSA's "VIN decoded clean" code.
_NHTSA_CLEAN = "0"


class AutoRefNotConfiguredError(Exception):
    """AutoRef was chosen, but it's switched off or has no readable key."""


class AutoRefNoMatchError(Exception):
    """AutoRef was chosen and has no record for this VIN."""


def _nhtsa_codes(info: dict[str, Any]) -> set[str]:
    raw = info.get("error_code")
    if not isinstance(raw, str):
        return set()
    return {code.strip() for code in raw.split(",") if code.strip()}


def quality_of(info: dict[str, Any], known: wmi_table.WMIInfo | None) -> DecodeQuality:
    """How much of the vehicle NHTSA's answer names. Called on NHTSA's own
    answer, before the WMI table fills the make, so ``wmi_only`` means the
    table knew the maker and NHTSA did not."""
    if info.get("make") and info.get("model"):
        return "full"
    if info.get("make"):
        return "partial"
    if known is not None:
        return "wmi_only"
    return "none"


def _check_digit_mismatch(vin: str) -> bool:
    expected = calculate_check_digit(vin)
    return expected is not None and vin[8] != expected


def enrich(vin: str, info: dict[str, Any], source: Provider = "nhtsa") -> dict[str, Any]:
    """A decoder's answer completed from the VIN's own structure. Pure.

    Args:
        vin: The VIN.
        info: The decoder's answer; any ``notes`` it carries come first.
        source: Which decoder answered, for ``make_source`` and ``decoded_by``.
    """
    vin = vin.strip().upper()
    result = dict(info)
    result["vin"] = result.get("vin") or vin
    known = wmi_table.lookup(vin)
    region = wmi_table.region_of(vin)
    country = known.country if known is not None else wmi_table.country_of(vin)
    # The decoder's own notes (AutoRef's best guess, a fallback) survive.
    carried = info.get("notes")
    notes: list[str] = (
        [n for n in carried if isinstance(n, str)] if isinstance(carried, list) else []
    )
    quality = quality_of(result, known)
    make_source: MakeSource | None = source if result.get("make") else None

    if known is not None:
        if not result.get("make"):
            result["make"] = known.make
            make_source = "wmi"
        if not result.get("manufacturer"):
            result["manufacturer"] = known.manufacturer

    clean = _nhtsa_codes(info) == {_NHTSA_CLEAN}
    if not clean and not wmi_table.model_year_applies(vin):
        if result.get("year") is not None:
            notes.append(NOTE_YEAR_UNRELIABLE)
        result["year"] = None

    if region is not None and region != "NA":
        if _check_digit_mismatch(vin) or _NHTSA_CHECK_DIGIT_ERROR in _nhtsa_codes(info):
            notes.append(NOTE_CHECK_DIGIT_NOT_APPLICABLE)
        if region == "EU" and not result.get("model"):
            notes.append(NOTE_EU_VIN_NO_MODEL)

    result["region"] = region
    result["wmi_country"] = country
    result["decode_quality"] = quality
    result["make_source"] = make_source
    result["decoded_by"] = source
    result["notes"] = list(dict.fromkeys(notes))
    return result


async def autoref_key(db: AsyncSession) -> str | None:
    """The AutoRef key when AutoRef is switched on and the key is readable.

    Read per request, so a key saved or cleared takes effect on the next
    decode. An undecryptable key reads as no key, logged at WARNING.
    """
    if not await SettingsService.get_bool(db, "autoref_enabled", default=False):
        return None
    try:
        key = await SettingsService.get_secret(db, "autoref_api_key")
    except SecretUnreadableError:
        logger.warning(
            "The stored AutoRef API key can't be decrypted; AutoRef is off until it's re-entered"
        )
        return None
    key = (key or "").strip()
    return key or None


def available_providers(autoref_configured: bool) -> list[Provider]:
    """NHTSA always; AutoRef when it has a key."""
    return ["nhtsa", "autoref"] if autoref_configured else ["nhtsa"]


def preferred_provider(
    country: str | None, available: list[Provider], vin: str | None = None
) -> Provider:
    """Which decoder Automatic asks first.

    NHTSA for a North American VIN whoever asks (it answers those fully and
    for free; Fable F-5); otherwise AutoRef when it's available and the
    country is in ``AUTOREF_FIRST_COUNTRIES``; otherwise NHTSA.
    """
    if vin is not None and wmi_table.region_of(vin) == "NA":
        return "nhtsa"
    if "autoref" in available and country in AUTOREF_FIRST_COUNTRIES:
        return "autoref"
    return "nhtsa"


def _fallback_note(exc: AutoRefError) -> str:
    if isinstance(exc, AutoRefAuthError):
        return NOTE_AUTOREF_KEY_REJECTED
    if isinstance(exc, AutoRefQuotaError):
        return NOTE_AUTOREF_QUOTA
    return NOTE_AUTOREF_UNAVAILABLE


def _title_case(info: dict[str, Any]) -> dict[str, Any]:
    out = dict(info)
    if isinstance(out.get("make"), str):
        out["make"] = normalize_make(out["make"])
    if isinstance(out.get("model"), str):
        make = out.get("make")
        out["model"] = normalize_model(out["model"], make if isinstance(make, str) else None)
    return out


async def decode(
    vin: str,
    nhtsa: NHTSAService | None = None,
    *,
    provider: Provider = "nhtsa",
    autoref: AutoRefService | None = None,
    fallback: bool = False,
) -> dict[str, Any]:
    """Validate, ask the decoder, enrich.

    Args:
        vin: The VIN.
        nhtsa: The NHTSA client (built when None).
        provider: Which decoder answers.
        autoref: The AutoRef client; required for ``provider="autoref"``.
        fallback: On an AutoRef miss or error, ask NHTSA and add a note
            (Automatic). Without it AutoRef's errors are raised.

    Raises:
        ValueError: A malformed VIN.
        AutoRefNotConfiguredError: AutoRef asked for with no client.
        AutoRefNoMatchError: AutoRef chosen and it has no record.
        AutoRefError: AutoRef chosen and it failed.
        httpx errors: NHTSA's, unchanged.
    """
    vin = vin.strip().upper()
    is_valid, error = validate_vin(vin)
    if not is_valid:
        raise ValueError(f"Invalid VIN: {error}")

    source: Provider = "nhtsa"
    info: dict[str, Any] | None = None
    fallback_note: str | None = None
    if provider == "autoref":
        if autoref is None:
            raise AutoRefNotConfiguredError()
        try:
            info = await autoref.decode(vin)
        except AutoRefError as exc:
            if not fallback:
                raise
            fallback_note = _fallback_note(exc)
            logger.info("AutoRef failed for VIN %s (%s); asking NHTSA", sanitize_for_log(vin), exc)
        else:
            if info is not None:
                source = "autoref"
            elif not fallback:
                raise AutoRefNoMatchError()
            else:
                fallback_note = NOTE_AUTOREF_NO_MATCH

    if info is None:
        service = nhtsa if nhtsa is not None else NHTSAService()
        info = await service.decode_vin(vin)
        if fallback_note is not None:
            info = {**info, "notes": [fallback_note]}

    result = enrich(vin, _title_case(info), source)
    logger.info(
        "VIN %s decoded by %s (%s, region %s): make=%s model=%s",
        sanitize_for_log(vin),
        source,
        result["decode_quality"],
        result["region"],
        sanitize_for_log(result.get("make")),
        sanitize_for_log(result.get("model")),
    )
    return result
