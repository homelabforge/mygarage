"""
Integration tests for photo upload routes.

Tests photo upload, retrieval, and deletion.
"""

import pytest
from httpx import AsyncClient
from io import BytesIO


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
class TestPhotoRoutes:
    """Test photo API endpoints."""

    async def test_upload_photo(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test uploading a photo to a vehicle."""
        # Create a fake image file (1x1 PNG)
        fake_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-"
            b"\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/photos",
            files={"file": ("test_photo.png", BytesIO(fake_png), "image/png")},
            data={"caption": "Test photo", "set_as_main": "false"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "filename" in data or "id" in data

    async def test_list_photos(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test listing photos for a vehicle."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/photos",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or ("photos" in data)

    async def test_delete_photo(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a photo."""
        # First upload a photo
        fake_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-"
            b"\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        upload_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/photos",
            files={"file": ("test_photo.png", BytesIO(fake_png), "image/png")},
            headers=auth_headers,
        )

        if upload_response.status_code == 201:
            photo_data = upload_response.json()
            photo_id = photo_data.get("id") or photo_data.get("filename")

            # Delete the photo
            if photo_id:
                delete_response = await client.delete(
                    f"/api/photos/{photo_id}",
                    headers=auth_headers,
                )

                assert delete_response.status_code in [204, 200]

    async def test_upload_invalid_format(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that non-image files are rejected."""
        # Create a fake text file
        fake_text = b"This is not an image"

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/photos",
            files={"file": ("test.txt", BytesIO(fake_text), "text/plain")},
            headers=auth_headers,
        )

        assert response.status_code in [
            400,
            415,
            422,
        ]  # Bad request or unsupported media type

    async def test_upload_exceeds_size_limit(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that oversized files are rejected."""
        # Create a large fake file (20MB)
        large_file = b"x" * (20 * 1024 * 1024)

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/photos",
            files={"file": ("large.png", BytesIO(large_file), "image/png")},
            headers=auth_headers,
        )

        assert response.status_code in [400, 413, 422]  # Payload too large

    async def test_upload_photo_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot upload photos."""
        fake_png = b"\x89PNG\r\n\x1a\n"

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/photos",
            files={"file": ("test.png", BytesIO(fake_png), "image/png")},
        )

        assert response.status_code == 401

    async def test_set_main_photo(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test setting a photo as the main photo."""
        fake_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-"
            b"\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/photos",
            files={"file": ("main_photo.png", BytesIO(fake_png), "image/png")},
            data={"set_as_main": "true"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        # Check if response indicates it's the main photo
        if "is_main" in data:
            assert data["is_main"] is True

    async def test_upload_photo_vehicle_not_found(
        self, client: AsyncClient, auth_headers
    ):
        """Test uploading photo to non-existent vehicle."""
        fake_png = b"\x89PNG\r\n\x1a\n"

        response = await client.post(
            "/api/vehicles/INVALIDVIN1234567/photos",
            files={"file": ("test.png", BytesIO(fake_png), "image/png")},
            headers=auth_headers,
        )

        assert response.status_code == 404
