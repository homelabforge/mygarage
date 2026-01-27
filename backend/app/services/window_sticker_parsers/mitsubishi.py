"""Mitsubishi window sticker parser."""

import re
from decimal import Decimal

from .base import BaseWindowStickerParser, WindowStickerData


class MitsubishiWindowStickerParser(BaseWindowStickerParser):
    """Parser for Mitsubishi vehicles."""

    MANUFACTURER_NAME = "Mitsubishi"
    SUPPORTED_MAKES = ["Mitsubishi"]

    def parse(self, text: str) -> WindowStickerData:
        """Parse Mitsubishi window sticker text."""
        data = WindowStickerData()
        data.parser_name = self.__class__.__name__
        data.raw_text = text

        text_upper = text.upper()

        # Extract VIN
        data.extracted_vin = self._extract_vin(text)

        # Extract pricing
        self._extract_mitsubishi_pricing(text_upper, data)

        # Extract colors
        data.exterior_color, data.interior_color = self._extract_colors(text_upper)

        # Extract engine and transmission
        data.engine_description, data.transmission_description = (
            self._extract_engine_transmission(text_upper)
        )

        # Extract equipment
        self._extract_mitsubishi_equipment(text, data)

        # Extract wheel/tire specs
        data.wheel_specs, data.tire_specs = self._extract_wheel_tire_specs(text_upper)

        # Extract assembly location
        data.assembly_location = self._extract_assembly_location(text_upper)

        # Extract warranty - Mitsubishi has notable 10-year/100k powertrain
        data.warranty_powertrain, data.warranty_basic = (
            self._extract_mitsubishi_warranty(text)
        )

        # Extract fuel economy
        city, highway, combined = self._extract_fuel_economy(text_upper)
        data.fuel_economy_city = city
        data.fuel_economy_highway = highway
        data.fuel_economy_combined = combined

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        return data

    def _extract_mitsubishi_pricing(self, text: str, data: WindowStickerData) -> None:
        """Extract pricing from Mitsubishi sticker format."""

        # Base price
        base_patterns = [
            r"BASE\s*(?:MSRP|PRICE)[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"MANUFACTURER[\'S]?\s*SUGGESTED\s*RETAIL\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        data.msrp_base = self._extract_price(text, base_patterns)

        # Total price
        total_patterns = [
            r"TOTAL\s*(?:MSRP|PRICE)[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"TOTAL\s*VEHICLE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        data.msrp_total = self._extract_price(text, total_patterns)

        # Destination charge
        dest_patterns = [
            r"DESTINATION[/\s]*(?:HANDLING)?[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"DELIVERY\s*CHARGE[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        data.destination_charge = self._extract_price(text, dest_patterns)

        # Extract individual options
        self._extract_option_prices(text, data)

        # Calculate options total
        if data.msrp_base and data.msrp_total:
            options = data.msrp_total - data.msrp_base
            if data.destination_charge:
                options -= data.destination_charge
            data.msrp_options = options

    def _extract_option_prices(self, text: str, data: WindowStickerData) -> None:
        """Extract individual options with prices."""
        # Look for option name followed by price
        pattern = r"([A-Za-z][A-Za-z0-9\s\-/®™]+?)\s+\$\s*([\d,]+)"

        for match in re.finditer(pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            price_str = match.group(2).replace(",", "")

            name = re.sub(r"\s+", " ", name).strip()
            if len(name) < 3 or len(name) > 100:
                continue

            # Skip pricing labels
            skip_words = ["TOTAL", "BASE", "MSRP", "DESTINATION", "DELIVERY", "PRICE"]
            if any(word in name.upper() for word in skip_words):
                continue

            try:
                price = Decimal(price_str)
                if 50 < price < 30000:
                    data.options_detail[name] = price
            except (ValueError, Exception):
                continue

    def _extract_mitsubishi_equipment(self, text: str, data: WindowStickerData) -> None:
        """Extract equipment lists from Mitsubishi sticker."""
        # Standard equipment
        std_match = re.search(
            r"STANDARD\s*(?:EQUIPMENT|FEATURES)(.*?)(?:OPTIONAL|ACCESSORIES|PACKAGE|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if std_match:
            items = [
                line.strip()
                for line in std_match.group(1).split("\n")
                if line.strip()
                and len(line.strip()) > 5
                and not re.match(r"^\$", line.strip())
            ]
            data.standard_equipment = items[:100]

        # Optional/Package equipment
        opt_match = re.search(
            r"(?:OPTIONAL|PACKAGE)\s*(?:EQUIPMENT)?(.*?)(?:TOTAL|DESTINATION|WARRANTY|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if opt_match:
            items = []
            for line in opt_match.group(1).split("\n"):
                line = re.sub(r"\s+\$[\d,]+\.?\d*$", "", line.strip())
                if line and len(line) > 5:
                    items.append(line)
            data.optional_equipment = items[:100]

    def _extract_mitsubishi_warranty(
        self, text: str
    ) -> tuple[str | None, str | None]:
        """Extract Mitsubishi warranty - famous for 10-year/100k powertrain."""
        powertrain = None
        basic = None

        # Mitsubishi's signature 10-year/100,000-mile powertrain warranty
        pt_patterns = [
            r"(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI).*?POWERTRAIN",
            r"POWERTRAIN.*?(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI)",
        ]
        for pattern in pt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(",", "")
                powertrain = f"{years}-year or {int(miles):,}-mile Powertrain"
                break

        # Basic warranty (typically 5-year/60,000-mile for Mitsubishi)
        basic_patterns = [
            r"(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI).*?(?:BASIC|BUMPER|LIMITED)",
            r"(?:BASIC|BUMPER|NEW\s*VEHICLE).*?(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI)",
        ]
        for pattern in basic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(",", "")
                basic = f"{years}-year or {int(miles):,}-mile Basic"
                break

        return powertrain, basic
