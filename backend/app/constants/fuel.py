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


# Convenience tuples for schema validators (avoids re-iterating the enum).
PAYMENT_METHOD_VALUES: tuple[str, ...] = tuple(m.value for m in PaymentMethod)
TRIP_TYPE_VALUES: tuple[str, ...] = tuple(t.value for t in TripType)
FUEL_TYPE_VALUES: tuple[str, ...] = tuple(f.value for f in FuelTypeEnum)


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
