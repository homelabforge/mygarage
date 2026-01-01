"""Base window sticker parser class with common extraction methods."""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class WindowStickerData:
    """Structured data extracted from a window sticker."""

    # Pricing
    msrp_base: Optional[Decimal] = None
    msrp_total: Optional[Decimal] = None
    msrp_options: Optional[Decimal] = None
    destination_charge: Optional[Decimal] = None

    # Individual options with pricing
    options_detail: dict[str, Decimal] = field(default_factory=dict)

    # Package contents (what's included in each package)
    packages: dict[str, list[str]] = field(default_factory=dict)

    # Colors
    exterior_color: Optional[str] = None
    interior_color: Optional[str] = None

    # Equipment lists
    standard_equipment: list[str] = field(default_factory=list)
    optional_equipment: list[str] = field(default_factory=list)

    # Fuel economy
    fuel_economy_city: Optional[int] = None
    fuel_economy_highway: Optional[int] = None
    fuel_economy_combined: Optional[int] = None

    # Vehicle specs
    engine_description: Optional[str] = None
    transmission_description: Optional[str] = None
    drivetrain: Optional[str] = None

    # Wheel/tire specs
    wheel_specs: Optional[str] = None
    tire_specs: Optional[str] = None

    # Warranty
    warranty_powertrain: Optional[str] = None
    warranty_basic: Optional[str] = None

    # Environmental ratings
    environmental_rating_ghg: Optional[str] = None
    environmental_rating_smog: Optional[str] = None

    # Location
    assembly_location: Optional[str] = None

    # VIN extracted from sticker (for validation)
    extracted_vin: Optional[str] = None

    # Raw text for debugging
    raw_text: Optional[str] = None

    # Parser metadata
    parser_name: Optional[str] = None
    confidence_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "msrp_base": str(self.msrp_base) if self.msrp_base else None,
            "msrp_total": str(self.msrp_total) if self.msrp_total else None,
            "msrp_options": str(self.msrp_options) if self.msrp_options else None,
            "destination_charge": str(self.destination_charge)
            if self.destination_charge
            else None,
            "options_detail": {k: str(v) for k, v in self.options_detail.items()},
            "packages": self.packages,
            "exterior_color": self.exterior_color,
            "interior_color": self.interior_color,
            "standard_equipment": self.standard_equipment,
            "optional_equipment": self.optional_equipment,
            "fuel_economy_city": self.fuel_economy_city,
            "fuel_economy_highway": self.fuel_economy_highway,
            "fuel_economy_combined": self.fuel_economy_combined,
            "engine_description": self.engine_description,
            "transmission_description": self.transmission_description,
            "drivetrain": self.drivetrain,
            "wheel_specs": self.wheel_specs,
            "tire_specs": self.tire_specs,
            "warranty_powertrain": self.warranty_powertrain,
            "warranty_basic": self.warranty_basic,
            "environmental_rating_ghg": self.environmental_rating_ghg,
            "environmental_rating_smog": self.environmental_rating_smog,
            "assembly_location": self.assembly_location,
            "extracted_vin": self.extracted_vin,
            "parser_name": self.parser_name,
            "confidence_score": self.confidence_score,
        }

    def get_validation_warnings(self) -> list[str]:
        """Return list of validation warnings for the extracted data."""
        warnings = []

        # Check if base + options ≈ total
        if self.msrp_base and self.msrp_total:
            calculated_options = self.msrp_total - self.msrp_base
            if self.destination_charge:
                calculated_options -= self.destination_charge
            if self.msrp_options:
                diff = abs(calculated_options - self.msrp_options)
                if diff > Decimal("100"):
                    warnings.append(
                        f"Price mismatch: Base + Options ({self.msrp_base} + {self.msrp_options}) "
                        f"doesn't match Total ({self.msrp_total}), difference: ${diff}"
                    )

        # Check for unusually high/low MSRP
        if self.msrp_total:
            if self.msrp_total < Decimal("10000"):
                warnings.append(f"Total MSRP seems unusually low: ${self.msrp_total}")
            elif self.msrp_total > Decimal("500000"):
                warnings.append(f"Total MSRP seems unusually high: ${self.msrp_total}")

        # Check fuel economy reasonableness
        if self.fuel_economy_combined:
            if self.fuel_economy_combined < 5:
                warnings.append(
                    f"Combined MPG seems unusually low: {self.fuel_economy_combined}"
                )
            elif self.fuel_economy_combined > 150:
                warnings.append(
                    f"Combined MPG seems unusually high: {self.fuel_economy_combined}"
                )

        return warnings


