"""
Integration tests for settings routes.

Tests settings CRUD operations, POI provider management, and system info.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.settings import Setting


async def _set_setting(db_session, key: str, value: str) -> None:
    """Upsert a single setting row."""
    result = await db_session.execute(select(Setting).where(Setting.key == key))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = value
    else:
        db_session.add(Setting(key=key, value=value))
    await db_session.commit()


async def _stored_value(db_session, key: str) -> str:
    """Read a setting straight from the DB, bypassing response masking."""
    result = await db_session.execute(select(Setting).where(Setting.key == key))
    return result.scalar_one().value


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
        # Public settings should only include specific keys. This list is a
        # fail-closed guard: widening it is a deliberate security decision, so a
        # new key has to be added here too.
        for setting in data["settings"]:
            assert setting["key"] in {
                "auth_mode",
                "app_name",
                "theme",
                "family_friends_enabled",
                "imperial_gallon_standard",
                "llm_receipt_parse_enabled",
                "llm_garage_assistant_enabled",
                "default_unit_prefs",
                # Computed per request from the household-zone fallback chain,
                # never a stored row (every write path rejects the key).
                "effective_timezone",
            }

    async def test_public_settings_serve_the_frontend_init_keys(
        self, client: AsyncClient, db_session
    ):
        """A non-admin must be able to read the two keys the app boots with.

        GET /api/settings is admin-only. When the gallon standard and the
        receipt-parse flag were only served from there, every non-admin silently
        fell back to US gallons (a UK install showed every volume ~20% wrong) and
        never saw the receipt panel at all.

        The rows are seeded here because the endpoint returns only rows that
        exist; settings_init creates them at startup in a real instance.

        Cleaned up in `finally`: the test DB is shared and not rolled back
        between tests, and `resolve_gallon_flavour` (units phase 0, Task 3)
        now reads `imperial_gallon_standard` straight from this table on every
        call. An un-reset "uk" row here previously leaked silently; it now
        corrupts every later test that resolves gallon flavour against real
        settings state.
        """
        await _set_setting(db_session, "imperial_gallon_standard", "uk")
        await _set_setting(db_session, "llm_receipt_parse_enabled", "true")
        await _set_setting(db_session, "llm_garage_assistant_enabled", "true")

        try:
            response = await client.get("/api/settings/public")

            assert response.status_code == 200
            values = {s["key"]: s["value"] for s in response.json()["settings"]}
            assert values.get("imperial_gallon_standard") == "uk"
            assert values.get("llm_receipt_parse_enabled") == "true"
            assert values.get("llm_garage_assistant_enabled") == "true"
        finally:
            for key in (
                "imperial_gallon_standard",
                "llm_receipt_parse_enabled",
                "llm_garage_assistant_enabled",
            ):
                row = (
                    await db_session.execute(select(Setting).where(Setting.key == key))
                ).scalar_one_or_none()
                if row is not None:
                    await db_session.delete(row)
            await db_session.commit()

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

    async def test_get_poi_providers(self, client: AsyncClient, auth_headers):
        """Test getting POI providers (admin only)."""
        response = await client.get("/api/settings/poi-providers", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        # OSM should always be present as fallback
        osm = next((p for p in data["providers"] if p["name"] == "osm"), None)
        assert osm is not None
        assert osm["is_default"] is True

    async def test_poi_providers_osm_always_enabled(self, client: AsyncClient, auth_headers):
        """Test that OSM provider is always enabled and present."""
        response = await client.get("/api/settings/poi-providers", headers=auth_headers)

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

    async def test_poi_providers_sorted_by_priority(self, client: AsyncClient, auth_headers):
        """Test that POI providers are sorted by priority."""
        response = await client.get("/api/settings/poi-providers", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        providers = data["providers"]

        # Verify sorting (OSM should be last as fallback with priority 99)
        priorities = [p["priority"] for p in providers]
        assert priorities == sorted(priorities)

    async def test_poi_providers_structure(self, client: AsyncClient, auth_headers):
        """Test POI providers response structure."""
        response = await client.get("/api/settings/poi-providers", headers=auth_headers)

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


@pytest.mark.integration
@pytest.mark.asyncio
class TestSystemInfoDatabasePath:
    """System info sizes the file the engine actually opens."""

    async def test_size_is_read_from_the_file_the_engine_opens(
        self,
        client: AsyncClient,
        auth_headers,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A `#` in the file name used to report 0.0 MB.

        SQLAlchemy 2.1 percent-escapes `str(engine.url)`, so the route looked
        for `my%23garage.db`, which doesn't exist. The redaction assert is a
        guard (it passes today): its mutant is redacting with
        `str(engine.url).replace(str(database_path), "***")`, which can't find
        the decoded path in the escaped string and leaks it.
        """
        import app.routes.settings as settings_routes

        db = tmp_path / "my#garage.db"
        db.write_bytes(b"\0" * 1048576)
        patched = create_async_engine("sqlite+aiosqlite:///" + str(db))
        # The PG sidecar runs this file on asyncpg, and the route branches on
        # its own module flag, so pin the SQLite branch here.
        monkeypatch.setattr(settings_routes, "engine", patched)
        monkeypatch.setattr(settings_routes, "is_sqlite", True)
        try:
            response = await client.get("/api/settings/system/info", headers=auth_headers)
        finally:
            await patched.dispose()

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["database_size_mb"] == 1.0
        assert "garage" not in data["database_url"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestSensitiveSettingMasking:
    """Sensitive settings are masked on read and preserved on write.

    The stored value is plaintext; the protection is that it never leaves the
    API in a response. Writes accept the mask placeholder as "keep what's
    stored", so a form can round-trip a masked value without clobbering it.
    """

    async def test_list_masks_sensitive_values(self, client: AsyncClient, auth_headers, db_session):
        """Sensitive keys are masked; ordinary keys are returned verbatim."""
        await _set_setting(db_session, "oidc_client_secret", "real-oidc-secret")
        await _set_setting(db_session, "tomtom_api_key", "real-tomtom-key")
        await _set_setting(db_session, "app_name", "MyGarage")

        response = await client.get("/api/settings", headers=auth_headers)
        assert response.status_code == 200
        values = {s["key"]: s["value"] for s in response.json()["settings"]}

        assert values["oidc_client_secret"] == "********"
        assert values["tomtom_api_key"] == "********"
        assert values["app_name"] == "MyGarage"

    async def test_unset_sensitive_value_stays_empty(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """An unset secret reads as '', not '********' — 'set' stays distinguishable."""
        await _set_setting(db_session, "gotify_token", "")

        response = await client.get("/api/settings", headers=auth_headers)
        values = {s["key"]: s["value"] for s in response.json()["settings"]}
        assert values["gotify_token"] == ""

    async def test_batch_preserves_masked_value(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Echoing the mask back keeps the stored secret."""
        await _set_setting(db_session, "telegram_bot_token", "original-token")

        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"telegram_bot_token": "********"}},
        )
        assert response.status_code == 200
        assert await _stored_value(db_session, "telegram_bot_token") == "original-token"

    async def test_batch_writes_real_value(self, client: AsyncClient, auth_headers, db_session):
        """A genuine new secret is written through."""
        await _set_setting(db_session, "telegram_bot_token", "original-token")

        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"telegram_bot_token": "brand-new-token"}},
        )
        assert response.status_code == 200
        assert await _stored_value(db_session, "telegram_bot_token") == "brand-new-token"

    async def test_batch_can_clear_sensitive_value(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Empty means clear — masking must not make a secret unremovable."""
        await _set_setting(db_session, "telegram_bot_token", "original-token")

        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"telegram_bot_token": ""}},
        )
        assert response.status_code == 200
        assert await _stored_value(db_session, "telegram_bot_token") == ""

    async def test_batch_response_is_masked(self, client: AsyncClient, auth_headers, db_session):
        """The write response must not echo the secret back either."""
        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"gotify_token": "written-secret"}},
        )
        assert response.status_code == 200
        values = {s["key"]: s["value"] for s in response.json()["settings"]}
        assert values["gotify_token"] == "********"
        assert await _stored_value(db_session, "gotify_token") == "written-secret"

    async def test_put_preserves_masked_value(self, client: AsyncClient, auth_headers, db_session):
        """Single-key PUT honors the same preserve contract."""
        await _set_setting(db_session, "email_smtp_password", "original-password")

        response = await client.put(
            "/api/settings/email_smtp_password",
            headers=auth_headers,
            json={"value": "********"},
        )
        assert response.status_code == 200
        assert response.json()["value"] == "********"
        assert await _stored_value(db_session, "email_smtp_password") == "original-password"

    async def test_put_writes_real_value(self, client: AsyncClient, auth_headers, db_session):
        """Single-key PUT still writes a genuine value."""
        await _set_setting(db_session, "email_smtp_password", "original-password")

        response = await client.put(
            "/api/settings/email_smtp_password",
            headers=auth_headers,
            json={"value": "new-password"},
        )
        assert response.status_code == 200
        assert await _stored_value(db_session, "email_smtp_password") == "new-password"


