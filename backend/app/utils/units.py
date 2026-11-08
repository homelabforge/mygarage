"""Unit conversion utilities for imperial/metric conversion.

Canonical storage format: SI METRIC (kilometers, liters, kilograms, etc.)
- All database values are stored in metric units (per migration 053)
- Conversion happens at the API/UI boundary for users on imperial preferences
- Display callers use the float-returning `*_to_*` methods (rounded for UI)
- Write callers (forms, importers, migrations) use `to_canonical_decimal()`
  to avoid float precision loss when storing user input

Supported conversions:
- Volume: gallons ↔ liters
- Distance: miles ↔ kilometers
- Fuel Economy: MPG ↔ L/100km
- Feet, °F, PSI (to kPa, not bar), pounds and lb-ft: into metric only, through
  `to_canonical_decimal`. Displaying them goes through `unit_adapters.py`.
- Electric: kWh, kW, voltage (no conversion needed, universal)
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
    PSI_TO_BAR = PSI_TO_KPA / Decimal(100)
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

    # ========== VOLUME CONVERSIONS ==========

    @classmethod
    def gallons_to_liters(cls, gallons: Numeric, flavour: GallonFlavour = "us") -> float | None:
        """Convert gallons to liters using the given gallon flavour."""
        val = cls.to_decimal(gallons)
        if val is None:
            return None
        return cls.round_result(val * cls._gallons_to_liters_factor(flavour))

    @classmethod
    def liters_to_gallons(cls, liters: Numeric, flavour: GallonFlavour = "us") -> float | None:
        """Convert liters to gallons using the given gallon flavour."""
        val = cls.to_decimal(liters)
        if val is None:
            return None
        return cls.round_result(val / cls._gallons_to_liters_factor(flavour))

    # ========== DISTANCE CONVERSIONS ==========

    @classmethod
    def miles_to_km(cls, miles: Numeric) -> float | None:
        """Convert miles to kilometers."""
        val = cls.to_decimal(miles)
        if val is None:
            return None
        return cls.round_result(val * cls.MILES_TO_KM)

    @classmethod
    def km_to_miles(cls, km: Numeric) -> float | None:
        """Convert kilometers to miles."""
        val = cls.to_decimal(km)
        if val is None:
            return None
        return cls.round_result(val / cls.MILES_TO_KM)

    # ========== FUEL ECONOMY CONVERSIONS ==========

    @classmethod
    def mpg_to_l100km(cls, mpg: Numeric, flavour: GallonFlavour = "us") -> float | None:
        """Convert MPG to L/100km. Formula: L/100km = numerator / MPG."""
        val = cls.to_decimal(mpg)
        if val is None or val == 0:
            return None
        return cls.round_result(cls._mpg_numerator(flavour) / val, 1)

    @classmethod
    def l100km_to_mpg(cls, l100km: Numeric, flavour: GallonFlavour = "us") -> float | None:
        """Convert L/100km to MPG. Formula: MPG = numerator / (L/100km)."""
        val = cls.to_decimal(l100km)
        if val is None or val == 0:
            return None
        return cls.round_result(cls._mpg_numerator(flavour) / val, 1)

    @classmethod
    def l100km_to_kmpl(cls, l100km: Numeric) -> float | None:
        """Convert L/100km to km/L.

        Formula: km/L = 100 / (L/100km)
        """
        val = cls.to_decimal(l100km)
        if val is None or val == 0:
            return None
        return cls.round_result(Decimal("100") / val, 2)
