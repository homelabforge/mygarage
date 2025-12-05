"""Unified Document OCR and extraction service.

This service handles text extraction from various document types using OCR
and routes to the appropriate parser based on document type.
"""

import logging
import os
from typing import Optional, Dict, Any
from pathlib import Path

from app.services.document_parsers import (
    DocumentType,
    DocumentParserRegistry,
    InsuranceData,
    get_parser_for_document,
)

logger = logging.getLogger(__name__)

# Check if PaddleOCR is enabled
PADDLEOCR_ENABLED = os.getenv("ENABLE_PADDLEOCR", "false").lower() == "true"


class DocumentOCRService:
    """Unified service for extracting data from documents using OCR."""

    def __init__(self):
        """Initialize the OCR service."""
        self.supported_formats = {'.pdf', '.jpg', '.jpeg', '.png'}
        self._paddleocr = None

    async def extract_insurance_data(
        self,
        file_path: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        target_vin: Optional[str] = None,
        provider_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract insurance data from a document.

        Args:
            file_path: Path to the document file
            file_bytes: Raw bytes of the document (alternative to file_path)
            target_vin: Optional VIN to extract vehicle-specific data
            provider_hint: Optional hint for which provider parser to use

        Returns:
            Dictionary containing extracted insurance data
        """
        # Extract text from document
        if file_path:
            text = await self._extract_text_from_file(file_path)
        elif file_bytes:
            text = await self._extract_text_from_bytes(file_bytes)
        else:
            raise ValueError("Either file_path or file_bytes must be provided")

        if not text or len(text.strip()) < 30:
            logger.warning("Insufficient text extracted from document")
            return {
                "success": False,
                "error": "Could not extract text from document",
                "raw_text": text,
            }

        # Get appropriate parser
        parser = get_parser_for_document(
            DocumentType.INSURANCE,
            text,
            provider_hint=provider_hint,
        )

        # Parse the document
        try:
            data = parser.parse(text, target_vin=target_vin)
            result = data.to_dict()
            result["success"] = True
            result["validation_warnings"] = data.get_validation_warnings()
            return result
        except Exception as e:
            logger.error("Error parsing insurance document: %s", e)
            return {
                "success": False,
                "error": str(e),
                "raw_text": text,
            }

    async def test_insurance_extraction(
        self,
        file_path: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        target_vin: Optional[str] = None,
        provider_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Test extraction without saving - returns full debug info.

        Args:
            file_path: Path to the document file
            file_bytes: Raw bytes of the document
            target_vin: Optional VIN for vehicle-specific extraction
            provider_hint: Optional provider hint

        Returns:
            Dictionary with extraction results and debug info
        """
        result = {
            "success": False,
            "parser_name": None,
            "provider_detected": None,
            "raw_text": None,
            "extracted_data": None,
            "validation_warnings": [],
            "error": None,
        }

        try:
            # Extract text
            if file_path:
                text = await self._extract_text_from_file(file_path)
            elif file_bytes:
                text = await self._extract_text_from_bytes(file_bytes)
            else:
                raise ValueError("Either file_path or file_bytes must be provided")

            result["raw_text"] = text

            if not text or len(text.strip()) < 30:
                result["error"] = "Insufficient text extracted from document"
                return result

            # Get parser
            parser = get_parser_for_document(
                DocumentType.INSURANCE,
                text,
                provider_hint=provider_hint,
            )

            result["parser_name"] = parser.PARSER_NAME
            result["provider_detected"] = getattr(parser, 'PROVIDER_NAME', None)

            # Parse
            data = parser.parse(text, target_vin=target_vin)
            result["extracted_data"] = data.to_dict()
            result["validation_warnings"] = data.get_validation_warnings()
            result["success"] = True

        except Exception as e:
            logger.error("Test extraction failed: %s", e)
            result["error"] = str(e)

        return result

    async def _extract_text_from_file(self, file_path: str) -> str:
        """Extract text from a file based on its type."""
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        if path.suffix.lower() not in self.supported_formats:
            raise ValueError(f"Unsupported file format: {path.suffix}")

        if path.suffix.lower() == '.pdf':
            return await self._extract_text_from_pdf(file_path)
        else:
            return await self._extract_text_from_image(file_path)

    async def _extract_text_from_bytes(self, file_bytes: bytes, is_pdf: bool = True) -> str:
        """Extract text from raw bytes."""
        if is_pdf:
            return await self._extract_text_from_pdf_bytes(file_bytes)
        else:
            return await self._ocr_image_bytes(file_bytes)

    async def _extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file using PyMuPDF."""
        try:
            import fitz  # PyMuPDF

            text_content = []
            with fitz.open(file_path) as doc:
                for page in doc:
                    text_content.append(page.get_text())

            full_text = "\n".join(text_content)

            # If PDF has minimal text, it might be a scanned image
            if len(full_text.strip()) < 100:
                logger.info("PDF appears to be scanned, attempting OCR")
                return await self._ocr_pdf(file_path)

            return full_text

        except ImportError:
            logger.warning("PyMuPDF not installed, falling back to OCR")
            return await self._ocr_pdf(file_path)
        except Exception as e:
            logger.error("Error extracting text from PDF: %s", e)
            return ""

    async def _extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes."""
        try:
            import fitz  # PyMuPDF
            import io

            text_content = []
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                for page in doc:
                    text_content.append(page.get_text())

            full_text = "\n".join(text_content)

            # If PDF has minimal text, OCR it
            if len(full_text.strip()) < 100:
                logger.info("PDF appears to be scanned, attempting OCR")
                return await self._ocr_pdf_bytes(pdf_bytes)

            return full_text

        except ImportError:
            logger.error("PyMuPDF not installed - cannot extract text from PDF")
            return ""
        except Exception as e:
            logger.error("Error extracting text from PDF bytes: %s", e)
            return ""

    async def _ocr_pdf(self, file_path: str) -> str:
        """OCR a PDF by converting to images first."""
        try:
            import fitz  # PyMuPDF

            text_content = []
            with fitz.open(file_path) as doc:
                for page_num, page in enumerate(doc):
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_data = pix.tobytes("png")
                    text = await self._ocr_image_bytes(img_data)
                    if text:
                        text_content.append(text)

            return "\n".join(text_content)
        except Exception as e:
            logger.error("Error OCR-ing PDF: %s", e)
            return ""

    async def _ocr_pdf_bytes(self, pdf_bytes: bytes) -> str:
        """OCR a PDF from bytes."""
        try:
            import fitz

            text_content = []
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_data = pix.tobytes("png")
                    text = await self._ocr_image_bytes(img_data)
                    if text:
                        text_content.append(text)

            return "\n".join(text_content)
        except Exception as e:
            logger.error("Error OCR-ing PDF bytes: %s", e)
            return ""

    async def _extract_text_from_image(self, file_path: str) -> str:
        """Extract text from an image file using OCR."""
        if PADDLEOCR_ENABLED:
            try:
                text = await self._paddleocr_extract(file_path)
                if text:
                    return text
            except Exception as e:
                logger.warning("PaddleOCR failed, falling back to Tesseract: %s", e)

        try:
            from PIL import Image
            import pytesseract

            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text
        except ImportError:
            logger.warning("PIL or pytesseract not installed")
            return ""
        except Exception as e:
            logger.error("Error extracting text from image: %s", e)
            return ""

    async def _ocr_image_bytes(self, img_bytes: bytes) -> str:
        """OCR image from bytes."""
        if PADDLEOCR_ENABLED:
            try:
                text = await self._paddleocr_extract_bytes(img_bytes)
                if text:
                    return text
            except Exception as e:
                logger.warning("PaddleOCR bytes failed: %s", e)

        try:
            from PIL import Image
            import pytesseract
            import io

            image = Image.open(io.BytesIO(img_bytes))
            return pytesseract.image_to_string(image)
        except Exception as e:
            logger.error("Error OCR-ing image bytes: %s", e)
            return ""

    async def _paddleocr_extract(self, file_path: str) -> str:
        """Extract text using PaddleOCR."""
        try:
            if self._paddleocr is None:
                from paddleocr import PaddleOCR
                self._paddleocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)

            result = self._paddleocr.ocr(file_path, cls=True)

            lines = []
            for line in result:
                if line:
                    for word_info in line:
                        if word_info and len(word_info) > 1:
                            text = word_info[1][0]
                            lines.append(text)

            return "\n".join(lines)

        except ImportError:
            logger.warning("PaddleOCR not installed")
            return ""
        except Exception as e:
            logger.error("PaddleOCR extraction failed: %s", e)
            return ""

    async def _paddleocr_extract_bytes(self, img_bytes: bytes) -> str:
        """Extract text from image bytes using PaddleOCR."""
        try:
            import numpy as np
            from PIL import Image
            import io

            if self._paddleocr is None:
                from paddleocr import PaddleOCR
                self._paddleocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)

            image = Image.open(io.BytesIO(img_bytes))
            img_array = np.array(image)

            result = self._paddleocr.ocr(img_array, cls=True)

            lines = []
            for line in result:
                if line:
                    for word_info in line:
                        if word_info and len(word_info) > 1:
                            text = word_info[1][0]
                            lines.append(text)

            return "\n".join(lines)

        except Exception as e:
            logger.error("PaddleOCR bytes extraction failed: %s", e)
            return ""

    @staticmethod
    def list_available_insurance_parsers() -> list[dict]:
        """List all available insurance parsers."""
        return DocumentParserRegistry.list_insurance_parsers()

    @staticmethod
    def get_ocr_status() -> dict:
        """Get OCR engine status."""
        status = {
            "pymupdf_available": False,
            "tesseract_available": False,
            "paddleocr_enabled": PADDLEOCR_ENABLED,
            "paddleocr_available": False,
        }

        try:
            import fitz
            status["pymupdf_available"] = True
        except ImportError:
            pass  # PyMuPDF is optional - status remains False if not installed

        try:
            import pytesseract
            status["tesseract_available"] = True
        except ImportError:
            pass  # Tesseract is optional - status remains False if not installed

        if PADDLEOCR_ENABLED:
            try:
                from paddleocr import PaddleOCR
                status["paddleocr_available"] = True
            except ImportError:
                pass  # PaddleOCR is optional - status remains False if not installed

        return status


# Singleton instance
document_ocr_service = DocumentOCRService()