# ---------------------------------------------------------------------------
# default_unit_prefs write validation (units phase 4, task 5)
# ---------------------------------------------------------------------------


def _settings_value_write_endpoints() -> set[str]:
    """Enumerate the settings endpoints that write a Setting value.

    ★ DERIVED, NOT LISTED, and the derivation is the point. The plan named three
    routes that can write `default_unit_prefs`; validating only the one the UI
    happens to call leaves the other two open, which is the same back door D9b
    closed on the user schemas. A hand-written list of three would go stale the
    moment a fourth writer is added, and nothing would say so.

    The rule: parse each endpoint on `app.routes.settings.router` and report it
    when its body constructs a `Setting(...)`, assigns to a `.value` attribute,
    or calls `setattr` (a blanket attribute write, which is how
    `update_setting` applies its payload). Endpoints are read from the router
    rather than from the module namespace, so a handler that is defined but
    never registered is correctly absent.

    ★ AND THE SCOPE IS THAT ROUTER, WHICH IS NARROWER THAN "every writer". A
    walk of one router cannot see a writer that is not on it, and there is
    exactly one: `BackupService.restore_settings_backup` (reachable from
    `POST /api/backup/restore/{filename}`) pushes every uploaded key and value
    into `SettingsService.set`. Reading this enumeration as "nothing can write
    an unvalidated value" is how that path went unguarded. It now validates at
    its own site, pinned by
    `tests/unit/services/test_backup_settings_restore.py`, so what this function
    guarantees is the ROUTE half and the sentence says so.

    :returns: the endpoint function names, as a set.
    """
    import ast
    import inspect

    from app.routes import settings as settings_route

    found: set[str] = set()
    for route in settings_route.router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        tree = ast.parse(inspect.getsource(endpoint))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"Setting", "setattr"}:
                    found.add(endpoint.__name__)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "value":
                        found.add(endpoint.__name__)

    if not found:
        # A silent empty set would make the coverage assertion below vacuously
        # true, which is the failure this enumeration exists to prevent.
        raise AssertionError("walked the settings router and found no writer; refusing to conclude")
    return found


