"""NHTSA (National Highway Traffic Safety Administration) API service."""

import json
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.fuel import FuelTypeEnum, normalize_fuel_type, split_combined_fuel_type
from app.exceptions import SSRFProtectionError
from app.utils.logging_utils import sanitize_for_log
from app.utils.url_validation import validate_nhtsa_url
from app.utils.vin import validate_vin

logger = logging.getLogger(__name__)

# Used when the setting is missing, blank or fails the SSRF check.
DEFAULT_RECALLS_API_URL = "https://api.nhtsa.gov/recalls"
DEFAULT_TSB_API_URL = "https://api.nhtsa.gov/products/vehicle/tsbs"
# The recalls setting is a base; the fetch adds this. The TSB setting is the
# whole endpoint, so it has no suffix to double.
RECALLS_BY_VEHICLE_PATH = "/recallsByVehicle"


class NHTSAUnavailableError(Exception):
    """NHTSA didn't answer usably, so a recall lookup says nothing.

    Raised by `get_vehicle_recalls(raise_on_error=True)` for a transport error
    (timeouts, connect, read, protocol and proxy errors), any HTTP error
    status, or a 200 whose body isn't JSON (a maintenance page), from the vPIC
    decode and the recalls fetch alike. Chained from the original error; the
    message names the API and the error type only, never the response body.
    """


class _VPICBodyNotJSONError(ValueError):
    """vPIC answered with a body that isn't JSON.

    Still a ValueError with the same message, as `decode_vin`'s callers have
    always seen it; the subclass only lets `get_vehicle_recalls` tell this
    outage from a VIN vPIC can't resolve.
    """


#: What `get_vehicle_recalls(raise_on_error=True)` reads as NHTSA being down.
#: Every HTTPStatusError counts, 4xx included (ruling F2-1): a permanent 4xx
#: for one model re-queries the fleet daily, which is noisy but misses nothing.
_OUTAGE_ERRORS: tuple[type[Exception], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
    json.JSONDecodeError,
    _VPICBodyNotJSONError,
)


