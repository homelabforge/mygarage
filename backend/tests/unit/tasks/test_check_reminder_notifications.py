"""The 08:00 job raises the brake reminders time alone made due, then notifies (#202)."""

import pytest

from app.services import reminder_service
from app.services.brake_service import BrakeService
from app.tasks import scheduled

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the job did, in order, with the session and both passes stubbed."""
    seen: list[str] = []

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

        async def rollback(self) -> None:
            seen.append("rollback")

    async def _zone(_db: object) -> None:
        seen.append("zone")

    async def _notify(_db: object) -> None:
        seen.append("notify")

    monkeypatch.setattr(scheduled, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(scheduled, "load_household_zone", _zone)
    monkeypatch.setattr(reminder_service, "check_due_reminders", _notify)
    return seen


async def test_brakes_are_refreshed_before_the_notifications(calls, monkeypatch):
    async def _refresh(_self: BrakeService) -> None:
        calls.append("brakes")

    monkeypatch.setattr(BrakeService, "refresh_reminders", _refresh)
    await scheduled.check_reminder_notifications()
    assert calls == ["zone", "brakes", "notify"]


async def test_a_failed_refresh_still_notifies(calls, monkeypatch):
    async def _refresh(_self: BrakeService) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(BrakeService, "refresh_reminders", _refresh)
    await scheduled.check_reminder_notifications()
    assert calls == ["zone", "rollback", "notify"]