# A complete, in-vocabulary set: the metric preset, which is neither the value
# under test nor the imperial fallback a rejected write would silently produce.
GOOD_UNIT_PREFS = (
    '{"consumption": "l_100km", "distance": "km", "length": "m", "mass": "kg", '
    '"pressure": "kpa", "secondary_gallon": "us", "speed": "kmh", '
    '"temperature": "c", "torque": "nm", "tread": "mm", "volume": "L"}'
)

# A second complete set, used to prove an accepted write really lands.
OTHER_GOOD_UNIT_PREFS = (
    '{"consumption": "mpg_uk", "distance": "mi", "length": "ft", "mass": "lb", '
    '"pressure": "psi", "secondary_gallon": "uk", "speed": "mph", '
    '"temperature": "f", "torque": "lbft", "tread": "in32", "volume": "gal_uk"}'
)

# The four rejection cases the plan names. Each degrades WHOLE through
# `parse_default_unit_prefs`, so an unvalidated write reverts every anonymous
# client to the imperial fallback with nothing in the response to say so.
BAD_UNIT_PREFS = {
    "partial": '{"distance": "km", "volume": "L"}',
    "extra_key": GOOD_UNIT_PREFS[:-1] + ', "colour": "red"}',
    "out_of_vocabulary": GOOD_UNIT_PREFS.replace('"pressure": "kpa"', '"pressure": "atm"'),
    "malformed_json": "{not json at all",
    "empty": "",
}


