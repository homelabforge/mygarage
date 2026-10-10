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

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import METRIC_PRESET
from app.models import HoursRecord, OdometerRecord, Reminder
from app.models.user import User
from app.schemas.reminder import ReminderResponse
from app.services import reminder_service
from app.services.reminder_service import (
    DUE_SOON_PROGRESS,
    DueContext,
    ReminderStart,
    _build_reminder_message,
    calculate_hours_driving_rate,
    check_due_reminders,
    classify_pending_reminders,
    count_pending_reminders,
    create_reminder,
    created_on,
    enrich_reminders,
    enrich_with_estimate,
    expected_due_date,
    get_current_hours,
    leading_progress,
    list_reminders,
    load_reminder_starts,
    order_reminders,
    progress_fractions,
    reminder_due_status,
    tally_due_statuses,
    validate_reminder_state,
)
from app.utils.household_time import household_today, household_zone, household_zone_var
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
# expected_due_date / classify_pending_reminders — the due-soon rule
# ---------------------------------------------------------------------------


def _pending(**kwargs) -> Reminder:
    base = {
        "vin": "1HGBH41JXMN109186",
        "title": "Test reminder",
        "reminder_type": "date",
        "status": "pending",
    }
    base.update(kwargs)
    return Reminder(**base)


TODAY = date(2026, 9, 25)


@pytest.mark.unit
class TestExpectedDueDate:
    """The one expected date the reminders list, the badges and the inbox share:
    the earlier of the calendar date and the usage projection."""

    def test_date_only_is_the_date_whatever_the_rates(self):
        reminder = _pending(due_date=TODAY + timedelta(days=40))
        assert expected_due_date(reminder, Decimal("1"), Decimal("1"), 100.0, 2.0, TODAY) == (
            TODAY + timedelta(days=40)
        )

    def test_mileage_projects_at_the_km_rate(self):
        reminder = _pending(reminder_type="mileage", due_mileage_km=Decimal("57000"))
        assert expected_due_date(reminder, Decimal("56000"), None, 100.0, None, TODAY) == (
            TODAY + timedelta(days=10)
        )

    def test_hours_projects_at_the_hours_rate(self):
        reminder = _pending(reminder_type="hours", due_hours=Decimal("500"))
        assert expected_due_date(reminder, None, Decimal("480"), None, 2.0, TODAY) == (
            TODAY + timedelta(days=10)
        )

    def test_mileage_wins_when_both_targets_are_set(self):
        # 10 days by mileage, 40 by hours: the mileage projection is the one taken.
        reminder = _pending(
            reminder_type="smart",
            due_mileage_km=Decimal("57000"),
            due_hours=Decimal("500"),
            due_date=TODAY + timedelta(days=90),
        )
        assert expected_due_date(reminder, Decimal("56000"), Decimal("420"), 100.0, 2.0, TODAY) == (
            TODAY + timedelta(days=10)
        )

    def test_the_earlier_of_date_and_projection(self):
        reminder = _pending(
            reminder_type="smart",
            due_mileage_km=Decimal("58000"),
            due_date=TODAY + timedelta(days=5),
        )
        # Projection is 20 days; the date comes first.
        assert expected_due_date(reminder, Decimal("56000"), None, 100.0, None, TODAY) == (
            TODAY + timedelta(days=5)
        )
        reminder.due_date = TODAY + timedelta(days=90)
        assert expected_due_date(reminder, Decimal("56000"), None, 100.0, None, TODAY) == (
            TODAY + timedelta(days=20)
        )

    def test_no_rate_or_no_reading_leaves_a_usage_reminder_undated(self):
        reminder = _pending(reminder_type="mileage", due_mileage_km=Decimal("57000"))
        assert expected_due_date(reminder, Decimal("56000"), None, None, None, TODAY) is None
        assert expected_due_date(reminder, None, None, 100.0, None, TODAY) is None

    def test_nothing_to_go_on_is_none(self):
        assert expected_due_date(_pending(), None, None, None, None, TODAY) is None


