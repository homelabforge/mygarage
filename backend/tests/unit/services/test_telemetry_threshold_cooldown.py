"""Unit tests for TelemetryService.check_thresholds cooldown (Task 13).

Task 12 backfilled `param_class` for existing telemetry parameters, which
makes the previously-inert `check_thresholds` path reachable in anger: a
breaching WiCAN telemetry frame can arrive several times a minute, and
without a cooldown every single one would dispatch a fresh notification.

These tests pin a per-parameter cooldown keyed off
`LiveLinkParameter.warning_last_notified_at`, sized by the pre-existing
admin setting ``livelink_alert_cooldown_minutes`` (migration 034, exposed
via ``LiveLinkService.get_alert_cooldown_minutes``, default 30 when unset):

- a breach dispatches a notification and stamps the cooldown
- a second breach inside the window is suppressed (no dispatch)
- a breach after the window elapses dispatches again
- a non-breaching value never dispatches and never stamps
- the stamp is only set when at least one service actually ACCEPTED the
  notification — an empty result (no services enabled) or an all-failed
  result (transient outage) must not start the cooldown clock
- changing the admin setting changes the window
"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle import Vehicle
from app.services.settings_service import SettingsService
from app.services.telemetry_service import TelemetryService


@pytest_asyncio.fixture
async def make_vehicle(db_session: AsyncSession):
    """Create a minimal vehicle so check_thresholds can resolve a display name."""

    async def _factory() -> str:
        vin = "THRESHCOOLDOWN001"
        vehicle = Vehicle(
            vin=vin,
            nickname="Threshold Test Car",
            vehicle_type="Car",
            year=2020,
            make="TestMake",
            model="TestModel",
        )
        db_session.add(vehicle)
        await db_session.flush()
        return vin

    return _factory


@pytest_asyncio.fixture
async def make_param(db_session: AsyncSession):
    """Create a LiveLinkParameter with a warning_max threshold."""

    async def _factory(param_key: str = "0C-ENGINERPM", warning_max: float = 100.0):
        param = LiveLinkParameter(
            param_key=param_key,
            display_name="Test Param",
            unit="unit",
            param_class="frequency",
            category="engine",
            warning_min=None,
            warning_max=warning_max,
            show_on_dashboard=True,
            archive_only=False,
            storage_interval_seconds=0,
        )
        db_session.add(param)
        await db_session.flush()
        return param

    return _factory


def _patch_dispatcher(monkeypatch, *, results: dict[str, bool] | None = None):
    """Patch NotificationDispatcher.notify_livelink_threshold_alert.

    ``results`` is the dict the dispatcher returns: service name -> success.
    ``{"ntfy": True}`` mimics a service accepting the message; ``{}`` mimics
    a dispatch that reached zero enabled services; ``{"discord": False}``
    mimics an attempted-but-failed send (the dispatcher records False for
    caught send errors).
    """
    mock = AsyncMock(return_value=results if results is not None else {"ntfy": True})
    monkeypatch.setattr(
        "app.services.notifications.dispatcher.NotificationDispatcher.notify_livelink_threshold_alert",
        mock,
    )
    return mock


@pytest.mark.unit
@pytest.mark.asyncio
class TestCheckThresholdsCooldown:
    async def test_breach_dispatches_and_stamps_cooldown(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch)

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)

        mock.assert_awaited_once()
        assert param.warning_last_notified_at is not None

    async def test_second_breach_within_window_is_suppressed(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch)

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)
        assert mock.await_count == 1
        first_stamp = param.warning_last_notified_at

        # 5 minutes later — still inside the default 30-minute window.
        monkeypatch.setattr(
            "app.services.telemetry_service.utc_now",
            lambda: first_stamp + timedelta(minutes=5),
        )
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=160.0)

        assert mock.await_count == 1  # no second dispatch
        assert param.warning_last_notified_at == first_stamp  # stamp unchanged

    async def test_breach_after_window_dispatches_again(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch)

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)
        assert mock.await_count == 1
        first_stamp = param.warning_last_notified_at

        # 31 minutes later — outside the default 30-minute window.
        later = first_stamp + timedelta(minutes=31)
        monkeypatch.setattr("app.services.telemetry_service.utc_now", lambda: later)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=160.0)

        assert mock.await_count == 2
        assert param.warning_last_notified_at == later

    async def test_admin_setting_changes_the_window(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        """The cooldown honors `livelink_alert_cooldown_minutes` — with a
        5-minute setting, a breach 6 minutes after the stamp dispatches again
        (it would still be suppressed under the 30-minute default)."""
        await SettingsService.set(db_session, "livelink_alert_cooldown_minutes", "5")
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch)

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)
        assert mock.await_count == 1
        first_stamp = param.warning_last_notified_at

        # 4 minutes later — inside the 5-minute window: suppressed.
        monkeypatch.setattr(
            "app.services.telemetry_service.utc_now",
            lambda: first_stamp + timedelta(minutes=4),
        )
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=160.0)
        assert mock.await_count == 1

        # 6 minutes later — outside the 5-minute window: dispatches again.
        monkeypatch.setattr(
            "app.services.telemetry_service.utc_now",
            lambda: first_stamp + timedelta(minutes=6),
        )
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=160.0)
        assert mock.await_count == 2

    async def test_non_breaching_value_never_dispatches_or_stamps(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch)

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=50.0)

        mock.assert_not_awaited()
        assert param.warning_last_notified_at is None

    async def test_stamp_not_set_when_no_services_enabled(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        """Dispatch reaches zero enabled services (empty result dict) — the
        cooldown clock must not start, so the very next breach dispatches
        again instead of silently going dark for the whole window."""
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch, results={})

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)

        mock.assert_awaited_once()
        assert param.warning_last_notified_at is None

    async def test_stamp_not_set_when_all_sends_failed(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        """The dispatcher records False for attempted-but-failed sends. An
        all-failed result (e.g. transient outage of every enabled service)
        must not stamp the cooldown — otherwise real alerts go silent for
        the whole window with nothing ever delivered."""
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch, results={"discord": False})

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)

        mock.assert_awaited_once()
        assert param.warning_last_notified_at is None

    async def test_stamp_set_when_at_least_one_send_succeeded(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        """Partial success (one service accepted, one failed) counts as sent."""
        vin = await make_vehicle()
        param = await make_param()
        mock = _patch_dispatcher(monkeypatch, results={"discord": True, "ntfy": False})

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=150.0)

        mock.assert_awaited_once()
        assert param.warning_last_notified_at is not None

    async def test_min_threshold_breach_also_respects_cooldown(
        self, db_session, make_vehicle, make_param, monkeypatch
    ):
        vin = await make_vehicle()
        param = await make_param(param_key="05-ENGINECOOLANTTEMP")
        param.warning_max = None
        param.warning_min = 10.0
        await db_session.flush()
        mock = _patch_dispatcher(monkeypatch)

        svc = TelemetryService(db_session)
        await svc.check_thresholds(vin=vin, param_key=param.param_key, value=-5.0)

        mock.assert_awaited_once()
        assert param.warning_last_notified_at is not None
