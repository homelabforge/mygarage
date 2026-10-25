"""check_thresholds for a preset sensor's readings: once per crossing.

WiCAN readings repeat an alert every cooldown window while they stay past a
line (`test_telemetry_threshold_cooldown.py`). A propane tank sits below its
low line for days, so its readings notify on entering a band, once more for a
worse one, and re-arm only once the level climbs clear (a refill).

Everything here is flushed, never committed: the session closes without a
commit, so nothing reaches the shared database.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle import Vehicle
from app.services.livelink_alerts import REARM_MARGIN
from app.services.settings_service import SettingsService
from app.services.telemetry_service import TelemetryService

#: The send is queued for after the commit in production (B6-1); these flush
#: without committing, so it's delivered inline (see the fixture).
pytestmark = pytest.mark.usefixtures("alerts_inline")

VIN = "THRESHONCE0000001"
#: An index no real sensor in the suite reaches.
LEVEL = "PROPANE_T9701_LEVEL_PCT"


@pytest_asyncio.fixture
async def vin(db_session: AsyncSession) -> str:
    db_session.add(
        Vehicle(
            vin=VIN,
            nickname="Once Test RV",
            vehicle_type="RV",
            year=2023,
            make="KZ",
            model="Durango",
        )
    )
    await db_session.flush()
    return VIN


@pytest_asyncio.fixture
async def make_param(db_session: AsyncSession):
    async def _factory(
        param_key: str = LEVEL,
        warning_min: float | None = 25.0,
        critical_min: float | None = 10.0,
    ) -> LiveLinkParameter:
        param = LiveLinkParameter(
            param_key=param_key,
            display_name="Tank 1 level",
            unit="%",
            param_class="propane",
            warning_min=warning_min,
            critical_min=critical_min,
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=300,
        )
        db_session.add(param)
        await db_session.flush()
        return param

    return _factory


def _dispatcher(monkeypatch, results: dict[str, bool] | None = None) -> AsyncMock:
    mock = AsyncMock(return_value=results if results is not None else {"discord": True})
    monkeypatch.setattr(
        "app.services.notifications.dispatcher.NotificationDispatcher.notify_livelink_threshold_alert",
        mock,
    )
    return mock


def _sent(mock: AsyncMock) -> list[tuple[str, float]]:
    """(band, threshold_value) of every notification sent."""
    return [(call.kwargs["band"], call.kwargs["threshold_value"]) for call in mock.await_args_list]


def _at(monkeypatch, when: datetime) -> None:
    monkeypatch.setattr("app.services.telemetry_service.utc_now", lambda: when)


@pytest.mark.unit
@pytest.mark.asyncio
class TestNotifyOnce:
    async def test_a_tank_notifies_once_below_low_and_once_below_critical(
        self, db_session, vin, make_param, monkeypatch
    ):
        param = await make_param()
        mock = _dispatcher(monkeypatch)
        svc = TelemetryService(db_session)

        for level in (30.0, 24.0, 23.0, 22.0, 9.0, 8.0, 12.0, 7.0):
            await svc.check_thresholds(vin, LEVEL, level, once=True)

        assert _sent(mock) == [("low", 25.0), ("critical", 10.0)]
        assert param.alert_state == "critical"

    async def test_the_cooldown_does_not_bring_it_back(
        self, db_session, vin, make_param, monkeypatch
    ):
        """Hours later, still low: a WiCAN reading would notify again here."""
        param = await make_param()
        mock = _dispatcher(monkeypatch)
        svc = TelemetryService(db_session)

        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)
        later = param.warning_last_notified_at + timedelta(hours=6)
        monkeypatch.setattr("app.services.telemetry_service.utc_now", lambda: later)
        await svc.check_thresholds(vin, LEVEL, 23.0, once=True)

        assert mock.await_count == 1

    async def test_a_refill_rearms_it(self, db_session, vin, make_param, monkeypatch):
        param = await make_param()
        mock = _dispatcher(monkeypatch)
        svc = TelemetryService(db_session)

        await svc.check_thresholds(vin, LEVEL, 8.0, once=True)
        await svc.check_thresholds(vin, LEVEL, 100.0, once=True)
        assert param.alert_state is None

        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)

        assert _sent(mock) == [("critical", 10.0), ("low", 25.0)]

    async def test_jitter_at_the_line_does_not_rearm(
        self, db_session, vin, make_param, monkeypatch
    ):
        param = await make_param()
        mock = _dispatcher(monkeypatch)
        svc = TelemetryService(db_session)

        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)
        await svc.check_thresholds(vin, LEVEL, 25.0 + REARM_MARGIN - 1, once=True)
        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)

        assert mock.await_count == 1
        assert param.alert_state == "low"

    async def test_a_failed_send_waits_out_the_cooldown_then_tries_again(
        self, db_session, vin, make_param, monkeypatch
    ):
        """Nothing delivered, nothing held. Not retried on every reading: each
        send to a service that is down retries inline and stalls ingest."""
        param = await make_param()
        mock = _dispatcher(monkeypatch, results={"discord": False})
        svc = TelemetryService(db_session)

        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)
        assert param.alert_state is None
        failed_at = param.alert_retry_at - timedelta(minutes=30)

        mock.return_value = {"discord": True}
        _at(monkeypatch, failed_at + timedelta(minutes=29))
        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)
        assert mock.await_count == 1

        _at(monkeypatch, failed_at + timedelta(minutes=30))
        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)

        assert mock.await_count == 2
        assert param.alert_state == "low"
        assert param.alert_retry_at is None

    async def test_nothing_to_send_to_waits_too(self, db_session, vin, make_param, monkeypatch):
        """No service switched on, or the event switched off: an empty result."""
        param = await make_param()
        mock = _dispatcher(monkeypatch, results={})
        svc = TelemetryService(db_session)

        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)
        await svc.check_thresholds(vin, LEVEL, 23.0, once=True)

        assert mock.await_count == 1
        assert param.alert_state is None
        assert param.alert_retry_at is not None

    async def test_the_wait_follows_the_cooldown_setting(
        self, db_session, vin, make_param, monkeypatch
    ):
        await SettingsService.set(db_session, "livelink_alert_cooldown_minutes", "5")
        param = await make_param()
        _dispatcher(monkeypatch, results={})
        _at(monkeypatch, datetime(2026, 9, 22, 12, 0))

        await TelemetryService(db_session).check_thresholds(vin, LEVEL, 24.0, once=True)

        assert param.alert_retry_at == datetime(2026, 9, 22, 12, 5)

    async def test_a_failed_critical_send_keeps_the_low_state(
        self, db_session, vin, make_param, monkeypatch
    ):
        param = await make_param()
        mock = _dispatcher(monkeypatch)
        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin, LEVEL, 24.0, once=True)

        mock.return_value = {}
        await svc.check_thresholds(vin, LEVEL, 9.0, once=True)

        assert param.alert_state == "low"

    async def test_no_lines_no_alert(self, db_session, vin, make_param, monkeypatch):
        await make_param(warning_min=None, critical_min=None)
        mock = _dispatcher(monkeypatch)

        await TelemetryService(db_session).check_thresholds(vin, LEVEL, 0.0, once=True)

        mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
class TestCooldownModeKnowsCritical:
    async def test_a_wican_reading_below_critical_says_critical(
        self, db_session, vin, make_param, monkeypatch
    ):
        """The cooldown mode (a WiCAN reading): it still names the band."""
        await make_param(param_key="THRESHONCE-FUEL", warning_min=25.0, critical_min=10.0)
        mock = _dispatcher(monkeypatch)

        await TelemetryService(db_session).check_thresholds(vin, "THRESHONCE-FUEL", 5.0)

        assert _sent(mock) == [("critical", 10.0)]

    async def test_a_wican_reading_keeps_no_state(self, db_session, vin, make_param, monkeypatch):
        param = await make_param(param_key="THRESHONCE-FUEL2", warning_min=25.0, critical_min=None)
        _dispatcher(monkeypatch)

        await TelemetryService(db_session).check_thresholds(vin, "THRESHONCE-FUEL2", 5.0)

        assert param.alert_state is None
        assert param.warning_last_notified_at is not None
