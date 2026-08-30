"""
Unit tests for reminder_service — hours-based reminders (Phase 5 of the
hours-usage-model feature).

Adds `due_hours` + a new `'hours'` reminder type with parity to the existing
mileage-reminder path, and redefines `'smart'` to require `due_date` and
EXACTLY ONE of `{due_mileage_km, due_hours}`.

The single most important test in this module is
``test_smart_accepts_existing_date_and_mileage_only`` — an existing-style
smart reminder (`due_date` + `due_mileage_km`, `due_hours` null) MUST still
validate and project via km/day exactly as it did before this feature
existed. Every other backward-compat assertion (mileage/date/both unaffected)
lives alongside it in ``TestValidateReminderStateBackwardCompat``.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import METRIC_PRESET
from app.models import HoursRecord, OdometerRecord, Reminder
from app.models.user import User
from app.services.reminder_service import (
    _build_reminder_message,
    calculate_hours_driving_rate,
    check_due_reminders,
    create_reminder,
    enrich_with_estimate,
    get_current_hours,
    validate_reminder_state,
)
from app.utils.render_context import RenderContext

# `_build_reminder_message` renders a reminder's `due_mileage_km` in the
# reader's distance unit, so these tests state the unit set they expect
# rather than inheriting whatever the shared fixture user happens to carry.
_METRIC_CTX = RenderContext(units=METRIC_PRESET, show_both=False)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def clean_odometer_records(db_session: AsyncSession, test_vehicle):
    """Isolate OdometerRecord rows for the shared test_vehicle vin."""
    await db_session.execute(
        delete(OdometerRecord).where(OdometerRecord.vin == test_vehicle["vin"])
    )
    await db_session.commit()
    yield
    await db_session.execute(
        delete(OdometerRecord).where(OdometerRecord.vin == test_vehicle["vin"])
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def clean_reminders(db_session: AsyncSession, test_vehicle):
    """Isolate Reminder rows for the shared test_vehicle vin."""
    await db_session.execute(delete(Reminder).where(Reminder.vin == test_vehicle["vin"]))
    await db_session.commit()
    yield
    await db_session.execute(delete(Reminder).where(Reminder.vin == test_vehicle["vin"]))
    await db_session.commit()


# clean_hours_records is a shared fixture in tests/unit/conftest.py.


async def _add_odometer_record(
    db_session: AsyncSession, vin: str, reading_date: date, odometer_km: Decimal
) -> OdometerRecord:
    record = OdometerRecord(vin=vin, date=reading_date, odometer_km=odometer_km, source="manual")
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def _add_hours_record(
    db_session: AsyncSession, vin: str, reading_date: date, engine_hours: Decimal
) -> HoursRecord:
    record = HoursRecord(vin=vin, date=reading_date, engine_hours=engine_hours, source="manual")
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


# ---------------------------------------------------------------------------
# validate_reminder_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateReminderStateBackwardCompat:
    """Existing date/mileage/both/smart behavior must be untouched."""

    def test_date_requires_due_date(self):
        with pytest.raises(ValueError, match="due_date required"):
            validate_reminder_state("date", None, None, None)
        # Unaffected: providing due_date satisfies it.
        validate_reminder_state("date", date.today(), None, None)

    def test_mileage_requires_due_mileage_km(self):
        with pytest.raises(ValueError, match="due_mileage_km required"):
            validate_reminder_state("mileage", None, None, None)
        validate_reminder_state("mileage", None, Decimal("50000"), None)

    def test_mileage_type_is_unaffected_by_due_hours_param(self):
        """A due_hours value present alongside 'mileage' changes nothing."""
        validate_reminder_state("mileage", None, Decimal("50000"), Decimal("100.0"))

    def test_both_requires_date_and_mileage(self):
        with pytest.raises(ValueError, match="due_date required"):
            validate_reminder_state("both", None, Decimal("50000"), None)
        with pytest.raises(ValueError, match="due_mileage_km required"):
            validate_reminder_state("both", date.today(), None, None)
        # Unaffected: 'both' stays date+mileage, never date+hours.
        validate_reminder_state("both", date.today(), Decimal("50000"), None)

    def test_smart_accepts_existing_date_and_mileage_only(self):
        """CRITICAL backward-compat case: due_date + due_mileage_km, due_hours
        null — exactly today's existing smart-reminder shape — must still
        validate cleanly under the redefined rule."""
        validate_reminder_state("smart", date.today(), Decimal("60000"), None)

    def test_smart_still_requires_due_date(self):
        with pytest.raises(ValueError, match="due_date required"):
            validate_reminder_state("smart", None, Decimal("60000"), None)


@pytest.mark.unit
class TestValidateReminderStateHours:
    """New 'hours' type + redefined 'smart' exactly-one-of rule."""

    def test_hours_requires_due_hours(self):
        with pytest.raises(ValueError, match="due_hours required"):
            validate_reminder_state("hours", None, None, None)
        validate_reminder_state("hours", None, None, Decimal("500.0"))

    def test_hours_type_does_not_require_due_date(self):
        """Mirrors 'mileage': no date requirement."""
        validate_reminder_state("hours", None, None, Decimal("500.0"))

    def test_smart_accepts_date_and_hours_only(self):
        """New capability: date + due_hours (mileage null) for hour-vehicles."""
        validate_reminder_state("smart", date.today(), None, Decimal("500.0"))

    def test_smart_rejects_date_plus_both_metrics(self):
        with pytest.raises(ValueError, match="exactly one"):
            validate_reminder_state("smart", date.today(), Decimal("60000"), Decimal("500.0"))

    def test_smart_rejects_date_plus_neither_metric(self):
        with pytest.raises(ValueError, match="exactly one"):
            validate_reminder_state("smart", date.today(), None, None)

    def test_smart_no_longer_hard_requires_due_mileage_km(self):
        """Old code raised on missing due_mileage_km unconditionally for
        'smart'; the redefined rule must NOT do that when due_hours covers
        the exactly-one requirement instead."""
        # Should not raise — due_hours alone satisfies 'smart' now.
        validate_reminder_state("smart", date.today(), None, Decimal("1.0"))


# ---------------------------------------------------------------------------
# get_current_hours
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetCurrentHours:
    """Mirrors get_current_mileage; reuses hours_service semantics (max
    reading wins, not most recent date)."""

    async def test_returns_none_when_no_history(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        result = await get_current_hours(test_vehicle["vin"], db_session)
        assert result is None

    async def test_returns_canonical_max_reading(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date(2024, 1, 1), Decimal("500.0"))
        # Later date, LOWER reading — the max reading must still win (a
        # physical hour-meter is monotonic; mirrors latest_engine_hours_and_date).
        await _add_hours_record(db_session, vin, date(2024, 6, 1), Decimal("120.0"))

        result = await get_current_hours(vin, db_session)
        assert result == Decimal("500.0")


# ---------------------------------------------------------------------------
# calculate_hours_driving_rate
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCalculateHoursDrivingRate:
    """Mirrors calculate_driving_rate: average engine-hours/day over the
    last 90 days, substituting engine_hours for odometer_km."""

    async def test_none_with_fewer_than_two_records(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date.today(), Decimal("100.0"))
        rate = await calculate_hours_driving_rate(vin, db_session)
        assert rate is None

    async def test_computes_average_hours_per_day(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        vin = test_vehicle["vin"]
        start = date.today() - timedelta(days=20)
        end = date.today() - timedelta(days=0)
        await _add_hours_record(db_session, vin, start, Decimal("100.0"))
        await _add_hours_record(db_session, vin, end, Decimal("300.0"))

        rate = await calculate_hours_driving_rate(vin, db_session)

        # (300 - 100) / 20 days = 10.0 hr/day
        assert rate == pytest.approx(10.0)

    async def test_outside_90_day_window_excluded(
        self, db_session: AsyncSession, test_vehicle, clean_hours_records
    ):
        vin = test_vehicle["vin"]
        # Only one record inside the 90-day window -> None.
        await _add_hours_record(
            db_session, vin, date.today() - timedelta(days=200), Decimal("1000.0")
        )
        await _add_hours_record(db_session, vin, date.today(), Decimal("1200.0"))

        rate = await calculate_hours_driving_rate(vin, db_session)
        assert rate is None


# ---------------------------------------------------------------------------
# is_reminder_overdue — Phase 6b shared helper (dashboard + family dashboard)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsReminderOverdue:
    """Pure-function tests for the shared overdue check extracted to end the
    dashboard.py / family_dashboard_service.py duplication (Phase 6b). Field-
    presence gated, mirroring how both call sites evaluated it inline before
    extraction: a reminder is overdue if ANY of due_date/due_mileage_km/
    due_hours has been reached, regardless of reminder_type.
    """

    def _reminder(self, **kwargs) -> Reminder:
        base = {
            "vin": "1HGBH41JXMN109186",
            "title": "Test reminder",
            "reminder_type": "date",
            "status": "pending",
        }
        base.update(kwargs)
        return Reminder(**base)

    def test_overdue_by_date(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(due_date=date(2020, 1, 1))
        assert is_reminder_overdue(reminder, None, None, today=date(2024, 1, 1)) is True

    def test_not_overdue_by_future_date(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(due_date=date(2024, 6, 1))
        assert is_reminder_overdue(reminder, None, None, today=date(2024, 1, 1)) is False

    def test_overdue_by_mileage(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(
            reminder_type="mileage", due_date=None, due_mileage_km=Decimal("50000")
        )
        assert is_reminder_overdue(reminder, Decimal("55000"), None, today=date.today()) is True

    def test_not_overdue_by_mileage_when_below_target(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(
            reminder_type="mileage", due_date=None, due_mileage_km=Decimal("50000")
        )
        assert is_reminder_overdue(reminder, Decimal("40000"), None, today=date.today()) is False

    def test_overdue_by_hours(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(reminder_type="hours", due_date=None, due_hours=Decimal("500.0"))
        assert is_reminder_overdue(reminder, None, Decimal("600.0"), today=date.today()) is True

    def test_not_overdue_by_hours_when_below_target(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(reminder_type="hours", due_date=None, due_hours=Decimal("500.0"))
        assert is_reminder_overdue(reminder, None, Decimal("100.0"), today=date.today()) is False

    def test_no_readings_never_overdue_by_usage(self):
        """None current_km / current_hours must never crash and must never
        count as overdue (mirrors the pre-extraction inline `and` guards)."""
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(reminder_type="hours", due_date=None, due_hours=Decimal("500.0"))
        assert is_reminder_overdue(reminder, None, None, today=date.today()) is False

    def test_defaults_today_when_not_provided(self):
        """Without an explicit `today` override, uses date.today()."""
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(due_date=date.today() - timedelta(days=1))
        assert is_reminder_overdue(reminder, None, None) is True


# ---------------------------------------------------------------------------
# enrich_with_estimate — smart projection (backward-compat + hours)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestEnrichWithEstimateSmartProjection:
    """The single most important suite: proves the redefined 'smart' type
    still projects mileage-based estimates exactly as before, AND that the
    new hours-based projection works via the same formula fed by the
    hours-per-day rate."""

    async def test_backward_compat_smart_mileage_projection_unchanged(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_odometer_records,
        clean_reminders,
    ):
        """CRITICAL: an existing-style smart reminder (due_date +
        due_mileage_km, due_hours null) must still validate and project via
        km/day exactly as before this feature existed."""
        vin = test_vehicle["vin"]

        # Known rate: 1000 km over 20 days = 50 km/day.
        start = date.today() - timedelta(days=20)
        await _add_odometer_record(db_session, vin, start, Decimal("10000"))
        await _add_odometer_record(db_session, vin, date.today(), Decimal("11000"))

        hard_date = date.today() + timedelta(days=365)
        reminder = Reminder(
            vin=vin,
            title="Oil change",
            reminder_type="smart",
            due_date=hard_date,
            due_mileage_km=Decimal("13000"),
            due_hours=None,
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        response = await enrich_with_estimate(reminder, db_session)

        # (13000 - 11000) / 50 km/day = 40 days from today.
        expected = date.today() + timedelta(days=40)
        assert response.estimated_due_date == expected
        assert response.due_mileage_km == Decimal("13000")
        assert response.due_hours is None

    async def test_smart_hours_projection_from_engine_hours_per_day_rate(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_hours_records,
        clean_reminders,
    ):
        """New capability: due_date + due_hours (mileage null) projects a
        due-date from the engine-hours-per-day rate, mirroring the mileage
        case above via the same calculate_smart_estimated_date formula."""
        vin = test_vehicle["vin"]

        # Known rate: 200 hours over 20 days = 10 hr/day.
        start = date.today() - timedelta(days=20)
        await _add_hours_record(db_session, vin, start, Decimal("800.0"))
        await _add_hours_record(db_session, vin, date.today(), Decimal("1000.0"))

        hard_date = date.today() + timedelta(days=365)
        reminder = Reminder(
            vin=vin,
            title="Engine service",
            reminder_type="smart",
            due_date=hard_date,
            due_mileage_km=None,
            due_hours=Decimal("1300.0"),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        response = await enrich_with_estimate(reminder, db_session)

        # (1300 - 1000) / 10 hr/day = 30 days from today.
        expected = date.today() + timedelta(days=30)
        assert response.estimated_due_date == expected
        assert response.due_hours == Decimal("1300.0")
        assert response.due_mileage_km is None

    async def test_smart_hours_projection_never_exceeds_hard_date(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_hours_records,
        clean_reminders,
    ):
        vin = test_vehicle["vin"]
        start = date.today() - timedelta(days=10)
        await _add_hours_record(db_session, vin, start, Decimal("10.0"))
        await _add_hours_record(db_session, vin, date.today(), Decimal("11.0"))  # 0.1 hr/day

        hard_date = date.today() + timedelta(days=5)
        reminder = Reminder(
            vin=vin,
            title="Slow accumulation",
            reminder_type="smart",
            due_date=hard_date,
            due_mileage_km=None,
            due_hours=Decimal("10000.0"),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        response = await enrich_with_estimate(reminder, db_session)

        assert response.estimated_due_date == hard_date


# ---------------------------------------------------------------------------
# create_reminder — persistence, 'hours' type + smart+hours
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCreateReminderHours:
    async def test_creates_and_persists_hours_type(
        self, db_session: AsyncSession, test_vehicle, clean_reminders
    ):
        from app.schemas.reminder import ReminderCreate

        vin = test_vehicle["vin"]
        data = ReminderCreate(
            title="Change hydraulic fluid",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
        )
        reminder = await create_reminder(vin, data, db_session)
        await db_session.commit()
        await db_session.refresh(reminder)

        assert reminder.reminder_type == "hours"
        assert reminder.due_hours == Decimal("500.0")
        assert reminder.due_mileage_km is None

    async def test_creates_smart_with_hours_only(
        self, db_session: AsyncSession, test_vehicle, clean_reminders
    ):
        from app.schemas.reminder import ReminderCreate

        vin = test_vehicle["vin"]
        data = ReminderCreate(
            title="Filter change",
            reminder_type="smart",
            due_date=date.today() + timedelta(days=180),
            due_hours=Decimal("750.0"),
        )
        reminder = await create_reminder(vin, data, db_session)
        await db_session.commit()
        await db_session.refresh(reminder)

        assert reminder.reminder_type == "smart"
        assert reminder.due_hours == Decimal("750.0")
        assert reminder.due_mileage_km is None


# ---------------------------------------------------------------------------
# check_due_reminders — overdue/soon + notification message uses due_hours
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCheckDueRemindersHours:
    async def test_hours_reminder_overdue_when_current_hours_meets_target(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_hours_records,
        clean_reminders,
        monkeypatch,
    ):
        """An 'hours' reminder is overdue when current hours >= due_hours,
        and the dispatched notification message reflects due_hours (not
        mileage)."""
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date.today(), Decimal("600.0"))

        reminder = Reminder(
            vin=vin,
            title="Hydraulic service",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()

        sent_messages: list[str] = []

        class _StubDispatcher:
            def __init__(self, db):
                pass

            async def dispatch(self, event_type, title, message):
                sent_messages.append(message)

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            _StubDispatcher,
        )

        await check_due_reminders(db_session)

        # check_due_reminders is a global scheduler entry point (queries ALL
        # pending reminders, not vin-scoped), so the shared test DB may carry
        # other pending/overdue reminders from other test modules. Filter to
        # the message for THIS reminder rather than asserting a global count.
        own_messages = [
            m for m in sent_messages if m.startswith(f"Service reminder: {reminder.title}")
        ]
        assert len(own_messages) == 1
        assert "Due hours: 500" in own_messages[0]
        assert "Due mileage" not in own_messages[0]

    async def test_hours_reminder_not_yet_due(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_hours_records,
        clean_reminders,
        monkeypatch,
    ):
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date.today(), Decimal("100.0"))

        reminder = Reminder(
            vin=vin,
            title="Hydraulic service",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()

        sent_messages: list[str] = []

        class _StubDispatcher:
            def __init__(self, db):
                pass

            async def dispatch(self, event_type, title, message):
                sent_messages.append(message)

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            _StubDispatcher,
        )

        await check_due_reminders(db_session)

        own_messages = [
            m for m in sent_messages if m.startswith(f"Service reminder: {reminder.title}")
        ]
        assert own_messages == []

    async def test_mileage_reminder_overdue_path_unaffected(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_odometer_records,
        clean_reminders,
        monkeypatch,
    ):
        """A 'mileage' reminder's overdue behavior is unchanged by the hours
        additions.

        The message now renders `due_mileage_km` in the VEHICLE OWNER's
        distance unit, so the owner is pinned to metric here (and restored
        afterwards) rather than inheriting whatever `test_user` happens to
        carry when this file runs. Which context the scheduler resolves is
        `test_reminder_notification_units.py`'s subject, not this test's.
        """
        vin = test_vehicle["vin"]
        await _add_odometer_record(db_session, vin, date.today(), Decimal("60000"))

        owner = await db_session.get(User, test_vehicle["user_id"])
        assert owner is not None
        original_preference = owner.unit_preference
        original_distance = owner.unit_distance
        owner.unit_preference = "metric"
        owner.unit_distance = None
        await db_session.commit()

        reminder = Reminder(
            vin=vin,
            title="Tire rotation",
            reminder_type="mileage",
            due_mileage_km=Decimal("55000"),
            status="pending",
        )
        db_session.add(reminder)
        await db_session.commit()

        sent_messages: list[str] = []

        class _StubDispatcher:
            def __init__(self, db):
                pass

            async def dispatch(self, event_type, title, message):
                sent_messages.append(message)

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            _StubDispatcher,
        )

        try:
            await check_due_reminders(db_session)

            own_messages = [
                m for m in sent_messages if m.startswith(f"Service reminder: {reminder.title}")
            ]
            assert len(own_messages) == 1
            assert "Due mileage: 55,000 km" in own_messages[0]
        finally:
            owner.unit_preference = original_preference
            owner.unit_distance = original_distance
            await db_session.commit()


# ---------------------------------------------------------------------------
# check_due_reminders — naive last_notified_at regression (Phase 5 fix)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestCheckDueRemindersNaiveLastNotifiedAt:
    """Regression test for the naive-vs-aware last_notified_at bug fixed in
    check_due_reminders (~lines 322-325).

    Reminder.last_notified_at is a plain (non-tz-aware) DateTime column.
    SQLite's bind processor drops tzinfo on write, so a value round-tripped
    through the DB comes back naive even though it was written as UTC.
    Comparing that naive value directly against the aware `datetime.now(UTC)`
    raises TypeError on the scheduler's next tick after a reminder has ever
    been notified once. Without the `.replace(tzinfo=UTC)` normalization,
    this test fails with exactly that TypeError.
    """

    async def test_naive_last_notified_at_within_cooldown_is_not_renotified(
        self,
        db_session: AsyncSession,
        test_vehicle,
        clean_hours_records,
        clean_reminders,
        monkeypatch,
    ):
        vin = test_vehicle["vin"]
        # Overdue by hours target, but already notified 1 hour ago — well
        # inside the 24h NOTIFICATION_COOLDOWN.
        await _add_hours_record(db_session, vin, date.today(), Decimal("600.0"))

        reminder = Reminder(
            vin=vin,
            title="Hydraulic service",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
            status="pending",
            last_notified_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        # Confirms the setup actually reproduces the bug's precondition:
        # the value written as UTC-aware round-trips through SQLite naive.
        assert reminder.last_notified_at.tzinfo is None

        sent_messages: list[str] = []

        class _StubDispatcher:
            def __init__(self, db):
                pass

            async def dispatch(self, event_type, title, message):
                sent_messages.append(message)

        monkeypatch.setattr(
            "app.services.notifications.dispatcher.NotificationDispatcher",
            _StubDispatcher,
        )

        # Must not raise: "TypeError: can't subtract offset-naive and
        # offset-aware datetimes."
        await check_due_reminders(db_session)

        own_messages = [
            m for m in sent_messages if m.startswith(f"Service reminder: {reminder.title}")
        ]
        # Within the cooldown window -> skipped, not re-notified. This
        # assertion only passes if the naive last_notified_at was correctly
        # normalized and compared — a broken dedup (e.g. always False on
        # exception, or always True without normalization) would fail here.
        assert own_messages == []


# ---------------------------------------------------------------------------
# _build_reminder_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildReminderMessage:
    def test_includes_due_hours_when_set(self):
        reminder = Reminder(
            vin="1HGBH41JXMN109186",
            title="Oil change",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
        )
        message = _build_reminder_message(reminder, _METRIC_CTX)
        assert "Due hours: 500" in message

    def test_omits_due_hours_when_unset(self):
        reminder = Reminder(
            vin="1HGBH41JXMN109186",
            title="Oil change",
            reminder_type="mileage",
            due_mileage_km=Decimal("50000"),
        )
        message = _build_reminder_message(reminder, _METRIC_CTX)
        assert "Due hours" not in message
        assert "Due mileage: 50,000 km" in message