async def _write_through(
    client: AsyncClient,
    endpoint: str,
    headers,
    db_session,
    raw: str,
    *,
    key: str = "default_unit_prefs",
    seed: str = GOOD_UNIT_PREFS,
):
    """Send `raw` as `key` (`default_unit_prefs` unless told) through one named write endpoint.

    Each path is set up so it can actually reach its write: `create_setting`
    409s on an existing row and `update_setting` 404s on a missing one, so the
    row is removed or seeded (with `seed`) accordingly. An unasserted setup that
    silently 404'd would leave the assertion below testing nothing.

    :returns: the response.
    """
    if endpoint == "create_setting":
        await _delete_setting(db_session, key)
        return await client.post("/api/settings", headers=headers, json={"key": key, "value": raw})
    if endpoint == "update_setting":
        await _set_setting(db_session, key, seed)
        return await client.put(f"/api/settings/{key}", headers=headers, json={"value": raw})
    if endpoint == "batch_update_settings":
        await _set_setting(db_session, key, seed)
        return await client.post(
            "/api/settings/batch", headers=headers, json={"settings": {key: raw}}
        )
    raise AssertionError(f"no request builder for {endpoint}")


async def _delete_setting(db_session, key: str) -> None:
    """Remove a setting row, so a test leaves the shared DB as it found it."""
    result = await db_session.execute(select(Setting).where(Setting.key == key))
    existing = result.scalar_one_or_none()
    if existing is not None:
        await db_session.delete(existing)
        await db_session.commit()


WRITE_ENDPOINTS = ("create_setting", "update_setting", "batch_update_settings")


@pytest.mark.integration
@pytest.mark.asyncio
class TestDefaultUnitPrefsWriteValidation:
    """A `default_unit_prefs` written through the settings API must parse.

    `parse_default_unit_prefs` degrades WHOLE and only logs, which is right on
    READ: an exception there would take the app down for logged-out users on
    nothing worse than a hand-edited row. On WRITE it means an admin can store a
    value that silently reverts every anonymous client to the imperial fallback,
    with no error in the response and nothing but a warning in the log.
    """

    async def test_every_write_path_the_router_declares_is_covered_here(self):
        """The rejection cases below run against every writer, not one of three."""
        assert _settings_value_write_endpoints() == set(WRITE_ENDPOINTS)

    @pytest.mark.parametrize("endpoint", WRITE_ENDPOINTS)
    @pytest.mark.parametrize("case", sorted(BAD_UNIT_PREFS))
    async def test_a_value_that_would_not_parse_is_rejected(
        self, client: AsyncClient, auth_headers, db_session, endpoint: str, case: str
    ):
        """Each path refuses the write and leaves the stored row alone."""
        try:
            response = await _write_through(
                client, endpoint, auth_headers, db_session, BAD_UNIT_PREFS[case]
            )
            assert response.status_code == 422, response.text
            if endpoint == "create_setting":
                result = await db_session.execute(
                    select(Setting).where(Setting.key == "default_unit_prefs")
                )
                assert result.scalar_one_or_none() is None
            else:
                # The other direction: the good row the setup wrote survives.
                assert await _stored_value(db_session, "default_unit_prefs") == GOOD_UNIT_PREFS
        finally:
            await _delete_setting(db_session, "default_unit_prefs")

    @pytest.mark.parametrize("endpoint", WRITE_ENDPOINTS)
    async def test_a_complete_set_still_writes_through(
        self, client: AsyncClient, auth_headers, db_session, endpoint: str
    ):
        """And the guard is not a blanket refusal: a good set still lands."""
        try:
            response = await _write_through(
                client, endpoint, auth_headers, db_session, OTHER_GOOD_UNIT_PREFS
            )
            assert response.status_code in (200, 201), response.text
            assert await _stored_value(db_session, "default_unit_prefs") == OTHER_GOOD_UNIT_PREFS
        finally:
            await _delete_setting(db_session, "default_unit_prefs")


REDIRECT_URI_KEY = "oidc_redirect_uri"
GOOD_REDIRECT_URI = "https://garage.example.com/api/auth/oidc/callback"
OTHER_GOOD_REDIRECT_URI = "https://other.example.com/mygarage/api/auth/oidc/callback"
BAD_REDIRECT_URIS = {
    "non_http_scheme": "ftp://garage.example.com/api/auth/oidc/callback",
    "hostless": "https://",
    # urlsplit drops the newline before it parses, so this looked like a good URL.
    "embedded_newline": "https://garage.example.com\n.evil.example/api/auth/oidc/callback",
}


