"""Parser registry for manufacturer-specific window sticker parsers."""

import logging
from typing import Any, Optional, Type

from .base import BaseWindowStickerParser

logger = logging.getLogger(__name__)


# World Manufacturer Identifier (WMI) to manufacturer mapping
# First 3 characters of VIN identify the manufacturer
WMI_MAPPING: dict[str, str] = {
    # Stellantis (Chrysler/Dodge/Jeep/RAM)
    "1C3": "Stellantis",
    "1C4": "Stellantis",
    "1C6": "Stellantis",
    "1D3": "Stellantis",
    "1D4": "Stellantis",
    "1D7": "Stellantis",
    "1D8": "Stellantis",
    "1J4": "Stellantis",
    "1J8": "Stellantis",
    "2C3": "Stellantis",
    "2C4": "Stellantis",
    "2D3": "Stellantis",
    "3C4": "Stellantis",
    "3C6": "Stellantis",
    "3C7": "Stellantis",
    "3D3": "Stellantis",
    "3D4": "Stellantis",
    "3D7": "Stellantis",
    # Toyota/Lexus
    "1TM": "Toyota",
    "2T1": "Toyota",
    "2T2": "Toyota",
    "2T3": "Toyota",
    "3TM": "Toyota",
    "4T1": "Toyota",
    "4T3": "Toyota",
    "4T4": "Toyota",
    "5TD": "Toyota",
    "5TF": "Toyota",
    "5TJ": "Toyota",
    "JT1": "Toyota",
    "JT2": "Toyota",
    "JT3": "Toyota",
    "JT4": "Toyota",
    "JT5": "Toyota",
    "JT6": "Toyota",
    "JT7": "Toyota",
    "JT8": "Toyota",
    "JTD": "Toyota",
    "JTE": "Toyota",
    "JTH": "Toyota",
    "JTJ": "Toyota",
    "JTK": "Toyota",
    "JTL": "Toyota",
    "JTM": "Toyota",
    "JTN": "Toyota",
    # Mitsubishi
    "4A3": "Mitsubishi",
    "4A4": "Mitsubishi",
    "6MM": "Mitsubishi",
    "JA3": "Mitsubishi",
    "JA4": "Mitsubishi",
    "JA7": "Mitsubishi",
    "JMY": "Mitsubishi",
    # Tesla
    "5YJ": "Tesla",
    "7SA": "Tesla",
    "7G2": "Tesla",
    "LRW": "Tesla",
    "XP7": "Tesla",
    # Ford (for generic fallback reference)
    "1FA": "Ford",
    "1FB": "Ford",
    "1FC": "Ford",
    "1FD": "Ford",
    "1FM": "Ford",
    "1FT": "Ford",
    "2FA": "Ford",
    "2FB": "Ford",
    "2FM": "Ford",
    "2FT": "Ford",
    "3FA": "Ford",
    "3FM": "Ford",
    # GM (for generic fallback reference)
    "1G1": "GM",
    "1G2": "GM",
    "1G3": "GM",
    "1G4": "GM",
    "1G6": "GM",
    "1G8": "GM",
    "1GC": "GM",
    "1GT": "GM",
    "1GY": "GM",
    "2G1": "GM",
    "2G2": "GM",
    "2G4": "GM",
    "3G1": "GM",
    "3G5": "GM",
    "3GN": "GM",
    "3GT": "GM",
    # Honda/Acura
    "1HG": "Honda",
    "2HG": "Honda",
    "2HK": "Honda",
    "2HJ": "Honda",
    "3H1": "Honda",
    "5FN": "Honda",
    "5FP": "Honda",
    "5J6": "Honda",
    "5J8": "Honda",
    "JH2": "Honda",
    "JH4": "Honda",
    "JHL": "Honda",
    "JHM": "Honda",
    "19U": "Honda",
    "19X": "Honda",
    # Nissan/Infiniti
    "1N4": "Nissan",
    "1N6": "Nissan",
    "3N1": "Nissan",
    "5N1": "Nissan",
    "JN1": "Nissan",
    "JN6": "Nissan",
    "JN8": "Nissan",
    # Hyundai/Kia/Genesis
    "5NM": "Hyundai",
    "5NP": "Hyundai",
    "5XY": "Hyundai",
    "KM8": "Hyundai",
    "KMH": "Hyundai",
    "5XX": "Kia",
    "KNA": "Kia",
    "KNC": "Kia",
    "KND": "Kia",
    # BMW
    "WBA": "BMW",
    "WBS": "BMW",
    "WBY": "BMW",
    "5UX": "BMW",
    "5UY": "BMW",
    # Mercedes-Benz
    "WDB": "Mercedes",
    "WDC": "Mercedes",
    "WDD": "Mercedes",
    "WDF": "Mercedes",
    "4JG": "Mercedes",
    "55S": "Mercedes",
    # Volkswagen/Audi
    "WVW": "VW",
    "WV1": "VW",
    "WV2": "VW",
    "WAU": "Audi",
    "WA1": "Audi",
}