@pytest.mark.unit
class TestClassifyPendingReminders:
    def test_partition(self):
        pending = [
            _pending(title="today", due_date=TODAY),  # overdue
            _pending(title="30d", due_date=TODAY + timedelta(days=30)),  # due soon (boundary)
            _pending(title="31d", due_date=TODAY + timedelta(days=31)),  # upcoming only
            _pending(
                title="snoozed",
                due_date=TODAY + timedelta(days=5),
                snoozed_until=TODAY + timedelta(days=20),
            ),  # in no count
        ]
        counts = classify_pending_reminders(pending, None, None, None, None, TODAY)
        assert (counts.overdue, counts.upcoming, counts.due_soon) == (1, 2, 1)

    def test_a_projected_mileage_reminder_is_due_soon(self):
        pending = [_pending(reminder_type="mileage", due_mileage_km=Decimal("57000"))]
        counts = classify_pending_reminders(pending, Decimal("56000"), None, 100.0, None, TODAY)
        assert (counts.overdue, counts.upcoming, counts.due_soon) == (0, 1, 1)

    def test_without_rates_or_a_start_a_usage_reminder_is_not_due_soon(self):
        pending = [_pending(reminder_type="mileage", due_mileage_km=Decimal("57000"))]
        counts = classify_pending_reminders(pending, Decimal("56000"), None, None, None, TODAY)
        assert (counts.overdue, counts.upcoming, counts.due_soon) == (0, 1, 0)

    def test_the_counts_tally_the_statuses(self):
        pending = [
            _pending(id=1, due_date=TODAY),
            _pending(id=2, due_date=TODAY + timedelta(days=10)),
            _pending(id=3, due_date=TODAY + timedelta(days=90)),
            _pending(
                id=4,
                due_date=TODAY - timedelta(days=1),
                snoozed_until=TODAY + timedelta(days=5),
            ),
            _anchored(
                id=5,
                reminder_type="mileage",
                anchor_odometer_km=Decimal("50000"),
                due_mileage_km=Decimal("60000"),
            ),
        ]
        ctx = _ctx(km="59500")
        assert [reminder_due_status(r, ctx) for r in pending] == [
            "overdue",
            "due_soon",
            "on_track",
            "snoozed",
            "due_soon",
        ]
        counts = tally_due_statuses(pending, ctx)
        assert (counts.overdue, counts.upcoming, counts.due_soon) == (1, 3, 2)
        assert classify_pending_reminders(pending, Decimal("59500"), None, None, None, TODAY) == (
            counts
        )

    def test_derived_starts_reach_the_fallback(self):
        one_off = _pending(id=9, reminder_type="mileage", due_mileage_km=Decimal("60000"))
        starts = {9: ReminderStart(TODAY - timedelta(days=100), Decimal("50000"), None)}
        without = tally_due_statuses([one_off], _ctx(km="59500"))
        with_start = tally_due_statuses([one_off], _ctx(km="59500", starts=starts))
        assert (without.due_soon, with_start.due_soon) == (0, 1)


# ---------------------------------------------------------------------------
# Due status and progress (#192 D1-D3)
# ---------------------------------------------------------------------------


def _ctx(
    km: str | None = None,
    hours: str | None = None,
    km_rate: float | None = None,
    hours_rate: float | None = None,
    starts: dict[int, ReminderStart] | None = None,
) -> DueContext:
    return DueContext(
        today=TODAY,
        current_km=Decimal(km) if km is not None else None,
        current_hours=Decimal(hours) if hours is not None else None,
        km_per_day=km_rate,
        hours_per_day=hours_rate,
        starts=starts or {},
    )


def _anchored(**kwargs) -> Reminder:
    """A pending reminder anchored on a service 100 days before TODAY."""
    base = {"anchor_kind": "service", "anchor_date": TODAY - timedelta(days=100)}
    base.update(kwargs)
    return _pending(**base)


