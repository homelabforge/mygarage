"""Registry for document parsers including insurance providers."""

import logging
from typing import Any, Optional, Type

from .base import BaseDocumentParser, DocumentType
from .insurance import (
    InsuranceDocumentParser,
    ProgressiveInsuranceParser,
    StateFarmInsuranceParser,
    GeicoInsuranceParser,
    AllstateInsuranceParser,
    GenericInsuranceParser,
)

logger = logging.getLogger(__name__)


class DocumentParserRegistry:
    """Registry for document parsers organized by type and provider."""

    _insurance_parsers: dict[str, Type[InsuranceDocumentParser]] = {}
    _initialized: bool = False

    @classmethod
    def register_insurance_parser(
        cls, provider: str, parser_class: Type[InsuranceDocumentParser]
    ) -> None:
        """Register an insurance parser for a provider."""
        cls._insurance_parsers[provider.lower()] = parser_class
        logger.debug(
            "Registered insurance parser for %s: %s", provider, parser_class.__name__
        )

    @classmethod
    def get_insurance_parser(cls, provider: str) -> Optional[InsuranceDocumentParser]:
        """Get a specific insurance parser by provider name."""
        cls._ensure_initialized()

        parser_class = cls._insurance_parsers.get(provider.lower())
        if parser_class:
            return parser_class()

        # Return generic as fallback
        generic_class = cls._insurance_parsers.get("generic")
        if generic_class:
            logger.info("No specific parser for %s, using generic", provider)
            return generic_class()

        return None

    @classmethod
    def detect_insurance_parser(cls, text: str) -> InsuranceDocumentParser:
        """
        Auto-detect the appropriate insurance parser based on document content.

        Args:
            text: The extracted document text

        Returns:
            The most appropriate parser for this document
        """
        cls._ensure_initialized()

        # Try each provider-specific parser
        for provider, parser_class in cls._insurance_parsers.items():
            if provider == "generic":
                continue

            parser = parser_class()
            if parser.can_parse(text):
                logger.info(
                    "Auto-detected insurance provider: %s", parser.PROVIDER_NAME
                )
                return parser

        # Fall back to generic
        logger.info("Could not detect insurance provider, using generic parser")
        return GenericInsuranceParser()

    @classmethod
    def list_insurance_parsers(cls) -> list[dict[str, Any]]:
        """List all registered insurance parsers."""
        cls._ensure_initialized()
        return [
            {
                "provider": parser_class.PROVIDER_NAME,
                "parser_name": parser_class.PARSER_NAME,
            }
            for _name, parser_class in cls._insurance_parsers.items()
        ]

    @classmethod
    def _ensure_initialized(cls) -> None:
        """Ensure parsers are loaded."""
        if cls._initialized:
            return

        # Register all insurance parsers
        cls.register_insurance_parser("progressive", ProgressiveInsuranceParser)
        cls.register_insurance_parser("statefarm", StateFarmInsuranceParser)
        cls.register_insurance_parser("state farm", StateFarmInsuranceParser)
        cls.register_insurance_parser("geico", GeicoInsuranceParser)
        cls.register_insurance_parser("allstate", AllstateInsuranceParser)
        cls.register_insurance_parser("generic", GenericInsuranceParser)

        cls._initialized = True
        logger.info(
            "Document parser registry initialized with %s insurance parsers",
            len(cls._insurance_parsers),
        )


def get_parser_for_document(
    document_type: DocumentType,
    text: str,
    provider_hint: Optional[str] = None,
) -> BaseDocumentParser:
    """
    Get the appropriate parser for a document.

    Args:
        document_type: Type of document (INSURANCE, etc.)
        text: Extracted document text for auto-detection
        provider_hint: Optional hint for which provider to use

    Returns:
        Appropriate parser instance
    """
    if document_type == DocumentType.INSURANCE:
        if provider_hint:
            parser = DocumentParserRegistry.get_insurance_parser(provider_hint)
            if parser:
                return parser

        # Auto-detect based on content
        return DocumentParserRegistry.detect_insurance_parser(text)

    # For other document types, would add handling here
    raise ValueError(f"No parser available for document type: {document_type}")
