"""`last_notified_at` is a naive column and must be written naive.

`check_due_reminders` builds `now = datetime.now(UTC)` (aware) and assigns it to
`reminder.last_notified_at`, declared `DateTime` with no timezone
(`models/reminder.py:40`).

SQLite accepts that silently, which is why no dev instance has ever shown it.
PostgreSQL raises asyncpg `DataError: invalid input for query argument ...
can't subtract offset-naive and offset-aware datetimes` on the very first
reminder notification, so nobody running PostgreSQL has ever received one.

The READ path was already guarded (`reminder_service.py:370-372` re-attaches
UTC to the naive value it gets back). Only the write was not, which is the
tell: someone hit the symptom on the read side and fixed the half they saw.

This file lives in `tests/integration/` on purpose. `ci.yml:25` sets
`pg-migrations-pytest-path: "tests/migrations/ tests/integration/"`, so only
these two paths run against the PostgreSQL sidecar. The natural home would be
`tests/unit/services/test_reminder_service.py`, where it would pass on SQLite
with the bug fully present and stay green forever.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder


@pytest.mark.asyncio
class TestLastNotifiedAtIsWrittenNaive:
    async def test_a_due_reminder_can_be_marked_notified(
        self, db_session: AsyncSession, test_vehicle: dict[str, object]
    ) -> None:
        """The regression. On PostgreSQL this raised before the row was written."""
        from app.services.reminder_service import check_due_reminders

        reminder = Reminder(
            vin=str(test_vehicle["vin"]),
            title="Naive datetime guard",
            reminder_type="date",
            due_date=date.today() - timedelta(days=1),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        await check_due_reminders(db_session)

        stored = (
            await db_session.execute(select(Reminder).where(Reminder.id == reminder.id))
        ).scalar_one()
        await db_session.refresh(stored)
        assert stored.last_notified_at is not None, (
            "the reminder was due and should have been stamped as notified"
        )
        assert stored.last_notified_at.tzinfo is None, (
            "last_notified_at is a naive column; an aware value must be stripped "
            "before assignment, not handed to the driver"
        )

    async def test_the_cooldown_still_works_after_a_notification(
        self, db_session: AsyncSession, test_vehicle: dict[str, object]
    ) -> None:
        """The read guard and the write must agree.

        Written because stripping tzinfo on write could plausibly be "fixed" by
        making `now` naive throughout, which would break the aware comparison at
        `:370-372` on the next tick. This asserts the second tick is a no-op
        rather than a TypeError.
        """
        from app.services.reminder_service import check_due_reminders

        reminder = Reminder(
            vin=str(test_vehicle["vin"]),
            title="Cooldown guard",
            reminder_type="date",
            due_date=date.today() - timedelta(days=1),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()

        await check_due_reminders(db_session)
        await db_session.refresh(reminder)
        first = reminder.last_notified_at
        assert first is not None

        # Second tick, inside the 24h cooldown: must not raise, must not restamp.
        await check_due_reminders(db_session)
        await db_session.refresh(reminder)
        assert reminder.last_notified_at == first

    async def test_now_is_still_aware_where_it_is_compared(self) -> None:
        """Pins the shape of the fix.

        The column is naive; the comparison against `NOTIFICATION_COOLDOWN` is
        aware. Both are true at once, and a fix that makes `now` naive
        everywhere would pass the first test and silently reintroduce the
        TypeError this module's read guard exists to prevent.
        """
        import inspect

        from app.services import reminder_service

        src = inspect.getsource(reminder_service.check_due_reminders)
        assert "datetime.now(UTC)" in src, (
            "the comparison clock must stay timezone-aware; only the value "
            "assigned to the naive column is stripped"
        )
