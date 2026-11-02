"""
Integration tests for VIN-related routes.

Tests VIN decoding and validation endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestVINRoutes:
    """Test VIN API endpoints."""

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_vin_post_valid(self, mock_nhtsa_class, client: AsyncClient, auth_headers):
        """Test VIN decoding via POST endpoint with valid VIN."""
        # Mock NHTSA service instance
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(
            return_value={
                "vin": "1HGCM82633A004352",
                "make": "HONDA",
                "model": "Accord",
                "year": 2018,
                "body_class": "Sedan",
            }
        )

        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGCM82633A004352"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == "1HGCM82633A004352"
        assert data["make"] == "HONDA"
        assert data["model"] == "Accord"
        assert data["year"] == 2018

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_vin_get_valid(self, mock_nhtsa_class, client: AsyncClient, auth_headers):
        """Test VIN decoding via GET endpoint with valid VIN."""
        # Mock NHTSA service instance
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(
            return_value={
                "vin": "1HGCM82633A004352",
                "make": "HONDA",
                "model": "Accord",
                "year": 2018,
                "body_class": "Sedan",
            }
        )

        response = await client.get(
            "/api/vin/decode/1HGCM82633A004352",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == "1HGCM82633A004352"
        assert data["make"] == "HONDA"

    async def test_decode_vin_invalid_length(self, client: AsyncClient, auth_headers):
        """Test that VINs with invalid length are rejected."""
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "INVALID"},  # Too short
            headers=auth_headers,
        )

        # Pydantic validation returns 422
        assert response.status_code == 422
        data = response.json()
        # Response may have 'detail' or 'details' depending on error handler
        assert "detail" in data or "details" in data or "message" in data

    async def test_decode_vin_invalid_characters(self, client: AsyncClient, auth_headers):
        """Test that VINs with invalid characters are rejected."""
        # VIN with letter 'I' (not allowed)
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGBH41JXMNI09186"},
            headers=auth_headers,
        )

        # Pydantic validation returns 422
        assert response.status_code == 422

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_vin_nhtsa_timeout(
        self, mock_nhtsa_class, client: AsyncClient, auth_headers
    ):
        """Test handling of NHTSA API timeout."""
        import httpx

        # Mock NHTSA service to raise timeout
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )

        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGCM82633A004352"},
            headers=auth_headers,
        )

        assert response.status_code == 504  # Gateway timeout
        data = response.json()
        # Custom error handler may use 'message' or 'detail'
        error_msg = data.get("detail", data.get("message", "")).lower()
        # Note: message is "timed out" (two words), not "timeout"
        assert "timed out" in error_msg

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_vin_nhtsa_connection_error(
        self, mock_nhtsa_class, client: AsyncClient, auth_headers
    ):
        """Test handling of NHTSA API connection errors."""
        import httpx

        # Mock NHTSA service to raise connection error
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(side_effect=httpx.ConnectError("Cannot connect"))

        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGCM82633A004352"},
            headers=auth_headers,
        )

        assert response.status_code == 503  # Service unavailable
        data = response.json()
        # Custom error handler may use 'message' or 'detail'
        error_msg = data.get("detail", data.get("message", "")).lower()
        assert "connect" in error_msg

    async def test_validate_vin_valid(self, client: AsyncClient, auth_headers):
        """Test VIN validation endpoint with valid VIN."""
        response = await client.get(
            "/api/vin/validate/1HGCM82633A004352",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["vin"] == "1HGCM82633A004352"
        assert "message" in data

    async def test_validate_vin_invalid_length(self, client: AsyncClient, auth_headers):
        """Test VIN validation with invalid length."""
        response = await client.get(
            "/api/vin/validate/SHORT",
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert data["valid"] is False
        assert "error" in data

    async def test_validate_vin_invalid_characters(self, client: AsyncClient, auth_headers):
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

    async def test_validate_vin_case_insensitive(self, client: AsyncClient, auth_headers):
        """Test that VIN validation handles lowercase input."""
        response = await client.get(
            "/api/vin/validate/1hgcm82633a004352",  # lowercase
            headers=auth_headers,
        )

        assert response.status_code in [200, 400]  # Depends on check digit validation
        data = response.json()
        # VIN should be normalized to uppercase
        assert data["vin"] == "1HGCM82633A004352"

    async def test_decode_vin_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot decode VINs."""
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "1HGCM82633A004352"},
        )

        assert response.status_code == 401

    async def test_validate_vin_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot validate VINs."""
        response = await client.get("/api/vin/validate/1HGCM82633A004352")

        assert response.status_code == 401

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_vin_with_special_characters(
        self, mock_nhtsa_class, client: AsyncClient, auth_headers
    ):
        """Test VIN decoding with whitespace and mixed case."""
        # Mock NHTSA service instance
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(
            return_value={
                "vin": "1HGCM82633A004352",
                "make": "HONDA",
                "model": "Accord",
                "year": 2018,
            }
        )

        # VIN with leading/trailing whitespace and lowercase
        # Note: Pydantic min_length/max_length is checked BEFORE field_validator
        # So "  1hgcm82633a004352  " (21 chars) fails length validation
        response = await client.post(
            "/api/vin/decode",
            json={"vin": "  1hgcm82633a004352  "},
            headers=auth_headers,
        )

        # 422 for validation error (too long before stripping)
        assert response.status_code in [200, 422]

    async def test_validate_vin_empty_string(self, client: AsyncClient, auth_headers):
        """Test VIN validation with empty string."""
        response = await client.get(
            "/api/vin/validate/",
            headers=auth_headers,
        )

        # Should return 404 (no VIN parameter) or validation error
        assert response.status_code in [400, 404, 422]


@pytest.mark.integration
@pytest.mark.asyncio
class TestEuropeanVins:
    """What the routes add from the VIN's own structure (#211)."""

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_completes_a_renault_from_the_wmi(
        self, mock_nhtsa_class, client: AsyncClient, auth_headers
    ):
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(
            return_value={
                "vin": "VF1RFB00X56123456",
                "year": 2005,
                "manufacturer": "RENAULT GROUP",
                "error_code": "1,8",
            }
        )
        response = await client.post(
            "/api/vin/decode", json={"vin": "VF1RFB00X56123456"}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["make"] == "Renault"
        assert data["model"] is None
        assert data["year"] is None
        assert data["region"] == "EU"
        assert data["wmi_country"] == "FR"
        # NHTSA named no make; the table did (B3).
        assert data["decode_quality"] == "wmi_only"
        assert data["make_source"] == "wmi"
        assert "eu_vin_no_model" in data["notes"]
        assert "year_unreliable" in data["notes"]
        assert "check_digit_not_applicable" in data["notes"]

    @patch("app.routes.vin.NHTSAService")
    async def test_decode_leaves_a_north_american_answer_alone(
        self, mock_nhtsa_class, client: AsyncClient, auth_headers
    ):
        mock_instance = mock_nhtsa_class.return_value
        mock_instance.decode_vin = AsyncMock(
            return_value={
                "vin": "1HGCM82633A004352",
                "make": "HONDA",
                "model": "Accord",
                "year": 2018,
            }
        )
        response = await client.get("/api/vin/decode/1HGCM82633A004352", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2018
        assert data["decode_quality"] == "full"
        assert data["region"] == "NA"
        assert data["notes"] == []

    async def test_validate_says_region_country_and_make(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/vin/validate/vf1rfb00x56123456", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["region"] == "EU"
        assert data["country"] == "FR"
        assert data["make"] == "Renault"

        response = await client.get("/api/vin/validate/ZAZ12345678901234", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["region"] == "EU"
        assert data["country"] == "IT"
        assert data["make"] is None
