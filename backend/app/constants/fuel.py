"""Fuel-tracking enums and NHTSA fuel-string normalization.

Single source of truth for:
- Payment method (per-fillup + user default)
- Trip type (per-fillup + user default)
- Fuel type (vehicle primary, vehicle secondary, per-fillup actual)

Stored as `String(20)` in the database (no DB CHECK constraints) and validated
at the schema layer via Pydantic `field_validator`. Matches the existing
`fuel_records.price_basis` pattern from migration 053.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TypeIs


class PaymentMethod(StrEnum):
    """How a fill-up was paid for."""

    CASH = "cash"
    CREDIT = "credit"
    DEBIT = "debit"
    FLEET_CARD = "fleet_card"
    APP = "app"  # mobile pay (Apple Pay, Google Pay, station app)
    OTHER = "other"


class TripType(StrEnum):
    """Primary use of the fuel between this fill-up and the previous one."""

    PRIVATE = "private"
    BUSINESS = "business"
    COMMUTE = "commute"
    OTHER = "other"


class FuelTypeEnum(StrEnum):
    """Canonical fuel-type vocabulary.

    Used in three contexts:
    - `vehicles.fuel_type`           — primary capability of the vehicle
    - `vehicles.fuel_type_secondary` — optional secondary capability (PHEV / flex)
    - `fuel_records.fuel_type_used`  — actual fuel dispensed for this fill-up
    """

    GASOLINE = "gasoline"
    DIESEL = "diesel"
    ELECTRIC = "electric"
    HYBRID = "hybrid"  # non-pluggable hybrid
    PLUGIN_HYBRID = "plugin_hybrid"
    E85 = "e85"
    PROPANE_LPG = "propane_lpg"
    CNG = "cng"
    HYDROGEN = "hydrogen"
    OTHER = "other"


class FuelGradeEnum(StrEnum):
    """EN 16942 pump labels, the fuel grade of one fill-up (#211).

    The European label on the pump and on the filler flap: a circle for
    petrol (E5, E10, E85 — the maximum ethanol share), a square for diesel
    (B7, B10, B20, B30, B100 — the maximum FAME share; XTL for paraffinic
    diesel such as HVO), a diamond for gaseous fuels. Stored next to
    ``octane`` (RON in Europe, AKI in North America) and ``diesel_grade``
    (the US clear-vs-dyed distinction) on ``fuel_records.fuel_grade``.
    """

    E5 = "E5"
    E10 = "E10"
    E85 = "E85"
    B7 = "B7"
    B10 = "B10"
    B20 = "B20"
    B30 = "B30"
    B100 = "B100"
    XTL = "XTL"
    H2 = "H2"
    CNG = "CNG"
    LPG = "LPG"
    LNG = "LNG"


# Convenience tuples for schema validators (avoids re-iterating the enum).
PAYMENT_METHOD_VALUES: tuple[str, ...] = tuple(m.value for m in PaymentMethod)
TRIP_TYPE_VALUES: tuple[str, ...] = tuple(t.value for t in TripType)
FUEL_TYPE_VALUES: tuple[str, ...] = tuple(f.value for f in FuelTypeEnum)
FUEL_GRADE_VALUES: tuple[str, ...] = tuple(g.value for g in FuelGradeEnum)

#: Which EN 16942 labels a fuel type can be dispensed as. A hybrid refuels
#: with petrol; a flex vehicle on E85 picks E85 through ``fuel_type_used``.
GRADES_FOR_FUEL_TYPE: dict[FuelTypeEnum, tuple[FuelGradeEnum, ...]] = {
    FuelTypeEnum.GASOLINE: (FuelGradeEnum.E5, FuelGradeEnum.E10),
    FuelTypeEnum.HYBRID: (FuelGradeEnum.E5, FuelGradeEnum.E10),
    FuelTypeEnum.PLUGIN_HYBRID: (FuelGradeEnum.E5, FuelGradeEnum.E10),
    FuelTypeEnum.E85: (FuelGradeEnum.E85,),
    FuelTypeEnum.DIESEL: (
        FuelGradeEnum.B7,
        FuelGradeEnum.B10,
        FuelGradeEnum.B20,
        FuelGradeEnum.B30,
        FuelGradeEnum.B100,
        FuelGradeEnum.XTL,
    ),
    FuelTypeEnum.PROPANE_LPG: (FuelGradeEnum.LPG,),
    FuelTypeEnum.CNG: (FuelGradeEnum.CNG, FuelGradeEnum.LNG),
    FuelTypeEnum.HYDROGEN: (FuelGradeEnum.H2,),
}

#: Field P.3 of a French registration certificate (energy code) → the
#: vehicle's primary and secondary fuel capability. The harmonised code is the
#: same on every EU certificate, but the two-letter values are France's.
CARTE_GRISE_ENERGY_CODES: dict[str, tuple[FuelTypeEnum, FuelTypeEnum | None]] = {
    "ES": (FuelTypeEnum.GASOLINE, None),
    "GO": (FuelTypeEnum.DIESEL, None),
    "EL": (FuelTypeEnum.ELECTRIC, None),
    "EE": (FuelTypeEnum.PLUGIN_HYBRID, FuelTypeEnum.ELECTRIC),  # essence, rechargeable
    "EH": (FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC),  # essence, non rechargeable
    "GL": (FuelTypeEnum.PLUGIN_HYBRID, FuelTypeEnum.ELECTRIC),  # gazole, rechargeable
    "GH": (FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC),  # gazole, non rechargeable
    "GP": (FuelTypeEnum.PROPANE_LPG, None),
    "GN": (FuelTypeEnum.CNG, None),
    "FE": (FuelTypeEnum.E85, None),
    "H2": (FuelTypeEnum.HYDROGEN, None),
    "EG": (FuelTypeEnum.GASOLINE, FuelTypeEnum.PROPANE_LPG),  # bicarburation essence-GPL
    "EN": (FuelTypeEnum.GASOLINE, FuelTypeEnum.CNG),  # bicarburation essence-GNV
    "ET": (FuelTypeEnum.E85, None),
    "FG": (FuelTypeEnum.E85, FuelTypeEnum.PROPANE_LPG),
}


# ---------------------------------------------------------------------------
#  NHTSA / free-text → FuelTypeEnum normalization
# ---------------------------------------------------------------------------
#
# NHTSA's `FuelTypePrimary` / `FuelTypeSecondary` returns capitalized
# human-readable strings. Free-text user input may also include legacy
# spellings ("Regular", "87", "Premium"). The mapping below normalizes both.
#
# Lookups are case-insensitive and whitespace-trimmed; if a string contains
# no recognized token the result is `None` (caller decides whether to fall
# back to FuelTypeEnum.OTHER and log).
# ---------------------------------------------------------------------------

_NORMALIZATION_MAP: dict[str, FuelTypeEnum] = {
    # Direct enum values (allow already-normalized input through unchanged)
    "gasoline": FuelTypeEnum.GASOLINE,
    "diesel": FuelTypeEnum.DIESEL,
    "electric": FuelTypeEnum.ELECTRIC,
    "hybrid": FuelTypeEnum.HYBRID,
    "plugin_hybrid": FuelTypeEnum.PLUGIN_HYBRID,
    "e85": FuelTypeEnum.E85,
    "propane_lpg": FuelTypeEnum.PROPANE_LPG,
    "cng": FuelTypeEnum.CNG,
    "hydrogen": FuelTypeEnum.HYDROGEN,
    "other": FuelTypeEnum.OTHER,
    # Common gasoline aliases / octane grades
    "gas": FuelTypeEnum.GASOLINE,
    "petrol": FuelTypeEnum.GASOLINE,
    "regular": FuelTypeEnum.GASOLINE,
    "regular gasoline": FuelTypeEnum.GASOLINE,
    "unleaded": FuelTypeEnum.GASOLINE,
    "premium": FuelTypeEnum.GASOLINE,
    "premium gasoline": FuelTypeEnum.GASOLINE,
    "midgrade": FuelTypeEnum.GASOLINE,
    "mid-grade": FuelTypeEnum.GASOLINE,
    "87": FuelTypeEnum.GASOLINE,
    "89": FuelTypeEnum.GASOLINE,
    "91": FuelTypeEnum.GASOLINE,
    "93": FuelTypeEnum.GASOLINE,
    # Diesel
    "biodiesel": FuelTypeEnum.DIESEL,  # treated as diesel for tracking purposes
    "b20": FuelTypeEnum.DIESEL,
    # Electric / battery
    "ev": FuelTypeEnum.ELECTRIC,
    "battery electric": FuelTypeEnum.ELECTRIC,
    "battery": FuelTypeEnum.ELECTRIC,
    # Hybrid (non-pluggable)
    "hev": FuelTypeEnum.HYBRID,
    "hybrid electric": FuelTypeEnum.HYBRID,
    "gasoline, hybrid electric": FuelTypeEnum.HYBRID,
    # Plug-in hybrid
    "phev": FuelTypeEnum.PLUGIN_HYBRID,
    "plug-in hybrid": FuelTypeEnum.PLUGIN_HYBRID,
    "plug in hybrid": FuelTypeEnum.PLUGIN_HYBRID,
    "plugin hybrid": FuelTypeEnum.PLUGIN_HYBRID,
    # E85 / flex fuel
    "flex fuel": FuelTypeEnum.E85,
    "flex-fuel": FuelTypeEnum.E85,
    "flexfuel": FuelTypeEnum.E85,
    "ethanol": FuelTypeEnum.E85,
    "ethanol (e85)": FuelTypeEnum.E85,
    "gasoline, e85 (flex fuel)": FuelTypeEnum.E85,
    # LPG / propane
    "lpg": FuelTypeEnum.PROPANE_LPG,
    "propane": FuelTypeEnum.PROPANE_LPG,
    "propane (lpg)": FuelTypeEnum.PROPANE_LPG,
    "liquified petroleum gas (propane)": FuelTypeEnum.PROPANE_LPG,
    # CNG / natural gas
    "natural gas": FuelTypeEnum.CNG,
    "compressed natural gas": FuelTypeEnum.CNG,
    "compressed natural gas (cng)": FuelTypeEnum.CNG,
    # Hydrogen
    "fuel cell": FuelTypeEnum.HYDROGEN,
    "fuel cell vehicle": FuelTypeEnum.HYDROGEN,
    "fuel cell hydrogen": FuelTypeEnum.HYDROGEN,
    # ---- Locale aliases (pl/uk/ru) — mirror of migration 054 _NORMALIZATION_MAP
    # Surfaced by issue #69 for CSV imports of records typed in Slavic
    # locales. Polish/Ukrainian/Russian "gaz/газ" intentionally maps to
    # PROPANE_LPG (autogas / LPG retrofit, very common in Poland), NOT
    # to GASOLINE despite the surface similarity to English "gas".
    # Polish ----
    "benzyna": FuelTypeEnum.GASOLINE,
    "olej napędowy": FuelTypeEnum.DIESEL,
    "gaz": FuelTypeEnum.PROPANE_LPG,
    "elektryczny": FuelTypeEnum.ELECTRIC,
    "hybryda": FuelTypeEnum.HYBRID,
    "hybrydowy": FuelTypeEnum.HYBRID,
    # Ukrainian ----
    "бензин": FuelTypeEnum.GASOLINE,
    "дизель": FuelTypeEnum.DIESEL,
    "газ": FuelTypeEnum.PROPANE_LPG,
    "електричний": FuelTypeEnum.ELECTRIC,
    "гібрид": FuelTypeEnum.HYBRID,
    # Russian (бензин/дизель/газ shared with Ukrainian above) ----
    "электрический": FuelTypeEnum.ELECTRIC,
    "гибрид": FuelTypeEnum.HYBRID,
    # ---- Western European aliases (#211): pump names and the words a French,
    # German, Italian, Dutch or Spanish CSV export uses for a fuel type.
    # French ----
    "essence": FuelTypeEnum.GASOLINE,
    "sans plomb": FuelTypeEnum.GASOLINE,
    "sp95": FuelTypeEnum.GASOLINE,
    "sp 95": FuelTypeEnum.GASOLINE,
    "sp95-e10": FuelTypeEnum.GASOLINE,
    "sp95 e10": FuelTypeEnum.GASOLINE,
    "e10": FuelTypeEnum.GASOLINE,
    "e5": FuelTypeEnum.GASOLINE,
    "sp98": FuelTypeEnum.GASOLINE,
    "sp 98": FuelTypeEnum.GASOLINE,
    "gazole": FuelTypeEnum.DIESEL,
    "gasoil": FuelTypeEnum.DIESEL,
    "b7": FuelTypeEnum.DIESEL,
    "b10": FuelTypeEnum.DIESEL,
    "hvo": FuelTypeEnum.DIESEL,
    "hvo100": FuelTypeEnum.DIESEL,
    "xtl": FuelTypeEnum.DIESEL,
    "électrique": FuelTypeEnum.ELECTRIC,
    "electrique": FuelTypeEnum.ELECTRIC,
    "hybride": FuelTypeEnum.HYBRID,
    "hybride rechargeable": FuelTypeEnum.PLUGIN_HYBRID,
    "superéthanol": FuelTypeEnum.E85,
    "superethanol": FuelTypeEnum.E85,
    "superéthanol e85": FuelTypeEnum.E85,
    "éthanol": FuelTypeEnum.E85,
    "gpl": FuelTypeEnum.PROPANE_LPG,
    "gnv": FuelTypeEnum.CNG,
    "hydrogène": FuelTypeEnum.HYDROGEN,
    "hydrogene": FuelTypeEnum.HYDROGEN,
    # German ----
    "benzin": FuelTypeEnum.GASOLINE,
    "super": FuelTypeEnum.GASOLINE,
    "super e10": FuelTypeEnum.GASOLINE,
    "super e5": FuelTypeEnum.GASOLINE,
    "super plus": FuelTypeEnum.GASOLINE,
    "elektro": FuelTypeEnum.ELECTRIC,
    "elektrisch": FuelTypeEnum.ELECTRIC,
    "erdgas": FuelTypeEnum.CNG,
    "autogas": FuelTypeEnum.PROPANE_LPG,
    "wasserstoff": FuelTypeEnum.HYDROGEN,
    # Italian ----
    "benzina": FuelTypeEnum.GASOLINE,
    "gasolio": FuelTypeEnum.DIESEL,
    "metano": FuelTypeEnum.CNG,
    "elettrica": FuelTypeEnum.ELECTRIC,
    "elettrico": FuelTypeEnum.ELECTRIC,
    "ibrida": FuelTypeEnum.HYBRID,
    "ibrido": FuelTypeEnum.HYBRID,
    # Dutch ----
    "benzine": FuelTypeEnum.GASOLINE,
    "aardgas": FuelTypeEnum.CNG,
    "waterstof": FuelTypeEnum.HYDROGEN,
    # Spanish ----
    "gasolina": FuelTypeEnum.GASOLINE,
    "gasóleo": FuelTypeEnum.DIESEL,
    "gasoleo": FuelTypeEnum.DIESEL,
    "eléctrico": FuelTypeEnum.ELECTRIC,
    "electrico": FuelTypeEnum.ELECTRIC,
    "híbrido": FuelTypeEnum.HYBRID,
    "hibrido": FuelTypeEnum.HYBRID,
    "glp": FuelTypeEnum.PROPANE_LPG,
    "gnc": FuelTypeEnum.CNG,
}


def normalize_fuel_type(raw: str | None) -> FuelTypeEnum | None:
    """Normalize a free-text or NHTSA fuel-type string to `FuelTypeEnum`.

    Returns `None` for empty / unrecognized values; callers decide whether
    to fall back to `FuelTypeEnum.OTHER`.

    Recognizes:
    - Direct enum values (case-insensitive)
    - NHTSA capitalized strings ("Gasoline", "Diesel", "Electric", ...)
    - Common aliases ("gas", "petrol", "regular", octane grades, "EV", "PHEV", ...)
    - Combined NHTSA strings ("Gasoline, Hybrid Electric") for primary capability
    """
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return _NORMALIZATION_MAP.get(key)


def is_diesel_vehicle(fuel_type: str | None, fuel_type_secondary: str | None = None) -> bool:
    """True when either fuel slot normalizes to diesel.

    Normalizes internally so this tolerates any legacy non-canonical DB
    value ("Diesel", "biodiesel") — gates built on this predicate must not
    depend on migration 061 having run.
    """
    return FuelTypeEnum.DIESEL in (
        normalize_fuel_type(fuel_type),
        normalize_fuel_type(fuel_type_secondary),
    )


def has_def_capacity(
    value: Decimal | float | int | None,
) -> TypeIs[Decimal | float | int]:
    """True when a `def_tank_capacity_liters`-shaped value is a real capacity.

    The column is Numeric, so payloads/DB values may arrive as Decimal,
    float, int, or None. None and 0 both mean "no capacity" — shared by the
    vehicle-level capacity gate and the DEF analytics remaining-liters math.
    `TypeIs` return lets callers narrow away `None` after the check.
    """
    return value is not None and value > 0


def split_combined_fuel_type(raw: str | None) -> tuple[FuelTypeEnum | None, FuelTypeEnum | None]:
    """Decode an NHTSA `FuelTypePrimary` value that may encode two fuels.

    NHTSA returns combined strings like ``"Gasoline, Hybrid Electric"`` or
    ``"Gasoline, E85 (Flex Fuel)"`` in the *primary* slot when a vehicle has
    dual fuel capability and `FuelTypeSecondary` is empty. This decoder
    returns ``(primary, secondary)`` tuples so the caller can populate both
    `vehicles.fuel_type` and `vehicles.fuel_type_secondary`.

    Returns ``(None, None)`` if the input doesn't decode cleanly — caller
    should fall back to the standalone ``normalize_fuel_type``.
    """
    if raw is None:
        return None, None
    key = raw.strip().lower()
    if not key:
        return None, None

    # Hybrid Electric in the primary slot → primary=hybrid, secondary=electric.
    # Plug-in Hybrid → primary=plugin_hybrid, secondary=electric.
    # E85 Flex Fuel → primary=gasoline, secondary=e85.
    if "plug-in hybrid" in key or "plug in hybrid" in key or "phev" in key:
        return FuelTypeEnum.PLUGIN_HYBRID, FuelTypeEnum.ELECTRIC
    if "hybrid electric" in key or "hybrid" in key:
        return FuelTypeEnum.HYBRID, FuelTypeEnum.ELECTRIC
    if "e85" in key or "flex fuel" in key or "flex-fuel" in key:
        return FuelTypeEnum.GASOLINE, FuelTypeEnum.E85

    return None, None
