"""Document parser package with type-specific implementations.

This package provides a unified parsing architecture for various document types
including window stickers and insurance policies.
"""

from .base import BaseDocumentParser, DocumentData, DocumentType
from .insurance import InsuranceDocumentParser, InsuranceData
from .registry import DocumentParserRegistry, get_parser_for_document

__all__ = [
    "BaseDocumentParser",
    "DocumentData",
    "DocumentType",
    "InsuranceDocumentParser",
    "InsuranceData",
    "DocumentParserRegistry",
    "get_parser_for_document",
]
