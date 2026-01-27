"""Generic window sticker parser for unknown manufacturers."""

import re
from decimal import Decimal

from .base import BaseWindowStickerParser, WindowStickerData


class GenericWindowStickerParser(BaseWindowStickerParser):
    """Generic parser that works with any manufacturer's window sticker."""

    MANUFACTURER_NAME = "Generic"
    SUPPORTED_MAKES = []  # Fallback for all unknown makes

    def parse(self, text: str) -> WindowStickerData:
        """Parse window sticker text using generic patterns."""
        data = WindowStickerData()
        data.parser_name = self.__class__.__name__
        data.raw_text = text

        text_upper = text.upper()

        # Extract VIN
        data.extracted_vin = self._extract_vin(text)

        # Extract pricing using generic patterns
        self._extract_generic_pricing(text_upper, data)

        # Extract colors
        data.exterior_color, data.interior_color = self._extract_colors(text_upper)

        # Extract engine and transmission
        data.engine_description, data.transmission_description = (
            self._extract_engine_transmission(text_upper)
        )

        # Extract equipment
        self._extract_generic_equipment(text, data)

        # Extract wheel/tire specs
        data.wheel_specs, data.tire_specs = self._extract_wheel_tire_specs(text_upper)

        # Extract assembly location
        data.assembly_location = self._extract_assembly_location(text_upper)

        # Extract warranty
        data.warranty_powertrain, data.warranty_basic = self._extract_warranty(text)

        # Extract fuel economy
        city, highway, combined = self._extract_fuel_economy(text_upper)
        data.fuel_economy_city = city
        data.fuel_economy_highway = highway
        data.fuel_economy_combined = combined

        # Calculate confidence (generic parser gets lower base confidence)
        data.confidence_score = (
            self._calculate_confidence(data) * 0.85
        )  # 15% penalty for generic

        return data

    def _extract_generic_pricing(self, text: str, data: WindowStickerData) -> None:
        """Extract pricing using multiple generic patterns."""

        # Try various base price patterns
        base_patterns = [
            r"BASE\s*(?:MSRP|PRICE|VEHICLE)[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"MANUFACTURER[\'S]?\s*SUGGESTED\s*RETAIL\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"MSRP[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"VEHICLE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"STARTING\s*(?:PRICE|MSRP)[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        data.msrp_base = self._extract_price(text, base_patterns)

        # Try various total price patterns
        total_patterns = [
            r"TOTAL\s*(?:MSRP|PRICE|VEHICLE\s*PRICE)[:\s]*\*?\s*\$?\s*([\d,]+\.?\d*)",
            r"TOTAL[:\s]*\*?\s*\$?\s*([\d,]+\.?\d*)",
            r"FINAL\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"AS\s*CONFIGURED[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        data.msrp_total = self._extract_price(text, total_patterns)

        # Destination/delivery charge
        dest_patterns = [
            r"DESTINATION\s*(?:AND\s*)?(?:DELIVERY)?[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"DELIVERY[,\s]*PROCESSING[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"FREIGHT[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"DESTINATION\s*CHARGE[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        data.destination_charge = self._extract_price(text, dest_patterns)

        # Extract individual options with prices
        self._extract_generic_options(text, data)

        # Calculate options total
        if data.msrp_base and data.msrp_total:
            options = data.msrp_total - data.msrp_base
            if data.destination_charge:
                options -= data.destination_charge
            data.msrp_options = options

    def _extract_generic_options(self, text: str, data: WindowStickerData) -> None:
        """Extract options with prices using generic patterns."""
        # Look for patterns like "Option Name $X,XXX" or "Option Name........$X,XXX"
        patterns = [
            r"([A-Za-z][A-Za-z0-9\s\-/®™\.]+?)\s+\$\s*([\d,]+\.?\d*)",
            r"([A-Za-z][A-Za-z0-9\s\-/®™]+?)\.+\s*\$\s*([\d,]+\.?\d*)",
        ]

        # Words/phrases to skip
        skip_patterns = [
            "TOTAL",
            "BASE",
            "MSRP",
            "PRICE",
            "DESTINATION",
            "DELIVERY",
            "FREIGHT",
            "SUGGESTED",
            "RETAIL",
            "MANUFACTURER",
            "WARRANTY",
            "ASSEMBLED",
            "COUNTRY",
            "ORIGIN",
            "FINAL",
            "VIN",
            "MODEL",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                price_str = match.group(2).replace(",", "")

                # Clean up name
                name = re.sub(r"\s+", " ", name).strip()
                name = re.sub(r"\.+$", "", name).strip()

                if len(name) < 3 or len(name) > 100:
                    continue

                # Skip if name contains skip words
                name_upper = name.upper()
                if any(word in name_upper for word in skip_patterns):
                    continue

                try:
                    price = Decimal(price_str)
                    # Reasonable option price range
                    if 25 < price < 50000:
                        data.options_detail[name] = price
                except (ValueError, Exception):
                    continue

    def _extract_generic_equipment(self, text: str, data: WindowStickerData) -> None:
        """Extract equipment lists using generic patterns."""

        # Standard equipment section
        std_patterns = [
            r"STANDARD\s*(?:EQUIPMENT|FEATURES)\s*(.*?)(?:OPTIONAL|OPTIONS|ACCESSORIES|AVAILABLE|PACKAGE|TOTAL|PRICE|$)",
            r"INCLUDED\s*(?:EQUIPMENT|FEATURES)\s*(.*?)(?:OPTIONAL|OPTIONS|AVAILABLE|PACKAGE|$)",
        ]

        for pattern in std_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                section = match.group(1)
                items = self._parse_equipment_section(section)
                if items:
                    data.standard_equipment = items
                    break

        # Optional equipment section
        opt_patterns = [
            r"OPTIONAL\s*(?:EQUIPMENT|FEATURES|PACKAGES?)\s*(.*?)(?:TOTAL|DESTINATION|WARRANTY|STANDARD|$)",
            r"(?:AVAILABLE|ADDED)\s*(?:EQUIPMENT|OPTIONS|FEATURES)\s*(.*?)(?:TOTAL|DESTINATION|WARRANTY|$)",
            r"OPTIONS?\s*(.*?)(?:TOTAL|DESTINATION|WARRANTY|$)",
        ]

        for pattern in opt_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                section = match.group(1)
                items = self._parse_equipment_section(section)
                if items:
                    data.optional_equipment = items
                    break

    def _parse_equipment_section(self, section_text: str) -> list[str]:
        """Parse a section of text into equipment items."""
        items = []

        for line in section_text.split("\n"):
            line = line.strip()

            # Skip empty or very short lines
            if not line or len(line) < 4:
                continue

            # Skip price-only lines
            if re.match(r"^[\$\d,\.]+$", line):
                continue

            # Skip header-like lines
            if re.match(
                r"^(STANDARD|OPTIONAL|EQUIPMENT|FEATURES|SAFETY|INTERIOR|EXTERIOR|MECHANICAL)",
                line,
                re.IGNORECASE,
            ):
                continue

            # Remove price at end if present
            line = re.sub(r"\s+\$[\d,]+\.?\d*$", "", line)

            # Remove leading bullets/dashes
            line = re.sub(r"^[\-–•*]\s*", "", line)

            if line and len(line) > 4:
                items.append(line)

        return items[:100]  # Limit to 100 items

    def _extract_price(self, text: str, patterns: list[str]) -> Decimal | None:
        """Override to be more lenient with price extraction."""
        for pattern in patterns:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            for match in matches:
                try:
                    value = match.group(1).replace(",", "").replace("$", "")
                    price = Decimal(value)
                    # Validate it's a reasonable vehicle price
                    if 1000 < price < 1000000:
                        return price
                except (ValueError, IndexError, Exception):
                    continue
        return None
