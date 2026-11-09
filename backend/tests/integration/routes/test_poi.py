"""
Integration tests for POI discovery routes.

Tests POI search, save, and recommendations endpoints.
"""

import logging
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.address_book import AddressBookEntry
from tests._logged import problems

# Usage far above anything the rest of the suite records.
_HEAVY_USE = 10_000


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

    async def test_an_empty_poi_category_is_saved_as_none(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """An empty poi_category used to skip the category check and land as "",
        which the POI list counts as categorised."""
        name = f"Empty POI Category {uuid.uuid4().hex[:8]}"
        try:
            response = await client.post(
                "/api/poi/save",
                headers=auth_headers,
                json={"business_name": name, "poi_category": ""},
            )
            assert response.status_code == 201, response.text
            stored = (
                await db_session.execute(
                    select(AddressBookEntry.poi_category).where(
                        AddressBookEntry.id == response.json()["id"]
                    )
                )
            ).one()
            assert stored.poi_category is None
        finally:
            await db_session.rollback()
            await db_session.execute(
                delete(AddressBookEntry).where(AddressBookEntry.business_name == name)
            )
            await db_session.commit()

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

    @pytest.mark.parametrize(
        ("params", "entry"),
        [
            ({"category": "gas_station"}, {"category": "Gas Station"}),
            ({}, {"category": "Service"}),
            # What the POI Finder actually asks: no category at all.
            ({}, {"category": "Gas Station"}),
        ],
        ids=[
            "manual-gas-station-under-gas_station",
            "service-chip-with-no-category",
            "manual-gas-station-with-no-category",
        ],
    )
    async def test_recommendations_include_address_book_page_entries(
        self, client: AsyncClient, auth_headers, db_session, params, entry
    ):
        """The Address Book page stores the chip values "Gas Station" and "Service".
        The POI Finder's "used N times" list asked poi_category or an exact
        lowercase "service", so neither ever showed up there (#194)."""
        name = f"ZZ Rec {uuid.uuid4().hex[:8]}"
        try:
            # Far above any other row's usage, so the limit can't push it out.
            db_session.add(AddressBookEntry(business_name=name, usage_count=_HEAVY_USE, **entry))
            await db_session.commit()

            response = await client.get(
                "/api/poi/recommendations",
                headers=auth_headers,
                params={**params, "limit": 50},
            )

            assert response.status_code == 200, response.text
            names = [r["business_name"] for r in response.json()["recommendations"]]
            assert name in names
        finally:
            await db_session.rollback()
            await db_session.execute(
                delete(AddressBookEntry).where(AddressBookEntry.business_name == name)
            )
            await db_session.commit()

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

    async def test_search_error_does_not_leak_exception(
        self, client: AsyncClient, auth_headers, caplog, caplog_only
    ):
        """Test that internal errors return generic message, not exception details."""
        with (
            caplog_only("app.routes.poi"),
            patch(
                "app.routes.poi.POIDiscoveryService",
                return_value=AsyncMock(
                    search_nearby_pois=AsyncMock(
                        side_effect=RuntimeError("secret db connection string")
                    )
                ),
            ),
        ):
            response = await client.post(
                "/api/poi/search",
                json={
                    "latitude": 41.8781,
                    "longitude": -87.6298,
                    "categories": ["auto_shop"],
                },
                headers=auth_headers,
            )

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "secret db connection string" not in detail
        assert detail == "Failed to search for POIs"
        # The log keeps what the response hides.
        (logged,) = problems(caplog, "app.routes.poi")
        assert logged.levelno == logging.ERROR
        assert logged.exc_info is not None
        assert str(logged.exc_info[1]) == "secret db connection string"
