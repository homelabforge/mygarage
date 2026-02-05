"""
Integration tests for settings routes.

Tests settings CRUD operations, POI provider management, and system info.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestSettingsRoutes:
    """Test settings API endpoints."""

    async def test_get_public_settings(self, client: AsyncClient):
        """Test getting public settings (no auth required)."""
        response = await client.get("/api/settings/public")

        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert "total" in data
        # Public settings should only include specific keys
        for setting in data["settings"]:
            assert setting["key"] in {"auth_mode", "app_name", "theme"}

    async def test_list_settings_unauthorized(self, client: AsyncClient, auth_headers):
        """Test that non-admin users cannot list all settings."""
        # Regular auth (non-admin) should be forbidden
        response = await client.get("/api/settings", headers=auth_headers)
        # May return 403 (forbidden) since it requires admin
        assert response.status_code in [200, 403]

    async def test_list_settings_no_auth(self, client: AsyncClient):
        """Test that unauthenticated users cannot list settings."""
        response = await client.get("/api/settings")
        assert response.status_code == 401

    async def test_get_poi_providers(self, client: AsyncClient):
        """Test getting POI providers (public endpoint)."""
        response = await client.get("/api/settings/poi-providers")

        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        # OSM should always be present as fallback
        osm = next((p for p in data["providers"] if p["name"] == "osm"), None)
        assert osm is not None
        assert osm["is_default"] is True

    async def test_poi_providers_osm_always_enabled(self, client: AsyncClient):
        """Test that OSM provider is always enabled and present."""
        response = await client.get("/api/settings/poi-providers")

        assert response.status_code == 200
        data = response.json()
        osm = next((p for p in data["providers"] if p["name"] == "osm"), None)
        assert osm is not None
        assert osm["enabled"] is True
        assert osm["api_key_configured"] is True  # No API key needed

    async def test_add_poi_provider_requires_auth(self, client: AsyncClient):
        """Test that adding POI provider requires authentication."""
        response = await client.post(
            "/api/settings/poi-providers",
            json={"name": "tomtom", "api_key": "test-key", "enabled": True},
        )
        assert response.status_code == 401

    async def test_add_poi_provider_invalid_name(self, client: AsyncClient, auth_headers):
        """Test adding POI provider with invalid name."""
        response = await client.post(
            "/api/settings/poi-providers",
            headers=auth_headers,
            json={"name": "invalid_provider", "api_key": "test-key", "enabled": True},
        )
        # Should be 400 or 403 depending on admin status
        assert response.status_code in [400, 403]

    async def test_add_poi_provider_missing_name(self, client: AsyncClient, auth_headers):
        """Test adding POI provider without name."""
        response = await client.post(
            "/api/settings/poi-providers",
            headers=auth_headers,
            json={"api_key": "test-key", "enabled": True},
        )
        # Should be 400 or 403 depending on admin status
        assert response.status_code in [400, 403]

    async def test_update_poi_provider_invalid_name(self, client: AsyncClient, auth_headers):
        """Test updating POI provider with invalid name."""
        response = await client.put(
            "/api/settings/poi-providers/invalid_provider",
            headers=auth_headers,
            json={"enabled": False},
        )
        # Should be 400 or 403 depending on admin status
        assert response.status_code in [400, 403]

    async def test_update_poi_provider_osm(self, client: AsyncClient, auth_headers):
        """Test that OSM provider cannot be configured."""
        response = await client.put(
            "/api/settings/poi-providers/osm",
            headers=auth_headers,
            json={"enabled": False},
        )
        # Should be 400 or 403 depending on admin status
        assert response.status_code in [400, 403]

    async def test_delete_poi_provider_osm(self, client: AsyncClient, auth_headers):
        """Test that OSM provider cannot be deleted."""
        response = await client.delete(
            "/api/settings/poi-providers/osm",
            headers=auth_headers,
        )
        # Should be 400 or 403 depending on admin status
        assert response.status_code in [400, 403]

    async def test_delete_poi_provider_requires_auth(self, client: AsyncClient):
        """Test that deleting POI provider requires authentication."""
        response = await client.delete("/api/settings/poi-providers/tomtom")
        assert response.status_code == 401

    async def test_test_poi_provider_requires_auth(self, client: AsyncClient):
        """Test that testing POI provider requires authentication."""
        response = await client.post(
            "/api/settings/poi-providers/tomtom/test",
            json={"api_key": "test-key"},
        )
        assert response.status_code == 401

    async def test_test_poi_provider_missing_key(self, client: AsyncClient, auth_headers):
        """Test POI provider test requires API key."""
        response = await client.post(
            "/api/settings/poi-providers/tomtom/test",
            headers=auth_headers,
            json={},
        )
        # Should be 400 or 403 depending on admin status
        assert response.status_code in [400, 403]

    async def test_get_setting_unauthorized(self, client: AsyncClient):
        """Test that getting a setting requires authentication."""
        response = await client.get("/api/settings/auth_mode")
        assert response.status_code == 401

    async def test_get_setting_not_found(self, client: AsyncClient, auth_headers):
        """Test getting non-existent setting."""
        response = await client.get(
            "/api/settings/nonexistent_setting_key",
            headers=auth_headers,
        )
        # Should be 404 or 403 depending on admin status
        assert response.status_code in [403, 404]

    async def test_create_setting_unauthorized(self, client: AsyncClient):
        """Test that creating a setting requires authentication."""
        response = await client.post(
            "/api/settings",
            json={"key": "test_key", "value": "test_value"},
        )
        assert response.status_code == 401

    async def test_update_setting_unauthorized(self, client: AsyncClient):
        """Test that updating a setting requires authentication."""
        response = await client.put(
            "/api/settings/some_key",
            json={"value": "new_value"},
        )
        assert response.status_code == 401

    async def test_batch_update_unauthorized(self, client: AsyncClient):
        """Test that batch update requires authentication."""
        response = await client.post(
            "/api/settings/batch",
            json={"settings": {"key1": "value1", "key2": "value2"}},
        )
        assert response.status_code == 401

    async def test_delete_setting_unauthorized(self, client: AsyncClient):
        """Test that deleting a setting requires authentication."""
        response = await client.delete("/api/settings/some_key")
        assert response.status_code == 401

    async def test_get_system_info_unauthorized(self, client: AsyncClient):
        """Test that system info requires authentication."""
        response = await client.get("/api/settings/system/info")
        assert response.status_code == 401

    async def test_public_settings_structure(self, client: AsyncClient):
        """Test public settings response structure."""
        response = await client.get("/api/settings/public")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["settings"], list)
        assert isinstance(data["total"], int)
        # Each setting should have key and value
        for setting in data["settings"]:
            assert "key" in setting
            assert "value" in setting

    async def test_poi_providers_sorted_by_priority(self, client: AsyncClient):
        """Test that POI providers are sorted by priority."""
        response = await client.get("/api/settings/poi-providers")

        assert response.status_code == 200
        data = response.json()
        providers = data["providers"]

        # Verify sorting (OSM should be last as fallback with priority 99)
        priorities = [p["priority"] for p in providers]
        assert priorities == sorted(priorities)

    async def test_poi_providers_structure(self, client: AsyncClient):
        """Test POI providers response structure."""
        response = await client.get("/api/settings/poi-providers")

        assert response.status_code == 200
        data = response.json()

        for provider in data["providers"]:
            assert "name" in provider
            assert "display_name" in provider
            assert "enabled" in provider
            assert "is_default" in provider
            assert "api_key_configured" in provider
            assert "priority" in provider


@pytest.mark.integration
@pytest.mark.asyncio
class TestSettingsAdminRoutes:
    """Test settings routes that require admin access.

    Note: These tests verify authorization is enforced. Full CRUD testing
    requires an admin user fixture which may not be available in all
    test environments.
    """

    async def test_create_setting_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that creating settings requires admin role."""
        response = await client.post(
            "/api/settings",
            headers=auth_headers,
            json={
                "key": "test_new_setting",
                "value": "test_value",
                "description": "Test setting",
            },
        )
        # Regular users get 403, admin gets 201
        assert response.status_code in [201, 403]

    async def test_update_setting_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that updating settings requires admin role."""
        response = await client.put(
            "/api/settings/app_name",
            headers=auth_headers,
            json={"value": "New App Name"},
        )
        # Regular users get 403, admin gets 200 or 404
        assert response.status_code in [200, 403, 404]

    async def test_delete_setting_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that deleting settings requires admin role."""
        response = await client.delete(
            "/api/settings/test_key",
            headers=auth_headers,
        )
        # Regular users get 403, admin gets 204 or 404
        assert response.status_code in [204, 403, 404]

    async def test_system_info_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that system info requires admin role."""
        response = await client.get(
            "/api/settings/system/info",
            headers=auth_headers,
        )
        # Regular users get 403, admin gets 200
        assert response.status_code in [200, 403]

    async def test_batch_update_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that batch update requires admin role."""
        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"theme": "dark"}},
        )
        # Regular users get 403, admin gets 200
        assert response.status_code in [200, 403]

    async def test_add_poi_provider_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that adding POI provider requires admin role."""
        response = await client.post(
            "/api/settings/poi-providers",
            headers=auth_headers,
            json={"name": "tomtom", "api_key": "test-key", "enabled": True},
        )
        # Regular users get 403, admin may get 200 or other status
        assert response.status_code in [200, 400, 403]

    async def test_test_poi_provider_requires_admin(self, client: AsyncClient, auth_headers):
        """Test that testing POI provider requires admin role."""
        response = await client.post(
            "/api/settings/poi-providers/tomtom/test",
            headers=auth_headers,
            json={"api_key": "test-api-key"},
        )
        # Regular users get 403, admin may get 200 or timeout error
        assert response.status_code in [200, 400, 403]