@pytest.mark.unit
class TestProgressFractions:
    def test_anchored_date(self):
        reminder = _anchored(due_date=TODAY + timedelta(days=100))
        assert progress_fractions(reminder, _ctx()) == pytest.approx({"date": 0.5})

    def test_anchored_distance(self):
        reminder = _anchored(
            reminder_type="mileage",
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )
        assert progress_fractions(reminder, _ctx(km="59000")) == pytest.approx({"distance": 0.9})

    def test_anchored_hours(self):
        reminder = _anchored(
            reminder_type="hours", anchor_hours=Decimal("100.0"), due_hours=Decimal("200.0")
        )
        assert progress_fractions(reminder, _ctx(hours="150.0")) == pytest.approx({"hours": 0.5})

    def test_past_due_is_unclamped(self):
        reminder = _anchored(
            reminder_type="mileage",
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )
        assert progress_fractions(reminder, _ctx(km="62500")) == pytest.approx({"distance": 1.25})

    def test_a_reading_below_the_start_is_negative_not_dropped(self):
        reminder = _anchored(
            reminder_type="mileage",
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )
        assert progress_fractions(reminder, _ctx(km="49000")) == pytest.approx({"distance": -0.1})

    def test_a_span_of_zero_or_less_is_skipped(self):
        same_day = _anchored(due_date=TODAY - timedelta(days=100))
        assert progress_fractions(same_day, _ctx()) == {}
        no_distance = _anchored(
            reminder_type="mileage",
            anchor_odometer_km=Decimal("60000"),
            due_mileage_km=Decimal("60000"),
        )
        assert progress_fractions(no_distance, _ctx(km="61000")) == {}

    def test_a_missing_reading_skips_its_dimension(self):
        reminder = _anchored(
            reminder_type="smart",
            due_date=TODAY + timedelta(days=100),
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )
        assert progress_fractions(reminder, _ctx()) == pytest.approx({"date": 0.5})

    def test_no_start_no_fractions(self):
        # Unanchored, and the context holds no derived start for it.
        reminder = _pending(id=7, due_date=TODAY + timedelta(days=10))
        assert progress_fractions(reminder, _ctx()) == {}

    def test_an_unanchored_reminder_reads_its_derived_start(self):
        reminder = _pending(
            id=7,
            reminder_type="smart",
            due_date=TODAY + timedelta(days=10),
            due_mileage_km=Decimal("50000"),
        )
        ctx = _ctx(
            km="45000",
            starts={7: ReminderStart(TODAY - timedelta(days=10), Decimal("40000"), None)},
        )
        assert progress_fractions(reminder, ctx) == pytest.approx({"date": 0.5, "distance": 0.5})

    def test_a_kind_without_a_date_is_unanchored(self):
        # maintenance_service treats this row as unanchored (no anchor_date), so it
        # counts from its derived start: 0.5, where its anchor reading would give 0.875.
        reminder = _pending(
            id=7,
            reminder_type="mileage",
            anchor_kind="service",
            anchor_date=None,
            anchor_odometer_km=Decimal("10000"),
            due_mileage_km=Decimal("50000"),
        )
        ctx = _ctx(km="45000", starts={7: ReminderStart(TODAY, Decimal("40000"), None)})
        assert progress_fractions(reminder, ctx) == pytest.approx({"distance": 0.5})


@pytest.mark.unit
class TestLeadingProgress:
    def test_the_highest_fraction_leads(self):
        assert leading_progress({"date": 0.4, "distance": 0.8}) == ("distance", 0.8)
        assert leading_progress({"date": 0.9, "hours": 0.3}) == ("date", 0.9)

    def test_ties_go_to_distance_then_hours_then_date(self):
        assert leading_progress({"date": 0.5, "distance": 0.5}) == ("distance", 0.5)
        assert leading_progress({"date": 0.5, "hours": 0.5}) == ("hours", 0.5)

    def test_nothing_measured_is_none(self):
        assert leading_progress({}) is None


