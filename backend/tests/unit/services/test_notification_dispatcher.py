"""Unit tests for notification dispatcher service.

Tests event routing, service discovery, and priority handling.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.notifications.base import NotificationService
from app.services.notifications.dispatcher import (
    EVENT_PRIORITY_MAP,
    EVENT_SETTINGS_MAP,
    EVENT_TAGS_MAP,
    NotificationDispatcher,
)


class FakeNotificationService(NotificationService):
    """Fake notification service for testing."""

    service_name = "fake"

    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed
        self.sent_messages: list[dict] = []
        self.closed = False

    async def send(self, title, message, priority="default", tags=None, url=None):
        self.sent_messages.append(
            {"title": title, "message": message, "priority": priority, "tags": tags, "url": url}
        )
        return self.should_succeed

    async def test_connection(self):
        return (True, "OK")

    async def close(self):
        self.closed = True


@pytest.mark.unit
@pytest.mark.notifications
class TestEventSettingsMaps:
    """Test that event configuration maps are consistent."""

    def test_all_events_have_priority(self):
        """Every mapped event should have a priority entry."""
        for event_type in EVENT_SETTINGS_MAP:
            assert event_type in EVENT_PRIORITY_MAP, f"Missing priority for {event_type}"

    def test_all_events_have_tags(self):
        """Every mapped event should have a tags entry."""
        for event_type in EVENT_SETTINGS_MAP:
            assert event_type in EVENT_TAGS_MAP, f"Missing tags for {event_type}"

    def test_priority_values_are_valid(self):
        """All priority values should be valid ntfy priorities."""
        valid_priorities = {"min", "low", "default", "high", "urgent"}
        for event_type, priority in EVENT_PRIORITY_MAP.items():
            assert priority in valid_priorities, f"Invalid priority '{priority}' for {event_type}"


@pytest.mark.unit
@pytest.mark.notifications
class TestNotificationDispatcher:
    """Test the NotificationDispatcher class."""

    @pytest.fixture
    def mock_db(self):
        """Provide a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def dispatcher(self, mock_db):
        """Provide a dispatcher instance."""
        return NotificationDispatcher(mock_db)

    @pytest.mark.asyncio
    async def test_dispatch_returns_empty_when_event_disabled(self, dispatcher):
        """Test dispatch returns empty dict when event type is disabled."""
        with patch.object(dispatcher, "_is_event_enabled", return_value=False):
            results = await dispatcher.dispatch("recall_detected", "Title", "Message")

        assert results == {}

    @pytest.mark.asyncio
    async def test_dispatch_returns_empty_when_no_services(self, dispatcher):
        """Test dispatch returns empty dict when no services enabled."""
        with (
            patch.object(dispatcher, "_is_event_enabled", return_value=True),
            patch.object(dispatcher, "_get_enabled_services", return_value=[]),
        ):
            results = await dispatcher.dispatch("recall_detected", "Title", "Message")

        assert results == {}

    @pytest.mark.asyncio
    async def test_dispatch_sends_to_enabled_service(self, dispatcher):
        """Test dispatch sends to all enabled services."""
        fake_service = FakeNotificationService(should_succeed=True)

        with (
            patch.object(dispatcher, "_is_event_enabled", return_value=True),
            patch.object(dispatcher, "_get_enabled_services", return_value=[fake_service]),
            patch.object(dispatcher, "_get_setting_int", return_value=3),
            patch.object(dispatcher, "_get_setting", return_value="2.0"),
        ):
            results = await dispatcher.dispatch(
                "service_due",
                "Service Due",
                "Oil change is due",
            )

        assert results == {"fake": True}
        assert len(fake_service.sent_messages) == 1
        assert fake_service.sent_messages[0]["title"] == "Service Due"
        assert fake_service.closed is True

    @pytest.mark.asyncio
    async def test_dispatch_uses_default_priority(self, dispatcher):
        """Test dispatch uses event-specific priority when not overridden."""
        fake_service = FakeNotificationService(should_succeed=True)

        with (
            patch.object(dispatcher, "_is_event_enabled", return_value=True),
            patch.object(dispatcher, "_get_enabled_services", return_value=[fake_service]),
            patch.object(dispatcher, "_get_setting_int", return_value=3),
            patch.object(dispatcher, "_get_setting", return_value="2.0"),
        ):
            await dispatcher.dispatch("recall_detected", "Alert", "Recall found")

        assert fake_service.sent_messages[0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_dispatch_uses_retry_for_high_priority(self, dispatcher):
        """Test that high-priority events use send_with_retry."""
        fake_service = FakeNotificationService(should_succeed=True)
        fake_service.send_with_retry = AsyncMock(return_value=True)

        with (
            patch.object(dispatcher, "_is_event_enabled", return_value=True),
            patch.object(dispatcher, "_get_enabled_services", return_value=[fake_service]),
            patch.object(dispatcher, "_get_setting_int", return_value=3),
            patch.object(dispatcher, "_get_setting", return_value="2.0"),
        ):
            await dispatcher.dispatch("recall_detected", "Alert", "High priority")

        fake_service.send_with_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_handles_service_failure(self, dispatcher):
        """Test dispatch handles service exceptions gracefully."""
        failing_service = FakeNotificationService(should_succeed=False)
        failing_service.send = AsyncMock(side_effect=Exception("Connection failed"))

        with (
            patch.object(dispatcher, "_is_event_enabled", return_value=True),
            patch.object(dispatcher, "_get_enabled_services", return_value=[failing_service]),
            patch.object(dispatcher, "_get_setting_int", return_value=3),
            patch.object(dispatcher, "_get_setting", return_value="2.0"),
        ):
            results = await dispatcher.dispatch("service_due", "Title", "Message")

        assert results == {"fake": False}
        assert failing_service.closed is True

    @pytest.mark.asyncio
    async def test_dispatch_multiple_services(self, dispatcher):
        """Test dispatch sends to multiple enabled services."""
        service1 = FakeNotificationService(should_succeed=True)
        service1.service_name = "ntfy"
        service2 = FakeNotificationService(should_succeed=True)
        service2.service_name = "discord"

        with (
            patch.object(dispatcher, "_is_event_enabled", return_value=True),
            patch.object(dispatcher, "_get_enabled_services", return_value=[service1, service2]),
            patch.object(dispatcher, "_get_setting_int", return_value=3),
            patch.object(dispatcher, "_get_setting", return_value="2.0"),
        ):
            results = await dispatcher.dispatch("service_due", "Title", "Message")

        assert results == {"ntfy": True, "discord": True}
        assert len(service1.sent_messages) == 1
        assert len(service2.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_is_event_enabled_unknown_event(self, dispatcher):
        """Test unknown event types are allowed by default."""
        with patch.object(dispatcher, "_has_any_service_enabled", return_value=True):
            result = await dispatcher._is_event_enabled("unknown_event")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_event_enabled_no_services(self, dispatcher):
        """Test event is disabled when no services are enabled."""
        with patch.object(dispatcher, "_has_any_service_enabled", return_value=False):
            result = await dispatcher._is_event_enabled("recall_detected")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_setting_bool_true_values(self, dispatcher):
        """Test boolean setting parsing for true values."""
        for val in ("true", "1", "yes", "True", "YES"):
            with patch.object(dispatcher, "_get_setting", return_value=val):
                result = await dispatcher._get_setting_bool("key")
                assert result is True, f"Expected True for '{val}'"

    @pytest.mark.asyncio
    async def test_get_setting_bool_false_values(self, dispatcher):
        """Test boolean setting parsing for false values."""
        for val in ("false", "0", "no", ""):
            with patch.object(dispatcher, "_get_setting", return_value=val):
                result = await dispatcher._get_setting_bool("key")
                assert result is False, f"Expected False for '{val}'"

    @pytest.mark.asyncio
    async def test_get_setting_int_valid(self, dispatcher):
        """Test integer setting parsing."""
        with patch.object(dispatcher, "_get_setting", return_value="42"):
            result = await dispatcher._get_setting_int("key")
            assert result == 42

    @pytest.mark.asyncio
    async def test_get_setting_int_invalid_returns_default(self, dispatcher):
        """Test integer setting returns default on parse failure."""
        with patch.object(dispatcher, "_get_setting", return_value="not-a-number"):
            result = await dispatcher._get_setting_int("key", default=5)
            assert result == 5


@pytest.mark.unit
@pytest.mark.notifications
class TestConvenienceMethods:
    """Test notification dispatcher convenience methods."""

    @pytest.fixture
    def dispatcher(self):
        """Provide a dispatcher with mocked dispatch."""
        d = NotificationDispatcher(AsyncMock())
        d.dispatch = AsyncMock(return_value={"ntfy": True})
        return d

    @pytest.mark.asyncio
    async def test_notify_recall_detected(self, dispatcher):
        """Test recall notification formatting."""
        await dispatcher.notify_recall_detected("2018 Honda Accord", 3)

        dispatcher.dispatch.assert_awaited_once()
        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "recall_detected"
        assert "2018 Honda Accord" in call_kwargs.kwargs["title"]
        assert "3 new recall(s)" in call_kwargs.kwargs["message"]

    @pytest.mark.asyncio
    async def test_notify_service_due(self, dispatcher):
        """Test service due notification formatting."""
        await dispatcher.notify_service_due("My Truck", "Oil Change", 7)

        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "service_due"
        assert "Oil Change" in call_kwargs.kwargs["message"]
        assert "7 day(s)" in call_kwargs.kwargs["message"]

    @pytest.mark.asyncio
    async def test_notify_service_overdue(self, dispatcher):
        """Test service overdue notification formatting."""
        await dispatcher.notify_service_overdue("My Truck", "Tire Rotation", 14)

        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "service_overdue"
        assert "14 day(s) overdue" in call_kwargs.kwargs["message"]

    @pytest.mark.asyncio
    async def test_notify_odometer_milestone(self, dispatcher):
        """Test odometer milestone notification formatting."""
        await dispatcher.notify_odometer_milestone("My Truck", 100000)

        call_kwargs = dispatcher.dispatch.call_args
        assert "100,000" in call_kwargs.kwargs["message"]

    @pytest.mark.asyncio
    async def test_notify_livelink_new_device(self, dispatcher):
        """Test new device notification formatting."""
        await dispatcher.notify_livelink_new_device("wican-abc123", "3.0")

        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "livelink_new_device"
        assert "wican-abc123" in call_kwargs.kwargs["message"]
        assert "(3.0)" in call_kwargs.kwargs["message"]

    @pytest.mark.asyncio
    async def test_notify_livelink_threshold_alert(self, dispatcher):
        """Test threshold alert notification formatting."""
        await dispatcher.notify_livelink_threshold_alert(
            "My Truck", "Engine Temp", 250.5, "max", 230.0, "°F"
        )

        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "livelink_threshold_alert"
        assert "exceeded maximum" in call_kwargs.kwargs["message"]
        assert "250.5 °F" in call_kwargs.kwargs["message"]

    @pytest.mark.asyncio
    async def test_notify_livelink_firmware_update(self, dispatcher):
        """Test firmware update notification formatting."""
        await dispatcher.notify_livelink_firmware_update("wican-abc", "2.95", "3.0")

        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs.kwargs["event_type"] == "livelink_firmware_update"
        assert "v2.95" in call_kwargs.kwargs["message"]
        assert "3.0" in call_kwargs.kwargs["message"]
