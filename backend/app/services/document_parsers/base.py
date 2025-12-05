"""Base document parser class with common extraction methods."""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Any

logger = logging.getLogger(__name__)


class DocumentType(Enum):
    """Types of documents that can be parsed."""
    WINDOW_STICKER = "window_sticker"
    INSURANCE = "insurance"
    # Future types can be added here
    # REGISTRATION = "registration"
    # TITLE = "title"
    # SERVICE_RECORD = "service_record"


@dataclass
class DocumentData:
    """Base class for structured data extracted from documents."""

    # Common metadata
    raw_text: Optional[str] = None
    parser_name: Optional[str] = None
    confidence_score: float = 0.0
    document_type: Optional[DocumentType] = None

    # VIN if applicable
    extracted_vin: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "raw_text": self.raw_text,
            "parser_name": self.parser_name,
            "confidence_score": self.confidence_score,
            "document_type": self.document_type.value if self.document_type else None,
            "extracted_vin": self.extracted_vin,
        }

    def get_validation_warnings(self) -> list[str]:
        """Return list of validation warnings for the extracted data."""
        return []


class BaseDocumentParser(ABC):
    """Abstract base class for document parsers."""

    # Override in subclasses
    PARSER_NAME: str = "Unknown"
    DOCUMENT_TYPE: DocumentType = DocumentType.WINDOW_STICKER

    # Common regex patterns
    VIN_PATTERN = r'[A-HJ-NPR-Z0-9]{17}'
    PRICE_PATTERN = r'\$?\s*([\d,]+\.?\d*)'

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def parse(self, text: str, **kwargs) -> DocumentData:
        """
        Parse document text and extract structured data.

        Args:
            text: Raw text extracted from document
            **kwargs: Additional parsing context (e.g., target_vin)

        Returns:
            DocumentData subclass with extracted fields
        """
        pass

    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """
        Check if this parser can handle the given text.

        Args:
            text: Raw text to check

        Returns:
            True if this parser should handle the document
        """
        pass

    def _extract_price(self, text: str, patterns: list[str]) -> Optional[Decimal]:
        """Extract a price value using multiple patterns."""
        import decimal
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    value = match.group(1).replace(',', '').replace('$', '')
                    return Decimal(value)
                except (ValueError, IndexError, decimal.InvalidOperation):
                    continue
        return None

    def _extract_vin(self, text: str) -> Optional[str]:
        """Extract VIN from text."""
        # Look for VIN label first
        vin_patterns = [
            r'VIN[:\s]*([A-HJ-NPR-Z0-9\-\s]{17,21})',
            r'V\.I\.N\.[:\s]*([A-HJ-NPR-Z0-9\-\s]{17,21})',
            r'VEHICLE\s*IDENTIFICATION\s*NUMBER[:\s]*([A-HJ-NPR-Z0-9\-\s]{17,21})',
        ]

        for pattern in vin_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                vin = match.group(1).upper()
                vin = re.sub(r'[\-\s]', '', vin)
                if len(vin) == 17 and re.match(r'^[A-HJ-NPR-Z0-9]{17}$', vin):
                    return vin

        # Fallback: find any 17-char alphanumeric
        match = re.search(self.VIN_PATTERN, text)
        if match:
            return match.group(0).upper()

        return None

    def _extract_all_vins(self, text: str) -> list[str]:
        """Extract all VINs found in text."""
        vins = []
        matches = re.finditer(self.VIN_PATTERN, text)
        for match in matches:
            vin = match.group(0).upper()
            if vin not in vins:
                vins.append(vin)
        return vins

    def _extract_pattern(self, text: str, patterns: list[str]) -> Optional[str]:
        """Extract first match from list of regex patterns."""
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()
        return None

    def _parse_currency(self, value: str) -> Optional[Decimal]:
        """Parse currency string to Decimal."""
        try:
            cleaned = value.replace('$', '').replace(',', '').strip()
            return Decimal(cleaned)
        except (ValueError, InvalidOperation, AttributeError) as e:
            logger.debug("Failed to parse currency value '%s': %s", value, e)
            return None
