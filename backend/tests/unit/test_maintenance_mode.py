"""Maintenance mode gives the documented upgrade procedure a window to run in.

The upgrade note tells operators to run the odometer repair tools "before the
upgraded instance records new readings". There was no way to do that. Migrations
run inside the app's own lifespan, `livelink_mqtt_enabled` is a database row
rather than an env var (so it cannot be turned off before the process that reads
it starts), and HTTP ingest serves the moment routers mount. A buffered WiCAN
replays its backlog within seconds of the broker connecting, which lands the
instance in exactly the half-converted state the tools then refuse to touch.

`MYGARAGE_MAINTENANCE_MODE=1` starts the app far enough to run migrations, and
no further: no scheduler, no MQTT subscriber, and ingest answers 503.
"""

import pytest

INGEST_PATHS = [
    "/api/v1/livelink/ingest",
    "/api/v1/torque/upload",
]


@pytest.mark.asyncio
class TestMaintenanceModeGate:
    """Ingest is closed in maintenance mode and open outside it."""

    @pytest.mark.parametrize("path", INGEST_PATHS)
    async def test_ingest_is_refused_with_503(self, client, monkeypatch, path):
        """503, not 404 or 401: the endpoint exists and is deliberately closed."""
        from app.config import settings

        monkeypatch.setattr(settings, "maintenance_mode", True)

        response = await client.post(path, json={})

        assert response.status_code == 503, (
            f"{path} accepted a reading while the instance was in maintenance mode"
        )
        assert "maintenance" in response.text.lower()

    @pytest.mark.parametrize("path", INGEST_PATHS)
    async def test_ingest_is_not_gated_when_maintenance_mode_is_off(
        self, client, monkeypatch, path
    ):
        """The complement. Without it, a gate that always fires would pass above.

        Any status but 503 proves the request reached real handling; an
        unauthenticated empty POST is expected to be rejected on its own terms
        (401/403/422), which is not this gate's doing.
        """
        from app.config import settings

        monkeypatch.setattr(settings, "maintenance_mode", False)

        response = await client.post(path, json={})

        assert response.status_code != 503, f"{path} was gated with maintenance mode off"

    async def test_health_still_answers_in_maintenance_mode(self, client, monkeypatch):
        """The container's healthcheck must not fail the upgrade window."""
        from app.config import settings

        monkeypatch.setattr(settings, "maintenance_mode", True)

        response = await client.get("/api/health")

        assert response.status_code == 200


class TestMaintenanceModeSetting:
    """The flag is off unless explicitly set."""

    def test_defaults_to_off(self):
        from app.config import Settings

        assert Settings().maintenance_mode is False
