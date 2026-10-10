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
            settings, "european_vin_api_base_url", "https://api-gateway.autoref.eu"
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
            self.base_url = "https://api-gateway.autoref.eu"

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

    async def test_connection(
        self, api_key: str | None = None
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Test connection to AutoRef API using the /usage endpoint.

        Does not consume monthly decoding quota.

        Returns:
            Tuple of (success, message, data)
        """
        key_to_test = (api_key if api_key is not None else self.api_key).strip()
        if not key_to_test:
            return False, "AutoRef API key is required", None

        url = f"{self.base_url}/usage?api_key={key_to_test}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    plan = data.get("plan", "Unknown")
                    rem = data.get("remaining")
                    limit = data.get("limit")
                    quota_str = (
                        f" ({rem}/{limit} remaining)"
                        if rem is not None and limit is not None
                        else ""
                    )
                    return (
                        True,
                        f"Connected to AutoRef successfully! Plan: {plan}{quota_str}",
                        data,
                    )
                if res.status_code in (401, 403):
                    return False, "Invalid API key or unauthorized by AutoRef", None
                return False, f"AutoRef returned HTTP {res.status_code}", None
        except httpx.TimeoutException:
            return False, "AutoRef API request timed out", None
        except httpx.ConnectError:
            return False, "Cannot connect to AutoRef API", None
        except Exception as e:
            return False, f"Connection to AutoRef failed: {e}", None

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
            "x-api-key": self.api_key,
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

                # If matches were found, try to enrich top match with full vehicle specs
                record: dict[str, Any] | None = None
                if isinstance(data, list) and data:
                    record = dict(data[0])
                elif isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list) and data["data"]:
                        record = dict(data["data"][0])
                    else:
                        record = dict(data)

                if record:
                    rec_type = record.get("RECORD_TYPE") or record.get("record_type")
                    rec_id = record.get("id") or record.get("ID")
                    if rec_type and rec_id:
                        try:
                            specs_url = f"{self.base_url}/vehicle/{rec_type}/{rec_id}?lang=en"
                            specs_res = await client.get(specs_url, headers=headers)
                            if specs_res.status_code == 200:
                                specs_data = specs_res.json()
                                if isinstance(specs_data, dict):
                                    if "SPECS" in specs_data and isinstance(
                                        specs_data["SPECS"], dict
                                    ):
                                        record.update(specs_data["SPECS"])
                                    if "VIN_INFO" in specs_data and isinstance(
                                        specs_data["VIN_INFO"], dict
                                    ):
                                        record.update(specs_data["VIN_INFO"])
                        except Exception as e:
                            logger.debug(
                                "Failed to fetch detailed vehicle specs from AutoRef: %s",
                                sanitize_for_log(e),
                            )

                return self._parse_autoref_response(vin, record or data)

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
            elif "BRAND" in data or "make" in data or "MODEL_RESOLVED" in data:
                record = data

        if not record:
            return None

        make = (
            record.get("BRAND")
            or record.get("brand")
            or record.get("Make")
            or record.get("make")
            or record.get("MANUFACTURER_MOTOR")
        )
        model = (
            record.get("MODEL_RESOLVED")
            or record.get("MODEL_LINE")
            or record.get("MODEL")
            or record.get("model")
            or record.get("Model")
            or record.get("MODEL_FULL")
            or record.get("BRAND_MODEL")
        )
        series = (
            record.get("MODEL2")
            or record.get("series")
            or record.get("Series")
            or record.get("SUBTYPE_VEHICLE")
        )
        trim = (
            record.get("MOTORIZATION")
            or record.get("MODEL3")
            or record.get("trim")
            or record.get("Trim")
            or record.get("VARIANT")
            or record.get("VERSION")
        )

        # Parse year
        date_circ = (
            record.get("DATE_FIRST_CIRCULATION")
            or record.get("year")
            or record.get("ModelYear")
            or record.get("DATE_REGISTRAR_START")
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

        # Displacement in liters
        displacement_l: str | None = None
        disp = record.get("DISPLACEMENT") or record.get("displacement")
        if disp is not None:
            try:
                displacement_l = f"{float(disp) / 1000:.1f}"
            except ValueError, TypeError:
                pass

        # Cylinders
        cylinders: int | None = None
        cyl_val = record.get("CYLINDERS") or record.get("cylinders")
        if cyl_val is not None:
            try:
                cylinders = int(cyl_val)
            except ValueError, TypeError:
                pass
        elif "MOTOR_DETAILS" in record and record["MOTOR_DETAILS"]:
            cyl_match = re.search(r"/\s*(\d+)\s*/", str(record["MOTOR_DETAILS"]))
            if cyl_match:
                cylinders = int(cyl_match.group(1))

        raw_fuel = record.get("FUEL") or record.get("fuel_type") or record.get("FuelTypePrimary")
        normalized_fuel = normalize_fuel_type(str(raw_fuel)) if raw_fuel else None

        # Check secondary fuel for PHEVs/hybrids or combined fuels (e.g. Gasoline / Electric)
        fuel_secondary: str | None = None
        if normalized_fuel and "hybrid" in normalized_fuel.value:
            fuel_secondary = "electric"
        elif (
            raw_fuel
            and "electric" in str(raw_fuel).lower()
            and any(k in str(raw_fuel).lower() for k in ("gas", "petrol", "benzin", "diesel"))
        ):
            fuel_secondary = "electric"

        gearbox = record.get("GEARBOX") or record.get("transmission")
        transmission_type: str | None = None
        if isinstance(gearbox, list) and gearbox:
            transmission_type = str(gearbox[0])
        elif gearbox:
            transmission_type = str(gearbox)

        # Parse doors (handles "4+1" or "5")
        doors: int | None = None
        doors_val = record.get("DOORS") or record.get("doors")
        if doors_val is not None:
            doors_match = re.search(r"\d+", str(doors_val))
            if doors_match:
                doors = int(doors_match.group(0))

        # Drivetrain
        drivetrain = record.get("DRIVETRAIN") or record.get("drive_type")
        drive_type: str | None = None
        if drivetrain:
            dt_str = str(drivetrain).upper()
            if any(k in dt_str for k in ("4X4", "AWD", "ALL", "ENGAGEABLE")):
                drive_type = "AWD"
            elif any(k in dt_str for k in ("FRONT", "FWD")):
                drive_type = "FWD"
            elif any(k in dt_str for k in ("REAR", "RWD")):
                drive_type = "RWD"
            else:
                drive_type = str(drivetrain)
        elif any(
            "4X4" in str(record.get(k, "")).upper()
            for k in ("BRAND_MODEL", "MODEL_FULL", "MODEL_LINE")
        ):
            drive_type = "AWD"

        result: dict[str, Any] = {
            "vin": vin,
            "make": make,
            "model": model,
            "series": series,
            "trim": trim,
            "year": year,
            "vehicle_type": record.get("TYPE_VEHICLE") or "PASSENGER CAR",
            "body_class": record.get("BODY") or record.get("body_class"),
            "drive_type": drive_type,
            "doors": doors,
            "manufacturer": record.get("MANUFACTURER") or record.get("manufacturer") or make,
            "engine": {
                "displacement_l": displacement_l,
                "cylinders": cylinders,
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
