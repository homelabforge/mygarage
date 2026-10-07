"""Tax record types (#211).

Codes, not display strings. The form shows a translated label and, with a
country profile, the national proper name beside it (« Malus écologique »,
« Kfz-Steuer »); the profile also says which types a country uses and in
what order. The four display strings stored before migration 146
(`Registration`, `Inspection`, `Property Tax`, `Tolls`) read and import as
their codes, so an older CSV or a restored backup still lands.
"""

from __future__ import annotations

from typing import Final

#: Every tax type, in the order the form offers them without a profile.
TAX_TYPE_VALUES: Final[tuple[str, ...]] = (
    # Plates, certificate, registration fee.
    "registration",
    # One-off tax at first registration: FR taxe régionale (Y.1), NL BPM,
    # BE TMC/BIV, ES impuesto de matriculación, IT IPT.
    "registration_tax",
    # FR malus écologique (Y.3).
    "co2_malus",
    # FR malus au poids.
    "weight_malus",
    # Annual ownership tax: DE Kfz-Steuer, IT bollo, NL MRB, ES IVTM, LU.
    "circulation_tax",
    # FR taxes annuelles sur les véhicules de société.
    "company_vehicle_tax",
    # The periodic technical inspection fee.
    "inspection",
    # US ad valorem / personal property tax on the vehicle.
    "property_tax",
    "tolls",
    # Time-based road charge: AT, CH, CZ, SI, HU…
    "vignette",
    # Crit'Air, Umweltplakette, DGT distintivo, LEZ registration.
    "lez_sticker",
    # Resident parking permit.
    "parking_permit",
    "other",
)

#: The display strings the column held before migration 146, by code.
LEGACY_TAX_TYPES: Final[dict[str, str]] = {
    "Registration": "registration",
    "Inspection": "inspection",
    "Property Tax": "property_tax",
    "Tolls": "tolls",
}

# Case-folded spellings that mean a code: the code itself, the code with
# spaces, and the legacy display string.
_SPELLINGS: Final[dict[str, str]] = {
    **{code: code for code in TAX_TYPE_VALUES},
    **{code.replace("_", " "): code for code in TAX_TYPE_VALUES},
    **{legacy.casefold(): code for legacy, code in LEGACY_TAX_TYPES.items()},
}


def is_tax_type(value: str | None) -> bool:
    """Whether `value` is one of the codes, exactly."""
    return value in TAX_TYPE_VALUES


def normalize_tax_type(value: str | None) -> str | None:
    """The code a stored or typed tax type means; the trimmed input when unknown.

    Blank → None. A code, a legacy display string, or either in any case or
    with spaces for underscores → the code. Anything else comes back trimmed
    for the caller to refuse (a schema answers 422) or to file under `other`
    (the CSV importer).
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return _SPELLINGS.get(trimmed.casefold(), trimmed)
