"""NHTSA vPIC VIN Decoder provider."""

import logging
from typing import Any

from app.services.nhtsa import NHTSAService
from app.services.vin_decoders.base import BaseVINDecoder
from app.utils.logging_utils import sanitize_for_log
from app.utils.wmi import MarketRegion

logger = logging.getLogger(__name__)


class NHTSAVINDecoder(BaseVINDecoder):
    """VIN Decoder using the US NHTSA vPIC API.

    Primary decoder for North American vehicles (US, Canada, Mexico).
    Detects ErrorCode 1 ("Check Digit does not calculate properly / vehicle not found /
    outside US market") and signals failure so the routing orchestrator can fall back
    to European / alternative decoders.
    """

    name = "nhtsa"

    def __init__(self, nhtsa_service: NHTSAService | None = None) -> None:
        self.nhtsa_service = nhtsa_service or NHTSAService()

    def can_handle(self, vin: str, region: MarketRegion) -> bool:
        """NHTSA is the primary decoder for North America, but can also be queried as fallback."""
        return True

    async def decode(self, vin: str) -> dict[str, Any] | None:
        """Decode a VIN using the NHTSA vPIC API.

        Returns:
            Decoded vehicle info dictionary, or None if NHTSA returned ErrorCode 1
            or incomplete model data indicating the vehicle is outside the US market.
        """
        logger.info("Querying NHTSA vPIC API for VIN: %s", sanitize_for_log(vin))
        result = await self.nhtsa_service.decode_vin(vin)
        if not result:
            return None

        # Analyze error code and text
        error_code = str(result.get("error_code") or result.get("ErrorCode") or "")
        error_codes = [c.strip() for c in error_code.split(",") if c.strip()]
        error_text = str(result.get("error_text") or result.get("ErrorText") or "")
        model = result.get("model") or result.get("Model")

        # ErrorCode 1: Check Digit mismatch / vehicle outside US market / no detailed data
        # NHTSA returns ErrorCode 1 (often with 8 or 400) for European-spec vehicles and leaves Model empty.
        has_error_1 = "1" in error_codes or "1 -" in error_text
        if has_error_1 or not model:
            logger.info(
                "NHTSA returned error code 1 or missing model for VIN %s (error_code: %s, model: %s). "
                "Triggering fallback to European VIN Decoder.",
                sanitize_for_log(vin),
                sanitize_for_log(error_code),
                sanitize_for_log(model),
            )
            return None

        result["decoder_source"] = self.name
        return result