@pytest.mark.unit
class TestReminderDueStatus:
    def _belt(self) -> Reminder:
        """Anchored at 50,000 km, due at 60,000 km."""
        return _anchored(
            reminder_type="mileage",
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )

    def test_a_snooze_wins_over_overdue(self):
        reminder = _pending(
            due_date=TODAY - timedelta(days=1), snoozed_until=TODAY + timedelta(days=5)
        )
        assert reminder_due_status(reminder, _ctx()) == "snoozed"

    def test_a_snooze_ends_on_its_date(self):
        reminder = _pending(due_date=TODAY - timedelta(days=1), snoozed_until=TODAY)
        assert reminder_due_status(reminder, _ctx()) == "overdue"

    def test_due_today_is_overdue(self):
        assert reminder_due_status(_pending(due_date=TODAY), _ctx()) == "overdue"

    def test_the_thirty_day_window(self):
        assert reminder_due_status(_pending(due_date=TODAY + timedelta(days=30)), _ctx()) == (
            "due_soon"
        )
        assert reminder_due_status(_pending(due_date=TODAY + timedelta(days=31)), _ctx()) == (
            "on_track"
        )

    def test_a_projection_inside_the_window_is_due_soon(self):
        reminder = _pending(reminder_type="mileage", due_mileage_km=Decimal("57000"))
        assert reminder_due_status(reminder, _ctx(km="56000", km_rate=100.0)) == "due_soon"

    def test_the_fallback_fires_at_ninety_percent_without_a_projection(self):
        assert DUE_SOON_PROGRESS == 0.9
        assert reminder_due_status(self._belt(), _ctx(km="59000")) == "due_soon"

    def test_the_fallback_does_not_fire_at_eighty_nine_percent(self):
        assert reminder_due_status(self._belt(), _ctx(km="58900")) == "on_track"

    def test_the_fallback_never_contradicts_a_projection(self):
        # 95% of the way, but at 1 km/day the last 500 km take 500 days.
        assert reminder_due_status(self._belt(), _ctx(km="59500", km_rate=1.0)) == "on_track"

    def test_a_smart_reminder_with_a_far_date_is_due_soon_on_its_mileage(self):
        reminder = _anchored(
            reminder_type="smart",
            due_date=TODAY + timedelta(days=300),
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )
        assert reminder_due_status(reminder, _ctx(km="59500")) == "due_soon"

    def test_the_fallback_reads_hours_too(self):
        reminder = _anchored(
            reminder_type="hours", anchor_hours=Decimal("100.0"), due_hours=Decimal("200.0")
        )
        assert reminder_due_status(reminder, _ctx(hours="190.0")) == "due_soon"
        assert reminder_due_status(reminder, _ctx(hours="180.0")) == "on_track"

    def test_the_fallback_reads_the_usage_dimension_not_the_leading_one(self):
        # 95% of the way by date, but the date is 40 days out and the mileage is half way.
        reminder = _anchored(
            reminder_type="smart",
            anchor_date=TODAY - timedelta(days=760),
            due_date=TODAY + timedelta(days=40),
            anchor_odometer_km=Decimal("50000"),
            due_mileage_km=Decimal("60000"),
        )
        assert reminder_due_status(reminder, _ctx(km="55000")) == "on_track"

    def test_a_date_reminder_never_takes_the_fallback(self):
        reminder = _anchored(
            anchor_date=TODAY - timedelta(days=760), due_date=TODAY + timedelta(days=40)
        )
        assert reminder_due_status(reminder, _ctx()) == "on_track"

    def test_nothing_to_measure_is_on_track(self):
        assert reminder_due_status(_pending(), _ctx()) == "on_track"


# ---------------------------------------------------------------------------
# Derived starts and count_pending_reminders (#192 D2, D4)
# ---------------------------------------------------------------------------


@contextmanager
def _household_zone(name: str) -> Iterator[None]:
    token = household_zone_var.set(ZoneInfo(name))
    try:
        yield
    finally:
        household_zone_var.reset(token)


