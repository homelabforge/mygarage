"""Base classes and types for VIN decoders."""

from abc import ABC, abstractmethod
from typing import Any

from app.utils.wmi import MarketRegion


class BaseVINDecoder(ABC):
    """Abstract base class for all VIN decoder implementations.

    Subclasses must implement ``decode`` and provide a unique ``name``.
    Decoders can declare region suitability via ``can_handle`` and
    availability via ``is_available``.
    """

    name: str

    @abstractmethod
    async def decode(self, vin: str) -> dict[str, Any] | None:
        """Decode a VIN into standardized vehicle information dictionary.

        Args:
            vin: Cleaned 17-character VIN string

        Returns:
            Dictionary matching VINDecodeResponse fields, or None if the
            decoder has no data for this VIN or cannot decode it.
        """
        ...

    def is_available(self) -> bool:
        """Return True if this decoder is enabled and operational."""
        return True

    def can_handle(self, vin: str, region: MarketRegion) -> bool:
        """Return True if this decoder is capable of handling this region/VIN."""
        return True
