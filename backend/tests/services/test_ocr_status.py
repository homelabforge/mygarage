"""Tests for the OCR status both OCR services report: tesseract means the binary."""

import subprocess
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

# What get_tesseract_version raises: no binary on PATH, or one that exits non-zero.
PROBE_FAILURES = [
    pytest.param(pytesseract.TesseractNotFoundError(), id="not_found"),
    pytest.param(subprocess.CalledProcessError(1, ["tesseract", "--version"]), id="exits_nonzero"),
]


@pytest.mark.parametrize("error", PROBE_FAILURES)
@pytest.mark.parametrize("get_status", STATUS_GETTERS)
def test_tesseract_unavailable_without_working_binary(get_status: Any, error: Exception) -> None:
    """pytesseract imports without the engine, which is not OCR being available."""
    with patch.object(pytesseract, "get_tesseract_version", side_effect=error):
        assert get_status()["tesseract_available"] is False


@pytest.mark.parametrize("get_status", STATUS_GETTERS)
def test_tesseract_available_when_binary_answers(get_status: Any) -> None:
    """The binary answering --version is what counts as available."""
    with patch.object(pytesseract, "get_tesseract_version", return_value="5.5.0") as probe:
        assert get_status()["tesseract_available"] is True
    probe.assert_called_once_with(cached=True)