class NHTSAService:
    """Service for interacting with NHTSA vPIC API.

    Security:
        - Validates all NHTSA API URLs against SSRF attacks
        - Only allows requests to official NHTSA domains (*.nhtsa.dot.gov)
        - Blocks private IPs, localhost, and cloud metadata endpoints
    """

    def __init__(self):
        base_url = settings.nhtsa_api_base_url

        # SECURITY: Validate base URL against SSRF attacks (CWE-918)
        # This prevents attackers from modifying settings to point to internal services
        try:
            validate_nhtsa_url(base_url)
            self.base_url = base_url
        except (SSRFProtectionError, ValueError) as e:
            logger.error(
                "SSRF protection blocked NHTSA base URL: %s - %s",
                sanitize_for_log(base_url),
                sanitize_for_log(e),
            )
            # Fallback to official NHTSA URL if validation fails
            self.base_url = "https://vpic.nhtsa.dot.gov/api"
            logger.warning("Using fallback NHTSA URL: %s", self.base_url)

        self.timeout = 30.0

    async def decode_vin(self, vin: str) -> dict[str, Any]:
        """
        Decode a VIN using the NHTSA vPIC API.

        Args:
            vin: The 17-character VIN to decode

        Returns:
            Dictionary containing decoded vehicle information

        Raises:
            ValueError: If VIN is invalid
            httpx.HTTPError: If API request fails
        """
        # Validate VIN format
        is_valid, error_msg = validate_vin(vin)
        if not is_valid:
            raise ValueError(f"Invalid VIN: {error_msg}")

        # Build API URL
        # Using DecodeVinValues endpoint which returns formatted data
        url = f"{self.base_url}/vehicles/DecodeVinValues/{vin}?format=json"

        logger.info("Decoding VIN: %s", sanitize_for_log(vin))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - self.base_url validated in __init__ by validate_nhtsa_url
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                # Parse response
                if "Results" not in data or not data["Results"]:
                    raise ValueError("No results returned from NHTSA API")

                # Get first result (should only be one for VIN decode)
                result = data["Results"][0]

                # Check for errors in response
                error_code = result.get("ErrorCode", "")
                error_text = result.get("ErrorText", "")

                if error_code and error_code != "0":
                    logger.warning(
                        "NHTSA API returned error for VIN %s: %s",
                        sanitize_for_log(vin),
                        sanitize_for_log(error_text),
                    )
                    # Some error codes are just warnings, continue processing

                # Extract key vehicle information
                vehicle_info = self._extract_vehicle_info(result)

                logger.info(
                    "Successfully decoded VIN %s: %s %s",
                    sanitize_for_log(vin),
                    sanitize_for_log(vehicle_info.get("Make")),
                    sanitize_for_log(vehicle_info.get("Model")),
                )

                return vehicle_info

            except httpx.TimeoutException:
                logger.error("NHTSA API timeout decoding VIN %s", sanitize_for_log(vin))
                raise
            except httpx.ConnectError as e:
                logger.error(
                    "Cannot connect to NHTSA API for VIN %s: %s",
                    sanitize_for_log(vin),
                    sanitize_for_log(e),
                )
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    "NHTSA API error decoding VIN %s: %s",
                    sanitize_for_log(vin),
                    sanitize_for_log(e),
                )
                raise
            except json.JSONDecodeError as e:
                logger.error(
                    "Error parsing NHTSA response for VIN %s: %s",
                    sanitize_for_log(vin),
                    sanitize_for_log(e),
                )
                raise _VPICBodyNotJSONError(f"Invalid NHTSA response: {e}") from e
            except (ValueError, KeyError) as e:
                logger.error(
                    "Error parsing NHTSA response for VIN %s: %s",
                    sanitize_for_log(vin),
                    sanitize_for_log(e),
                )
                raise ValueError(f"Invalid NHTSA response: {e}")

    def _extract_vehicle_info(self, result: dict) -> dict[str, Any]:
        """
        Extract relevant vehicle information from NHTSA API result.

        Args:
            result: Raw result from NHTSA API

        Returns:
            Dictionary with cleaned vehicle information
        """
        # Map NHTSA fields to our application fields
        # NHTSA returns many fields, we extract the most useful ones
        # Normalize NHTSA fuel-type strings to the canonical enum vocabulary.
        # NHTSA returns combined values ("Gasoline, Hybrid Electric") in the
        # primary slot for some PHEVs/flex vehicles even when secondary is set;
        # `split_combined_fuel_type` decodes those into (primary, secondary).
        raw_primary = result.get("FuelTypePrimary")
        raw_secondary = result.get("FuelTypeSecondary")

        primary_split, secondary_from_split = split_combined_fuel_type(raw_primary)
        if primary_split is not None:
            fuel_type_primary: FuelTypeEnum | None = primary_split
            fuel_type_secondary: FuelTypeEnum | None = (
                normalize_fuel_type(raw_secondary) or secondary_from_split
            )
        else:
            fuel_type_primary = normalize_fuel_type(raw_primary)
            fuel_type_secondary = normalize_fuel_type(raw_secondary)

        info = {
            "vin": result.get("VIN"),
            "year": self._parse_int(result.get("ModelYear")),
            "make": result.get("Make"),
            "model": result.get("Model"),
            "trim": result.get("Trim"),
            "vehicle_type": result.get("VehicleType"),
            "body_class": result.get("BodyClass"),
            "engine": {
                "displacement_l": result.get("DisplacementL"),
                "cylinders": self._parse_int(result.get("EngineCylinders")),
                "hp": self._parse_int(result.get("EngineHP")),
                "kw": self._parse_int(result.get("EngineKW")),
                # `fuel_type` keeps the raw NHTSA string for legacy callers;
                # normalized values surface via `fuel_type_normalized` and
                # `fuel_type_secondary` below.
                "fuel_type": raw_primary,
                "fuel_type_normalized": (fuel_type_primary.value if fuel_type_primary else None),
                "fuel_type_secondary": (fuel_type_secondary.value if fuel_type_secondary else None),
            },
            "transmission": {
                "type": result.get("TransmissionStyle"),
                "speeds": result.get("TransmissionSpeeds"),
            },
            "drive_type": result.get("DriveType"),
            "manufacturer": result.get("Manufacturer"),
            "plant_city": result.get("PlantCity"),
            "plant_country": result.get("PlantCountry"),
            "doors": self._parse_int(result.get("Doors")),
            "gvwr": result.get("GVWR"),  # Gross Vehicle Weight Rating
            "error_code": result.get("ErrorCode"),
            "error_text": result.get("ErrorText"),
            # Additional useful fields
            "series": result.get("Series"),
            "steering_location": result.get("SteeringLocation"),
            "entertainment_system": result.get("EntertainmentSystem"),
        }

        # Clean up None values and empty strings
        return {k: v for k, v in info.items() if v not in (None, "", "Not Applicable", "N/A")}

    def _parse_int(self, value: str | None) -> int | None:
        """
        Safely parse string to int.

        Args:
            value: String value to parse

        Returns:
            Integer value or None if parsing fails
        """
        if value in (None, "", "Not Applicable", "N/A"):
            return None
        try:
            return int(value)
        except ValueError, TypeError:
            return None

    async def get_vehicle_recalls(
        self, vin: str, db: AsyncSession, *, raise_on_error: bool = False
    ) -> list[dict[str, Any]]:
        """
        Get recalls for a specific VIN from NHTSA.

        Note: NHTSA does not provide a direct VIN-to-recalls API endpoint.
        This method first decodes the VIN to get make/model/year, then
        queries recalls by those parameters.

        Args:
            vin: The 17-character VIN
            db: Database session for fetching settings
            raise_on_error: Raise NHTSAUnavailableError when NHTSA doesn't
                answer, instead of the manual check's fallbacks (a decode
                failure as ValueError, a failed recalls fetch as no recalls).

        Returns:
            List of recall dictionaries

        Raises:
            ValueError: If VIN is invalid or vehicle info cannot be decoded
            NHTSAUnavailableError: Only with raise_on_error, when NHTSA times
                out, can't be reached, answers an HTTP error, or answers a
                body that isn't JSON
        """
        # Empty unless asked, so `except ()` matches nothing and the manual
        # check keeps the fallbacks below.
        outage_errors = _OUTAGE_ERRORS if raise_on_error else ()

        # First, decode the VIN to get make/model/year
        try:
            vehicle_info = await self.decode_vin(vin)
        except outage_errors as e:
            raise NHTSAUnavailableError(f"NHTSA vPIC API unavailable ({type(e).__name__})") from e
        except Exception as e:
            logger.error(
                "Failed to decode VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise ValueError(f"Could not decode VIN to fetch recalls: {str(e)}")

        # Extract make, model, and year
        make = vehicle_info.get("make")
        model = vehicle_info.get("model")
        year = vehicle_info.get("year")

        if not all([make, model, year]):
            logger.warning(
                "Incomplete vehicle info for VIN %s: make=%s, model=%s, year=%s",
                sanitize_for_log(vin),
                sanitize_for_log(make),
                sanitize_for_log(model),
                year,
            )
            raise ValueError("Could not determine vehicle make, model, and year from VIN")

        # Get recalls API URL from settings
        from sqlalchemy import select

        from app.models.settings import Setting

        result = await db.execute(select(Setting).where(Setting.key == "nhtsa_recalls_api_url"))
        setting = result.scalar_one_or_none()
        # Blank or NULL is nobody having set one, so it's the default and not
        # an SSRF block worth an ERROR. The value column is nullable. Spaces
        # round a pasted URL aren't part of it, and httpx can't fetch it with them.
        stored_url = setting.value.strip() if setting and setting.value else ""
        # Before v2.19.0 the seed was the full endpoint, and the Integrations tab
        # saved it when the field was blank. The fetch below appends the path,
        # so those rows doubled it. Read a stored endpoint as its base.
        stored_url = stored_url.rstrip("/").removesuffix(RECALLS_BY_VEHICLE_PATH)
        recalls_api_base = stored_url or DEFAULT_RECALLS_API_URL

        # SECURITY: Validate recalls API base URL against SSRF attacks
        try:
            validate_nhtsa_url(recalls_api_base)
        except (SSRFProtectionError, ValueError) as e:
            logger.error(
                "SSRF protection blocked recalls API URL: %s - %s",
                sanitize_for_log(recalls_api_base),
                sanitize_for_log(e),
            )
            # Use safe default if validation fails
            recalls_api_base = DEFAULT_RECALLS_API_URL
            logger.warning("Using fallback recalls API URL: %s", recalls_api_base)

        # Query NHTSA recalls API by make/model/year
        # URL parameters should be properly encoded
        from urllib.parse import urlencode

        params = {"make": make, "model": model, "modelYear": year}
        recalls_url = f"{recalls_api_base}{RECALLS_BY_VEHICLE_PATH}?{urlencode(params)}"

        logger.info(
            "Fetching recalls for %s %s %s (VIN: %s)",
            year,
            sanitize_for_log(make),
            sanitize_for_log(model),
            sanitize_for_log(vin),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - recalls_api_base validated by validate_nhtsa_url above
                response = await client.get(recalls_url)
                response.raise_for_status()
                data = response.json()

                # Extract recalls from the response
                recalls = data.get("results", [])

                logger.info(
                    "Found %s recall(s) for %s %s %s",
                    len(recalls),
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                )

                return recalls

            except outage_errors as e:
                raise NHTSAUnavailableError(
                    f"NHTSA recalls API unavailable ({type(e).__name__})"
                ) from e
            except httpx.TimeoutException:
                logger.error(
                    "NHTSA recalls API timeout for %s %s %s",
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                )
                return []  # Intentional fallback: don't break UI for timeout
            except httpx.ConnectError as e:
                logger.error(
                    "Cannot connect to NHTSA recalls API for %s %s %s: %s",
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                    sanitize_for_log(e),
                )
                return []  # Intentional fallback: don't break UI for connection issues
            except httpx.HTTPStatusError as e:
                logger.error(
                    "NHTSA recalls API error for %s %s %s: %s",
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                    sanitize_for_log(e),
                )
                return []  # Intentional fallback: return empty list on API error

    async def get_vehicle_tsbs(self, vin: str, db: AsyncSession) -> list[dict[str, Any]]:
        """
        Get Technical Service Bulletins (TSBs) for a specific VIN from NHTSA.

        Similar to recalls, NHTSA does not provide a direct VIN-to-TSB endpoint.
        This method decodes the VIN first, then queries TSBs by make/model/year.

        Args:
            vin: The 17-character VIN
            db: Database session for fetching settings

        Returns:
            List of TSB dictionaries

        Raises:
            ValueError: If VIN is invalid or vehicle info cannot be decoded
        """
        # First, decode the VIN to get make/model/year
        try:
            vehicle_info = await self.decode_vin(vin)
        except Exception as e:
            logger.error(
                "Failed to decode VIN %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise ValueError(f"Could not decode VIN to fetch TSBs: {str(e)}")

        # Extract make, model, and year
        make = vehicle_info.get("make")
        model = vehicle_info.get("model")
        year = vehicle_info.get("year")

        if not all([make, model, year]):
            logger.warning(
                "Incomplete vehicle info for VIN %s: make=%s, model=%s, year=%s",
                sanitize_for_log(vin),
                sanitize_for_log(make),
                sanitize_for_log(model),
                year,
            )
            raise ValueError("Could not determine vehicle make, model, and year from VIN")

        # Get TSB API URL from settings (if configured)
        from sqlalchemy import select

        from app.models.settings import Setting

        result = await db.execute(select(Setting).where(Setting.key == "nhtsa_tsb_api_url"))
        setting = result.scalar_one_or_none()
        # Same as recalls: blank or NULL means the default, quietly, and a URL
        # is used stripped.
        stored_url = setting.value.strip() if setting and setting.value else ""
        tsb_api_base = stored_url or DEFAULT_TSB_API_URL

        # SECURITY: Validate TSB API base URL against SSRF attacks
        try:
            validate_nhtsa_url(tsb_api_base)
        except (SSRFProtectionError, ValueError) as e:
            logger.error(
                "SSRF protection blocked TSB API URL: %s - %s",
                sanitize_for_log(tsb_api_base),
                sanitize_for_log(e),
            )
            # Use safe default if validation fails
            tsb_api_base = DEFAULT_TSB_API_URL
            logger.warning("Using fallback TSB API URL: %s", tsb_api_base)

        # Query NHTSA TSB API by make/model/year
        from urllib.parse import urlencode

        params = {"make": make, "model": model, "modelYear": year}
        tsb_url = f"{tsb_api_base}?{urlencode(params)}"

        logger.info(
            "Fetching TSBs for %s %s %s (VIN: %s)",
            year,
            sanitize_for_log(make),
            sanitize_for_log(model),
            sanitize_for_log(vin),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - tsb_api_base validated by validate_nhtsa_url above
                response = await client.get(tsb_url)
                response.raise_for_status()
                data = response.json()

                # Extract TSBs from the response
                # NHTSA TSB API structure may vary - adapt as needed
                tsbs = data.get("results", [])

                logger.info(
                    "Found %s TSB(s) for %s %s %s",
                    len(tsbs),
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                )

                return tsbs

            except httpx.TimeoutException:
                logger.error(
                    "NHTSA TSB API timeout for %s %s %s",
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                )
                return []  # Intentional fallback: don't break UI for timeout
            except httpx.ConnectError as e:
                logger.error(
                    "Cannot connect to NHTSA TSB API for %s %s %s: %s",
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                    sanitize_for_log(e),
                )
                return []  # Intentional fallback: don't break UI for connection issues
            except httpx.HTTPStatusError as e:
                logger.error(
                    "NHTSA TSB API error for %s %s %s: %s",
                    year,
                    sanitize_for_log(make),
                    sanitize_for_log(model),
                    sanitize_for_log(e),
                )
                return []  # Intentional fallback: return empty list on API error
