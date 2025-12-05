"""Tesla window sticker parser."""

import re
from decimal import Decimal
from typing import Optional

from .base import BaseWindowStickerParser, WindowStickerData


class TeslaWindowStickerParser(BaseWindowStickerParser):
    """Parser for Tesla vehicles - handles electronic Monroney format."""

    MANUFACTURER_NAME = "Tesla"
    SUPPORTED_MAKES = ["Tesla"]

    def parse(self, text: str) -> WindowStickerData:
        """Parse Tesla window sticker/order sheet text."""
        data = WindowStickerData()
        data.parser_name = self.__class__.__name__
        data.raw_text = text

        text_upper = text.upper()

        # Extract VIN
        data.extracted_vin = self._extract_vin(text)

        # Extract pricing
        self._extract_tesla_pricing(text_upper, data)

        # Extract colors (Tesla has specific color names)
        data.exterior_color, data.interior_color = self._extract_tesla_colors(text)

        # Extract configuration/features (Tesla doesn't have traditional engine)
        self._extract_tesla_config(text, data)

        # Extract wheel specs
        data.wheel_specs, data.tire_specs = self._extract_tesla_wheels(text)

        # Extract assembly location
        data.assembly_location = self._extract_tesla_assembly(text_upper)

        # Extract warranty
        data.warranty_powertrain, data.warranty_basic = self._extract_tesla_warranty(text)

        # Tesla EVs have range instead of MPG - store combined as MPGe if available
        self._extract_tesla_efficiency(text_upper, data)

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        return data

    def _extract_tesla_pricing(self, text: str, data: WindowStickerData) -> None:
        """Extract pricing from Tesla sticker/order sheet."""

        # Tesla base price patterns
        base_patterns = [
            r'(?:MODEL\s*[3SXY]|CYBERTRUCK)\s*(?:LONG\s*RANGE|STANDARD|PERFORMANCE|PLAID)?[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'BASE\s*(?:PRICE|VEHICLE)[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'VEHICLE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.msrp_base = self._extract_price(text, base_patterns)

        # Total price
        total_patterns = [
            r'TOTAL\s*(?:PRICE|DUE)[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'PURCHASE\s*PRICE[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'ORDER\s*TOTAL[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.msrp_total = self._extract_price(text, total_patterns)

        # Destination/delivery charge
        dest_patterns = [
            r'DESTINATION\s*(?:AND\s*)?(?:DOC(?:UMENTATION)?)?\s*(?:FEE)?[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'DELIVERY\s*(?:FEE)?[:\s]*\$?\s*([\d,]+\.?\d*)',
            r'ORDER\s*FEE[:\s]*\$?\s*([\d,]+\.?\d*)',
        ]
        data.destination_charge = self._extract_price(text, dest_patterns)

        # Extract individual options (Autopilot, FSD, colors, wheels, etc.)
        self._extract_tesla_options(text, data)

        # Calculate options
        if data.msrp_base and data.msrp_total:
            options = data.msrp_total - data.msrp_base
            if data.destination_charge:
                options -= data.destination_charge
            data.msrp_options = options

    def _extract_tesla_options(self, text: str, data: WindowStickerData) -> None:
        """Extract Tesla options with prices."""
        # Tesla specific options
        tesla_options = [
            (r'(?:FULL\s*SELF[- ]?DRIVING|FSD)\s*(?:CAPABILITY)?[:\s]*\$?\s*([\d,]+)', 'Full Self-Driving'),
            (r'(?:ENHANCED\s*)?AUTOPILOT[:\s]*\$?\s*([\d,]+)', 'Autopilot'),
            (r'(?:PREMIUM\s*)?(?:INTERIOR|UPGRADE)[:\s]*\$?\s*([\d,]+)', 'Premium Interior'),
            (r'(?:PAINT|COLOR)[:\s]*([A-Za-z\s]+)\s*\$?\s*([\d,]+)', None),  # Color with price
            (r'(\d+["\']?\s*(?:INCH|IN)?\s*WHEELS?)[:\s]*\$?\s*([\d,]+)', None),  # Wheels
            (r'TOW\s*(?:HITCH|PACKAGE)[:\s]*\$?\s*([\d,]+)', 'Tow Hitch'),
            (r'ACCELERATION\s*BOOST[:\s]*\$?\s*([\d,]+)', 'Acceleration Boost'),
        ]

        for pattern_info in tesla_options:
            pattern = pattern_info[0]
            default_name = pattern_info[1] if len(pattern_info) > 1 else None

            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    # Just price
                    try:
                        price = Decimal(groups[0].replace(',', ''))
                        if default_name and price > 0:
                            data.options_detail[default_name] = price
                    except (ValueError, Exception):
                        pass  # Skip malformed price data - OCR extraction is best-effort
                elif len(groups) == 2:
                    # Name and price
                    name = groups[0].strip() if not default_name else default_name
                    try:
                        price = Decimal(groups[1].replace(',', ''))
                        if name and price > 0:
                            data.options_detail[name] = price
                    except (ValueError, Exception):
                        pass  # Skip malformed price data - OCR extraction is best-effort

    def _extract_tesla_colors(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract Tesla color options."""
        exterior = None
        interior = None

        # Tesla exterior colors
        tesla_colors = [
            'Pearl White Multi-Coat',
            'Solid Black',
            'Midnight Silver Metallic',
            'Deep Blue Metallic',
            'Red Multi-Coat',
            'Ultra White',
            'Quicksilver',
            'Midnight Cherry Red',
        ]

        text_clean = text.replace('\n', ' ')
        for color in tesla_colors:
            if color.upper() in text_clean.upper():
                exterior = color
                break

        # Fallback pattern
        if not exterior:
            ext_match = re.search(
                r'(?:EXTERIOR|PAINT)[:\s]*([A-Za-z][A-Za-z\s\-]+?)(?:\s*\$|\s*INTERIOR|$|\n)',
                text,
                re.IGNORECASE
            )
            if ext_match:
                exterior = ext_match.group(1).strip()[:100]

        # Tesla interior options
        interior_options = [
            'All Black',
            'Black and White',
            'Cream',
            'Black',
            'White',
        ]

        for option in interior_options:
            if option.upper() in text.upper():
                interior = option
                break

        if not interior:
            int_match = re.search(
                r'INTERIOR[:\s]*([A-Za-z][A-Za-z\s\-]+?)(?:\s*\$|$|\n)',
                text,
                re.IGNORECASE
            )
            if int_match:
                interior = int_match.group(1).strip()[:100]

        return exterior, interior

    def _extract_tesla_config(self, text: str, data: WindowStickerData) -> None:
        """Extract Tesla configuration details."""
        # Battery/Range configuration (serves as "engine" equivalent)
        config_patterns = [
            r'(MODEL\s*[3SXY]\s*(?:LONG\s*RANGE|STANDARD\s*RANGE|PERFORMANCE|PLAID)?\s*(?:AWD|RWD)?)',
            r'(CYBERTRUCK\s*(?:AWD|TRI[- ]?MOTOR|CYBERBEAST)?)',
        ]

        for pattern in config_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data.engine_description = match.group(1).strip()
                break

        # Battery pack info
        battery_match = re.search(r'(\d+\.?\d*)\s*KWH\s*BATTERY', text, re.IGNORECASE)
        if battery_match:
            if data.engine_description:
                data.engine_description += f" ({battery_match.group(1)} kWh Battery)"
            else:
                data.engine_description = f"{battery_match.group(1)} kWh Battery"

        # Drivetrain
        if 'AWD' in text.upper() or 'ALL-WHEEL' in text.upper() or 'ALL WHEEL' in text.upper():
            data.drivetrain = 'All-Wheel Drive'
        elif 'RWD' in text.upper() or 'REAR-WHEEL' in text.upper() or 'REAR WHEEL' in text.upper():
            data.drivetrain = 'Rear-Wheel Drive'

        # Tesla doesn't have traditional transmission
        data.transmission_description = 'Single-Speed Direct Drive'

        # Standard and optional equipment
        std_items = []
        opt_items = []

        # Check for common Tesla features
        tesla_features = [
            ('AUTOPILOT', 'Autopilot'),
            ('FULL SELF', 'Full Self-Driving Capability'),
            ('PREMIUM CONNECTIVITY', 'Premium Connectivity'),
            ('SUPERCHARGING', 'Supercharging Access'),
            ('PREMIUM AUDIO', 'Premium Audio System'),
            ('GLASS ROOF', 'All-Glass Roof'),
            ('HEATED SEATS', 'Heated Seats'),
            ('HEATED STEERING', 'Heated Steering Wheel'),
            ('POWER LIFTGATE', 'Power Liftgate'),
        ]

        for keyword, feature_name in tesla_features:
            if keyword in text.upper():
                # Check if it's an add-on (has price) or standard
                if re.search(rf'{keyword}[:\s]*\$[\d,]+', text, re.IGNORECASE):
                    opt_items.append(feature_name)
                else:
                    std_items.append(feature_name)

        data.standard_equipment = std_items
        data.optional_equipment = opt_items

    def _extract_tesla_wheels(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract Tesla wheel configuration."""
        wheels = None
        tires = None

        # Tesla wheel patterns
        wheel_patterns = [
            r'(\d+["\']?\s*(?:INCH|IN)?\s*(?:TEMPEST|AERO|SPORT|INDUCTION|ÜBERTURBINE|CYBERWHEEL)\s*WHEELS?)',
            r'(\d+["\']?\s*WHEELS?)',
        ]

        for pattern in wheel_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                wheels = match.group(1).strip()[:100]
                break

        # Tire specs
        tire_match = re.search(r'(\d{3}/\d{2}[RZ]\d{2})', text)
        if tire_match:
            tires = tire_match.group(1)

        return wheels, tires

    def _extract_tesla_assembly(self, text: str) -> Optional[str]:
        """Extract Tesla assembly location."""
        # Tesla factories
        if 'FREMONT' in text:
            return 'Fremont, California, USA'
        elif 'AUSTIN' in text or 'TEXAS' in text:
            return 'Austin, Texas, USA'
        elif 'SHANGHAI' in text or 'CHINA' in text:
            return 'Shanghai, China'
        elif 'BERLIN' in text or 'GERMANY' in text:
            return 'Berlin, Germany'

        # Fallback to generic extraction
        return self._extract_assembly_location(text)

    def _extract_tesla_warranty(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract Tesla warranty information."""
        powertrain = None
        basic = None

        # Tesla battery/drivetrain warranty (varies by model)
        # Model 3/Y Standard: 8 years or 100,000 miles
        # Model 3/Y Long Range/Performance: 8 years or 120,000 miles
        # Model S/X: 8 years or 150,000 miles

        pt_patterns = [
            r'(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI).*?(?:BATTERY|DRIVETRAIN|POWERTRAIN)',
            r'(?:BATTERY|DRIVETRAIN).*?(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI)',
        ]
        for pattern in pt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(',', '')
                powertrain = f"{years}-year or {int(miles):,}-mile Battery & Drivetrain"
                break

        # Tesla basic warranty: 4 years or 50,000 miles
        basic_patterns = [
            r'(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI).*?(?:BASIC|VEHICLE|LIMITED)',
            r'(?:BASIC|VEHICLE|NEW\s*VEHICLE).*?(\d+)[- ]?(?:YEAR|YR)[/\s](?:OR\s*)?(\d+,?\d*)[- ]?(?:MILE|MI)',
        ]
        for pattern in basic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                years = match.group(1)
                miles = match.group(2).replace(',', '')
                basic = f"{years}-year or {int(miles):,}-mile Basic"
                break

        return powertrain, basic

    def _extract_tesla_efficiency(self, text: str, data: WindowStickerData) -> None:
        """Extract Tesla efficiency ratings (MPGe, range)."""
        # MPGe (miles per gallon equivalent)
        mpge_match = re.search(r'(\d+)\s*MPGE?\s*(?:COMBINED|CITY|HIGHWAY)?', text, re.IGNORECASE)
        if mpge_match:
            data.fuel_economy_combined = int(mpge_match.group(1))

        # EPA estimated range
        range_match = re.search(r'(\d+)\s*(?:MI(?:LE)?S?)\s*(?:RANGE|EPA)', text, re.IGNORECASE)
        if range_match:
            # Store range in packages as metadata
            data.packages['EPA Range'] = [f"{range_match.group(1)} miles"]

        # Wh/mi efficiency
        efficiency_match = re.search(r'(\d+)\s*WH/MI', text, re.IGNORECASE)
        if efficiency_match:
            data.packages['Efficiency'] = [f"{efficiency_match.group(1)} Wh/mi"]