class ParserRegistry:
    """Registry for window sticker parsers."""

    _parsers: dict[str, Type[BaseWindowStickerParser]] = {}
    _initialized: bool = False

    @classmethod
    def register(
        cls, manufacturer: str, parser_class: Type[BaseWindowStickerParser]
    ) -> None:
        """Register a parser for a manufacturer."""
        cls._parsers[manufacturer.lower()] = parser_class
        logger.debug(
            "Registered parser for %s: %s", manufacturer, parser_class.__name__
        )

    @classmethod
    def get_parser(cls, manufacturer: str) -> Optional[BaseWindowStickerParser]:
        """Get a parser instance for a manufacturer."""
        cls._ensure_initialized()

        parser_class = cls._parsers.get(manufacturer.lower())
        if parser_class:
            return parser_class()

        # Try generic fallback
        generic_class = cls._parsers.get("generic")
        if generic_class:
            logger.info("No specific parser for %s, using generic", manufacturer)
            return generic_class()

        return None

    @classmethod
    def get_parser_for_vin(cls, vin: str) -> Optional[BaseWindowStickerParser]:
        """Get appropriate parser based on VIN."""
        if not vin or len(vin) < 3:
            return cls.get_parser("generic")

        wmi = vin[:3].upper()
        manufacturer = WMI_MAPPING.get(wmi)

        if manufacturer:
            parser = cls.get_parser(manufacturer)
            if parser:
                logger.info(
                    "Selected %s for VIN %s (WMI: %s)",
                    parser.__class__.__name__,
                    vin,
                    wmi,
                )
                return parser

        logger.info("Unknown manufacturer for WMI %s, using generic parser", wmi)
        return cls.get_parser("generic")

    @classmethod
    def list_parsers(cls) -> list[dict[str, Any]]:
        """List all registered parsers."""
        cls._ensure_initialized()
        return [
            {
                "manufacturer": name,
                "parser_class": parser_class.__name__,
                "supported_makes": parser_class.SUPPORTED_MAKES,
            }
            for name, parser_class in cls._parsers.items()
        ]

    @classmethod
    def get_manufacturer_for_vin(cls, vin: str) -> Optional[str]:
        """Get manufacturer name from VIN."""
        if not vin or len(vin) < 3:
            return None
        wmi = vin[:3].upper()
        return WMI_MAPPING.get(wmi)

    @classmethod
    def _ensure_initialized(cls) -> None:
        """Ensure parsers are loaded."""
        if cls._initialized:
            return

        # Import and register all parsers
        try:
            from .stellantis import StellantisWindowStickerParser

            cls.register("stellantis", StellantisWindowStickerParser)
        except ImportError as e:
            logger.warning("Failed to load Stellantis parser: %s", e)

        try:
            from .toyota import ToyotaWindowStickerParser

            cls.register("toyota", ToyotaWindowStickerParser)
        except ImportError as e:
            logger.warning("Failed to load Toyota parser: %s", e)

        try:
            from .mitsubishi import MitsubishiWindowStickerParser

            cls.register("mitsubishi", MitsubishiWindowStickerParser)
        except ImportError as e:
            logger.warning("Failed to load Mitsubishi parser: %s", e)

        try:
            from .tesla import TeslaWindowStickerParser

            cls.register("tesla", TeslaWindowStickerParser)
        except ImportError as e:
            logger.warning("Failed to load Tesla parser: %s", e)

        try:
            from .generic import GenericWindowStickerParser

            cls.register("generic", GenericWindowStickerParser)
        except ImportError as e:
            logger.warning("Failed to load Generic parser: %s", e)

        cls._initialized = True
        logger.info("Parser registry initialized with %s parsers", len(cls._parsers))


def get_parser_for_vehicle(
    vin: str, make: Optional[str] = None
) -> BaseWindowStickerParser:
    """
    Get the appropriate parser for a vehicle.

    Args:
        vin: Vehicle VIN
        make: Optional make name (used as fallback)

    Returns:
        Appropriate parser instance
    """
    # Try VIN-based lookup first
    parser = ParserRegistry.get_parser_for_vin(vin)
    if parser:
        return parser

    # Try make-based lookup if provided
    if make:
        make_lower = make.lower()
        # Map make names to manufacturers
        make_to_manufacturer = {
            "ram": "stellantis",
            "dodge": "stellantis",
            "chrysler": "stellantis",
            "jeep": "stellantis",
            "fiat": "stellantis",
            "alfa romeo": "stellantis",
            "toyota": "toyota",
            "lexus": "toyota",
            "scion": "toyota",
            "mitsubishi": "mitsubishi",
            "tesla": "tesla",
        }
        manufacturer = make_to_manufacturer.get(make_lower)
        if manufacturer:
            parser = ParserRegistry.get_parser(manufacturer)
            if parser:
                return parser

    # Return generic parser as last resort
    return ParserRegistry.get_parser("generic") or GenericWindowStickerParser()


# Import for last resort fallback
from .generic import GenericWindowStickerParser