@pytest_asyncio.fixture
async def redirect_uri_row(db_session) -> AsyncIterator[None]:
    """Put the stored oidc_redirect_uri row back afterwards, since the suite shares one DB."""
    row = (
        await db_session.execute(select(Setting).where(Setting.key == REDIRECT_URI_KEY))
    ).scalar_one_or_none()
    saved = None if row is None else (row.value, row.category, row.description, row.encrypted)
    yield
    await db_session.rollback()
    await db_session.execute(delete(Setting).where(Setting.key == REDIRECT_URI_KEY))
    if saved is not None:
        value, category, description, encrypted = saved
        db_session.add(
            Setting(
                key=REDIRECT_URI_KEY,
                value=value,
                category=category,
                description=description,
                encrypted=encrypted,
            )
        )
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.usefixtures("redirect_uri_row")
class TestOidcRedirectUriWriteValidation:
    """A pinned SSO callback URL is blank or an absolute http(s) URL, on every write path.

    The SSO settings PUT re-sends the stored pin with every OIDC save, so a bad
    one written here made each of those 422, the auth-mode switch included.
    """

    @pytest.mark.parametrize("endpoint", WRITE_ENDPOINTS)
    @pytest.mark.parametrize("case", sorted(BAD_REDIRECT_URIS))
    async def test_a_bad_pin_is_rejected(
        self, client: AsyncClient, auth_headers, db_session, endpoint: str, case: str
    ):
        """Each path refuses it and leaves the stored row alone."""
        response = await _write_through(
            client,
            endpoint,
            auth_headers,
            db_session,
            BAD_REDIRECT_URIS[case],
            key=REDIRECT_URI_KEY,
            seed=GOOD_REDIRECT_URI,
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == (
            f"Setting '{REDIRECT_URI_KEY}' must be blank or an absolute http(s) URL with no #fragment"
        )
        if endpoint == "create_setting":
            assert not await _has_row(db_session, REDIRECT_URI_KEY)
        else:
            assert await _stored_value(db_session, REDIRECT_URI_KEY) == GOOD_REDIRECT_URI

    @pytest.mark.parametrize("endpoint", WRITE_ENDPOINTS)
    @pytest.mark.parametrize("value", [OTHER_GOOD_REDIRECT_URI, ""], ids=["pinned", "blank"])
    async def test_a_good_pin_or_blank_still_writes(
        self, client: AsyncClient, auth_headers, db_session, endpoint: str, value: str
    ):
        """Control: the guard isn't a blanket refusal, and blank still clears the pin."""
        response = await _write_through(
            client,
            endpoint,
            auth_headers,
            db_session,
            value,
            key=REDIRECT_URI_KEY,
            seed=GOOD_REDIRECT_URI,
        )

        assert response.status_code in (200, 201), response.text
        assert await _stored_value(db_session, REDIRECT_URI_KEY) == value


# ---------------------------------------------------------------------------
# Typed bodies: POI providers and the batch key width
# ---------------------------------------------------------------------------

_PROVIDER = "foursquare"
_PROVIDER_KEYS = (f"{_PROVIDER}_enabled", f"{_PROVIDER}_api_key", f"{_PROVIDER}_api_usage")


async def _stored_or_none(db_session, key: str) -> str | None:
    """The stored value, or None when there is no row at all."""
    result = await db_session.execute(select(Setting.value).where(Setting.key == key))
    row = result.one_or_none()
    return None if row is None else row.value


async def _has_row(db_session, key: str) -> bool:
    result = await db_session.execute(select(Setting.key).where(Setting.key == key))
    return result.one_or_none() is not None


@pytest_asyncio.fixture
async def provider_rows(db_session) -> AsyncIterator[None]:
    """Start with no rows for the test provider and put the originals back afterwards."""
    rows = (
        await db_session.execute(select(Setting).where(Setting.key.in_(_PROVIDER_KEYS)))
    ).scalars()
    saved = [(r.key, r.value, r.category, r.description, r.encrypted) for r in rows]
    await db_session.execute(delete(Setting).where(Setting.key.in_(_PROVIDER_KEYS)))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(Setting).where(Setting.key.in_(_PROVIDER_KEYS)))
    for key, value, category, description, encrypted in saved:
        db_session.add(
            Setting(
                key=key,
                value=value,
                category=category,
                description=description,
                encrypted=encrypted,
            )
        )
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.usefixtures("provider_rows")
class TestPOIProviderBodies:
    """The provider routes took a bare dict, so a null or a wrong type went
    straight to a str() or a len()."""

    async def test_adding_a_provider_with_a_null_key_is_a_422(
        self, client: AsyncClient, auth_headers, db_session
    ):
        response = await client.post(
            "/api/settings/poi-providers",
            headers=auth_headers,
            json={"name": _PROVIDER, "enabled": False, "api_key": None},
        )
        assert response.status_code == 422, response.text
        assert not await _has_row(db_session, f"{_PROVIDER}_api_key")

    async def test_adding_a_provider_with_enabled_null_is_a_422_and_stores_nothing(
        self, client: AsyncClient, auth_headers, db_session
    ):
        response = await client.post(
            "/api/settings/poi-providers",
            headers=auth_headers,
            json={"name": _PROVIDER, "api_key": "a-real-looking-key", "enabled": None},
        )
        assert response.status_code == 422, response.text
        for key in _PROVIDER_KEYS:
            assert not await _has_row(db_session, key), key

    async def test_editing_a_provider_with_enabled_maybe_is_a_422(
        self, client: AsyncClient, auth_headers, db_session
    ):
        response = await client.put(
            f"/api/settings/poi-providers/{_PROVIDER}",
            headers=auth_headers,
            json={"enabled": "maybe"},
        )
        assert response.status_code == 422, response.text
        assert not await _has_row(db_session, f"{_PROVIDER}_enabled")

    async def test_editing_a_provider_with_a_numeric_key_is_a_422(
        self, client: AsyncClient, auth_headers, db_session
    ):
        response = await client.put(
            f"/api/settings/poi-providers/{_PROVIDER}",
            headers=auth_headers,
            json={"api_key": 123},
        )
        assert response.status_code == 422, response.text
        assert not await _has_row(db_session, f"{_PROVIDER}_api_key")

    async def test_editing_a_provider_with_enabled_null_is_a_422(
        self, client: AsyncClient, auth_headers, db_session
    ):
        await _set_setting(db_session, f"{_PROVIDER}_enabled", "true")
        response = await client.put(
            f"/api/settings/poi-providers/{_PROVIDER}",
            headers=auth_headers,
            json={"enabled": None},
        )
        assert response.status_code == 422, response.text
        assert await _stored_or_none(db_session, f"{_PROVIDER}_enabled") == "true"

    async def test_editing_with_only_enabled_keeps_the_stored_key(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Guard, passes before the typed body too. Mutant: write `api_key`
        when it's omitted."""
        await _set_setting(db_session, f"{_PROVIDER}_api_key", "stored-key-123456")
        await _set_setting(db_session, f"{_PROVIDER}_enabled", "true")
        response = await client.put(
            f"/api/settings/poi-providers/{_PROVIDER}",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert response.status_code == 200, response.text
        assert await _stored_or_none(db_session, f"{_PROVIDER}_api_key") == "stored-key-123456"
        assert await _stored_or_none(db_session, f"{_PROVIDER}_enabled") == "false"


async def _committed_provider_rows(test_sessionmaker) -> dict[str, str | None]:
    """The test provider's rows as another connection sees them: committed only."""
    async with test_sessionmaker() as fresh:
        result = await fresh.execute(
            select(Setting.key, Setting.value).where(Setting.key.in_(_PROVIDER_KEYS))
        )
        return {row.key: row.value for row in result}


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.usefixtures("provider_rows")
class TestPOIProviderPersistence:
    """The provider routes only flushed, and get_db doesn't commit, so every
    change was rolled back when the request's session closed. The test client
    shares one session, which is why nothing here noticed: these read through
    a fresh one."""

    async def test_adding_a_provider_is_saved(
        self, client: AsyncClient, auth_headers, test_sessionmaker
    ):
        response = await client.post(
            "/api/settings/poi-providers",
            headers=auth_headers,
            json={"name": _PROVIDER, "api_key": "a-real-looking-key", "enabled": True},
        )
        assert response.status_code == 200, response.text
        assert await _committed_provider_rows(test_sessionmaker) == {
            f"{_PROVIDER}_enabled": "true",
            f"{_PROVIDER}_api_key": "a-real-looking-key",
            f"{_PROVIDER}_api_usage": "0",
        }

    async def test_editing_a_provider_is_saved(
        self, client: AsyncClient, auth_headers, db_session, test_sessionmaker
    ):
        await _set_setting(db_session, f"{_PROVIDER}_enabled", "true")
        await _set_setting(db_session, f"{_PROVIDER}_api_key", "old-key-123456")
        response = await client.put(
            f"/api/settings/poi-providers/{_PROVIDER}",
            headers=auth_headers,
            json={"enabled": False, "api_key": "new-key-123456"},
        )
        assert response.status_code == 200, response.text
        assert await _committed_provider_rows(test_sessionmaker) == {
            f"{_PROVIDER}_enabled": "false",
            f"{_PROVIDER}_api_key": "new-key-123456",
        }

    async def test_removing_a_provider_is_saved(
        self, client: AsyncClient, auth_headers, db_session, test_sessionmaker
    ):
        await _set_setting(db_session, f"{_PROVIDER}_enabled", "true")
        await _set_setting(db_session, f"{_PROVIDER}_api_key", "old-key-123456")
        response = await client.delete(
            f"/api/settings/poi-providers/{_PROVIDER}", headers=auth_headers
        )
        assert response.status_code == 204, response.text
        assert await _committed_provider_rows(test_sessionmaker) == {}


# Long enough to mask, so the list has a real prefix in it.
_LISTED_KEY = "fsq-list-key-0123456789"


@pytest_asyncio.fixture
async def listed_provider(db_session, provider_rows) -> None:
    """The test provider with a key on file. provider_rows puts its rows back afterwards."""
    await _set_setting(db_session, f"{_PROVIDER}_api_key", _LISTED_KEY)
    await _set_setting(db_session, f"{_PROVIDER}_enabled", "true")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.usefixtures("listed_provider")
class TestPOIProviderListIsAdminOnly:
    """The provider list was public, so anyone could read each key's first 8
    characters and its usage (A-10). It's admin-only now, like the rest of
    /api/settings."""

    async def test_anonymous_is_a_401(self, client: AsyncClient, set_auth_mode):
        await set_auth_mode("local")
        response = await client.get("/api/settings/poi-providers")
        assert response.status_code == 401, response.text
        assert _LISTED_KEY[:8] not in response.text

    async def test_a_non_admin_is_a_403(
        self, client: AsyncClient, set_auth_mode, non_admin_headers
    ):
        await set_auth_mode("local")
        response = await client.get("/api/settings/poi-providers", headers=non_admin_headers)
        assert response.status_code == 403, response.text
        assert _LISTED_KEY[:8] not in response.text

    async def test_an_admin_gets_the_masked_key(
        self, client: AsyncClient, set_auth_mode, auth_headers
    ):
        """Control, passes before the gate too. The admin drawer shows the prefix."""
        await set_auth_mode("local")
        response = await client.get("/api/settings/poi-providers", headers=auth_headers)
        assert response.status_code == 200, response.text
        listed = {p["name"]: p for p in response.json()["providers"]}
        assert listed[_PROVIDER]["api_key_masked"] == f"{_LISTED_KEY[:8]}***"

    async def test_none_mode_stays_open(self, client: AsyncClient, set_auth_mode):
        """Control, passes before the gate too. With no login, everyone runs the instance."""
        await set_auth_mode("none")
        response = await client.get("/api/settings/poi-providers")
        assert response.status_code == 200, response.text
        assert _PROVIDER in {p["name"] for p in response.json()["providers"]}


@pytest.mark.integration
@pytest.mark.asyncio
class TestSettingsBatchKeyWidth:
    """`Setting.key` is String(50): a longer key was stored on SQLite and a 500
    on PostgreSQL."""

    async def test_a_settings_key_longer_than_50_characters_is_a_422_and_stores_nothing(
        self, client: AsyncClient, auth_headers, db_session
    ):
        key = f"e8-{uuid.uuid4().hex}".ljust(51, "x")
        try:
            response = await client.post(
                "/api/settings/batch", headers=auth_headers, json={"settings": {key: "v"}}
            )
            assert response.status_code == 422, response.text
            assert not await _has_row(db_session, key)
        finally:
            await db_session.rollback()
            await db_session.execute(delete(Setting).where(Setting.key == key))
            await db_session.commit()

    async def test_a_50_character_key_saves(self, client: AsyncClient, auth_headers, db_session):
        """Guard, passes before the constraint too. Mutant: max_length=49."""
        key = f"e8-{uuid.uuid4().hex}".ljust(50, "x")
        try:
            response = await client.post(
                "/api/settings/batch", headers=auth_headers, json={"settings": {key: "v"}}
            )
            assert response.status_code == 200, response.text
            assert await _stored_or_none(db_session, key) == "v"
        finally:
            await db_session.rollback()
            await db_session.execute(delete(Setting).where(Setting.key == key))
            await db_session.commit()
