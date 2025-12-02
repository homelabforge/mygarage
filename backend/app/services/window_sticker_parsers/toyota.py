"""Toyota/Lexus window sticker parser."""

import re
from decimal import Decimal
from typing import Optional

from .base import BaseWindowStickerParser, WindowStickerData


class ToyotaWindowStickerParser(BaseWindowStickerParser):
    """Parser for Toyota and Lexus vehicles."""

    MANUFACTURER_NAME = "Toyota"
    SUPPORTED_MAKES = ["Toyota", "Lexus", "Scion"]

    def parse(self, text: str) -> WindowStickerData:
        """Parse Toyota/Lexus window sticker text."""
        data = WindowStickerData()
        data.parser_name = self.__class__.__name__
        data.raw_text = text

        text_upper = text.upper()

        # Extract VIN
        data.extracted_vin = self._extract_vin(text)

        # Extract pricing
        self._extract_toyota_pricing(text_upper, data)

        # Extract colors
        data.exterior_color, data.interior_color = self._extract_toyota_colors(text)

        # Extract engine and transmission
        data.engine_description, data.transmission_description = self._extract_engine_transmission(text_upper)

        # Extract equipment
        self._extract_toyota_equipment(text, data)

        # Extract wheel/tire specs
        data.wheel_specs, data.tire_specs = self._extract_wheel_tire_specs(text_upper)

        # Extract assembly location
        data.assembly_location = self._extract_assembly_location(text_upper)

        # Extract warranty
        data.warranty_powertrain, data.warranty_basic = self._extract_toyota_warranty(text)

        # Extract fuel economy
        city, highway, combined = self._extract_fuel_economy(text_upper)
        data.fuel_economy_city = city
        data.fuel_economy_highway = highway
        data.fuel_economy_combined = combined

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        return data

    def _extract_toyota_pricing(self, text: str, data: WindowStickerData) -> None:
        """Extract pricing from Toyota sticker format."""

        # Toyota uses "BASE MSRP" or "BASE VEHICLE PRICE"
        base_patterns = [
            r'BASE\s*(?:MSRP|VEHICLE\s*PRICE)[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'BASE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.msrp_base = self._extract_price(text, base_patterns)

        # Toyota uses "TOTAL MSRP" or "TOTAL VEHICLE PRICE"
        total_patterns = [
            r'TOTAL\s*(?:MSRP|VEHICLE\s*PRICE)[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'TOTAL\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'MANUFACTURER[\'S]?\s*SUGGESTED\s*RETAIL\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.msrp_total = self._extract_price(text, total_patterns)

        # Destination/Delivery charge
        dest_patterns = [
            r'DELIVERY[,\s]*PROCESSING\s*(?:AND\s*)?HANDLING[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'DESTINATION\s*(?:CHARGE)?[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.destination_charge = self._extract_price(text, dest_patterns)

        # Extract individual options
        self._extract_toyota_options(text, data)

        # Calculate options
        if data.msrp_base and data.msrp_total:
            options = data.msrp_total - data.msrp_base
            if data.destination_charge:
                options -= data.destination_charge
            data.msrp_options = options

    def _extract_toyota_options(self, text: str, data: WindowStickerData) -> None:
        """Extract individual options with prices from Toyota sticker."""
        # Toyota format varies but typically lists options with prices
        option_patterns = [
            r'([A-Za-z][A-Za-z0-9\s\-/®™]+?)\s+\$\s*([\d,]+)',
        ]

        for pattern in option_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                price_str = match.group(2).replace(',', '')

                # Clean and validate
                name = re.sub(r'\s+', ' ', name).strip()
                if len(name) < 3 or len(name) > 100:
                    continue

                # Skip common non-option text
                skip_words = ['TOTAL', 'BASE', 'MSRP', 'PRICE', 'DELIVERY', 'DESTINATION']
                if any(word in name.upper() for word in skip_words):
                    continue

                try:
                    price = Decimal(price_str)
                    if 50 < price < 50000:  # Reasonable option price range
                        data.options_detail[name] = price
                except (ValueError, Exception):
                    continue

    def _extract_toyota_colors(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract colors from Toyota sticker."""
        exterior = None
        interior = None

        # Toyota color formats
        ext_patterns = [
            r'EXTERIOR\s*(?:COLOR)?[:\s]*([A-Za-z][A-Za-z0-9\s\-]+?)(?:\s*\(|\s*INTERIOR|$|\n)',
            r'EXT\.?\s*COLOR[:\s]*([^\n]+)',
        ]
        for pattern in ext_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                exterior = match.group(1).strip()[:100]
                break

        int_patterns = [
            r'INTERIOR\s*(?:COLOR)?[:\s]*([A-Za-z][A-Za-z0-9\s\-/]+?)(?:\s*ENGINE|\s*TRANS|$|\n)',
            r'INT\.?\s*COLOR[:\s]*([^\n]+)',
        ]
        for pattern in int_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                interior = match.group(1).strip()[:100]
                break

        return exterior, interior

    def _extract_toyota_equipment(self, text: str, data: WindowStickerData) -> None:
        """Extract equipment from Toyota sticker."""
        # Standard equipment
        std_match = re.search(
            r'STANDARD\s*(?:EQUIPMENT|FEATURES)(.*?)(?:OPTIONAL|ACCESSORIES|TOTAL|$)',
            text,
            re.DOTALL | re.IGNORECASE
        )
        if std_match:
            items = [
                line.strip() for line in std_match.group(1).split('\n')
                if line.strip() and len(line.strip()) > 5 and not re.match(r'^\$', line.strip())
            ]
            data.standard_equipment = items[:100]

        # Optional equipment
        opt_match = re.search(
            r'OPTIONAL\s*(?:EQUIPMENT|ACCESSORIES)(.*?)(?:TOTAL|DESTINATION|WARRANTY|$)',
            text,
            re.DOTALL | re.IGNORECASE
        )
        if opt_match:
            items = []
            for line in opt_match.group(1).split('\n'):
                line = re.sub(r'\s+\$[\d,]+\.?\d*$', '', line.strip())
                if line and len(line) > 5:
                    items.append(line)
            data.optional_equipment = items[:100]

    def _extract_toyota_warranty(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract warranty from Toyota sticker."""
        powertrain = None
        basic = None

        # Toyota specific warranty patterns
        # Typically 5-year/60,000-mile powertrain, 3-year/36,000-mile basic
        pt_match = re.search(r'(\d+)[- ]?(?:YEAR|YR)[/ ](\d+,?\d*)[- ]?(?:MILE|MI).*?POWERTRAIN', text, re.IGNORECASE)
        if pt_match:
            years = pt_match.group(1)
            miles = pt_match.group(2).replace(',', '')
            powertrain = f"{years}-year or {int(miles):,}-mile Powertrain"

        basic_match = re.search(r'(\d+)[- ]?(?:YEAR|YR)[/ ](\d+,?\d*)[- ]?(?:MILE|MI).*?(?:BASIC|BUMPER)', text, re.IGNORECASE)
        if basic_match:
            years = basic_match.group(1)
            miles = basic_match.group(2).replace(',', '')
            basic = f"{years}-year or {int(miles):,}-mile Basic"

        return powertrain, basic
