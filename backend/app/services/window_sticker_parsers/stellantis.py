"""Stellantis (RAM/Dodge/Chrysler/Jeep) window sticker parser."""

import re
from decimal import Decimal
from typing import Optional

from .base import BaseWindowStickerParser, WindowStickerData


class StellantisWindowStickerParser(BaseWindowStickerParser):
    """Parser for Stellantis vehicles (RAM, Dodge, Chrysler, Jeep, Fiat, Alfa Romeo)."""

    MANUFACTURER_NAME = "Stellantis"
    SUPPORTED_MAKES = ["RAM", "Dodge", "Chrysler", "Jeep", "Fiat", "Alfa Romeo"]

    def parse(self, text: str) -> WindowStickerData:
        """Parse Stellantis window sticker text."""
        data = WindowStickerData()
        data.parser_name = self.__class__.__name__
        data.raw_text = text

        # Normalize text for parsing
        text_upper = text.upper()

        # Extract VIN
        data.extracted_vin = self._extract_vin(text)

        # Extract pricing
        self._extract_pricing(text, text_upper, data)

        # Extract colors
        data.exterior_color, data.interior_color = self._extract_stellantis_colors(text)

        # Extract engine and transmission
        data.engine_description, data.transmission_description = self._extract_stellantis_powertrain(text)

        # Extract equipment
        self._extract_stellantis_equipment(text, data)

        # Extract wheel/tire specs
        data.wheel_specs, data.tire_specs = self._extract_wheel_tire_specs(text_upper)

        # Extract assembly location
        data.assembly_location = self._extract_assembly_location(text_upper)

        # Extract warranty - use Stellantis-specific patterns
        data.warranty_powertrain, data.warranty_basic = self._extract_stellantis_warranty(text)

        # Extract environmental ratings (CARB for diesel/California)
        self._extract_environmental_ratings(text_upper, data)

        # Extract fuel economy (may not be present for diesel)
        city, highway, combined = self._extract_fuel_economy(text_upper)
        data.fuel_economy_city = city
        data.fuel_economy_highway = highway
        data.fuel_economy_combined = combined

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        return data

    def _extract_pricing(self, text: str, text_upper: str, data: WindowStickerData) -> None:
        """Extract all pricing information from Stellantis sticker."""

        # Base Price - Stellantis uses "Base Price:" format
        base_patterns = [
            r'BASE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'MANUFACTURER[\'S]?\s*SUGGESTED\s*RETAIL\s*PRICE.*?BASE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.msrp_base = self._extract_price(text_upper, base_patterns)

        # Total Price - Stellantis uses "TOTAL PRICE:" format
        total_patterns = [
            r'TOTAL\s*PRICE[:\s]*\*?\s*\$?\s*([\d,]+\.?\d*)',
            r'TOTAL\s*MSRP[:\s]*\*?\s*\$?\s*([\d,]+\.?\d*)',
        ]
        data.msrp_total = self._extract_price(text_upper, total_patterns)

        # Destination Charge
        dest_patterns = [
            r'DESTINATION\s*CHARGE[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'DESTINATION[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.destination_charge = self._extract_price(text_upper, dest_patterns)

        # Extract individual options with prices
        self._extract_option_prices(text, data)

        # Calculate options total
        if data.msrp_base and data.msrp_total:
            options_total = data.msrp_total - data.msrp_base
            if data.destination_charge:
                options_total -= data.destination_charge
            data.msrp_options = options_total

    def _extract_option_prices(self, text: str, data: WindowStickerData) -> None:
        """Extract individual optional equipment with prices."""
        # Stellantis format: "Option Name $X,XXX" or "Option Name    $X,XXX"
        # Look for section between OPTIONAL EQUIPMENT and DESTINATION/TOTAL

        optional_section = re.search(
            r'OPTIONAL\s*EQUIPMENT.*?(?=DESTINATION|TOTAL\s*PRICE|WARRANTY)',
            text,
            re.DOTALL | re.IGNORECASE
        )

        if optional_section:
            section_text = optional_section.group(0)

            # Pattern for "Item Name $X,XXX" on same line or nearby
            # Handle multi-line items like package groups
            # Allow items starting with digits (e.g., "6.7L I6 Cummins...")
            price_pattern = r'([A-Za-z0-9][A-Za-z0-9\s\.\-–/®™&]+?)\s+\$\s*([\d,]+\.?\d*)'

            for match in re.finditer(price_pattern, section_text):
                item_name = match.group(1).strip()
                price_str = match.group(2).replace(',', '')

                # Clean up item name
                item_name = re.sub(r'\s+', ' ', item_name).strip()

                # Skip if name is too short or just noise
                if len(item_name) < 3 or item_name.upper() in ['THE', 'AND', 'FOR', 'WITH']:
                    continue

                try:
                    price = Decimal(price_str)
                    if price > 0:  # Only include positive prices
                        data.options_detail[item_name] = price
                except (ValueError, decimal.InvalidOperation):
                    continue

        # Also extract package contents
        self._extract_package_contents(text, data)

    def _extract_package_contents(self, text: str, data: WindowStickerData) -> None:
        """Extract what's included in each package/group."""
        # Stellantis groups options under headers like "Night Edition" or "Tow Technology Plus Group"
        # Skip complex regex matching - parse line by line instead for reliability
        pass  # Package content extraction disabled for performance

    def _extract_stellantis_colors(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract colors from Stellantis sticker format."""
        exterior = None
        interior = None

        # Stellantis uses "Exterior Color: Diamond Black Crystal Pearl–Coat Exterior Paint"
        ext_match = re.search(
            r'EXTERIOR\s*COLOR[:\s]*([^\n]+?)(?:EXTERIOR\s*PAINT|INTERIOR|$|\n)',
            text,
            re.IGNORECASE
        )
        if ext_match:
            exterior = ext_match.group(1).strip()
            # Remove trailing "Exterior Paint" if present
            exterior = re.sub(r'\s*(?:–|-)\s*Coat\s*Exterior\s*Paint$', '', exterior, flags=re.IGNORECASE)
            exterior = exterior.strip()[:100] if exterior else None

        # Interior Color
        int_match = re.search(
            r'INTERIOR\s*COLOR[:\s]*([^\n]+?)(?:INTERIOR[:\s]*|ENGINE|$|\n)',
            text,
            re.IGNORECASE
        )
        if int_match:
            interior = int_match.group(1).strip()
            interior = interior.strip()[:100] if interior else None

        # Also try "Interior:" format
        if not interior:
            int_match2 = re.search(
                r'INTERIOR[:\s]*([A-Za-z][^\n]+?)(?:ENGINE|TRANS|SEATS|$|\n)',
                text,
                re.IGNORECASE
            )
            if int_match2:
                interior = int_match2.group(1).strip()[:100]

        return exterior, interior

    def _extract_stellantis_powertrain(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract engine and transmission from Stellantis sticker."""
        engine = None
        transmission = None

        # Engine - Stellantis format: "Engine: 6.7L I6 Cummins HO Turbo Diesel Engine"
        engine_match = re.search(
            r'ENGINE[:\s]*([^\n]+?)(?:TRANSMISSION|TRANS[:\s]|$|\n)',
            text,
            re.IGNORECASE
        )
        if engine_match:
            engine = engine_match.group(1).strip()
            # Clean up trailing "Engine" word if duplicated
            engine = re.sub(r'\s+Engine$', '', engine, flags=re.IGNORECASE)
            engine = engine.strip()[:150] if engine else None

        # Transmission - Stellantis format: "Transmission: 8–Speed TorqueFlite HD Automatic Transmission"
        trans_match = re.search(
            r'TRANSMISSION[:\s]*([^\n]+?)(?:STANDARD|OPTIONAL|$|\n)',
            text,
            re.IGNORECASE
        )
        if trans_match:
            transmission = trans_match.group(1).strip()
            # Clean up trailing "Transmission" word if duplicated
            transmission = re.sub(r'\s+Transmission$', '', transmission, flags=re.IGNORECASE)
            transmission = transmission.strip()[:150] if transmission else None

        return engine, transmission

    def _extract_stellantis_equipment(self, text: str, data: WindowStickerData) -> None:
        """Extract standard and optional equipment lists using line-by-line parsing."""
        lines = text.split('\n')

        in_standard = False
        in_optional = False
        standard_items = []
        optional_items = []

        # Get option names from options_detail to filter out from standard equipment
        # Stellantis OCR sometimes includes option package details in what looks like standard section
        option_keywords = set()
        if data.options_detail:
            for option_name in data.options_detail.keys():
                # Extract significant words from option names for matching
                # e.g., "Night Edition" -> {"night", "edition"}
                words = re.findall(r'[A-Za-z]{4,}', option_name.lower())
                option_keywords.update(words)

        for line in lines:
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            # Detect section boundaries
            if 'STANDARD' in line_upper and 'EQUIPMENT' in line_upper:
                in_standard = True
                in_optional = False
                continue
            elif 'OPTIONAL' in line_upper and 'EQUIPMENT' in line_upper:
                in_standard = False
                in_optional = True
                continue
            elif any(x in line_upper for x in ['DESTINATION', 'WARRANTY', 'TOTAL PRICE']):
                in_standard = False
                in_optional = False
                continue

            # Skip headers and empty lines
            if not line_stripped or len(line_stripped) < 5:
                continue
            if any(x in line_upper for x in ['FEATURES', 'FUNCTIONAL', 'SAFETY', 'INTERIOR', 'EXTERIOR']):
                continue
            if line_stripped.startswith('$'):
                continue

            # Collect items
            if in_standard:
                # Check if this item is actually an optional package component
                # by seeing if it matches keywords from options_detail
                line_words = set(re.findall(r'[A-Za-z]{4,}', line_stripped.lower()))
                common_words = line_words & option_keywords
                # If 2+ significant words match an option, it's probably part of optional equipment
                if len(common_words) >= 2:
                    optional_items.append(line_stripped)
                else:
                    standard_items.append(line_stripped)
            elif in_optional:
                # Remove trailing price if present
                clean_line = re.sub(r'\s+\$[\d,]+\.?\d*$', '', line_stripped)
                if clean_line and len(clean_line) > 3:
                    optional_items.append(clean_line)

        data.standard_equipment = standard_items[:100]
        data.optional_equipment = optional_items[:100]

    def _extract_environmental_ratings(self, text: str, data: WindowStickerData) -> None:
        """Extract CARB environmental ratings (California vehicles)."""
        # CARB label OCR output format (from actual Stellantis window stickers):
        #
        # The OCR extracts the visual CARB label which shows:
        # - Two rating scales (GHG and Smog), each from A+ (best) to D (worst)
        # - The actual vehicle ratings appear BETWEEN scale markers
        #
        # Typical OCR output pattern:
        #   A+           <- scale top marker
        #   D            <- scale bottom marker
        #   Cleaner
        #   B            <- scale marker
        #   C+           <- ACTUAL GHG RATING (not A+ or D)
        #   A+           <- scale top marker (smog column)
        #   D            <- scale bottom marker
        #   CleanerB
        #   B+           <- ACTUAL SMOG RATING
        #
        # Strategy: Find CARB section, collect all ratings, skip the scale endpoint
        # markers (A+, D which appear first), and take the B/B+/C/C+ values

        # Find the CARB/environmental section
        carb_match = re.search(
            r'(California\s*Air\s*Resources|Environmental\s*Performance|'
            r'Greenhouse\s*Gas\s*Rating)',
            text, re.IGNORECASE
        )

        if carb_match:
            # Get text from CARB section onwards
            carb_text = text[carb_match.start():]

            # Find all standalone rating values (A+, A, B+, B, C+, C, D)
            # that appear on their own line or surrounded by whitespace
            rating_pattern = r'(?:^|\s)([A-D]\+?)(?:\s|$)'
            all_ratings = re.findall(rating_pattern, carb_text, re.MULTILINE)

            # The CARB label visual scale shows A+ and D as endpoints
            # The actual ratings (B, B+, C, C+) appear after these scale markers
            # We need to skip the scale markers and find the actual ratings
            #
            # Pattern: A+ D [markers] C+ A+ D [markers] B+
            # Skip first 4-5 entries (scale markers), look for middle values

            # Filter: Find ratings that are B, B+, C, or C+ (actual ratings, not scale endpoints)
            middle_ratings = [r.upper() for r in all_ratings if r.upper() in ('B', 'B+', 'C', 'C+')]

            # Key insight from OCR analysis:
            # - Plain 'B' often appears as a scale marker BEFORE the actual ratings
            # - Actual vehicle ratings typically have '+' suffix (B+, C+)
            # - Pattern: A+ D B(scale) C+(GHG) A+ D B+(Smog)
            #
            # Strategy: Prefer ratings with '+' suffix over plain letters
            # If we have: ['B', 'C+', 'B+'], we want C+ and B+, not B and C+

            # Separate ratings with and without '+' suffix
            plus_ratings = [r for r in middle_ratings if '+' in r]  # B+, C+
            plain_ratings = [r for r in middle_ratings if '+' not in r]  # B, C

            if len(plus_ratings) >= 2:
                # Best case: two ratings with '+' suffix
                data.environmental_rating_ghg = plus_ratings[0]
                data.environmental_rating_smog = plus_ratings[1]
            elif len(plus_ratings) == 1 and len(plain_ratings) >= 1:
                # One '+' rating and one plain - the '+' rating comes from actual vehicle
                # Check position: if plain appears before '+', skip the plain one
                plus_idx = middle_ratings.index(plus_ratings[0])
                plain_before_plus = [r for r in plain_ratings if middle_ratings.index(r) < plus_idx]

                if plain_before_plus:
                    # Plain rating before '+' is likely a scale marker - use '+' ratings only
                    # Or look for second '+' rating after
                    remaining = [r for r in middle_ratings[plus_idx+1:] if r in ('B', 'B+', 'C', 'C+')]
                    if remaining:
                        data.environmental_rating_ghg = plus_ratings[0]
                        data.environmental_rating_smog = remaining[0]
                    else:
                        # Just use what we have
                        data.environmental_rating_ghg = plus_ratings[0]
                else:
                    # Plain appears after '+', both are real ratings
                    data.environmental_rating_ghg = middle_ratings[0]
                    data.environmental_rating_smog = middle_ratings[1]
            elif len(middle_ratings) >= 2:
                # Fallback: use first two middle ratings
                data.environmental_rating_ghg = middle_ratings[0]
                data.environmental_rating_smog = middle_ratings[1]
            elif len(middle_ratings) == 1:
                # Only one found - likely GHG
                data.environmental_rating_ghg = middle_ratings[0]

        # Fallback if above didn't work
        if data.environmental_rating_ghg is None or data.environmental_rating_smog is None:
            # Try simple pattern matching for B/B+/C/C+ near rating keywords
            if data.environmental_rating_ghg is None:
                ghg_match = re.search(r'Greenhouse.*?([BC]\+?)', text, re.IGNORECASE | re.DOTALL)
                if ghg_match:
                    data.environmental_rating_ghg = ghg_match.group(1).upper()

            if data.environmental_rating_smog is None:
                # Look for B+ after the GHG rating or "Smog" keyword
                smog_section = re.search(r'Smog.*?Rating.*?$(.{0,200})', text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
                if smog_section:
                    smog_match = re.search(r'([BC]\+?)', smog_section.group(1))
                    if smog_match:
                        data.environmental_rating_smog = smog_match.group(1).upper()

    def _extract_stellantis_warranty(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract warranty from Stellantis sticker - handles their specific format."""
        powertrain = None
        basic = None

        # Stellantis format: "5–year or 100,000–mile Powertrain Limited Warranty"
        # Note the en-dash (–) vs hyphen (-)
        pt_patterns = [
            r'(\d+)[–\-]year\s*(?:or\s*)?(\d+,?\d*)[–\-]mile\s*Powertrain',
            r'Powertrain.*?(\d+)[–\-]year\s*(?:or\s*)?(\d+,?\d*)[–\-]mile',
        ]
        for pattern in pt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(',', '')
                powertrain = f"{years}-year or {int(miles):,}-mile Powertrain"
                break

        # Stellantis format: "3–year or 36,000–mile Basic Limited Warranty"
        basic_patterns = [
            r'(\d+)[–\-]year\s*(?:or\s*)?(\d+,?\d*)[–\-]mile\s*Basic',
            r'Basic.*?(\d+)[–\-]year\s*(?:or\s*)?(\d+,?\d*)[–\-]mile',
        ]
        for pattern in basic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(',', '')
                basic = f"{years}-year or {int(miles):,}-mile Basic"
                break

        return powertrain, basic


# Import decimal for exception handling
import decimal
