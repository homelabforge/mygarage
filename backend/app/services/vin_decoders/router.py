"""VIN Decoder Router and multi-provider orchestrator.

Handles:
1. WMI and market region detection (North America vs Europe vs Other).
2. Intelligent provider routing and error code 1 / missing-data fallback.
3. Extensible provider registration for 3rd/4th/nth VIN decoder services.
"""

import logging
from typing import Any

import httpx

from app.services.vin_decoders.base import BaseVINDecoder
from app.services.vin_decoders.european import EuropeanVINDecoder
from app.services.vin_decoders.nhtsa import NHTSAVINDecoder
from app.utils.logging_utils import sanitize_for_log
from app.utils.vin import validate_vin
from app.utils.wmi import MarketRegion, detect_market_region

logger = logging.getLogger(__name__)


class VINDecoderRouter:
    """Orchestrates VIN decoding across multiple region-specific and global providers.

    Features:
    - Routes North American VINs (1, 4, 5, 2, 3) to NHTSA first, falling back to European
      API if NHTSA returns ErrorCode 1 or lacks vehicle data.
    - Bypasses NHTSA for European VINs (S through Z), calling European VIN Decoder directly.
    - Easily extensible: external providers (e.g. Vincario, CarVertical) can be added
      via ``register_decoder``.
    """

    def __init__(
        self,
        nhtsa_decoder: BaseVINDecoder | None = None,
        european_decoder: BaseVINDecoder | None = None,
    ) -> None:
        self._decoders: dict[str, BaseVINDecoder] = {}

        # Register default decoders
        self.register_decoder(nhtsa_decoder or NHTSAVINDecoder())
        self.register_decoder(european_decoder or EuropeanVINDecoder())

    def register_decoder(self, decoder: BaseVINDecoder) -> None:
        """Register a new VIN decoder provider.

        Args:
            decoder: Instance of BaseVINDecoder subclass
        """
        self._decoders[decoder.name] = decoder
        logger.debug("Registered VIN decoder provider: %s", decoder.name)

    def get_decoder(self, name: str) -> BaseVINDecoder | None:
        """Retrieve a registered decoder by name."""
        return self._decoders.get(name)

    def determine_decoder_chain(self, vin: str) -> list[BaseVINDecoder]:
        """Determine the prioritized sequence of decoders for a given VIN based on WMI market region.

        Rules:
        - NORTH_AMERICA (VIN starts with 1, 4, 5, 2, 3):
          [nhtsa, european, other registered...]
        - EUROPE (VIN starts with S-Z):
          [european, nhtsa (fallback), other registered...]
        - OTHER (Asia, Oceania, South America, etc.):
          [nhtsa, european, other registered...]
        """
        region = detect_market_region(vin)
        nhtsa = self._decoders.get("nhtsa")
        european = self._decoders.get("european")

        # Collect any other custom registered decoders
        other_decoders = [
            d
            for name, d in self._decoders.items()
            if name not in ("nhtsa", "european") and d.is_available()
        ]

        chain: list[BaseVINDecoder] = []

        if region == MarketRegion.EUROPE:
            # European vehicle:
            # If european decoder has an API key configured, use it first (rich European catalog data).
            # If no API key is configured, use NHTSA first (free, public, no key), then fallback to WMI.
            has_euro_api = getattr(european, "has_api_key", False)
            if european and european.is_available() and has_euro_api:
                chain.append(european)
                chain.extend(other_decoders)
                if nhtsa and nhtsa.is_available():
                    chain.append(nhtsa)
            else:
                if nhtsa and nhtsa.is_available():
                    chain.append(nhtsa)
                chain.extend(other_decoders)
                if european and european.is_available():
                    chain.append(european)

        elif region == MarketRegion.NORTH_AMERICA:
            # North American vehicle: call NHTSA first, fallback to European decoder if error code 1
            if nhtsa and nhtsa.is_available():
                chain.append(nhtsa)
            if european and european.is_available():
                chain.append(european)
            chain.extend(other_decoders)

        else:
            # Other regions (Asia, etc.): NHTSA -> European -> others
            if nhtsa and nhtsa.is_available():
                chain.append(nhtsa)
            if european and european.is_available():
                chain.append(european)
            chain.extend(other_decoders)

        return chain

    async def decode_vin(self, vin: str) -> dict[str, Any]:
        """Decode a VIN using intelligent market routing and provider fallbacks.

        Args:
            vin: 17-character VIN

        Returns:
            Dictionary with decoded vehicle information

        Raises:
            ValueError: If VIN format is invalid or vehicle could not be decoded
            httpx.TimeoutException: If primary API timed out and no fallback succeeded
            httpx.ConnectError: If primary API connection failed and no fallback succeeded
        """
        # Validate format
        is_valid, error_msg = validate_vin(vin)
        if not is_valid:
            raise ValueError(f"Invalid VIN: {error_msg}")

        cleaned_vin = vin.strip().upper()
        region = detect_market_region(cleaned_vin)
        decoder_chain = self.determine_decoder_chain(cleaned_vin)

        logger.info(
            "Routing VIN %s (market: %s) through decoder chain: %s",
            sanitize_for_log(cleaned_vin),
            region.value,
            [d.name for d in decoder_chain],
        )

        last_network_error: Exception | None = None

        for decoder in decoder_chain:
            try:
                logger.info(
                    "Attempting VIN decode with provider '%s' for VIN %s",
                    decoder.name,
                    sanitize_for_log(cleaned_vin),
                )
                result = await decoder.decode(cleaned_vin)
                if result and (result.get("make") or result.get("model")):
                    result["market_region"] = region.value
                    if "decoder_source" not in result:
                        result["decoder_source"] = decoder.name

                    logger.info(
                        "Successfully decoded VIN %s using provider '%s' (%s %s)",
                        sanitize_for_log(cleaned_vin),
                        result.get("decoder_source"),
                        sanitize_for_log(result.get("make")),
                        sanitize_for_log(result.get("model")),
                    )
                    return result

                logger.info(
                    "Provider '%s' returned no data for VIN %s; trying next provider in chain",
                    decoder.name,
                    sanitize_for_log(cleaned_vin),
                )

            except (httpx.TimeoutException, httpx.ConnectError) as net_err:
                logger.warning(
                    "Network error with decoder '%s' for VIN %s: %s",
                    decoder.name,
                    sanitize_for_log(cleaned_vin),
                    sanitize_for_log(net_err),
                )
                if last_network_error is None:
                    last_network_error = net_err
                # Continue to next decoder in chain if available
                continue

            except Exception as e:
                logger.warning(
                    "Error executing decoder '%s' for VIN %s: %s",
                    decoder.name,
                    sanitize_for_log(cleaned_vin),
                    sanitize_for_log(e),
                )
                continue

        # If all decoders failed and we encountered a critical network error on primary, re-raise it
        if last_network_error is not None:
            raise last_network_error

        raise ValueError(
            f"No vehicle details found for VIN {cleaned_vin} across available providers"
        )


# Global router singleton
_router_instance: VINDecoderRouter | None = None


def get_vin_decoder_router() -> VINDecoderRouter:
    """Get or create the global VINDecoderRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = VINDecoderRouter()
    return _router_instance