class BaseWindowStickerParser(ABC):
    """Abstract base class for manufacturer-specific window sticker parsers."""

    # Override in subclasses
    MANUFACTURER_NAME: str = "Unknown"
    SUPPORTED_MAKES: list[str] = []

    # Common regex patterns
    PRICE_PATTERN = r"\$?\s*([\d,]+\.?\d*)"
    VIN_PATTERN = r"[A-HJ-NPR-Z0-9]{17}"

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def parse(self, text: str) -> WindowStickerData:
        """
        Parse window sticker text and extract structured data.

        Args:
            text: Raw text extracted from window sticker

        Returns:
            WindowStickerData with extracted fields
        """
        pass

    def _extract_price(self, text: str, patterns: list[str]) -> Optional[Decimal]:
        """Extract a price value using multiple patterns."""
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = match.group(1).replace(",", "").replace("$", "")
                    return Decimal(value)
                except (ValueError, IndexError, decimal.InvalidOperation):
                    continue
        return None

    def _extract_vin(self, text: str) -> Optional[str]:
        """Extract VIN from text."""
        # Look for VIN label first - handle VINs with dashes/spaces
        vin_patterns = [
            r"VIN[:\s]*([A-HJ-NPR-Z0-9\-–\s]{17,21})",
            r"V\.I\.N\.[:\s]*([A-HJ-NPR-Z0-9\-–\s]{17,21})",
            r"VEHICLE\s*IDENTIFICATION\s*NUMBER[:\s]*([A-HJ-NPR-Z0-9\-–\s]{17,21})",
        ]

        for pattern in vin_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Clean up the VIN - remove dashes, spaces, en-dashes
                vin = match.group(1).upper()
                vin = re.sub(r"[\-–\s]", "", vin)
                if len(vin) == 17 and re.match(r"^[A-HJ-NPR-Z0-9]{17}$", vin):
                    return vin

        # Fallback: find any 17-char alphanumeric without I, O, Q
        match = re.search(self.VIN_PATTERN, text)
        if match:
            return match.group(0).upper()

        return None

    def _extract_fuel_economy(
        self, text: str
    ) -> tuple[Optional[int], Optional[int], Optional[int]]:
        """Extract city, highway, and combined MPG."""
        city = None
        highway = None
        combined = None

        # City patterns
        city_patterns = [
            r"CITY[:\s]*(\d+)\s*MPG",
            r"(\d+)\s*MPG\s*CITY",
            r"CITY\s*(\d+)",
        ]
        for pattern in city_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                city = int(match.group(1))
                break

        # Highway patterns
        highway_patterns = [
            r"(?:HWY|HIGHWAY)[:\s]*(\d+)\s*MPG",
            r"(\d+)\s*MPG\s*(?:HWY|HIGHWAY)",
            r"HIGHWAY\s*(\d+)",
        ]
        for pattern in highway_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                highway = int(match.group(1))
                break

        # Combined patterns
        combined_patterns = [
            r"COMBINED[:\s]*(\d+)\s*MPG",
            r"(\d+)\s*MPG\s*COMBINED",
            r"COMBINED\s*(\d+)",
        ]
        for pattern in combined_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                combined = int(match.group(1))
                break

        return city, highway, combined

    def _extract_assembly_location(self, text: str) -> Optional[str]:
        """Extract assembly/manufacturing location."""
        patterns = [
            r"ASSEMBLY\s*POINT[/\s]*PORT\s*OF\s*ENTRY[:\s]*([^\n]+)",
            r"FINAL\s*ASSEMBLY\s*POINT[:\s]*([^\n]+)",
            r"ASSEMBLED\s*IN[:\s]*([^\n]+)",
            r"COUNTRY\s*OF\s*ORIGIN[:\s]*([^\n]+)",
            r"MANUFACTURED\s*(?:IN|AT)[:\s]*([^\n]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                # Clean up trailing punctuation
                location = re.sub(r"[;\.]$", "", location).strip()
                location = re.sub(r"\s+", " ", location)
                # Remove trailing codes/numbers (but not location names)
                # Only remove if it's clearly a code (uppercase letters/digits without lowercase)
                location = re.sub(r"\s+[A-Z0-9]{3,}[-–][A-Z0-9]+$", "", location)
                # Remove trailing comma if at end
                location = re.sub(r",\s*$", "", location).strip()
                if location and len(location) > 2:
                    return location[:100]

        return None

    def _extract_warranty(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract powertrain and basic warranty terms."""
        powertrain = None
        basic = None

        # Powertrain warranty
        powertrain_patterns = [
            r"(\d+)[- ]?(?:year|yr)[/ ](?:or\s*)?(\d+,?\d*)[- ]?(?:mile|mi).*?powertrain",
            r"powertrain.*?(\d+)[- ]?(?:year|yr)[/ ](?:or\s*)?(\d+,?\d*)[- ]?(?:mile|mi)",
        ]
        for pattern in powertrain_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(",", "")
                powertrain = f"{years}-year or {int(miles):,}-mile Powertrain"
                break

        # Basic warranty
        basic_patterns = [
            r"(\d+)[- ]?(?:year|yr)[/ ](?:or\s*)?(\d+,?\d*)[- ]?(?:mile|mi).*?basic",
            r"basic.*?(\d+)[- ]?(?:year|yr)[/ ](?:or\s*)?(\d+,?\d*)[- ]?(?:mile|mi)",
        ]
        for pattern in basic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(",", "")
                basic = f"{years}-year or {int(miles):,}-mile Basic"
                break

        return powertrain, basic

    def _extract_colors(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract exterior and interior colors."""
        exterior = None
        interior = None

        # Exterior color patterns
        ext_patterns = [
            r"EXTERIOR\s*COLOR[:\s]*([^\n]+?)(?:INTERIOR|$|\n)",
            r"EXT(?:ERIOR)?\.?\s*COLOR[:\s]*([^\n]+)",
            r"EXTERIOR[:\s]*([^\n]+?)(?:INTERIOR|$|\n)",
        ]
        for pattern in ext_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                color = match.group(1).strip()
                color = re.sub(r"[,;\.]$", "", color).strip()
                if color and len(color) > 2:
                    exterior = color[:100]
                    break

        # Interior color patterns
        int_patterns = [
            r"INTERIOR\s*COLOR[:\s]*([^\n]+)",
            r"INT(?:ERIOR)?\.?\s*COLOR[:\s]*([^\n]+)",
            r"INTERIOR[:\s]*([^\n]+?)(?:ENGINE|TRANS|$|\n)",
        ]
        for pattern in int_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                color = match.group(1).strip()
                color = re.sub(r"[,;\.]$", "", color).strip()
                if color and len(color) > 2:
                    interior = color[:100]
                    break

        return exterior, interior

    def _extract_engine_transmission(
        self, text: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract engine and transmission descriptions."""
        engine = None
        transmission = None

        # Engine patterns
        engine_patterns = [
            r"ENGINE[:\s]*([^\n]+?)(?:TRANSMISSION|TRANS\.|$|\n)",
            r"(\d+\.?\d*L?\s*[VI]\d+[^\n]*(?:TURBO|DIESEL|HYBRID)?[^\n]*)",
        ]
        for pattern in engine_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                eng = match.group(1).strip()
                eng = re.sub(r"[,;\.]$", "", eng).strip()
                if eng and len(eng) > 3:
                    engine = eng[:150]
                    break

        # Transmission patterns
        trans_patterns = [
            r"TRANSMISSION[:\s]*([^\n]+)",
            r"TRANS\.[:\s]*([^\n]+)",
            r"(\d+)[- ]?SPEED\s*(?:AUTO|MANUAL|CVT)[^\n]*",
        ]
        for pattern in trans_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                trans = (
                    match.group(1).strip()
                    if match.lastindex
                    else match.group(0).strip()
                )
                trans = re.sub(r"[,;\.]$", "", trans).strip()
                if trans and len(trans) > 3:
                    transmission = trans[:150]
                    break

        return engine, transmission

    def _extract_wheel_tire_specs(
        self, text: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract wheel and tire specifications."""
        wheels = None
        tires = None

        # Wheel patterns
        wheel_patterns = [
            r'(\d+["\']?\s*[xX]\s*\d+\.?\d*["\']?\s*(?:INCH|IN\.?)?\s*[^\n]*(?:WHEEL|ALLOY|ALUM)[^\n]*)',
            r"(\d+[- ]?INCH[^\n]*(?:WHEEL|ALLOY|ALUM)[^\n]*)",
        ]
        for pattern in wheel_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                wheels = match.group(1).strip()[:100]
                break

        # Tire patterns
        tire_patterns = [
            r"((?:LT|P)?\d{3}/\d{2}[RZ]\d{2}[A-Z]?\s*[^\n]*(?:TIRE|ALL[- ]?SEASON|ALL[- ]?TERRAIN)?[^\n]*)",
            r"((?:LT|P)?\d{3}/\d{2}[RZ]\d{2})",
        ]
        for pattern in tire_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                tires = match.group(1).strip()[:100]
                break

        return wheels, tires

    def _calculate_confidence(self, data: WindowStickerData) -> float:
        """Calculate confidence score based on extracted fields."""
        score = 0.0
        max_score = 100.0

        # Pricing fields (40 points)
        if data.msrp_base:
            score += 15
        if data.msrp_total:
            score += 15
        if data.destination_charge:
            score += 5
        if data.options_detail:
            score += 5

        # Equipment (20 points)
        if data.standard_equipment:
            score += 10
        if data.optional_equipment:
            score += 10

        # Vehicle details (20 points)
        if data.exterior_color:
            score += 5
        if data.interior_color:
            score += 5
        if data.engine_description:
            score += 5
        if data.transmission_description:
            score += 5

        # Other fields (20 points)
        if data.assembly_location:
            score += 5
        if data.extracted_vin:
            score += 5
        if data.warranty_powertrain or data.warranty_basic:
            score += 5
        if data.fuel_economy_city or data.fuel_economy_highway:
            score += 5

        return (score / max_score) * 100


# Import decimal module for InvalidOperation exception
import decimal
