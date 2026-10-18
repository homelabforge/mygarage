"""The 08:00 reminder job: brakes first (#202), then `check_due_reminders`.

The sweep tests run the real `NotificationDispatcher`, so the two switches and
the event priorities are the ones a user gets. Only the ntfy provider's
`send` and `send_with_retry` are stubbed, and they return what a provider
returns. The suite shares one database with no rollback: every vehicle here
carries this module's VIN prefix and is wiped before and after each test.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import Update, delete, select, text, update
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.settings import Setting
from app.models.vehicle import Vehicle
from app.services import reminder_service
from app.services.brake_service import BrakeService
from app.services.notifications.dispatcher import EVENT_SETTINGS_MAP
from app.services.notifications.ntfy import NtfyNotificationService
from app.services.reminder_service import DueContext, check_due_reminders
from app.services.settings_init import DEFAULT_SETTINGS
from app.tasks import scheduled
from app.utils.datetime_utils import utc_now
from app.utils.household_time import household_today

_VIN_PREFIX = "RMNOTIFY"


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


# ---------------------------------------------------------------------------
# The sweep, through the real dispatcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Sent:
    title: str
    priority: str
    retried: bool


@dataclass
class _Provider:
    """The stubbed ntfy provider: what it was asked to send, and what it answers."""

    calls: list[_Sent] = field(default_factory=list[_Sent])
    result: bool = True
    on_send: Callable[[str], Awaitable[None]] | None = None

    def titles(self, name: str) -> list[str]:
        """Titles sent for the reminder called ``name``. The sweep covers the
        whole shared database, so other modules' reminders go out too."""
        return [c.title for c in self.calls if c.title.endswith(f": {name}")]

    def sent(self, name: str) -> list[_Sent]:
        return [c for c in self.calls if c.title.endswith(f": {name}")]


_OTHER_PROVIDERS = (
    "gotify_enabled",
    "pushover_enabled",
    "slack_enabled",
    "discord_enabled",
    "matrix_enabled",
    "telegram_enabled",
    "email_enabled",
)


async def _set(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value, category="notifications"))
    else:
        row.value = value
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(db_session: AsyncSession) -> AsyncGenerator[None]:
    """Wipe this module's vehicles (their reminders and readings cascade)."""

    async def _wipe() -> None:
        await db_session.rollback()
        await db_session.execute(delete(Reminder).where(Reminder.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.execute(
            delete(OdometerRecord).where(OdometerRecord.vin.like(f"{_VIN_PREFIX}%"))
        )
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.like(f"{_VIN_PREFIX}%")))
        await db_session.commit()

    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def provider(
    db_session: AsyncSession,
    keep_rows: Callable[..., Awaitable[None]],
    monkeypatch: pytest.MonkeyPatch,
) -> _Provider:
    """ntfy on and configured, both switches on, every other provider off."""
    stub = _Provider()
    values = {
        "ntfy_enabled": "true",
        "ntfy_server": "http://ntfy.invalid",
        "ntfy_topic": "reminder-sweep",
        "notify_service_due": "true",
        "notify_service_overdue": "true",
        **dict.fromkeys(_OTHER_PROVIDERS, "false"),
    }
    await keep_rows(*values)
    for key, value in values.items():
        await _set(db_session, key, value)

    async def _record(title: str, priority: str, retried: bool) -> bool:
        stub.calls.append(_Sent(title=title, priority=priority, retried=retried))
        if stub.on_send is not None:
            await stub.on_send(title)
        return stub.result

    async def _send(
        _self: NtfyNotificationService,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | None = None,
        url: str | None = None,
    ) -> bool:
        return await _record(title, priority, retried=False)

    async def _send_with_retry(
        _self: NtfyNotificationService,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | None = None,
        url: str | None = None,
        max_attempts: int = 3,
        retry_delay: float = 2.0,
    ) -> bool:
        return await _record(title, priority, retried=True)

    monkeypatch.setattr(NtfyNotificationService, "send", _send)
    monkeypatch.setattr(NtfyNotificationService, "send_with_retry", _send_with_retry)
    return stub