def _created_on_day(day: date) -> datetime:
    """A naive-UTC ``created_at`` that falls on ``day`` in the household zone.

    Local noon, so a DST change inside the test's window or a run near local
    midnight can't move it to a neighbouring day.
    """
    return (
        datetime.combine(day, time(12), tzinfo=household_zone())
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


@pytest.mark.unit
class TestCreatedOn:
    def test_naive_and_aware_timestamps_read_alike(self):
        naive = Reminder(created_at=datetime(2026, 9, 1, 20, 0))
        aware = Reminder(created_at=datetime(2026, 9, 1, 20, 0, tzinfo=UTC))
        with _household_zone("Pacific/Auckland"):
            assert created_on(naive) == created_on(aware) == date(2026, 9, 2)

    def test_an_unsaved_reminder_has_no_creation_day(self):
        assert created_on(Reminder()) is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestLoadReminderStarts:
    async def _one_off(self, db_session: AsyncSession, vin: str, **kwargs) -> Reminder:
        base = {
            "vin": vin,
            "title": "One-off",
            "reminder_type": "mileage",
            "status": "pending",
            "due_mileage_km": Decimal("5000"),
            "created_at": datetime(2026, 9, 1, 12, 0),
        }
        base.update(kwargs)
        reminder = Reminder(**base)
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)
        return reminder

    async def test_a_one_off_counts_from_creation_and_the_nearest_reading(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders
    ):
        vin = test_vehicle["vin"]
        await _add_odometer_record(db_session, vin, date(2026, 8, 31), Decimal("1000"))
        await _add_odometer_record(db_session, vin, date(2026, 9, 3), Decimal("1300"))
        reminder = await self._one_off(db_session, vin)
        with _household_zone("UTC"):
            starts = await load_reminder_starts(db_session, vin, [reminder])
        assert starts == {reminder.id: ReminderStart(date(2026, 9, 1), Decimal("1000"), None)}

    async def test_creation_day_is_the_households_not_utcs(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders
    ):
        vin = test_vehicle["vin"]
        await _add_odometer_record(db_session, vin, date(2026, 8, 31), Decimal("1000"))
        await _add_odometer_record(db_session, vin, date(2026, 9, 3), Decimal("1300"))
        reminder = await self._one_off(db_session, vin, created_at=datetime(2026, 9, 1, 20, 0))
        with _household_zone("Pacific/Auckland"):
            starts = await load_reminder_starts(db_session, vin, [reminder])
        # 20:00 UTC on the 1st is 08:00 on the 2nd in Auckland, so the 3rd's reading is nearer.
        assert starts[reminder.id] == ReminderStart(date(2026, 9, 2), Decimal("1300"), None)

    async def test_hours_come_from_the_nearest_hours_reading(
        self, db_session, test_vehicle, clean_hours_records, clean_reminders
    ):
        vin = test_vehicle["vin"]
        await _add_hours_record(db_session, vin, date(2026, 9, 1), Decimal("120.0"))
        reminder = await self._one_off(
            db_session, vin, reminder_type="hours", due_mileage_km=None, due_hours=Decimal("200.0")
        )
        with _household_zone("UTC"):
            starts = await load_reminder_starts(db_session, vin, [reminder])
        assert starts[reminder.id] == ReminderStart(date(2026, 9, 1), None, Decimal("120.0"))

    async def test_a_date_reminder_looks_up_no_reading(
        self, db_session, test_vehicle, clean_reminders, monkeypatch
    ):
        spy = AsyncMock(wraps=reminder_service.nearest_odometer)
        monkeypatch.setattr(reminder_service, "nearest_odometer", spy)
        reminder = await self._one_off(
            db_session,
            test_vehicle["vin"],
            reminder_type="date",
            due_mileage_km=None,
            due_date=date(2026, 12, 1),
        )
        with _household_zone("UTC"):
            starts = await load_reminder_starts(db_session, test_vehicle["vin"], [reminder])
        assert starts[reminder.id] == ReminderStart(date(2026, 9, 1), None, None)
        spy.assert_not_awaited()

    async def test_an_anchored_reminder_gets_no_derived_start(
        self, db_session, test_vehicle, clean_reminders, monkeypatch
    ):
        spy = AsyncMock(wraps=reminder_service.nearest_odometer)
        monkeypatch.setattr(reminder_service, "nearest_odometer", spy)
        reminder = await self._one_off(
            db_session,
            test_vehicle["vin"],
            anchor_kind="service",
            anchor_date=date(2026, 8, 1),
            anchor_odometer_km=Decimal("900"),
        )
        assert await load_reminder_starts(db_session, test_vehicle["vin"], [reminder]) == {}
        spy.assert_not_awaited()

    async def test_one_lookup_per_creation_day(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders, monkeypatch
    ):
        vin = test_vehicle["vin"]
        await _add_odometer_record(db_session, vin, date(2026, 9, 1), Decimal("1000"))
        spy = AsyncMock(wraps=reminder_service.nearest_odometer)
        monkeypatch.setattr(reminder_service, "nearest_odometer", spy)
        first = await self._one_off(db_session, vin, title="First")
        second = await self._one_off(
            db_session, vin, title="Second", created_at=datetime(2026, 9, 1, 18, 0)
        )
        with _household_zone("UTC"):
            starts = await load_reminder_starts(db_session, vin, [first, second])
        assert starts[first.id].km == starts[second.id].km == Decimal("1000")
        assert spy.await_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestCountPendingRemindersFallback:
    async def test_an_unprojectable_one_off_is_due_soon_at_ninety_percent(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders
    ):
        vin = test_vehicle["vin"]
        today = household_today()
        # Only one reading falls inside the 90-day window, so there's no rate and no projection.
        await _add_odometer_record(db_session, vin, today - timedelta(days=100), Decimal("50000"))
        await _add_odometer_record(db_session, vin, today, Decimal("59500"))
        db_session.add(
            Reminder(
                vin=vin,
                title="Timing belt",
                reminder_type="mileage",
                status="pending",
                due_mileage_km=Decimal("60000"),
                created_at=_created_on_day(today - timedelta(days=100)),
            )
        )
        await db_session.commit()
        counts = await count_pending_reminders(db_session, vin, Decimal("59500"), None, today)
        assert (counts.overdue, counts.upcoming, counts.due_soon) == (0, 1, 1)


