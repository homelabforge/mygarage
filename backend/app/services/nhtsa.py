"""NHTSA (National Highway Traffic Safety Administration) API service."""

# pyright: reportArgumentType=false

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import SSRFProtectionError
from app.utils.logging_utils import sanitize_for_log
from app.utils.url_validation import validate_nhtsa_url
from app.utils.vin import validate_vin

logger = logging.getLogger(__name__)


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
                "fuel_type": result.get("FuelTypePrimary"),
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
        return {
            k: v
            for k, v in info.items()
            if v not in (None, "", "Not Applicable", "N/A")
        }

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
        except (ValueError, TypeError):
            return None

    async def get_vehicle_recalls(
        self, vin: str, db: AsyncSession
    ) -> list[dict[str, Any]]:
        """
        Get recalls for a specific VIN from NHTSA.

        Note: NHTSA does not provide a direct VIN-to-recalls API endpoint.
        This method first decodes the VIN to get make/model/year, then
        queries recalls by those parameters.

        Args:
            vin: The 17-character VIN
            db: Database session for fetching settings

        Returns:
            List of recall dictionaries

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
            raise ValueError(
                "Could not determine vehicle make, model, and year from VIN"
            )

        # Get recalls API URL from settings
        from sqlalchemy import select

        from app.models.settings import Setting

        result = await db.execute(
            select(Setting).where(Setting.key == "nhtsa_recalls_api_url")
        )
        setting = result.scalar_one_or_none()
        recalls_api_base = setting.value if setting else "https://api.nhtsa.gov/recalls"

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
            recalls_api_base = "https://api.nhtsa.gov/recalls"
            logger.warning("Using fallback recalls API URL: %s", recalls_api_base)

        # Query NHTSA recalls API by make/model/year
        # URL parameters should be properly encoded
        from urllib.parse import urlencode

        params = {"make": make, "model": model, "modelYear": year}
        recalls_url = f"{recalls_api_base}/recallsByVehicle?{urlencode(params)}"

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

    async def get_vehicle_tsbs(
        self, vin: str, db: AsyncSession
    ) -> list[dict[str, Any]]:
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
            raise ValueError(
                "Could not determine vehicle make, model, and year from VIN"
            )

        # Get TSB API URL from settings (if configured)
        from sqlalchemy import select

        from app.models.settings import Setting

        result = await db.execute(
            select(Setting).where(Setting.key == "nhtsa_tsb_api_url")
        )
        setting = result.scalar_one_or_none()
        tsb_api_base = (
            setting.value if setting else "https://api.nhtsa.gov/products/vehicle/tsbs"
        )

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
            tsb_api_base = "https://api.nhtsa.gov/products/vehicle/tsbs"
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
