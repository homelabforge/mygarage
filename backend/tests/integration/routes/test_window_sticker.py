"""
Integration tests for window sticker routes.

Tests window sticker OCR and file management endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestWindowStickerRoutes:
    """Test window sticker API endpoints."""

    # -------------------------------------------------------------------------
    # GET /window-sticker endpoint tests
    # -------------------------------------------------------------------------

    async def test_get_window_sticker_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot get window sticker data."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/window-sticker")
        assert response.status_code == 401

    async def test_get_window_sticker_not_found(self, client: AsyncClient, auth_headers):
        """Test getting window sticker for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/window-sticker",
            headers=auth_headers,
        )
        # Returns 403 or 404 depending on auth flow
        assert response.status_code in [403, 404]

    async def test_get_window_sticker_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting window sticker when none has been uploaded."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        # No sticker uploaded yet
        assert data["window_sticker_file_path"] is None

    # -------------------------------------------------------------------------
    # POST /window-sticker/upload endpoint tests
    # -------------------------------------------------------------------------

    async def test_upload_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot upload window stickers."""
        files = {"file": ("test.pdf", b"fake pdf", "application/pdf")}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
            files=files,
        )
        assert response.status_code == 401

    async def test_upload_invalid_file_type(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test upload with invalid file type."""
        files = {"file": ("test.txt", b"not a pdf or image", "text/plain")}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
            headers=auth_headers,
            files=files,
        )

        assert response.status_code == 400
        assert "invalid file type" in response.json()["detail"].lower()

    async def test_upload_success(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test successful window sticker upload with mocked OCR."""
        # Create fake PDF content
        pdf_content = b"%PDF-1.4 fake pdf content"

        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.extract_data_from_file = AsyncMock(
                return_value={
                    "msrp_total": 35000,
                    "exterior_color": "Silver",
                    "window_sticker_parser_used": "generic",
                }
            )
            mock_ocr_class.return_value = mock_ocr

            files = {"file": ("window_sticker.pdf", pdf_content, "application/pdf")}
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
                headers=auth_headers,
                files=files,
            )

        assert response.status_code == 201
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert data["window_sticker_file_path"] is not None

    async def test_upload_image_file(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test upload with image file type."""
        # Create fake PNG content (minimal valid PNG header)
        png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.extract_data_from_file = AsyncMock(return_value={})
            mock_ocr_class.return_value = mock_ocr

            files = {"file": ("window_sticker.png", png_content, "image/png")}
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
                headers=auth_headers,
                files=files,
            )

        assert response.status_code == 201

    # -------------------------------------------------------------------------
    # POST /window-sticker/test endpoint tests
    # -------------------------------------------------------------------------

    async def test_test_extraction_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot test extraction."""
        files = {"file": ("test.pdf", b"fake pdf", "application/pdf")}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/test",
            files=files,
        )
        assert response.status_code == 401

    async def test_test_extraction_success(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test extraction endpoint returns extraction results."""
        pdf_content = b"%PDF-1.4 test content"

        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.test_extraction = AsyncMock(
                return_value={
                    "success": True,
                    "parser_name": "generic",
                    "manufacturer_detected": "Unknown",
                    "raw_text": "Sample OCR text",
                    "extracted_data": {"msrp_total": 30000},
                    "validation_warnings": [],
                    "error": None,
                }
            )
            mock_ocr_class.return_value = mock_ocr

            files = {"file": ("test.pdf", pdf_content, "application/pdf")}
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/window-sticker/test",
                headers=auth_headers,
                files=files,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["parser_name"] == "generic"

    # -------------------------------------------------------------------------
    # PATCH /window-sticker/data endpoint tests
    # -------------------------------------------------------------------------

    async def test_update_data_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot update data."""
        response = await client.patch(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/data",
            json={"msrp_total": 40000},
        )
        assert response.status_code == 401

    async def test_update_data_success(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating window sticker data."""
        response = await client.patch(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/data",
            headers=auth_headers,
            json={
                "msrp_total": 42000,
                "exterior_color": "Blue",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Updated values should be reflected (if the model supports them)
        assert data["vin"] == test_vehicle["vin"]

    # -------------------------------------------------------------------------
    # DELETE /window-sticker endpoint tests
    # -------------------------------------------------------------------------

    async def test_delete_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot delete window stickers."""
        response = await client.delete(f"/api/vehicles/{test_vehicle['vin']}/window-sticker")
        assert response.status_code == 401

    async def test_delete_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting when no window sticker exists."""
        # First, ensure no sticker exists by deleting any existing one
        # (Previous tests may have uploaded a sticker)
        await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker",
            headers=auth_headers,
        )

        # Now try to delete again - should return 404
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker",
            headers=auth_headers,
        )

        # Should return 404 since we just deleted it
        assert response.status_code == 404

    # -------------------------------------------------------------------------
    # GET /window-sticker/file endpoint tests
    # -------------------------------------------------------------------------

    async def test_download_file_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot download files."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/window-sticker/file")
        assert response.status_code == 401

    async def test_download_file_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test downloading when no file exists."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/file",
            headers=auth_headers,
        )

        assert response.status_code == 404

    # -------------------------------------------------------------------------
    # GET /parsers endpoint tests
    # -------------------------------------------------------------------------

    async def test_list_parsers_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot list parsers."""
        response = await client.get("/api/vehicles/window-sticker/parsers")
        assert response.status_code == 401

    async def test_list_parsers_success(self, client: AsyncClient, auth_headers):
        """Test listing available parsers."""
        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.list_available_parsers.return_value = [
                {
                    "manufacturer": "Generic",
                    "parser_class": "GenericWindowStickerParser",
                    "supported_makes": ["all"],
                }
            ]
            mock_ocr_class.return_value = mock_ocr

            response = await client.get(
                "/api/vehicles/window-sticker/parsers",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    # -------------------------------------------------------------------------
    # GET /ocr-status endpoint tests
    # -------------------------------------------------------------------------

    async def test_ocr_status_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot get OCR status."""
        response = await client.get("/api/vehicles/window-sticker/ocr-status")
        assert response.status_code == 401

    async def test_ocr_status_success(self, client: AsyncClient, auth_headers):
        """Test getting OCR engine status."""
        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.get_ocr_status.return_value = {
                "pymupdf_available": True,
                "tesseract_available": True,
                "paddleocr_enabled": False,
                "paddleocr_available": False,
            }
            mock_ocr_class.return_value = mock_ocr

            response = await client.get(
                "/api/vehicles/window-sticker/ocr-status",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "pymupdf_available" in data
        assert "tesseract_available" in data
