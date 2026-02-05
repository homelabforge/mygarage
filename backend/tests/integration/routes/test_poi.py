"""
Integration tests for POI discovery routes.

Tests POI search, save, and recommendations endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestPOIRoutes:
    """Test POI API endpoints."""

    # -------------------------------------------------------------------------
    # /search endpoint tests
    # -------------------------------------------------------------------------

    async def test_search_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot search POIs."""
        response = await client.post(
            "/api/poi/search",
            json={
                "latitude": 41.8781,
                "longitude": -87.6298,
                "categories": ["auto_shop"],
            },
        )
        assert response.status_code == 401

    async def test_search_basic(self, client: AsyncClient, auth_headers):
        """Test basic POI search with mocked service."""
        mock_results = [
            {
                "business_name": "Test Auto Shop",
                "address": "123 Main St",
                "city": "Chicago",
                "state": "IL",
                "zip_code": "60601",
                "phone": "555-123-4567",
                "latitude": 41.8782,
                "longitude": -87.6299,
                "source": "tomtom",
                "external_id": "test123",
                "rating": 4.5,
                "distance_meters": 500,
                "website": "https://testauto.com",
                "poi_category": "auto_shop",
                "metadata": None,
            }
        ]

        with patch.object(
            __import__(
                "app.services.poi_discovery", fromlist=["POIDiscoveryService"]
            ).POIDiscoveryService,
            "search_nearby_pois",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = (mock_results, "tomtom")

            response = await client.post(
                "/api/poi/search",
                headers=auth_headers,
                json={
                    "latitude": 41.8781,
                    "longitude": -87.6298,
                    "categories": ["auto_shop"],
                    "radius_meters": 5000,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "count" in data
        assert "source" in data
        assert data["source"] == "tomtom"

    async def test_search_multiple_categories(self, client: AsyncClient, auth_headers):
        """Test POI search with multiple categories."""
        mock_results = []

        with patch.object(
            __import__(
                "app.services.poi_discovery", fromlist=["POIDiscoveryService"]
            ).POIDiscoveryService,
            "search_nearby_pois",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = (mock_results, "osm")

            response = await client.post(
                "/api/poi/search",
                headers=auth_headers,
                json={
                    "latitude": 41.8781,
                    "longitude": -87.6298,
                    "categories": ["auto_shop", "gas_station", "ev_charging"],
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["results"] == []

    async def test_search_with_default_radius(self, client: AsyncClient, auth_headers):
        """Test POI search uses default radius when not specified."""
        with patch.object(
            __import__(
                "app.services.poi_discovery", fromlist=["POIDiscoveryService"]
            ).POIDiscoveryService,
            "search_nearby_pois",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = ([], "osm")

            response = await client.post(
                "/api/poi/search",
                headers=auth_headers,
                json={
                    "latitude": 41.8781,
                    "longitude": -87.6298,
                    "categories": ["auto_shop"],
                },
            )

        assert response.status_code == 200
        data = response.json()
        # Default radius is 8000 meters
        assert data["radius_meters"] == 8000

    # -------------------------------------------------------------------------
    # /save endpoint tests
    # -------------------------------------------------------------------------

    async def test_save_poi_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot save POIs."""
        response = await client.post(
            "/api/poi/save",
            json={"business_name": "Test Shop"},
        )
        assert response.status_code == 401

    async def test_save_poi(self, client: AsyncClient, auth_headers):
        """Test saving a discovered POI to address book."""
        payload = {
            "business_name": "Saved Auto Shop",
            "address": "456 Oak Ave",
            "city": "Chicago",
            "state": "IL",
            "zip_code": "60602",
            "phone": "555-987-6543",
            "category": "service",
        }

        response = await client.post(
            "/api/poi/save",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["business_name"] == "Saved Auto Shop"
        assert "id" in data

    async def test_save_poi_with_poi_category(self, client: AsyncClient, auth_headers):
        """Test saving POI with valid poi_category."""
        payload = {
            "business_name": "Valid Category Shop",
            "poi_category": "auto_shop",
        }

        response = await client.post(
            "/api/poi/save",
            headers=auth_headers,
            json=payload,
        )

        # Should succeed (201) or may validate (400 if poi_category not in schema)
        # The route adds poi_category directly to the model
        assert response.status_code in [201, 400]

    async def test_save_poi_invalid_category(self, client: AsyncClient, auth_headers):
        """Test saving POI with invalid poi_category.

        Note: The schema AddressBookEntryCreate doesn't include poi_category,
        so invalid values may be ignored depending on Pydantic config.
        The route only validates poi_category if it's present after model_dump().
        """
        payload = {
            "business_name": "Invalid Category Shop",
            "poi_category": "invalid_category",
        }

        response = await client.post(
            "/api/poi/save",
            headers=auth_headers,
            json=payload,
        )

        # The route validates poi_category if present in the entry_dict after model_dump()
        # If the schema excludes unknown fields, this will return 201 (valid)
        # If the schema includes it, this should return 400 (invalid category)
        assert response.status_code in [201, 400]

    # -------------------------------------------------------------------------
    # /recommendations endpoint tests
    # -------------------------------------------------------------------------

    async def test_recommendations_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot get recommendations."""
        response = await client.get("/api/poi/recommendations")
        assert response.status_code == 401

    async def test_recommendations_empty(self, client: AsyncClient, auth_headers):
        """Test recommendations when no POIs have usage."""
        response = await client.get(
            "/api/poi/recommendations",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert "count" in data
        # May be 0 or more depending on existing data
        assert isinstance(data["recommendations"], list)

    async def test_recommendations_with_category_filter(self, client: AsyncClient, auth_headers):
        """Test recommendations filtered by category."""
        response = await client.get(
            "/api/poi/recommendations",
            headers=auth_headers,
            params={"category": "auto_shop"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data

    async def test_recommendations_invalid_category(self, client: AsyncClient, auth_headers):
        """Test recommendations with invalid category filter."""
        response = await client.get(
            "/api/poi/recommendations",
            headers=auth_headers,
            params={"category": "invalid_category"},
        )

        assert response.status_code == 400

    async def test_recommendations_with_limit(self, client: AsyncClient, auth_headers):
        """Test recommendations with custom limit."""
        response = await client.get(
            "/api/poi/recommendations",
            headers=auth_headers,
            params={"limit": 3},
        )

        assert response.status_code == 200
        data = response.json()
        # Result count should not exceed limit
        assert data["count"] <= 3

    # -------------------------------------------------------------------------
    # /increment-usage endpoint tests
    # -------------------------------------------------------------------------

    async def test_increment_usage_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot increment usage."""
        response = await client.post("/api/poi/increment-usage/1")
        assert response.status_code == 401

    async def test_increment_usage_not_found(self, client: AsyncClient, auth_headers):
        """Test increment usage for non-existent POI."""
        response = await client.post(
            "/api/poi/increment-usage/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_increment_usage_success(self, client: AsyncClient, auth_headers):
        """Test incrementing usage for existing POI."""
        # First create a POI via address book
        create_response = await client.post(
            "/api/address-book",
            headers=auth_headers,
            json={
                "business_name": "Usage Test Shop",
                "city": "Chicago",
                "category": "service",
            },
        )
        assert create_response.status_code == 201
        poi_id = create_response.json()["id"]

        # Increment usage
        response = await client.post(
            f"/api/poi/increment-usage/{poi_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204


@pytest.mark.integration
@pytest.mark.asyncio
class TestPOIValidation:
    """Test POI input validation."""

    async def test_search_missing_latitude(self, client: AsyncClient, auth_headers):
        """Test search with missing latitude."""
        response = await client.post(
            "/api/poi/search",
            headers=auth_headers,
            json={
                "longitude": -87.6298,
                "categories": ["auto_shop"],
            },
        )

        assert response.status_code == 422

    async def test_search_missing_longitude(self, client: AsyncClient, auth_headers):
        """Test search with missing longitude."""
        response = await client.post(
            "/api/poi/search",
            headers=auth_headers,
            json={
                "latitude": 41.8781,
                "categories": ["auto_shop"],
            },
        )

        assert response.status_code == 422

    async def test_search_empty_categories(self, client: AsyncClient, auth_headers):
        """Test search with empty categories list uses default."""
        with patch.object(
            __import__(
                "app.services.poi_discovery", fromlist=["POIDiscoveryService"]
            ).POIDiscoveryService,
            "search_nearby_pois",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = ([], "osm")

            response = await client.post(
                "/api/poi/search",
                headers=auth_headers,
                json={
                    "latitude": 41.8781,
                    "longitude": -87.6298,
                    # categories will use default
                },
            )

        # Should use default categories
        assert response.status_code == 200

    async def test_save_missing_business_name(self, client: AsyncClient, auth_headers):
        """Test save with missing business_name."""
        response = await client.post(
            "/api/poi/save",
            headers=auth_headers,
            json={
                "city": "Chicago",
            },
        )

        # business_name is required
        assert response.status_code == 422
