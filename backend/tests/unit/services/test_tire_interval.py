"""`distance_between`: what a tire rolled BETWEEN two tread readings.

Distinct from `distance_on_tire`, which answers the lifetime question and is
correct. The defect this file exists for: `project_wear` called
`distance_on_tire`, read its STATUS as a gate, discarded its VALUE, and then
used `newer.odometer_km - older.odometer_km`, the vehicle's raw odometer
span. For a two-set owner that counts distance driven on the OTHER set.

Every test here fails against 95b65b7 unless its docstring says otherwise.

Dates matter even in the tests that are about odometers. C5 checks that a
reading's date and odometer agree with the direction a period's own bounds
already moved (a reading after a dismount cannot read below the dismount
odometer, and one before a mount cannot read above the mount odometer), not
whether the reading falls inside a period's odometer range. So the fixtures
below keep the two coordinates coherent: periods run in sequence through
2026 and readings sit inside the period they belong to.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.models.tire import Tire, TireMountPeriod, TireReading
from app.services.tire_results import IntervalStatus
from app.services.tire_service import distance_between


def _period(
    pid: int,
    *,
    start_odo: str | None,
    end_odo: str | None,
    start_day: dt.date | None = dt.date(2026, 1, 1),
    end_day: dt.date | None = dt.date(2026, 3, 31),
    position: str = "FL",
) -> TireMountPeriod:
    """One mount period. `end_odo=None` with `end_day=None` means still on."""
    return TireMountPeriod(
        id=pid,
        position=position,
        mounted_on=start_day,
        dismounted_on=end_day,
        mounted_odometer_km=None if start_odo is None else Decimal(start_odo),
        dismounted_odometer_km=None if end_odo is None else Decimal(end_odo),
        is_assumed=False,
        observed_active_on=None,
    )


def _open_period(
    pid: int, *, start_odo: str | None, start_day: dt.date | None = dt.date(2026, 1, 1)
) -> TireMountPeriod:
    return _period(pid, start_odo=start_odo, end_odo=None, start_day=start_day, end_day=None)


def _reading(day: dt.date, odo: str) -> TireReading:
    return TireReading(recorded_at=day, odometer_km=Decimal(odo), tread_depth_mm=Decimal("5.0"))


def _tire(periods: list[TireMountPeriod]) -> Tire:
    tire = Tire(vin="V" * 17, position="FL")
    tire.mount_periods = periods
    return tire


class TestTheSeasonalDefect:
    def test_distance_excludes_the_storage_gap(self):
        """Case 1. The whole reason this release exists.

        Rolling 0 to 12,000 then 20,000 to 26,000. Readings at 10,000 and
        22,000. Driven on THIS tire between them: (12,000 - 10,000) +
        (22,000 - 20,000) = 4,000. The raw span is 12,000.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="0",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 3, 31),
                ),
                _period(
                    2,
                    start_odo="20000",
                    end_odo="26000",
                    start_day=dt.date(2026, 7, 1),
                    end_day=dt.date(2026, 10, 31),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 3, 1), "10000"),
            _reading(dt.date(2026, 8, 1), "22000"),
            Decimal("26000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("4000")


class TestTheMigratedTireRecovers:
    def test_a_disjoint_unbounded_period_does_not_block(self):
        """Case 2. The assumed period from migration 097 has a null START.

        Once a dismount gives it an END at or below the older reading, it is
        provably outside the interval, so its missing start stops mattering.
        Today this is suppressed because LIFETIME distance is incomplete.
        """
        tire = _tire(
            [
                _period(
                    1, start_odo=None, end_odo="10000", start_day=None, end_day=dt.date(2026, 3, 31)
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="16000",
                    start_day=dt.date(2026, 4, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 4, 2), "10000"),
            _reading(dt.date(2026, 5, 1), "12000"),
            Decimal("16000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")
        assert result.blocking_period_ids == []

    def test_an_open_period_with_a_synthesized_end_does_not_block_via_its_start(self):
        """Case 3. An OPEN period has no dismount, so with no current
        odometer its end SYNTHESIZES to `b_odo` rather than being null: the
        far bound is never actually missing here. The skip is proved by the
        START bound alone. See the next test for a period whose end is
        genuinely null, which this one does not exercise.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="0",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 3, 31),
                ),
                _open_period(2, start_odo="12000", start_day=dt.date(2026, 4, 1)),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 30), "12000"),
            None,
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")

    def test_a_closed_period_with_a_null_end_does_not_block_via_its_start(self):
        """Case 3b, C2 with a genuine null far bound. `dismounted_odometer_km`
        is nullable independently of `dismounted_on`: a period can be CLOSED
        (a real dismount date recorded) with no odometer ever captured for
        that dismount. Its START alone proves disjointness, so the missing
        END is never examined, and the period neither contributes nor
        blocks.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="0",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 3, 31),
                ),
                _period(
                    2,
                    start_odo="12000",
                    end_odo=None,
                    start_day=dt.date(2026, 4, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 30), "12000"),
            None,
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")
        assert result.blocking_period_ids == []

    def test_only_a_period_that_may_overlap_is_reported_as_blocking(self):
        """Case 4, C6. Naming a period whose repair changes nothing is the
        same dead end the typed statuses exist to replace."""
        tire = _tire(
            [
                _period(
                    1, start_odo=None, end_odo="10000", start_day=None, end_day=dt.date(2026, 3, 31)
                ),
                _period(
                    2,
                    start_odo=None,
                    end_odo="16000",
                    start_day=dt.date(2026, 4, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 4, 2), "10000"),
            _reading(dt.date(2026, 5, 1), "12000"),
            Decimal("16000"),
        )
        assert result.status is IntervalStatus.UNVERIFIED
        assert result.blocking_period_ids == [2]

    def test_a_period_with_both_bounds_null_that_may_overlap_blocks(self):
        """`mounted_odometer_km` and `dismounted_odometer_km` are
        independently nullable columns, so a closed period can carry
        neither. With no bound at all to test disjointness from, it cannot
        be proven safe to skip, so it is UNVERIFIED rather than silently
        dropped.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo=None,
                    end_odo=None,
                    start_day=dt.date(2026, 4, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 4, 2), "10000"),
            _reading(dt.date(2026, 5, 1), "12000"),
            Decimal("16000"),
        )
        assert result.status is IntervalStatus.UNVERIFIED
        assert result.blocking_period_ids == [1]


class TestReadingsTakenInStorage:
    """Case 5. A reading's odometer is the VEHICLE's, so it can land in a gap."""

    @pytest.fixture
    def seasonal(self) -> Tire:
        return _tire(
            [
                _period(
                    1,
                    start_odo="0",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 3, 31),
                ),
                _period(
                    2,
                    start_odo="20000",
                    end_odo="26000",
                    start_day=dt.date(2026, 7, 1),
                    end_day=dt.date(2026, 10, 31),
                ),
            ]
        )

    def test_older_reading_in_the_gap(self, seasonal: Tire):
        result = distance_between(
            seasonal,
            _reading(dt.date(2026, 5, 1), "14000"),
            _reading(dt.date(2026, 8, 1), "22000"),
            Decimal("26000"),
        )
        assert result.km == Decimal("2000")

    def test_newer_reading_in_the_gap(self, seasonal: Tire):
        result = distance_between(
            seasonal,
            _reading(dt.date(2026, 3, 1), "10000"),
            _reading(dt.date(2026, 5, 1), "18000"),
            Decimal("26000"),
        )
        assert result.km == Decimal("2000")

    def test_both_readings_in_the_gap_is_no_distance(self, seasonal: Tire):
        result = distance_between(
            seasonal,
            _reading(dt.date(2026, 5, 1), "14000"),
            _reading(dt.date(2026, 5, 20), "18000"),
            Decimal("26000"),
        )
        assert result.status is IntervalStatus.NO_DISTANCE
        assert result.km is None


class TestTheOpenPeriodEnd:
    def test_a_reading_past_the_current_odometer_is_not_clipped(self):
        """Case 8, pinning C4. PASSES against 95b65b7, by coincidence: the
        raw delta and the intersection agree on this shape. It exists to stop
        the obvious `min(b_odo, end)` implementation, which returns 1,000.

        An OPEN period has no recorded dismount, so a reading at 12,000 is
        itself evidence the tire was still mounted at 12,000.
        """
        tire = _tire([_open_period(1, start_odo="9000")])
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 1), "12000"),
            Decimal("11000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")

    def test_an_open_period_with_no_vehicle_odometer_still_resolves(self):
        tire = _tire([_open_period(1, start_odo="9000")])
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 1), "12000"),
            None,
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")


class TestTheDegenerateShapes:
    def test_no_periods(self):
        result = distance_between(
            _tire([]),
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 1), "12000"),
            Decimal("12000"),
        )
        assert result.status is IntervalStatus.NO_PERIODS

    def test_a_spare_only_tire_has_never_rolled(self):
        tire = _tire([_period(1, start_odo="0", end_odo="12000", position="SPARE")])
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 1), "12000"),
            Decimal("12000"),
        )
        assert result.status is IntervalStatus.SPARE_ONLY

    def test_readings_that_do_not_advance(self):
        tire = _tire([_open_period(1, start_odo="9000")])
        result = distance_between(
            tire,
            _reading(dt.date(2026, 3, 1), "12000"),
            _reading(dt.date(2026, 2, 1), "10000"),
            Decimal("12000"),
        )
        assert result.status is IntervalStatus.NO_DISTANCE


class TestFaultsSuppressRatherThanClamp:
    def test_overlapping_periods_are_not_summed(self):
        """Case 6. A tire cannot be in two places, so 7,000 + 5,000 over a
        union of 10,000 is a contradiction, not a total.

        Reachable: nothing validates that a mount's odometer exceeds the
        previous dismount's, so one mistyped backdated mount produces it.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="17000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
                _period(
                    2,
                    start_odo="15000",
                    end_odo="20000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "20000"),
            Decimal("20000"),
        )
        assert result.status is IntervalStatus.OVERLAPPING_HISTORY
        assert result.km is None
        assert result.blocking_period_ids == [1, 2]

    def test_a_period_contained_inside_another_is_caught(self):
        """Simple containment: two periods, one wholly inside the other.

        This alone does not prove the running-maximum behaviour claimed by
        `_overlapping_period_ids`'s docstring: with only two periods,
        "contained" and "adjacent in lo-sorted order" are the same
        relationship, so an implementation that compared each contribution
        only against its immediate predecessor would pass this unchanged.
        See `test_a_period_overlapping_a_non_adjacent_predecessor_is_caught`
        below for the shape that actually distinguishes the two.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="20000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
                _period(
                    2,
                    start_odo="12000",
                    end_odo="14000",
                    start_day=dt.date(2026, 2, 1),
                    end_day=dt.date(2026, 3, 1),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "20000"),
            Decimal("20000"),
        )
        assert result.status is IntervalStatus.OVERLAPPING_HISTORY

    def test_a_period_overlapping_a_non_adjacent_predecessor_is_caught(self):
        """Pins the running-maximum sweep specifically, not just "some
        overlap got detected."

        Three periods, sorted by start: 1 spans 10,000-20,000 for most of
        the year, 2 is a short backdated mount nested early at
        11,000-12,000, and 3 is a second short mount nested later at
        15,000-16,000. Period 3 overlaps period 1 (15,000 < 20,000) but not
        period 2, its immediate predecessor in sorted order
        (15,000 >= 12,000).

        A sweep that compares each period only against its immediate
        predecessor's end (rather than the running maximum end seen so
        far) would clash 1 against 2, then compare 3 against 2's end of
        12,000, see 15,000 >= 12,000, and never flag 3 at all: it would
        report `blocking_period_ids == [1, 2]`. Tracking the running
        maximum (still 20,000 after period 2, since 12,000 does not raise
        it) catches period 3 against period 1's end too, so the correct
        answer includes all three ids.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="20000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
                _period(
                    2,
                    start_odo="11000",
                    end_odo="12000",
                    start_day=dt.date(2026, 2, 1),
                    end_day=dt.date(2026, 3, 1),
                ),
                _period(
                    3,
                    start_odo="15000",
                    end_odo="16000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 6, 1),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "20000"),
            Decimal("20000"),
        )
        assert result.status is IntervalStatus.OVERLAPPING_HISTORY
        assert result.blocking_period_ids == [1, 2, 3]

    def test_touching_endpoints_are_a_continuous_history_not_an_overlap(self):
        """A dismount at 12,000 and a remount at 12,000 is the normal shape
        of a rotation. It must not be read as a contradiction."""
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
                _period(
                    2,
                    start_odo="12000",
                    end_odo="14000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "14000"),
            Decimal("14000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("4000")

    def test_a_reversed_period_is_not_clamped_away(self):
        """Case 7, pinning C3. PASSES against 95b65b7 for an unrelated
        reason: `distance_on_tire` returns ODOMETER_ROLLBACK for ANY reversed
        period anywhere on the tire, so today's gate suppresses without ever
        looking at the interval. This test exists to stop a
        `max(0, hi - lo)` implementation from silently contributing zero
        while a second period supplies a confident subtotal.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="13000",
                    end_odo="11000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "14000"),
            Decimal("14000"),
        )
        assert result.status is IntervalStatus.ODOMETER_ROLLBACK
        assert result.km is None
        assert result.blocking_period_ids == [1]


class TestReversedBoundsAreCaughtBeforeDisjointness:
    """PR #161 review, finding 1. `test_a_reversed_period_is_not_clamped_away`
    above pins C3's clamp-vs-suppress behaviour for a period C2 never skips
    in the first place (its bounds sit inside the interval). It does not pin
    the ORDER of the two checks, because a reversed period whose corrupt
    bound also happens to prove it disjoint was never exercised: C2 ran
    first and swallowed it via `continue` before the fault check ever saw
    it, so a genuinely corrupt period was silently treated as "not here" and
    a second, real contributor published a confident total over it.

    Both cases below fail if the C3 check is moved back below C2 (the
    pre-fix order): the reversed period is skipped as disjoint instead of
    faulted, and the second period's real distance makes it through alone,
    returning COMPLETE where ODOMETER_ROLLBACK is required.
    """

    def test_a_reversed_period_whose_corrupt_end_falls_below_the_interval(self):
        """The near bound (`end`) alone would prove this period disjoint
        from the older side, exactly the shape the finding's own repro used:
        mounted at 20,000, dismounted at 5,000, against an interval starting
        at 10,000. `end <= a_odo` is true, so C2-first skips it and never
        asks whether it is reversed.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="20000",
                    end_odo="5000",
                    start_day=dt.date(2026, 6, 1),
                    end_day=dt.date(2026, 10, 31),
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="15000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 4, 29), "15000"),
            Decimal("15000"),
        )
        assert result.status is IntervalStatus.ODOMETER_ROLLBACK
        assert result.km is None
        assert result.blocking_period_ids == [1]

    def test_a_reversed_period_whose_corrupt_start_falls_above_the_interval(self):
        """Mirror case: the near bound (`start`) alone proves this period
        disjoint from the newer side. Mounted at 25,000, dismounted at
        20,000 (reversed), against an interval ending at 15,000.
        `start >= b_odo` is true, so C2-first skips it via the SECOND
        disjointness rule instead of the first, and never asks whether it is
        reversed either.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="25000",
                    end_odo="20000",
                    start_day=dt.date(2026, 6, 1),
                    end_day=dt.date(2026, 10, 31),
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="15000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 4, 29), "15000"),
            Decimal("15000"),
        )
        assert result.status is IntervalStatus.ODOMETER_ROLLBACK
        assert result.km is None
        assert result.blocking_period_ids == [1]


class TestContradictoryHistory:
    def test_a_single_period_in_a_different_odometer_epoch(self):
        """Case 9. A January period, an odometer reset, then April readings at
        those same two values while the tire sits in storage.

        The April reading is AFTER the dismount and reads BELOW the dismount
        odometer, so the odometer went backwards in time. Without this the
        intersection returns a confident 2,000 km never driven on this tire.
        """
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 1, 31),
                )
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 4, 1), "10000"),
            _reading(dt.date(2026, 4, 15), "12000"),
            Decimal("12000"),
        )
        assert result.status is IntervalStatus.HISTORY_CONTRADICTS
        assert result.km is None
        assert result.blocking_period_ids == [1]

    def test_a_reading_predating_a_period_that_reads_lower(self):
        """Case 9b. A period mounted in May carrying bounds BELOW readings
        taken in February. The February reading predates the mount and reads
        above the mount odometer."""
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="20000",
                    end_odo="26000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "21000"),
            _reading(dt.date(2026, 3, 1), "25000"),
            Decimal("26000"),
        )
        assert result.status is IntervalStatus.HISTORY_CONTRADICTS


class TestTheMonotonicityCheckDoesNotOverFire:
    """The withdrawn range-membership form rejected all of these. They are
    ordinary histories, and a suppression here is a user watching a correct
    wear estimate disappear."""

    def test_a_tire_measured_in_storage_while_the_vehicle_is_parked(self):
        """Case 9c. Dismounted 31 Jan at 12,000, measured 2 Feb at 12,000.
        The vehicle did not move in between, so one odometer value spans both
        dates. That is not a contradiction."""
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 1, 31),
                ),
                _open_period(2, start_odo="12000", start_day=dt.date(2026, 2, 10)),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 1, 20), "11000"),
            _reading(dt.date(2026, 2, 2), "12000"),
            Decimal("12000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("1000")

    def test_two_periods_sharing_an_endpoint_odometer(self):
        """Case 9d. Dismount 31 Jan at 12,000, remount 1 Feb at 12,000, and a
        reading on 1 Feb at 12,000. The reading is inside BOTH periods'
        odometer ranges and outside one period's dates, which the withdrawn
        form read as corrupt."""
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 1, 31),
                ),
                _period(
                    2,
                    start_odo="12000",
                    end_odo="14000",
                    start_day=dt.date(2026, 2, 1),
                    end_day=dt.date(2026, 5, 31),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 1), "12000"),
            _reading(dt.date(2026, 5, 1), "14000"),
            Decimal("14000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")

    def test_a_zero_distance_period_rejects_nothing(self):
        """A mount and dismount at the same odometer contributes no distance
        and must not suppress readings it had no part in."""
        tire = _tire(
            [
                _period(
                    1,
                    start_odo="12000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 1, 1),
                ),
                _period(
                    2,
                    start_odo="12000",
                    end_odo="14000",
                    start_day=dt.date(2026, 2, 1),
                    end_day=dt.date(2026, 5, 31),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 2, 2), "12000"),
            _reading(dt.date(2026, 5, 1), "14000"),
            Decimal("14000"),
        )
        assert result.status is IntervalStatus.COMPLETE
        assert result.km == Decimal("2000")

    def test_an_assumed_period_with_no_dates_is_not_a_contradiction(self):
        """The migrated shape must not be mistaken for a corrupt one: a null
        `mounted_on` means unknown, not wrong."""
        tire = _tire(
            [
                _period(
                    1, start_odo=None, end_odo="10000", start_day=None, end_day=dt.date(2026, 3, 31)
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="16000",
                    start_day=dt.date(2026, 4, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            tire,
            _reading(dt.date(2026, 4, 2), "10000"),
            _reading(dt.date(2026, 5, 1), "12000"),
            Decimal("16000"),
        )
        assert result.status is IntervalStatus.COMPLETE

    def test_the_overlap_diagnosis_wins_over_a_simultaneous_c5_violation(self):
        """Ordering guard, overlap half. Same two periods as
        `test_overlapping_periods_are_not_summed`, but the readings are moved
        past BOTH dismounts: each is after both periods' dismount dates and
        below both dismount odometers, so C5 would name both periods too if it
        ran first. Overlap must still be the diagnosis that wins, because a
        C5-first implementation answers HISTORY_CONTRADICTS here and swallows
        the more specific overlap.
        """
        overlapping = _tire(
            [
                _period(
                    1,
                    start_odo="10000",
                    end_odo="17000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
                _period(
                    2,
                    start_odo="15000",
                    end_odo="20000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
            ]
        )
        result = distance_between(
            overlapping,
            _reading(dt.date(2026, 10, 5), "10000"),
            _reading(dt.date(2026, 10, 10), "20000"),
            Decimal("20000"),
        )
        assert result.status is IntervalStatus.OVERLAPPING_HISTORY
        assert result.blocking_period_ids == [1, 2]

    def test_the_rollback_diagnosis_wins_over_a_simultaneous_c5_violation(self):
        """Ordering guard, rollback half. Same two periods as
        `test_a_reversed_period_is_not_clamped_away`, but the older reading is
        moved past period 2's dismount and below its 12,000, which makes C5
        fire on both periods (period 1 via its own reversed dismount bound,
        period 2 via the same reading). Only period 1 is actually reversed, so
        ODOMETER_ROLLBACK naming just period 1 must still win over a
        C5-first HISTORY_CONTRADICTS naming both.
        """
        reversed_tire = _tire(
            [
                _period(
                    1,
                    start_odo="13000",
                    end_odo="11000",
                    start_day=dt.date(2026, 5, 1),
                    end_day=dt.date(2026, 9, 30),
                ),
                _period(
                    2,
                    start_odo="10000",
                    end_odo="12000",
                    start_day=dt.date(2026, 1, 1),
                    end_day=dt.date(2026, 4, 30),
                ),
            ]
        )
        result = distance_between(
            reversed_tire,
            _reading(dt.date(2026, 10, 5), "10000"),
            _reading(dt.date(2026, 10, 10), "14000"),
            Decimal("14000"),
        )
        assert result.status is IntervalStatus.ODOMETER_ROLLBACK
        assert result.blocking_period_ids == [1]


class TestEveryStatusIsReachable:
    """Guards the guard. A status nothing produces is a status no caller is
    ever tested against, and the fall-through gets found by a user."""

    PRODUCERS = {
        IntervalStatus.NO_PERIODS: lambda: distance_between(
            _tire([]), _reading(dt.date(2026, 2, 1), "1"), _reading(dt.date(2026, 3, 1), "2"), None
        ),
        IntervalStatus.SPARE_ONLY: lambda: distance_between(
            _tire([_period(1, start_odo="0", end_odo="1", position="SPARE")]),
            _reading(dt.date(2026, 2, 1), "1"),
            _reading(dt.date(2026, 3, 1), "2"),
            None,
        ),
        IntervalStatus.NO_DISTANCE: lambda: distance_between(
            _tire([_open_period(1, start_odo="0")]),
            _reading(dt.date(2026, 3, 1), "2"),
            _reading(dt.date(2026, 2, 1), "1"),
            None,
        ),
        IntervalStatus.COMPLETE: lambda: distance_between(
            _tire([_open_period(1, start_odo="9000")]),
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 1), "12000"),
            Decimal("12000"),
        ),
        IntervalStatus.UNVERIFIED: lambda: distance_between(
            _tire([_open_period(1, start_odo=None)]),
            _reading(dt.date(2026, 2, 1), "10000"),
            _reading(dt.date(2026, 3, 1), "12000"),
            Decimal("12000"),
        ),
        IntervalStatus.ODOMETER_ROLLBACK: lambda: distance_between(
            _tire(
                [
                    _period(
                        1,
                        start_odo="13000",
                        end_odo="11000",
                        start_day=dt.date(2026, 5, 1),
                        end_day=dt.date(2026, 9, 30),
                    ),
                    _period(
                        2,
                        start_odo="10000",
                        end_odo="12000",
                        start_day=dt.date(2026, 1, 1),
                        end_day=dt.date(2026, 4, 30),
                    ),
                ]
            ),
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "14000"),
            Decimal("14000"),
        ),
        IntervalStatus.OVERLAPPING_HISTORY: lambda: distance_between(
            _tire(
                [
                    _period(
                        1,
                        start_odo="10000",
                        end_odo="17000",
                        start_day=dt.date(2026, 1, 1),
                        end_day=dt.date(2026, 4, 30),
                    ),
                    _period(
                        2,
                        start_odo="15000",
                        end_odo="20000",
                        start_day=dt.date(2026, 5, 1),
                        end_day=dt.date(2026, 9, 30),
                    ),
                ]
            ),
            _reading(dt.date(2026, 1, 2), "10000"),
            _reading(dt.date(2026, 9, 29), "20000"),
            Decimal("20000"),
        ),
        IntervalStatus.HISTORY_CONTRADICTS: lambda: distance_between(
            _tire(
                [
                    _period(
                        1,
                        start_odo="10000",
                        end_odo="12000",
                        start_day=dt.date(2026, 1, 1),
                        end_day=dt.date(2026, 1, 31),
                    )
                ]
            ),
            _reading(dt.date(2026, 4, 1), "10000"),
            _reading(dt.date(2026, 4, 15), "12000"),
            Decimal("12000"),
        ),
    }

    @pytest.mark.parametrize("status", list(IntervalStatus), ids=lambda s: s.value)
    def test_status_has_a_producer(self, status: IntervalStatus):
        assert status in self.PRODUCERS, (
            f"{status} has no producer here, so nothing proves the calculation "
            f"can emit it and no caller test can be written against it"
        )
        assert self.PRODUCERS[status]().status is status