async def _vehicle(db: AsyncSession, *, archived: bool = False) -> str:
    vin = f"{_VIN_PREFIX}{uuid.uuid4().hex[:9].upper()}"
    db.add(
        Vehicle(
            vin=vin,
            nickname="Reminder sweep",
            vehicle_type="Car",
            archived_at=utc_now() if archived else None,
        )
    )
    await db.commit()
    return vin


async def _reading(db: AsyncSession, vin: str, day: date, km: str) -> int:
    record = OdometerRecord(vin=vin, date=day, odometer_km=Decimal(km), source="manual")
    db.add(record)
    await db.commit()
    return record.id


async def _reminder(db: AsyncSession, vin: str, title: str, **fields: object) -> int:
    reminder = Reminder(vin=vin, title=title, status="pending", **fields)
    db.add(reminder)
    await db.commit()
    return reminder.id


async def _stamp(sessionmaker: async_sessionmaker[AsyncSession], rid: int) -> datetime | None:
    """The committed stamp, read from a second session."""
    async with sessionmaker() as fresh:
        return (
            await fresh.execute(select(Reminder.last_notified_at).where(Reminder.id == rid))
        ).scalar_one()


class TestWhatTheSweepSends:
    async def test_a_date_reminder_due_in_twenty_days_gets_a_heads_up(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """Main sent nothing until the date itself: its date check was `due_date <= today`."""
        vin = await _vehicle(db_session)
        await _reminder(
            db_session,
            vin,
            "Sweep date twenty",
            reminder_type="date",
            due_date=household_today() + timedelta(days=20),
        )

        await check_due_reminders(db_session)

        assert provider.titles("Sweep date twenty") == ["Reminder due soon: Sweep date twenty"]
        assert [c.priority for c in provider.sent("Sweep date twenty")] == ["default"]

    async def test_a_heads_up_goes_once(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """A stamped due-soon reminder gets nothing, while a null-stamped twin in
        the same run does: the stamp, not the type gate, is what holds it back."""
        vin = await _vehicle(db_session)
        due = household_today() + timedelta(days=20)
        await _reminder(
            db_session,
            vin,
            "Sweep told already",
            reminder_type="date",
            due_date=due,
            last_notified_at=utc_now() - timedelta(days=3),
        )
        await _reminder(db_session, vin, "Sweep never told", reminder_type="date", due_date=due)

        await check_due_reminders(db_session)

        assert provider.titles("Sweep told already") == []
        assert provider.titles("Sweep never told") == ["Reminder due soon: Sweep never told"]

    async def test_an_overdue_reminder_goes_as_service_overdue_with_high_priority(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """Main sent `reminder_due`, an event no switch maps, at default priority."""
        vin = await _vehicle(db_session)
        await _reminder(
            db_session,
            vin,
            "Sweep overdue",
            reminder_type="date",
            due_date=household_today() - timedelta(days=1),
        )

        await check_due_reminders(db_session)

        assert provider.sent("Sweep overdue") == [
            _Sent(title="Reminder overdue: Sweep overdue", priority="high", retried=True)
        ]

    async def _one_of_each(self, db: AsyncSession) -> None:
        """A smart reminder five days out (main's 7-day window sent it) and an
        overdue date reminder, on one vehicle."""
        vin = await _vehicle(db)
        today = household_today()
        await _reading(db, vin, today - timedelta(days=10), "10000")
        await _reading(db, vin, today, "11000")
        await _reminder(
            db,
            vin,
            "Sweep switch soon",
            reminder_type="smart",
            due_date=today + timedelta(days=365),
            due_mileage_km=Decimal("11500"),
            start_odometer_km=Decimal("10000"),
        )
        await _reminder(
            db,
            vin,
            "Sweep switch late",
            reminder_type="date",
            due_date=today - timedelta(days=2),
        )

    async def test_the_due_switch_holds_back_only_the_heads_up(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """Main sent both, as `reminder_due`, whatever the switch said."""
        await _set(db_session, "notify_service_due", "false")
        await self._one_of_each(db_session)

        await check_due_reminders(db_session)

        assert provider.titles("Sweep switch soon") == []
        assert provider.titles("Sweep switch late") == ["Reminder overdue: Sweep switch late"]

    async def test_the_overdue_switch_holds_back_only_the_overdue_one(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        await _set(db_session, "notify_service_overdue", "false")
        await self._one_of_each(db_session)

        await check_due_reminders(db_session)

        assert provider.titles("Sweep switch soon") == ["Reminder due soon: Sweep switch soon"]
        assert provider.titles("Sweep switch late") == []

    async def test_a_mileage_reminder_with_no_rate_gets_a_heads_up_at_ninety_two_percent(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """One reading, so no rate: the 90% fallback decides. Main waited for the target."""
        vin = await _vehicle(db_session)
        await _reading(db_session, vin, household_today(), "19200")
        await _reminder(
            db_session,
            vin,
            "Sweep ninety two",
            reminder_type="mileage",
            due_mileage_km=Decimal("20000"),
            start_odometer_km=Decimal("10000"),
        )

        await check_due_reminders(db_session)

        assert provider.titles("Sweep ninety two") == ["Reminder due soon: Sweep ninety two"]

    async def test_a_smart_reminder_projected_in_twenty_days_gets_a_heads_up(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """100 km a day, 2,000 km to go. Main's smart window was 7 days."""
        vin = await _vehicle(db_session)
        today = household_today()
        await _reading(db_session, vin, today - timedelta(days=10), "10000")
        await _reading(db_session, vin, today, "11000")
        await _reminder(
            db_session,
            vin,
            "Sweep smart twenty",
            reminder_type="smart",
            due_date=today + timedelta(days=365),
            due_mileage_km=Decimal("13000"),
            start_odometer_km=Decimal("10000"),
        )

        await check_due_reminders(db_session)

        assert provider.titles("Sweep smart twenty") == ["Reminder due soon: Sweep smart twenty"]

    async def test_a_date_typed_reminder_past_its_mileage_is_overdue(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """Field presence decides, not the type. Main checked only the date of a `date` row."""
        vin = await _vehicle(db_session)
        await _reading(db_session, vin, household_today(), "6000")
        await _reminder(
            db_session,
            vin,
            "Sweep date typed mileage",
            reminder_type="date",
            due_date=household_today() + timedelta(days=200),
            due_mileage_km=Decimal("5000"),
        )

        await check_due_reminders(db_session)

        assert provider.titles("Sweep date typed mileage") == [
            "Reminder overdue: Sweep date typed mileage"
        ]

    async def test_an_archived_vehicle_is_silent(
        self, db_session: AsyncSession, provider: _Provider
    ) -> None:
        """Main sent it (NEW-2)."""
        vin = await _vehicle(db_session, archived=True)
        await _reminder(
            db_session,
            vin,
            "Sweep archived",
            reminder_type="date",
            due_date=household_today() - timedelta(days=5),
        )

        await check_due_reminders(db_session)

        assert provider.titles("Sweep archived") == []

    async def test_a_vehicle_whose_context_fails_costs_only_its_own_reminders(
        self,
        db_session: AsyncSession,
        provider: _Provider,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        broken = await _vehicle(db_session)
        healthy = await _vehicle(db_session)
        overdue = household_today() - timedelta(days=1)
        await _reminder(db_session, broken, "Sweep broken", reminder_type="date", due_date=overdue)
        await _reminder(
            db_session, healthy, "Sweep healthy", reminder_type="date", due_date=overdue
        )
        real = reminder_service.load_due_context

        async def _load_or_raise(
            db: AsyncSession, vin: str, pending: list[Reminder], today: date
        ) -> DueContext:
            if vin == broken:
                raise RuntimeError("context blew up")
            return await real(db, vin, pending, today)

        monkeypatch.setattr(reminder_service, "load_due_context", _load_or_raise)

        with caplog.at_level(logging.ERROR, logger="app.services.reminder_service"):
            await check_due_reminders(db_session)

        assert provider.titles("Sweep broken") == []
        assert provider.titles("Sweep healthy") == ["Reminder overdue: Sweep healthy"]
        failures = [
            r
            for r in caplog.records
            if r.getMessage() == f"Reminder check failed for vehicle {broken}"
        ]
        assert len(failures) == 1


class TestTheStamp:
    @pytest.mark.parametrize("failure", ["no provider on", "provider failed"])
    async def test_an_undelivered_overdue_notice_is_not_stamped(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        provider: _Provider,
        failure: str,
    ) -> None:
        """R1-H1. `{}` and `{"ntfy": False}` delivered nothing. Main stamped any
        dispatch that didn't raise."""
        if failure == "no provider on":
            await _set(db_session, "ntfy_enabled", "false")
        else:
            provider.result = False
        vin = await _vehicle(db_session)
        rid = await _reminder(
            db_session,
            vin,
            "Sweep undelivered",
            reminder_type="date",
            due_date=household_today() - timedelta(days=1),
        )

        await check_due_reminders(db_session)

        assert await _stamp(test_sessionmaker, rid) is None

    async def test_only_a_delivery_is_stamped(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        provider: _Provider,
    ) -> None:
        """R1-H1. Nothing configured, then a provider that fails: no stamp either
        time, so the heads-up still goes once the provider works. Then the stamp
        holds back a second heads-up, and the 24 h cooldown an overdue one."""
        vin = await _vehicle(db_session)
        today = household_today()
        await _reading(db_session, vin, today, "19200")
        rid = await _reminder(
            db_session,
            vin,
            "Sweep delivery",
            reminder_type="mileage",
            # Not a whole number, so the stamp's snapshot match covers a decimal.
            due_mileage_km=Decimal("19999.50"),
            start_odometer_km=Decimal("10000"),
        )

        # No provider on: dispatch returns {}.
        await _set(db_session, "ntfy_enabled", "false")
        await check_due_reminders(db_session)
        assert provider.titles("Sweep delivery") == []
        assert await _stamp(test_sessionmaker, rid) is None

        # A provider that fails: {"ntfy": False}.
        await _set(db_session, "ntfy_enabled", "true")
        provider.result = False
        await check_due_reminders(db_session)
        assert provider.titles("Sweep delivery") == ["Reminder due soon: Sweep delivery"]
        assert await _stamp(test_sessionmaker, rid) is None

        provider.result = True
        await check_due_reminders(db_session)
        assert provider.titles("Sweep delivery") == ["Reminder due soon: Sweep delivery"] * 2
        assert await _stamp(test_sessionmaker, rid) is not None

        # Told once: the next sweep says nothing.
        await check_due_reminders(db_session)
        assert len(provider.titles("Sweep delivery")) == 2

        # Past the target within the day: overdue, but inside the cooldown.
        await _reading(db_session, vin, today, "20500")
        await check_due_reminders(db_session)
        assert len(provider.titles("Sweep delivery")) == 2

        # A day on, the overdue one goes.
        await db_session.execute(
            update(Reminder)
            .where(Reminder.id == rid)
            .values(last_notified_at=utc_now() - timedelta(hours=25))
        )
        await db_session.commit()
        await check_due_reminders(db_session)
        assert provider.titles("Sweep delivery")[-1] == "Reminder overdue: Sweep delivery"
        assert len(provider.titles("Sweep delivery")) == 3

    async def test_an_edit_made_while_sending_keeps_its_null_stamp(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        provider: _Provider,
    ) -> None:
        """R1-H3. Another session moves the due date while the notification is
        going out. Main stamped by id regardless, which burned the heads-up for
        the new date."""
        vin = await _vehicle(db_session)
        today = household_today()
        moved_to = today + timedelta(days=10)
        rid = await _reminder(
            db_session,
            vin,
            "Sweep moved mid send",
            reminder_type="date",
            due_date=today - timedelta(days=1),
        )
        edited: list[int] = []

        async def _edit_elsewhere(title: str) -> None:
            if not title.endswith(": Sweep moved mid send") or edited:
                return
            async with test_sessionmaker() as other:
                reminder = await other.get(Reminder, rid)
                assert reminder is not None
                reminder.due_date = moved_to
                await other.commit()
            edited.append(rid)

        provider.on_send = _edit_elsewhere

        await check_due_reminders(db_session)

        assert edited == [rid]
        assert await _stamp(test_sessionmaker, rid) is None
        assert provider.titles("Sweep moved mid send") == ["Reminder overdue: Sweep moved mid send"]

        # The new date is ten days out, and it gets its heads-up.
        await check_due_reminders(db_session)
        assert provider.titles("Sweep moved mid send")[-1] == (
            "Reminder due soon: Sweep moved mid send"
        )
        assert await _stamp(test_sessionmaker, rid) is not None

    async def test_a_reminder_closed_while_sending_stays_unstamped(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        provider: _Provider,
    ) -> None:
        """R1-H3, the status half. Another session marks it done while the
        notification goes out: a closed reminder gets no stamp. Passes at
        5a8416e8, which already had the clause; dropping
        `status == 'pending'` from the stamp turns it red."""
        vin = await _vehicle(db_session)
        rid = await _reminder(
            db_session,
            vin,
            "Sweep closed mid send",
            reminder_type="date",
            due_date=household_today() - timedelta(days=1),
        )

        async def _close_elsewhere(title: str) -> None:
            if not title.endswith(": Sweep closed mid send"):
                return
            async with test_sessionmaker() as other:
                reminder = await other.get(Reminder, rid)
                assert reminder is not None
                reminder.status = "done"
                await other.commit()

        provider.on_send = _close_elsewhere

        await check_due_reminders(db_session)

        assert provider.titles("Sweep closed mid send") == [
            "Reminder overdue: Sweep closed mid send"
        ]
        assert await _stamp(test_sessionmaker, rid) is None

    async def test_a_failed_stamp_costs_only_its_own_reminder(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        provider: _Provider,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The first stamp's statement fails in the database. The second still
        gets stamped and the run still commits: PostgreSQL would otherwise keep
        the transaction aborted for every stamp after it."""
        vin = await _vehicle(db_session)
        overdue = household_today() - timedelta(days=1)
        failing = await _reminder(
            db_session, vin, "Sweep stamp fails", reminder_type="date", due_date=overdue
        )
        healthy = await _reminder(
            db_session, vin, "Sweep stamp holds", reminder_type="date", due_date=overdue
        )
        real_execute = db_session.execute

        async def _execute(statement: object, *args: object, **kwargs: object) -> Result[object]:
            if isinstance(statement, Update) and failing in statement.compile().params.values():
                await real_execute(text("SELECT no_such_column FROM vehicle_reminders"))
            return await real_execute(statement, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(db_session, "execute", _execute)

        with caplog.at_level(logging.ERROR, logger="app.services.reminder_service"):
            await check_due_reminders(db_session)

        assert provider.titles("Sweep stamp fails") == ["Reminder overdue: Sweep stamp fails"]
        assert provider.titles("Sweep stamp holds") == ["Reminder overdue: Sweep stamp holds"]
        assert await _stamp(test_sessionmaker, failing) is None
        assert await _stamp(test_sessionmaker, healthy) is not None
        assert any(
            r.getMessage().startswith(f"Failed to stamp reminder {failing}:")
            for r in caplog.records
        )

    async def test_due_soon_again_with_the_same_targets_gets_no_second_heads_up(
        self,
        db_session: AsyncSession,
        provider: _Provider,
    ) -> None:
        """F-12. Told, then on track when the rate drops, then due soon again when
        it recovers: the due values never changed, so it stays told."""
        vin = await _vehicle(db_session)
        today = household_today()
        await _reading(db_session, vin, today - timedelta(days=10), "10000")
        await _reading(db_session, vin, today, "11000")
        await _reminder(
            db_session,
            vin,
            "Sweep once gate",
            reminder_type="mileage",
            due_mileage_km=Decimal("13000"),
            start_odometer_km=Decimal("10000"),
        )

        # 100 km a day, 20 days out.
        await check_due_reminders(db_session)
        assert provider.titles("Sweep once gate") == ["Reminder due soon: Sweep once gate"]

        # An old low reading drops the rate to 25 km a day: 80 days out.
        slow = await _reading(db_session, vin, today - timedelta(days=80), "9000")
        await check_due_reminders(db_session)
        assert len(provider.titles("Sweep once gate")) == 1

        # Back to 100 km a day: due soon again, same targets.
        await db_session.execute(delete(OdometerRecord).where(OdometerRecord.id == slow))
        await db_session.commit()
        await check_due_reminders(db_session)
        assert len(provider.titles("Sweep once gate")) == 1


def test_the_old_event_and_the_lead_time_settings_are_gone() -> None:
    """Nothing maps `reminder_due` (it never had a switch), and the two lead
    times, which nothing read, are no longer seeded (D1c)."""
    assert "reminder_due" not in EVENT_SETTINGS_MAP
    assert "notify_service_days" not in DEFAULT_SETTINGS
    assert "notify_service_miles" not in DEFAULT_SETTINGS
