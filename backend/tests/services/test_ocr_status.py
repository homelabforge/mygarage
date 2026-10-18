"""Tests for the OCR status both OCR services report: tesseract means the binary."""

from typing import Any
from unittest.mock import patch

import pytesseract
import pytest

from app.services.document_ocr import DocumentOCRService
from app.services.window_sticker_ocr import WindowStickerOCRService

STATUS_GETTERS = [
    pytest.param(DocumentOCRService.get_ocr_status, id="document"),
    pytest.param(WindowStickerOCRService.get_ocr_status, id="window_sticker"),
]


@pytest.mark.parametrize("get_status", STATUS_GETTERS)
def test_tesseract_unavailable_without_binary(get_status: Any) -> None:
    """pytesseract imports without the engine, which is not OCR being available."""
    with patch.object(
        pytesseract,
        "get_tesseract_version",
        side_effect=pytesseract.TesseractNotFoundError(),
    ):
        assert get_status()["tesseract_available"] is False


@pytest.mark.parametrize("get_status", STATUS_GETTERS)
def test_tesseract_available_with_binary(get_status: Any) -> None:
    """The binary answering --version is what counts as available."""
    with patch.object(pytesseract, "get_tesseract_version", return_value="5.5.0"):
        assert get_status()["tesseract_available"] is True
