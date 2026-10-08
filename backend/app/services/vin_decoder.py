"""Decode a VIN: NHTSA's answer, read with what the VIN itself says (#211).

NHTSA's vPIC is the one decoder the app calls. On a North American VIN it
answers everything; on a European one it knows the manufacturer (« RENAULT
GROUP »), leaves the make and the model empty, reports a check-digit error
that is not one (the check digit is a North American rule), and reads a
model year off position 10 that most European makers use for something
else. This wrapper keeps every field NHTSA gives, fills the make and the
manufacturer from the bundled WMI table when NHTSA has none, drops the
year where the position is not a model year, and says how much was
decoded (``decode_quality``) with ``notes`` the form can show, so the
person types the model instead of trusting a blank.

Transport failures are NHTSA's own exceptions, raised unchanged: the route
maps them to 503/504 as before.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.services.nhtsa import NHTSAService
from app.utils import wmi as wmi_table
from app.utils.logging_utils import sanitize_for_log
from app.utils.vin import calculate_check_digit, validate_vin

logger = logging.getLogger(__name__)

DecodeQuality = Literal["full", "partial", "wmi_only", "none"]

#: The notes the form translates.
NOTE_EU_VIN_NO_MODEL = "eu_vin_no_model"
NOTE_YEAR_UNRELIABLE = "year_unreliable"
NOTE_CHECK_DIGIT_NOT_APPLICABLE = "check_digit_not_applicable"
#: NHTSA's "the check digit does not match" code.
_NHTSA_CHECK_DIGIT_ERROR = "1"


def quality_of(info: dict[str, Any], known: wmi_table.WMIInfo | None) -> DecodeQuality:
    """How much of the vehicle the answer names."""
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


def enrich(vin: str, info: dict[str, Any]) -> dict[str, Any]:
    """NHTSA's answer completed from the VIN's own structure. Pure."""
    vin = vin.strip().upper()
    result = dict(info)
    result["vin"] = result.get("vin") or vin
    known = wmi_table.lookup(vin)
    region = wmi_table.region_of(vin)
    country = known.country if known is not None else wmi_table.country_of(vin)
    notes: list[str] = []

    if known is not None:
        if not result.get("make"):
            result["make"] = known.make
        if not result.get("manufacturer"):
            result["manufacturer"] = known.manufacturer

    if not wmi_table.model_year_applies(vin):
        if result.get("year") is not None:
            notes.append(NOTE_YEAR_UNRELIABLE)
        result["year"] = None

    if region is not None and region != "NA":
        if _check_digit_mismatch(vin) or result.get("error_code") == _NHTSA_CHECK_DIGIT_ERROR:
            notes.append(NOTE_CHECK_DIGIT_NOT_APPLICABLE)
        if region == "EU" and not result.get("model"):
            notes.append(NOTE_EU_VIN_NO_MODEL)

    result["region"] = region
    result["wmi_country"] = country
    result["decode_quality"] = quality_of(result, known)
    result["notes"] = notes
    return result


async def decode(vin: str, nhtsa: NHTSAService | None = None) -> dict[str, Any]:
    """Validate, ask NHTSA, enrich. Raises ValueError on a malformed VIN and
    NHTSA's httpx errors unchanged."""
    vin = vin.strip().upper()
    is_valid, error = validate_vin(vin)
    if not is_valid:
        raise ValueError(f"Invalid VIN: {error}")
    service = nhtsa if nhtsa is not None else NHTSAService()
    info = await service.decode_vin(vin)
    result = enrich(vin, info)
    logger.info(
        "VIN %s decoded (%s, region %s): make=%s model=%s",
        sanitize_for_log(vin),
        result["decode_quality"],
        result["region"],
        sanitize_for_log(result.get("make")),
        sanitize_for_log(result.get("model")),
    )
    return result
