"""Window Sticker OCR and data extraction service."""

# pyright: reportMissingImports=false, reportArgumentType=false, reportOptionalMemberAccess=false

import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.window_sticker_parsers import (
    ParserRegistry,
    WindowStickerData,
    get_parser_for_vehicle,
)

logger = logging.getLogger(__name__)

# Check if PaddleOCR is enabled
PADDLEOCR_ENABLED = os.getenv("ENABLE_PADDLEOCR", "false").lower() == "true"


class WindowStickerOCRService:
    """Service for extracting data from window sticker documents."""

    def __init__(self):
        """Initialize the OCR service."""
        self.supported_formats = {".pdf", ".jpg", ".jpeg", ".png"}
        self._paddleocr = None

    async def extract_data_from_file(
        self,
        file_path: str,
        vin: str | None = None,
        make: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract structured data from a window sticker file.

        Args:
            file_path: Path to the window sticker file
            vin: Optional VIN for manufacturer-specific parsing
            make: Optional make name for parser selection

        Returns:
            Dictionary containing extracted window sticker data

        Raises:
            ValueError: If file format is not supported
            FileNotFoundError: If file does not exist
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Window sticker file not found: {file_path}")

        if path.suffix.lower() not in self.supported_formats:
            raise ValueError(
                f"Unsupported file format: {path.suffix}. Supported: {self.supported_formats}"
            )

        logger.info("Extracting data from window sticker: %s", file_path)

        try:
            # Extract text based on file type
            if path.suffix.lower() == ".pdf":
                text = await self._extract_text_from_pdf(file_path)
            else:
                text = await self._extract_text_from_image(file_path)

            if not text or len(text.strip()) < 50:
                logger.warning("Insufficient text extracted from %s", file_path)
                return {}

            # Get appropriate parser based on VIN/make
            parser = get_parser_for_vehicle(vin or "", make)
            logger.info("Using parser: %s", parser.__class__.__name__)

            # Parse the extracted text
            sticker_data = parser.parse(text)

            # Convert to dict for storage
            result = self._sticker_data_to_dict(sticker_data)

            logger.info(
                "Successfully extracted data from window sticker using %s",
                parser.__class__.__name__,
            )
            return result

        except Exception as e:
            logger.error(
                "Error extracting data from window sticker %s: %s", file_path, e
            )
            # Return empty dict on error - user can manually enter data
            return {}

    async def test_extraction(
        self,
        file_path: str,
        vin: str | None = None,
        make: str | None = None,
        parser_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Test extraction without saving - returns full debug info.

        Args:
            file_path: Path to the window sticker file
            vin: Optional VIN for manufacturer-specific parsing
            make: Optional make name for parser selection
            parser_name: Optional specific parser to use

        Returns:
            Dictionary with extraction results and debug info
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Window sticker file not found: {file_path}")

        result = {
            "success": False,
            "parser_name": None,
            "manufacturer_detected": None,
            "raw_text": None,
            "extracted_data": None,
            "validation_warnings": [],
            "error": None,
        }

        try:
            # Extract text
            if path.suffix.lower() == ".pdf":
                text = await self._extract_text_from_pdf(file_path)
            else:
                text = await self._extract_text_from_image(file_path)

            result["raw_text"] = text

            if not text or len(text.strip()) < 50:
                result["error"] = "Insufficient text extracted from document"
                return result

            # Get parser
            if parser_name:
                parser = ParserRegistry.get_parser(parser_name)
                if not parser:
                    result["error"] = f"Parser not found: {parser_name}"
                    return result
            else:
                parser = get_parser_for_vehicle(vin or "", make)

            result["parser_name"] = parser.__class__.__name__
            result["manufacturer_detected"] = (
                ParserRegistry.get_manufacturer_for_vin(vin) if vin else None
            )

            # Parse
            sticker_data = parser.parse(text)
            result["extracted_data"] = sticker_data.to_dict()
            result["validation_warnings"] = sticker_data.get_validation_warnings()
            result["success"] = True

        except Exception as e:
            logger.error("Test extraction failed: %s", e)
            result["error"] = str(e)

        return result

    async def _extract_text_from_pdf(self, file_path: str) -> str:
        """
        Extract text from a PDF file using PyMuPDF.

        Args:
            file_path: Path to the PDF file

        Returns:
            Extracted text content
        """
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

    async def _ocr_pdf(self, file_path: str) -> str:
        """OCR a PDF by converting to images first."""
        try:
            import fitz  # PyMuPDF

            text_content = []
            with fitz.open(file_path) as doc:
                for _page_num, page in enumerate(doc):
                    # Render page to image
                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(2, 2)
                    )  # 2x scale for better OCR
                    img_data = pix.tobytes("png")

                    # OCR the image
                    text = await self._ocr_image_bytes(img_data)
                    if text:
                        text_content.append(text)

            return "\n".join(text_content)
        except Exception as e:
            logger.error("Error OCR-ing PDF: %s", e)
            return ""

    async def _extract_text_from_image(self, file_path: str) -> str:
        """
        Extract text from an image file using OCR.

        Args:
            file_path: Path to the image file

        Returns:
            Extracted text content
        """
        # Try PaddleOCR first if enabled
        if PADDLEOCR_ENABLED:
            try:
                text = await self._paddleocr_extract(file_path)
                if text:
                    return text
            except Exception as e:
                logger.warning("PaddleOCR failed, falling back to Tesseract: %s", e)

        # Fallback to Tesseract
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text
        except ImportError:
            logger.warning("PIL or pytesseract not installed, OCR not available")
            return ""
        except Exception as e:
            logger.error("Error extracting text from image: %s", e)
            return ""

    async def _ocr_image_bytes(self, img_bytes: bytes) -> str:
        """OCR image from bytes."""
        # Try PaddleOCR first if enabled
        if PADDLEOCR_ENABLED:
            try:
                text = await self._paddleocr_extract_bytes(img_bytes)
                if text:
                    return text
            except Exception as e:
                logger.warning("PaddleOCR bytes failed: %s", e)

        # Fallback to Tesseract
        try:
            import io

            import pytesseract
            from PIL import Image

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

                self._paddleocr = PaddleOCR(
                    use_angle_cls=True, lang="en", show_log=False
                )

            result = self._paddleocr.ocr(file_path, cls=True)

            # Extract text from result
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
            import io

            import numpy as np
            from PIL import Image

            if self._paddleocr is None:
                from paddleocr import PaddleOCR

                self._paddleocr = PaddleOCR(
                    use_angle_cls=True, lang="en", show_log=False
                )

            # Convert bytes to numpy array
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

    def _sticker_data_to_dict(self, data: WindowStickerData) -> dict[str, Any]:
        """Convert WindowStickerData to dict for database storage."""
        result = {}

        # Pricing
        if data.msrp_base:
            result["msrp_base"] = data.msrp_base
        if data.msrp_total:
            result["msrp_total"] = data.msrp_total
        if data.msrp_options:
            result["msrp_options"] = data.msrp_options
        if data.destination_charge:
            result["destination_charge"] = data.destination_charge

        # Options detail
        if data.options_detail:
            result["window_sticker_options_detail"] = {
                k: str(v) for k, v in data.options_detail.items()
            }

        # Packages
        if data.packages:
            result["window_sticker_packages"] = data.packages

        # Colors
        if data.exterior_color:
            result["exterior_color"] = data.exterior_color
        if data.interior_color:
            result["interior_color"] = data.interior_color

        # Equipment
        if data.standard_equipment:
            result["standard_equipment"] = {"items": data.standard_equipment}
        if data.optional_equipment:
            result["optional_equipment"] = {"items": data.optional_equipment}

        # Fuel economy
        if data.fuel_economy_city:
            result["fuel_economy_city"] = data.fuel_economy_city
        if data.fuel_economy_highway:
            result["fuel_economy_highway"] = data.fuel_economy_highway
        if data.fuel_economy_combined:
            result["fuel_economy_combined"] = data.fuel_economy_combined

        # Vehicle specs
        if data.engine_description:
            result["sticker_engine_description"] = data.engine_description
        if data.transmission_description:
            result["sticker_transmission_description"] = data.transmission_description
        if data.drivetrain:
            result["sticker_drivetrain"] = data.drivetrain

        # Wheel/tire
        if data.wheel_specs:
            result["wheel_specs"] = data.wheel_specs
        if data.tire_specs:
            result["tire_specs"] = data.tire_specs

        # Warranty
        if data.warranty_powertrain:
            result["warranty_powertrain"] = data.warranty_powertrain
        if data.warranty_basic:
            result["warranty_basic"] = data.warranty_basic

        # Environmental ratings
        if data.environmental_rating_ghg:
            result["environmental_rating_ghg"] = data.environmental_rating_ghg
        if data.environmental_rating_smog:
            result["environmental_rating_smog"] = data.environmental_rating_smog

        # Assembly
        if data.assembly_location:
            result["assembly_location"] = data.assembly_location

        # Parser metadata
        if data.parser_name:
            result["window_sticker_parser_used"] = data.parser_name
        if data.confidence_score:
            result["window_sticker_confidence_score"] = Decimal(
                str(data.confidence_score)
            )
        if data.extracted_vin:
            result["window_sticker_extracted_vin"] = data.extracted_vin

        return result

    @staticmethod
    def list_available_parsers() -> list[dict[str, Any]]:
        """List all available window sticker parsers."""
        return ParserRegistry.list_parsers()

    @staticmethod
    def get_ocr_status() -> dict[str, Any]:
        """Get OCR engine status."""
        status = {
            "pymupdf_available": False,
            "tesseract_available": False,
            "paddleocr_enabled": PADDLEOCR_ENABLED,
            "paddleocr_available": False,
        }

        try:
            import fitz  # noqa: F401  # type: ignore[reportUnusedImport]

            status["pymupdf_available"] = True
        except ImportError:
            pass  # PyMuPDF is optional - status remains False if not installed

        try:
            import pytesseract  # noqa: F401  # type: ignore[reportUnusedImport]

            status["tesseract_available"] = True
        except ImportError:
            pass  # Tesseract is optional - status remains False if not installed

        if PADDLEOCR_ENABLED:
            try:
                from paddleocr import PaddleOCR  # noqa: F401  # type: ignore[reportUnusedImport]

                status["paddleocr_available"] = True
            except ImportError:
                pass  # PaddleOCR is optional - status remains False if not installed

        return status