@pytest.mark.unit
@pytest.mark.asyncio
class TestEnrichDueStatus:
    async def test_a_pending_reminder_says_where_it_stands(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders
    ):
        vin = test_vehicle["vin"]
        today = household_today()
        # One reading: no rate, so the mileage can't project and D2 decides.
        await _add_odometer_record(db_session, vin, today, Decimal("59000"))
        reminder = Reminder(
            vin=vin,
            title="Oil",
            reminder_type="smart",
            status="pending",
            due_date=today + timedelta(days=60),
            due_mileage_km=Decimal("60000"),
            anchor_kind="service",
            anchor_date=today - timedelta(days=120),
            anchor_odometer_km=Decimal("50000"),
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        response = await enrich_with_estimate(reminder, db_session)

        assert response.due_status == "due_soon"
        assert response.progress_basis == "distance"  # 0.9 beats the date's 120/180
        assert response.progress == pytest.approx(0.9)
        assert response.days_until_due == 60
        assert response.km_until_due == Decimal("1000")
        assert response.hours_until_due is None
        assert response.estimated_due_date is None  # no rate, no projection

    async def test_done_and_dismissed_rows_carry_nulls(
        self, db_session, test_vehicle, clean_reminders
    ):
        for status in ("done", "dismissed"):
            reminder = Reminder(
                vin=test_vehicle["vin"],
                title=f"Closed {status}",
                reminder_type="date",
                status=status,
                due_date=household_today() - timedelta(days=5),
            )
            db_session.add(reminder)
            await db_session.commit()
            await db_session.refresh(reminder)
            response = await enrich_with_estimate(reminder, db_session)
            assert (
                response.due_status,
                response.progress,
                response.progress_basis,
                response.days_until_due,
                response.km_until_due,
                response.hours_until_due,
            ) == (None, None, None, None, None, None)

    async def test_a_passed_context_is_used_and_nothing_is_fetched(
        self, db_session, test_vehicle, clean_reminders, monkeypatch
    ):
        reading = AsyncMock(wraps=reminder_service.get_current_mileage)
        rate = AsyncMock(wraps=reminder_service.calculate_driving_rate)
        monkeypatch.setattr(reminder_service, "get_current_mileage", reading)
        monkeypatch.setattr(reminder_service, "calculate_driving_rate", rate)
        reminder = Reminder(
            vin=test_vehicle["vin"],
            title="Oil",
            reminder_type="mileage",
            status="pending",
            due_mileage_km=Decimal("57000"),
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)
        ctx = DueContext(
            today=TODAY,
            current_km=Decimal("56000"),
            current_hours=None,
            km_per_day=100.0,
            hours_per_day=None,
        )

        response = await enrich_with_estimate(reminder, db_session, ctx)

        assert response.estimated_due_date == TODAY + timedelta(days=10)
        assert response.due_status == "due_soon"
        assert response.km_until_due == Decimal("1000")
        reading.assert_not_awaited()
        rate.assert_not_awaited()


# ---------------------------------------------------------------------------
# List order (#192 D5) and one context per list (D6)
# ---------------------------------------------------------------------------

_STAMP = datetime(2026, 9, 1, 12, 0)


def _resp(rid: int, **kwargs) -> ReminderResponse:
    base = {
        "id": rid,
        "vin": "1HGBH41JXMN109186",
        "line_item_id": None,
        "title": f"r{rid}",
        "reminder_type": "date",
        "due_date": None,
        "due_mileage_km": None,
        "due_hours": None,
        "status": "pending",
        "notes": None,
        "last_notified_at": None,
        "created_at": _STAMP,
        "updated_at": _STAMP,
    }
    base.update(kwargs)
    return ReminderResponse(**base)


@pytest.mark.unit
class TestOrderReminders:
    def _ids(self, responses: list[ReminderResponse]) -> list[int]:
        return [r.id for r in order_reminders(responses)]

    def test_status_rank_comes_first(self):
        rows = [
            _resp(1, due_status="on_track"),
            _resp(2, due_status="snoozed"),
            _resp(3, due_status="due_soon"),
            _resp(4, due_status="overdue"),
        ]
        assert self._ids(rows) == [4, 3, 1, 2]

    def test_then_the_expected_date_with_undated_last(self):
        rows = [
            _resp(1, due_status="on_track", due_date=TODAY + timedelta(days=50)),
            _resp(2, due_status="on_track"),
            # The projection (40 days) is what's expected, not the date (90).
            _resp(
                3,
                due_status="on_track",
                due_date=TODAY + timedelta(days=90),
                estimated_due_date=TODAY + timedelta(days=40),
            ),
        ]
        assert self._ids(rows) == [3, 1, 2]

    def test_then_progress_most_first_then_id(self):
        due = TODAY + timedelta(days=50)
        rows = [
            _resp(1, due_status="on_track", due_date=due, progress=0.2),
            _resp(2, due_status="on_track", due_date=due),
            _resp(4, due_status="on_track", due_date=due, progress=0.7),
            _resp(3, due_status="on_track", due_date=due, progress=0.7),
        ]
        assert self._ids(rows) == [3, 4, 1, 2]

    def test_pending_first_then_closed_newest_first(self):
        rows = [
            _resp(1, status="done", completed_date=date(2026, 9, 10)),
            _resp(2, status="done", updated_at=datetime(2026, 9, 20, 9, 0)),
            _resp(3, status="dismissed", updated_at=datetime(2026, 9, 15, 9, 0)),
            _resp(4, due_status="on_track"),
        ]
        assert self._ids(rows) == [4, 2, 3, 1]

    def test_closed_rows_compare_household_days_not_utc_days(self):
        # Chicago is UTC-5 in October. The legacy row's 00:00 UTC update is 19:00 on
        # the 3rd locally, an hour before the completed row: the completed row is newer.
        rows = [
            _resp(1, status="done", updated_at=datetime(2026, 10, 4, 0, 0)),
            _resp(
                2,
                status="done",
                completed_date=date(2026, 10, 3),
                updated_at=datetime(2026, 10, 4, 1, 0),
            ),
        ]
        with _household_zone("America/Chicago"):
            assert self._ids(rows) == [2, 1]


@pytest.mark.unit
@pytest.mark.asyncio
class TestListRemindersFetchesOnce:
    async def test_readings_and_rates_are_fetched_once_for_the_list(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders, monkeypatch
    ):
        vin = test_vehicle["vin"]
        await _add_odometer_record(
            db_session, vin, date.today() - timedelta(days=20), Decimal("10000")
        )
        await _add_odometer_record(db_session, vin, date.today(), Decimal("11000"))
        for km in ("12000", "13000", "14000"):
            db_session.add(
                Reminder(
                    vin=vin,
                    title=f"At {km}",
                    reminder_type="mileage",
                    status="pending",
                    due_mileage_km=Decimal(km),
                )
            )
        await db_session.commit()
        rate = AsyncMock(wraps=reminder_service.calculate_driving_rate)
        reading = AsyncMock(wraps=reminder_service.get_current_mileage)
        monkeypatch.setattr(reminder_service, "calculate_driving_rate", rate)
        monkeypatch.setattr(reminder_service, "get_current_mileage", reading)

        responses = await list_reminders(vin, db_session, "pending")

        assert [r.title for r in responses] == ["At 12000", "At 13000", "At 14000"]
        assert rate.await_count == 1
        assert reading.await_count == 1

    async def test_enrich_reminders_shares_one_context_across_rows(
        self, db_session, test_vehicle, clean_odometer_records, clean_reminders, monkeypatch
    ):
        # Applying a pack and reconciling duplicates return several rows at once.
        vin = test_vehicle["vin"]
        await _add_odometer_record(
            db_session, vin, date.today() - timedelta(days=20), Decimal("10000")
        )
        await _add_odometer_record(db_session, vin, date.today(), Decimal("11000"))
        reminders = [
            Reminder(
                vin=vin,
                title=f"At {km}",
                reminder_type="mileage",
                status="pending",
                due_mileage_km=Decimal(km),
            )
            for km in ("12000", "13000", "14000")
        ]
        db_session.add_all(reminders)
        await db_session.commit()
        for reminder in reminders:
            await db_session.refresh(reminder)
        rate = AsyncMock(wraps=reminder_service.calculate_driving_rate)
        reading = AsyncMock(wraps=reminder_service.get_current_mileage)
        monkeypatch.setattr(reminder_service, "calculate_driving_rate", rate)
        monkeypatch.setattr(reminder_service, "get_current_mileage", reading)

        responses = await enrich_reminders(reminders, db_session)

        assert [r.km_until_due for r in responses] == [
            Decimal("1000"),
            Decimal("2000"),
            Decimal("3000"),
        ]
        assert rate.await_count == 1
        assert reading.await_count == 1


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
            # A title no other module uses: the filter below is by title, and other
            # modules leave pending reminders like "Hydraulic service" behind.
            title="Reminder Service Hours Overdue",
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
            title="Reminder Service Hours Not Due",
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
            title="Reminder Service Mileage Overdue",
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
            title="Reminder Service Naive Cooldown",
            reminder_type="hours",
            due_hours=Decimal("500.0"),
            status="pending",
            # NAIVE, which is what the column actually holds on both dialects.
            #
            # This was seeded AWARE, relying on SQLite's bind processor to drop
            # the tzinfo on write. PostgreSQL does not: asyncpg rejects an aware
            # value for `TIMESTAMP WITHOUT TIME ZONE` outright, and because this
            # suite shares one session the failed flush then poisoned it, taking
            # two unrelated tests in `test_fuel_hours_economy.py` down with a
            # PendingRollbackError. Invisible in CI, which runs only
            # tests/migrations and tests/integration under PostgreSQL.
            #
            # The precondition under test is "the stored value is naive", and
            # seeding it naive establishes that directly rather than by relying
            # on one dialect's silent coercion.
            last_notified_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        # The precondition, asserted rather than assumed: without a naive stored
        # value there is no TypeError for `check_due_reminders` to avoid, and
        # this test would pass against the unfixed code.
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


# ---------------------------------------------------------------------------
# Snooze predicate (plan 2026-09-18, feature A)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReminderSnooze:
    """The snooze predicate and its guard inside `is_reminder_overdue`.

    The guard is what makes any FUTURE caller of `is_reminder_overdue`
    snooze-correct without knowing the feature exists; these tests are what
    keeps that guard killable (delete it and they fail).
    """

    def _reminder(self, **kwargs) -> Reminder:
        base = {
            "vin": "1HGBH41JXMN109186",
            "title": "Snoozed reminder",
            "reminder_type": "date",
            "status": "pending",
        }
        base.update(kwargs)
        return Reminder(**base)

    def test_snoozed_strictly_before_the_until_date(self):
        from app.services.reminder_service import is_reminder_snoozed

        reminder = self._reminder(snoozed_until=date(2026, 9, 20))
        assert is_reminder_snoozed(reminder, today=date(2026, 9, 19)) is True
        # "Until the 20th" means back ON the 20th.
        assert is_reminder_snoozed(reminder, today=date(2026, 9, 20)) is False
        assert is_reminder_snoozed(reminder, today=date(2026, 9, 21)) is False

    def test_no_snooze_means_not_snoozed(self):
        from app.services.reminder_service import is_reminder_snoozed

        assert is_reminder_snoozed(self._reminder(), today=date(2026, 9, 19)) is False

    def test_a_snooze_silences_every_overdue_trigger(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(
            due_date=date(2020, 1, 1),
            due_mileage_km=Decimal("1000"),
            due_hours=Decimal("100"),
            snoozed_until=date(2026, 9, 20),
        )
        overdue = is_reminder_overdue(
            reminder, Decimal("99999"), Decimal("9999"), today=date(2026, 9, 19)
        )
        assert overdue is False

    def test_the_overdue_state_returns_the_day_the_snooze_expires(self):
        from app.services.reminder_service import is_reminder_overdue

        reminder = self._reminder(due_date=date(2020, 1, 1), snoozed_until=date(2026, 9, 20))
        assert is_reminder_overdue(reminder, None, None, today=date(2026, 9, 20)) is True
