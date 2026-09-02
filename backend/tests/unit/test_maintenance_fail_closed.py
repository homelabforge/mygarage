"""Maintenance mode must be fail-closed at the writer, not only at the route.

The first implementation gated two URL prefixes. Review found the admin SD
backfill route open. That was fixed by matching the route exactly -- and review
then found `POST /api/livelink/mqtt/restart`, which writes no telemetry itself
but starts the MQTT subscriber, which does.

That is two rounds of the same defect, and the shape is clear: any gate that
enumerates entry points is a floor. MQTT is not a route. The scheduler is not a
route. A future ingest path need not be a route either.

So the gate moves to the place every path must pass through: the three writers
themselves. The route gate stays, because a 503 at the edge is a better answer
than a 500 from the middle, but it is no longer the thing being relied on.
"""

from datetime import UTC, datetime

import pytest

from app.services.telemetry_service import MaintenanceModeError


@pytest.fixture
def maintenance_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "maintenance_mode", True)


@pytest.mark.asyncio
class TestWritersRefuseInMaintenanceMode:
    """Every telemetry writer refuses, whatever called it."""

    async def test_store_telemetry_refuses(self, db_session, maintenance_on):
        from app.services.telemetry_service import TelemetryService

        with pytest.raises(MaintenanceModeError):
            await TelemetryService(db_session).store_telemetry(
                "1HGBH41JXMN109186", "dev-1", {"SPEED": 40}, {}
            )

    async def test_store_torque_telemetry_refuses(self, db_session, maintenance_on):
        from app.services.telemetry_service import TelemetryService

        with pytest.raises(MaintenanceModeError):
            await TelemetryService(db_session).store_torque_telemetry(
                "1HGBH41JXMN109186", "dev-1", datetime.now(UTC), {"SPEED": 40}
            )

    async def test_bulk_backfill_refuses(self, db_session, maintenance_on):
        """The SD path. This is the one an admin can trigger by hand."""
        from app.services.telemetry_service import TelemetryService

        with pytest.raises(MaintenanceModeError):
            await TelemetryService(db_session).bulk_backfill("1HGBH41JXMN109186", "dev-1", [])

    async def test_bulk_backfill_refuses_before_it_looks_at_its_rows(
        self, db_session, maintenance_on
    ):
        """An empty row list must not become an early return that skips the gate.

        Written because the natural implementation of `bulk_backfill` starts by
        short-circuiting on empty input, which would make the test above pass
        for the wrong reason and leave a non-empty backfill wide open.
        """
        from app.services.telemetry_service import TelemetryService

        with pytest.raises(MaintenanceModeError):
            await TelemetryService(db_session).bulk_backfill(
                "1HGBH41JXMN109186", "dev-1", [object()]
            )


@pytest.mark.asyncio
class TestMqttCannotBeStartedInMaintenanceMode:
    """`POST /api/livelink/mqtt/restart` is a route that writes no telemetry
    and yet lets telemetry in. The gate belongs on the starter."""

    async def test_start_is_refused(self, maintenance_on, monkeypatch):
        from app.services.mqtt_subscriber import mqtt_subscriber
        from app.tasks import livelink_tasks

        started = False

        async def _fake_start():
            nonlocal started
            started = True

        monkeypatch.setattr(mqtt_subscriber, "start", _fake_start)
        monkeypatch.setattr(livelink_tasks, "is_mqtt_enabled", lambda: _true())

        await livelink_tasks.start_mqtt_subscriber()
        assert started is False, "maintenance mode must not start the MQTT subscriber"

    async def test_restart_is_refused(self, maintenance_on, monkeypatch):
        from app.services.mqtt_subscriber import mqtt_subscriber
        from app.tasks import livelink_tasks

        started = False

        async def _fake_start():
            nonlocal started
            started = True

        async def _fake_stop():
            return None

        monkeypatch.setattr(mqtt_subscriber, "start", _fake_start)
        monkeypatch.setattr(mqtt_subscriber, "stop", _fake_stop)
        monkeypatch.setattr(livelink_tasks, "is_mqtt_enabled", lambda: _true())

        await livelink_tasks.restart_mqtt_subscriber()
        assert started is False, "the admin restart route must not reopen ingest"


async def _true() -> bool:
    return True


@pytest.mark.asyncio
class TestNormalOperationIsUnaffected:
    """The gate must be off when maintenance mode is off.

    Without this, a mutation that always raises would pass every test above.
    """

    async def test_bulk_backfill_runs_when_not_in_maintenance(self, db_session):
        from app.services.telemetry_service import TelemetryService

        assert await TelemetryService(db_session).bulk_backfill("V", "d", []) == 0
