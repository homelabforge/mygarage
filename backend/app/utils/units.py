"""Unit conversion utilities for imperial/metric conversion.

Canonical storage format: IMPERIAL
- All database values are stored in imperial units
- Conversion happens at API boundary (input → imperial, imperial → output)
- This ensures data consistency and simplifies queries/aggregations

Supported conversions:
- Volume: gallons ↔ liters
- Distance: miles ↔ kilometers
- Fuel Economy: MPG ↔ L/100km
- Dimensions: feet ↔ meters
- Temperature: °F ↔ °C
- Pressure: PSI ↔ bar
- Weight: pounds ↔ kilograms
- Torque: lb-ft ↔ Nm
- Electric: kWh, kW, voltage (no conversion needed, universal)
"""

from decimal import Decimal

# Type alias for numeric values
Numeric = int | float | Decimal | None


class UnitConverter:
    """Unit conversion between imperial and metric systems."""

    # Conversion factors (imperial to metric)
    GALLONS_TO_LITERS = Decimal("3.78541")
    MILES_TO_KM = Decimal("1.60934")
    FEET_TO_METERS = Decimal("0.3048")
    PSI_TO_BAR = Decimal("0.0689476")
    LBS_TO_KG = Decimal("0.453592")
    LBFT_TO_NM = Decimal("1.35582")

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
        """Round and convert Decimal to float for JSON serialization."""
        if value is None:
            return None
        return float(round(value, decimals))

    # ========== VOLUME CONVERSIONS ==========

    @classmethod
    def gallons_to_liters(cls, gallons: Numeric) -> float | None:
        """Convert gallons to liters."""
        val = cls.to_decimal(gallons)
        if val is None:
            return None
        return cls.round_result(val * cls.GALLONS_TO_LITERS)

    @classmethod
    def liters_to_gallons(cls, liters: Numeric) -> float | None:
        """Convert liters to gallons."""
        val = cls.to_decimal(liters)
        if val is None:
            return None
        return cls.round_result(val / cls.GALLONS_TO_LITERS)

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
    def mpg_to_l100km(cls, mpg: Numeric) -> float | None:
        """Convert MPG to L/100km.

        Formula: L/100km = 235.214 / MPG
        (Uses exact conversion factor for gallon and mile)
        """
        val = cls.to_decimal(mpg)
        if val is None or val == 0:
            return None
        conversion_factor = Decimal("235.214")
        return cls.round_result(conversion_factor / val, 1)

    @classmethod
    def l100km_to_mpg(cls, l100km: Numeric) -> float | None:
        """Convert L/100km to MPG.

        Formula: MPG = 235.214 / (L/100km)
        """
        val = cls.to_decimal(l100km)
        if val is None or val == 0:
            return None
        conversion_factor = Decimal("235.214")
        return cls.round_result(conversion_factor / val, 1)

    # ========== DIMENSION CONVERSIONS ==========

    @classmethod
    def feet_to_meters(cls, feet: Numeric) -> float | None:
        """Convert feet to meters."""
        val = cls.to_decimal(feet)
        if val is None:
            return None
        return cls.round_result(val * cls.FEET_TO_METERS)

    @classmethod
    def meters_to_feet(cls, meters: Numeric) -> float | None:
        """Convert meters to feet."""
        val = cls.to_decimal(meters)
        if val is None:
            return None
        return cls.round_result(val / cls.FEET_TO_METERS)

    # ========== TEMPERATURE CONVERSIONS ==========

    @classmethod
    def fahrenheit_to_celsius(cls, fahrenheit: Numeric) -> float | None:
        """Convert Fahrenheit to Celsius.

        Formula: C = (F - 32) × 5/9
        """
        val = cls.to_decimal(fahrenheit)
        if val is None:
            return None
        celsius = (val - 32) * Decimal("5") / Decimal("9")
        return cls.round_result(celsius, 1)

    @classmethod
    def celsius_to_fahrenheit(cls, celsius: Numeric) -> float | None:
        """Convert Celsius to Fahrenheit.

        Formula: F = C × 9/5 + 32
        """
        val = cls.to_decimal(celsius)
        if val is None:
            return None
        fahrenheit = val * Decimal("9") / Decimal("5") + 32
        return cls.round_result(fahrenheit, 1)

    # ========== PRESSURE CONVERSIONS ==========

    @classmethod
    def psi_to_bar(cls, psi: Numeric) -> float | None:
        """Convert PSI to bar."""
        val = cls.to_decimal(psi)
        if val is None:
            return None
        return cls.round_result(val * cls.PSI_TO_BAR)

    @classmethod
    def bar_to_psi(cls, bar: Numeric) -> float | None:
        """Convert bar to PSI."""
        val = cls.to_decimal(bar)
        if val is None:
            return None
        return cls.round_result(val / cls.PSI_TO_BAR)

    # ========== WEIGHT CONVERSIONS ==========

    @classmethod
    def lbs_to_kg(cls, lbs: Numeric) -> float | None:
        """Convert pounds to kilograms."""
        val = cls.to_decimal(lbs)
        if val is None:
            return None
        return cls.round_result(val * cls.LBS_TO_KG)

    @classmethod
    def kg_to_lbs(cls, kg: Numeric) -> float | None:
        """Convert kilograms to pounds."""
        val = cls.to_decimal(kg)
        if val is None:
            return None
        return cls.round_result(val / cls.LBS_TO_KG)

    # ========== TORQUE CONVERSIONS ==========

    @classmethod
    def lbft_to_nm(cls, lbft: Numeric) -> float | None:
        """Convert lb-ft to Newton-meters."""
        val = cls.to_decimal(lbft)
        if val is None:
            return None
        return cls.round_result(val * cls.LBFT_TO_NM)

    @classmethod
    def nm_to_lbft(cls, nm: Numeric) -> float | None:
        """Convert Newton-meters to lb-ft."""
        val = cls.to_decimal(nm)
        if val is None:
            return None
        return cls.round_result(val / cls.LBFT_TO_NM)
