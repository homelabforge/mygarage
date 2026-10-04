"""European VIN Decoder provider (AutoRef / European vehicle database)."""

import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.constants.fuel import normalize_fuel_type
from app.exceptions import SSRFProtectionError
from app.services.vin_decoders.base import BaseVINDecoder
from app.utils.logging_utils import sanitize_for_log
from app.utils.url_validation import validate_european_vin_url
from app.utils.wmi import MarketRegion, detect_market_region, lookup_wmi

logger = logging.getLogger(__name__)


class EuropeanVINDecoder(BaseVINDecoder):
    """VIN Decoder for European vehicles using AutoRef API with catalog fallback.

    Primary decoder for European vehicles (WMI starting with S through Z).
    Fallback decoder for North American vehicles when NHTSA returns ErrorCode 1.
    """

    name = "european"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        enabled: bool = True,
        timeout: float = 15.0,
    ) -> None:
        raw_url = base_url or getattr(
            settings, "european_vin_api_base_url", "https://api.autoref.eu"
        )
        try:
            validate_european_vin_url(raw_url)
            self.base_url = raw_url.rstrip("/")
        except (SSRFProtectionError, ValueError) as e:
            logger.warning(
                "SSRF validation blocked European VIN API base URL %s: %s; falling back to default",
                sanitize_for_log(raw_url),
                sanitize_for_log(e),
            )
            self.base_url = "https://api.autoref.eu"

        self.api_key = (
            api_key if api_key is not None else getattr(settings, "european_vin_api_key", "")
        )
        self.enabled = enabled
        self.timeout = timeout

    @property
    def has_api_key(self) -> bool:
        """Whether a valid API key is configured."""
        return bool(self.api_key and self.api_key.strip())

    def set_api_key(self, api_key: str | None) -> None:
        """Set or update the API key dynamically."""
        self.api_key = api_key.strip() if api_key else ""

    def is_available(self) -> bool:
        """European decoder is available if enabled."""
        return self.enabled

    def can_handle(self, vin: str, region: MarketRegion) -> bool:
        """European decoder can handle European VINs as primary and all VINs as fallback."""
        return self.enabled

    async def decode(self, vin: str) -> dict[str, Any] | None:
        """Decode a VIN using AutoRef European API, falling back to WMI database.

        Args:
            vin: 17-character VIN

        Returns:
            Dictionary matching VINDecodeResponse, or None if decoding failed
        """
        if not self.enabled:
            return None

        cleaned_vin = vin.strip().upper()

        # 1. Query external AutoRef European API only if API key is configured
        if self.has_api_key:
            api_result = await self._decode_from_api(cleaned_vin)
            if api_result:
                api_result["decoder_source"] = "autoref"
                return api_result

        # 2. WMI-based fallback if known manufacturer (restricted to European market)
        if detect_market_region(cleaned_vin) == MarketRegion.EUROPE:
            wmi_result = self._decode_wmi_fallback(cleaned_vin)
            if wmi_result:
                wmi_result["decoder_source"] = f"{self.name}_wmi"
                return wmi_result

        return None

    async def _decode_from_api(self, vin: str) -> dict[str, Any] | None:
        """Query the AutoRef European VIN API."""
        if not self.has_api_key:
            return None

        url = f"{self.base_url}/vehicles/{vin}?lang=en"
        headers: dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "MyGarage-EuropeanVINDecoder/1.0",
            "X-API-Key": self.api_key,
        }

        logger.info("Querying European VIN API (AutoRef) for VIN: %s", sanitize_for_log(vin))

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 404:
                    logger.info("VIN %s not found in European API (404)", sanitize_for_log(vin))
                    return None
                if response.status_code in (401, 403):
                    logger.warning(
                        "European VIN API returned %d (API key missing or restricted): %s",
                        response.status_code,
                        sanitize_for_log(response.text[:200]),
                    )
                    return None

                response.raise_for_status()
                data = response.json()
                return self._parse_autoref_response(vin, data)

        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e:
            logger.warning(
                "Error querying European VIN API for VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            return None
        except Exception as e:
            logger.warning(
                "Unexpected error parsing European VIN response for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            return None

    def _parse_autoref_response(self, vin: str, data: Any) -> dict[str, Any] | None:
        """Parse AutoRef JSON data into standardized vehicle dictionary."""
        record: dict[str, Any] | None = None

        if isinstance(data, list) and data:
            record = data[0]
        elif isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list) and data["data"]:
                record = data["data"][0]
            elif "VIN_INFO" in data and isinstance(data["VIN_INFO"], dict):
                record = data["VIN_INFO"]
                # Merge SPECS if present
                if "SPECS" in data and isinstance(data["SPECS"], dict):
                    record.update(data["SPECS"])
            elif "BRAND" in data or "make" in data:
                record = data

        if not record:
            return None

        make = (
            record.get("BRAND") or record.get("brand") or record.get("Make") or record.get("make")
        )
        model = record.get("MODEL") or record.get("model") or record.get("Model")
        series = record.get("MODEL2") or record.get("series") or record.get("Series")
        trim = (
            record.get("MODEL3")
            or record.get("trim")
            or record.get("Trim")
            or record.get("VARIANT")
        )

        # Parse year
        date_circ = (
            record.get("DATE_FIRST_CIRCULATION") or record.get("year") or record.get("ModelYear")
        )
        year: int | None = None
        if date_circ:
            year_match = re.search(r"\b(19\d\d|20\d\d)\b", str(date_circ))
            if year_match:
                year = int(year_match.group(1))

        # Engine specs
        hp_val = record.get("POWER_DIN") or record.get("hp") or record.get("EngineHP")
        kw_val = record.get("POWER_KW") or record.get("kw") or record.get("EngineKW")
        hp = int(round(float(hp_val))) if hp_val is not None else None
        kw = int(round(float(kw_val))) if kw_val is not None else None

        raw_fuel = record.get("FUEL") or record.get("fuel_type") or record.get("FuelTypePrimary")
        normalized_fuel = normalize_fuel_type(str(raw_fuel)) if raw_fuel else None

        # Check secondary fuel for PHEVs/hybrids
        fuel_secondary: str | None = None
        if normalized_fuel and "hybrid" in normalized_fuel.value:
            fuel_secondary = "electric"

        gearbox = record.get("GEARBOX") or record.get("transmission")
        transmission_type: str | None = None
        if isinstance(gearbox, list) and gearbox:
            transmission_type = str(gearbox[0])
        elif gearbox:
            transmission_type = str(gearbox)

        doors_val = record.get("DOORS") or record.get("doors")
        doors = int(doors_val) if doors_val is not None and str(doors_val).isdigit() else None

        result: dict[str, Any] = {
            "vin": vin,
            "make": make,
            "model": model,
            "series": series,
            "trim": trim,
            "year": year,
            "vehicle_type": record.get("TYPE_VEHICLE") or "PASSENGER CAR",
            "body_class": record.get("BODY") or record.get("body_class"),
            "drive_type": record.get("DRIVETRAIN") or record.get("drive_type"),
            "doors": doors,
            "manufacturer": record.get("MANUFACTURER") or record.get("manufacturer"),
            "engine": {
                "hp": hp,
                "kw": kw,
                "fuel_type": raw_fuel,
                "fuel_type_normalized": normalized_fuel.value if normalized_fuel else None,
                "fuel_type_secondary": fuel_secondary,
            },
            "transmission": {
                "type": transmission_type,
            },
        }

        # Filter out empty None values
        return {k: v for k, v in result.items() if v is not None}

    def _decode_wmi_fallback(self, vin: str) -> dict[str, Any] | None:
        """Generate high-confidence base vehicle information using WMI."""
        wmi_info = lookup_wmi(vin)
        if not wmi_info or not wmi_info.get("make"):
            return None

        # Extract year from ISO 3779 position 10 if standard code
        # A=2010 .. N=2022, P=2023, R=2024, S=2025, T=2026
        year_codes: dict[str, int] = {
            "A": 2010,
            "B": 2011,
            "C": 2012,
            "D": 2013,
            "E": 2014,
            "F": 2015,
            "G": 2016,
            "H": 2017,
            "J": 2018,
            "K": 2019,
            "L": 2020,
            "M": 2021,
            "N": 2022,
            "P": 2023,
            "R": 2024,
            "S": 2025,
            "T": 2026,
            "1": 2001,
            "2": 2002,
            "3": 2003,
            "4": 2004,
            "5": 2005,
            "6": 2006,
            "7": 2007,
            "8": 2008,
            "9": 2009,
        }
        year = None
        if len(vin) >= 10:
            year = year_codes.get(vin[9])

        return {
            "vin": vin,
            "make": wmi_info["make"],
            "manufacturer": wmi_info.get("manufacturer") or wmi_info["make"],
            "plant_country": wmi_info.get("country"),
            "year": year,
            "vehicle_type": "PASSENGER CAR",
        }
