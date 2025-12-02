"""
Integration tests for VIN-related routes.

Tests VIN decoding and validation endpoints.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch


@pytest.mark.integration
@pytest.mark.asyncio
class TestVINRoutes:
    """Test VIN API endpoints."""

    @patch("app.services.nhtsa.NHTSAService.decode_vin")
    async def test_decode_vin_post_valid(
        self, mock_decode, client: AsyncClient, auth_headers
    ):
        """Test VIN decoding via POST endpoint with valid VIN."""
        # Mock NHTSA response
        mock_decode.return_value = {
            "vin": "1HGBH41JXMN109186",
            "make": "HONDA",
            "model": "Accord",
            "year": 2018,
            "body_class": "Sedan",
            "engine": "2.0L I4",
            "transmission": "Automatic",
        }

        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGBH41JXMN109186"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == "1HGBH41JXMN109186"
        assert data["make"] == "HONDA"
        assert data["model"] == "Accord"
        assert data["year"] == 2018

    @patch("app.services.nhtsa.NHTSAService.decode_vin")
    async def test_decode_vin_get_valid(
        self, mock_decode, client: AsyncClient, auth_headers
    ):
        """Test VIN decoding via GET endpoint with valid VIN."""
        # Mock NHTSA response
        mock_decode.return_value = {
            "vin": "1HGBH41JXMN109186",
            "make": "HONDA",
            "model": "Accord",
            "year": 2018,
            "body_class": "Sedan",
        }

        response = await client.get(
            "/api/vin/decode/1HGBH41JXMN109186",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == "1HGBH41JXMN109186"
        assert data["make"] == "HONDA"

    async def test_decode_vin_invalid_length(
        self, client: AsyncClient, auth_headers
    ):
        """Test that VINs with invalid length are rejected."""
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "INVALID"},  # Too short
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    async def test_decode_vin_invalid_characters(
        self, client: AsyncClient, auth_headers
    ):
        """Test that VINs with invalid characters are rejected."""
        # VIN with letter 'I' (not allowed)
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGBH41JXMNI09186"},
            headers=auth_headers,
        )

        assert response.status_code == 400

    @patch("app.services.nhtsa.NHTSAService.decode_vin")
    async def test_decode_vin_nhtsa_timeout(
        self, mock_decode, client: AsyncClient, auth_headers
    ):
        """Test handling of NHTSA API timeout."""
        import httpx
        mock_decode.side_effect = httpx.TimeoutException("Request timed out")

        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGBH41JXMN109186"},
            headers=auth_headers,
        )

        assert response.status_code == 504  # Gateway timeout
        data = response.json()
        assert "timeout" in data["detail"].lower()

    @patch("app.services.nhtsa.NHTSAService.decode_vin")
    async def test_decode_vin_nhtsa_connection_error(
        self, mock_decode, client: AsyncClient, auth_headers
    ):
        """Test handling of NHTSA API connection errors."""
        import httpx
        mock_decode.side_effect = httpx.ConnectError("Cannot connect")

        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGBH41JXMN109186"},
            headers=auth_headers,
        )

        assert response.status_code == 503  # Service unavailable
        data = response.json()
        assert "connect" in data["detail"].lower()

    async def test_validate_vin_valid(
        self, client: AsyncClient, auth_headers
    ):
        """Test VIN validation endpoint with valid VIN."""
        response = await client.get(
            "/api/vin/validate/1HGBH41JXMN109186",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["vin"] == "1HGBH41JXMN109186"
        assert "message" in data

    async def test_validate_vin_invalid_length(
        self, client: AsyncClient, auth_headers
    ):
        """Test VIN validation with invalid length."""
        response = await client.get(
            "/api/vin/validate/SHORT",
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert data["valid"] is False
        assert "error" in data

    async def test_validate_vin_invalid_characters(
        self, client: AsyncClient, auth_headers
    ):
        """Test VIN validation with invalid characters."""
        # VIN with letter 'I' (not allowed)
        response = await client.get(
            "/api/vin/validate/1HGBH41JXMNI09186",
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert data["valid"] is False
        assert "error" in data

    async def test_validate_vin_case_insensitive(
        self, client: AsyncClient, auth_headers
    ):
        """Test that VIN validation handles lowercase input."""
        response = await client.get(
            "/api/vin/validate/1hgbh41jxmn109186",  # lowercase
            headers=auth_headers,
        )

        assert response.status_code in [200, 400]  # Depends on check digit validation
        data = response.json()
        # VIN should be normalized to uppercase
        assert data["vin"] == "1HGBH41JXMN109186"

    async def test_decode_vin_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot decode VINs."""
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGBH41JXMN109186"},
        )

        assert response.status_code == 401

    async def test_validate_vin_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot validate VINs."""
        response = await client.get("/api/vin/validate/1HGBH41JXMN109186")

        assert response.status_code == 401

    @patch("app.services.nhtsa.NHTSAService.decode_vin")
    async def test_decode_vin_with_special_characters(
        self, mock_decode, client: AsyncClient, auth_headers
    ):
        """Test VIN decoding with whitespace and mixed case."""
        # Mock NHTSA response
        mock_decode.return_value = {
            "vin": "1HGBH41JXMN109186",
            "make": "HONDA",
            "model": "Accord",
            "year": 2018,
        }

        # VIN with leading/trailing whitespace and lowercase
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "  1hgbh41jxmn109186  "},
            headers=auth_headers,
        )

        # Should be normalized and accepted
        assert response.status_code in [200, 400]

    async def test_validate_vin_empty_string(
        self, client: AsyncClient, auth_headers
    ):
        """Test VIN validation with empty string."""
        response = await client.get(
            "/api/vin/validate/",
            headers=auth_headers,
        )

        # Should return 404 (no VIN parameter) or validation error
        assert response.status_code in [400, 404, 422]
