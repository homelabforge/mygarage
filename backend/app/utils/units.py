"""Unit conversion utilities for imperial/metric conversion.

Canonical storage format: SI METRIC (kilometers, liters, kilograms, etc.)
- All database values are stored in metric units (per migration 053)
- Conversion happens at the API/UI boundary for users on imperial preferences
- Write callers (forms, importers, migrations) use `to_canonical_decimal()`
  to avoid float precision loss when storing user input
- Display goes through `unit_adapters.py`, which is built from the factors here
- `miles_to_km` is the one float conversion left, for a device's mile
  odometer reading (`odometer_units.py`) and one repair tool. `round_result`
  is just its rounding step

`to_canonical_decimal` takes gallons (US or UK), miles, MPG (US or UK), feet,
°F, PSI (to kPa, not bar), pounds and lb-ft into metric. Electric units (kWh,
kW, voltage) need no conversion.
"""

from decimal import Decimal
from typing import Literal

# Type alias for numeric values
Numeric = int | float | Decimal | None

GallonFlavour = Literal["us", "uk"]


class UnitConverter:
    """Unit conversion between imperial and metric systems."""

    # Conversion factors (imperial to metric), from their legal definitions.
    #
    # The base factors are exact by definition (the 1959 international yard
    # and pound agreement, the 231 cubic inch US gallon, the imperial gallon
    # of 4.54609 L, standard gravity). Every other factor is DERIVED from them
    # right here, so a derived value cannot drift from its inputs.
    #
    # Before v3.4.0 these were truncated (a mile of 1.60934 km, a US gallon of
    # 3.78541 L) while the CSV importer and the webhooks used the exact values,
    # so the same miles typed into a form and imported from a file stored
    # different kilometres. frontend/src/utils/units.ts mirrors this table and
    # frontend/src/utils/__tests__/unitFactorCrossLayer.test.ts fails when the
    # two disagree. Migration 053 keeps its own frozen copies on purpose: it is
    # a historical transform.
    MILES_TO_KM = Decimal("1.609344")
    FEET_TO_METERS = Decimal("0.3048")
    INCH_TO_METERS = Decimal("0.0254")
    US_GALLONS_TO_LITERS = Decimal("3.785411784")
    UK_GALLONS_TO_LITERS = Decimal("4.54609")
    LBS_TO_KG = Decimal("0.45359237")
    STANDARD_GRAVITY = Decimal("9.80665")
    LBF_TO_N = LBS_TO_KG * STANDARD_GRAVITY
    PSI_TO_KPA = LBF_TO_N / (INCH_TO_METERS * INCH_TO_METERS) / Decimal(1000)
    LBFT_TO_NM = LBF_TO_N * FEET_TO_METERS
    # L/100km = numerator / MPG (reciprocal - division, not multiplication).
    US_MPG_TO_L100KM_NUMERATOR = Decimal(100) * US_GALLONS_TO_LITERS / MILES_TO_KM
    UK_MPG_TO_L100KM_NUMERATOR = Decimal(100) * UK_GALLONS_TO_LITERS / MILES_TO_KM

    @classmethod
    def _gallons_to_liters_factor(cls, flavour: GallonFlavour) -> Decimal:
        """Litres per gallon for the requested flavour."""
        return cls.UK_GALLONS_TO_LITERS if flavour == "uk" else cls.US_GALLONS_TO_LITERS

    @classmethod
    def _mpg_numerator(cls, flavour: GallonFlavour) -> Decimal:
        """MPG <-> L/100km numerator for the requested flavour."""
        return cls.UK_MPG_TO_L100KM_NUMERATOR if flavour == "uk" else cls.US_MPG_TO_L100KM_NUMERATOR

    @staticmethod
    def to_decimal(value: Numeric) -> Decimal | None:
        """Convert numeric value to Decimal for precision."""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def round_result(value: Decimal | None, decimals: int = 2) -> float | None:
        """Round and convert Decimal to float for JSON serialization.

        Use this for DISPLAY callers only. Write callers should use
        `to_canonical_decimal()` so the stored value never loses precision.
        """
        if value is None:
            return None
        return float(round(value, decimals))

    # ========== DECIMAL-SAFE WRITE-PATH HELPERS ==========

    @classmethod
    def to_canonical_decimal(
        cls, value: Numeric, from_unit: str, flavour: GallonFlavour = "us"
    ) -> Decimal | None:
        """Convert a user-entered value into the canonical metric Decimal.

        Use this on the API write path so the stored value matches what the
        user typed (no float coercion, no display-rounding drift).

        `from_unit` declares what unit the input is in:
            - 'km'        → already metric, pass through as Decimal
            - 'mi'        → multiply by MILES_TO_KM
            - 'L'         → already metric, pass through
            - 'gal'       → multiply by the gallon factor for `flavour`
            - 'kg'        → already metric
            - 'lb'        → multiply by LBS_TO_KG
            - 'm'         → already metric
            - 'ft'        → multiply by FEET_TO_METERS
            - 'C'         → already metric
            - 'F'         → (val - 32) * 5/9
            - 'kPa'       → already metric
            - 'PSI'       → multiply by PSI_TO_KPA (canonical is kPa, not bar)
            - 'Nm'        → already metric
            - 'lbft'      → multiply by LBFT_TO_NM
            - 'L/100km'   → already metric
            - 'MPG'       → the MPG numerator for `flavour` / value

        `flavour` selects US (3.785 L) or UK (4.546 L) gallons; it only
        affects the 'gal' and 'MPG' cases and defaults to 'us'.

        Returns None for None input. Raises ValueError for unknown units so a
        typo at a call site fails loudly instead of silently corrupting data.
        """
        val = cls.to_decimal(value)
        if val is None:
            return None

        match from_unit:
            case "km" | "L" | "kg" | "m" | "C" | "kPa" | "Nm" | "L/100km":
                return val
            case "mi":
                return val * cls.MILES_TO_KM
            case "gal":
                return val * cls._gallons_to_liters_factor(flavour)
            case "lb":
                return val * cls.LBS_TO_KG
            case "ft":
                return val * cls.FEET_TO_METERS
            case "F":
                return (val - Decimal("32")) * Decimal("5") / Decimal("9")
            case "PSI":
                return val * cls.PSI_TO_KPA
            case "lbft":
                return val * cls.LBFT_TO_NM
            case "MPG":
                if val == 0:
                    return None
                return cls._mpg_numerator(flavour) / val
            case _:
                raise ValueError(
                    f"Unknown source unit {from_unit!r}; expected one of "
                    "km/mi/L/gal/kg/lb/m/ft/C/F/kPa/PSI/Nm/lbft/L_100km/MPG"
                )

    # ========== DISTANCE CONVERSIONS ==========

    @classmethod
    def miles_to_km(cls, miles: Numeric) -> float | None:
        """Convert miles to kilometers."""
        val = cls.to_decimal(miles)
        if val is None:
            return None
        return cls.round_result(val * cls.MILES_TO_KM)
