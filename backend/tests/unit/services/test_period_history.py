"""`validate_period_history`: the write-side twin of the projection's guards.

The projection suppresses a figure when a tire's periods contradict each
other. Until this validator, the same contradictions could be WRITTEN: a
dismount dated before its own mount, a remount at an odometer below the last
dismount. With dates on every dialog those shapes become reachable from the
UI, so they are refused at write time instead.

Every rule has a fixture that passes without it. Kill check per rule: delete
the rule, the test named for it fails.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.models.tire import TireMountPeriod, TireReading
from app.services.tire_history import (
    CONTRADICTS_READING,
    OVERLAPPING_DATES,
    OVERLAPPING_ODOMETER,
    REVERSED_DATES,
    REVERSED_ODOMETER,
    PeriodFault,
    distance_formatter,
    fault_map,
    format_km,
    new_or_touched_faults,
    validate_period_history,
)
from app.utils.unit_adapters import ADAPTERS

D = dt.date


def _period(
    pid: int,
    *,
    start: D | None,
    end: D | None,
    start_odo: str | None,
    end_odo: str | None,
    position: str = "FL",
) -> TireMountPeriod:
    return TireMountPeriod(
        id=pid,
        position=position,
        mounted_on=start,
        dismounted_on=end,
        mounted_odometer_km=None if start_odo is None else Decimal(start_odo),
        dismounted_odometer_km=None if end_odo is None else Decimal(end_odo),
        is_assumed=False,
        observed_active_on=None,
    )


def _reading(day: D, odo: str) -> TireReading:
    return TireReading(recorded_at=day, odometer_km=Decimal(odo), tread_depth_mm=Decimal("5.0"))


def _codes(faults) -> list[tuple[int, str]]:
    return [(f.period_id, f.code) for f in faults]


class TestSingleRules:
    def test_reversed_dates(self):
        p = _period(1, start=D(2026, 4, 10), end=D(2026, 3, 1), start_odo="1000", end_odo="2000")
        assert _codes(validate_period_history([p], [])) == [(1, REVERSED_DATES)]

    def test_reversed_odometer(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="5000", end_odo="4000")
        assert _codes(validate_period_history([p], [])) == [(1, REVERSED_ODOMETER)]

    def test_a_period_starting_before_the_previous_dismount_date(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="2000")
        q = _period(2, start=D(2026, 2, 15), end=D(2026, 5, 1), start_odo="2000", end_odo="3000")
        faults = validate_period_history([q, p], [])  # order of input must not matter
        assert _codes(faults) == [(2, OVERLAPPING_DATES)]
        # The fault names the intruding period first, by corner and mount date.
        assert faults[0].message.startswith("The FL period mounted 2026-02-15 ")

    def test_a_period_starting_while_an_earlier_one_is_still_open(self):
        p = _period(1, start=D(2026, 1, 1), end=None, start_odo="1000", end_odo=None)
        q = _period(2, start=D(2026, 2, 1), end=D(2026, 3, 1), start_odo="1500", end_odo="1800")
        assert _codes(validate_period_history([p, q], [])) == [(2, OVERLAPPING_DATES)]

    def test_a_mount_odometer_below_an_earlier_dismount(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="2000")
        q = _period(2, start=D(2026, 4, 1), end=None, start_odo="1900", end_odo=None)
        assert _codes(validate_period_history([p, q], [])) == [(2, OVERLAPPING_ODOMETER)]

    def test_a_later_remount_below_an_earlier_dismount_is_caught_in_date_order(self):
        """A sweep sorted by odometer alone puts the 500 first
        and sees nothing; chronology is what makes this a contradiction."""
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 1, 31), start_odo="1000", end_odo="2000")
        q = _period(2, start=D(2026, 3, 1), end=None, start_odo="500", end_odo=None)
        faults = validate_period_history([q, p], [])
        assert _codes(faults) == [(2, OVERLAPPING_ODOMETER)]
        assert faults[0].counterpart_id == 1

    def test_two_undated_spans_that_intersect_are_a_fault_regardless_of_order(self):
        """The order-free form: a tire cannot be in two places at once."""
        p = _period(1, start=None, end=None, start_odo="1000", end_odo="3000")
        q = _period(2, start=None, end=None, start_odo="2000", end_odo="4000")
        faults = validate_period_history([p, q], [])
        assert _codes(faults) == [(2, OVERLAPPING_ODOMETER)]
        assert faults[0].counterpart_id == 1

    def test_a_period_nested_by_odometer_inside_a_non_adjacent_earlier_one(self):
        """Every earlier period, not the neighbour: p3 is inside p1, two places
        back, and below p2's dismount as well."""
        p1 = _period(1, start=D(2025, 1, 1), end=D(2025, 6, 1), start_odo="0", end_odo="30000")
        p2 = _period(2, start=D(2025, 7, 1), end=D(2025, 8, 1), start_odo="30000", end_odo="31000")
        p3 = _period(3, start=D(2025, 9, 1), end=None, start_odo="20000", end_odo=None)
        faults = validate_period_history([p1, p2, p3], [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (3, OVERLAPPING_ODOMETER, 1),
            (3, OVERLAPPING_ODOMETER, 2),
        ]


class TestReadingsContradictPeriods:
    """The four monotonicity implications, one fixture each. Strict dates."""

    P = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="5000")

    def test_after_dismount_below_dismount_odometer(self):
        assert _codes(validate_period_history([self.P], [_reading(D(2026, 4, 1), "4000")])) == [
            (1, CONTRADICTS_READING)
        ]

    def test_before_mount_above_mount_odometer(self):
        assert _codes(validate_period_history([self.P], [_reading(D(2025, 12, 1), "2000")])) == [
            (1, CONTRADICTS_READING)
        ]

    def test_after_mount_below_mount_odometer(self):
        assert _codes(validate_period_history([self.P], [_reading(D(2026, 2, 1), "500")])) == [
            (1, CONTRADICTS_READING)
        ]

    def test_before_dismount_above_dismount_odometer(self):
        assert _codes(validate_period_history([self.P], [_reading(D(2026, 2, 15), "6000")])) == [
            (1, CONTRADICTS_READING)
        ]


#: 89,044 mi, as typed today (the exact mile) and as a service visit saved
#: before v3.4.0 stored it (the old 1.60934 km mile), each rounded to the
#: odometer column's 0.01 km. Worked here from the definitions, not read back
#: from the code under test.
MILES = Decimal("89044")
EXACT = (MILES * Decimal("1.609344")).quantize(Decimal("0.01"))
OLD = (MILES * Decimal("1.60934")).quantize(Decimal("0.01"))


def _band(value: Decimal) -> Decimal:
    """The same-reading band, computed independently: 3 ppm of the figure plus 0.01 km."""
    return abs(value) * Decimal("3e-6") + Decimal("0.01")


BEYOND = EXACT - Decimal("0.45")


class TestTheOldMileAtABoundary:
    """A figure stored before the exact factors is the same reading as itself
    retyped, for every ordering rule, and nothing further off than the band."""

    def test_the_figures(self):
        assert (EXACT, OLD) == (Decimal("143302.43"), Decimal("143302.07"))
        assert EXACT - OLD < _band(EXACT)
        assert EXACT - BEYOND > _band(EXACT)

    @staticmethod
    def _rr(end_odo: Decimal) -> TireMountPeriod:
        return _period(
            1,
            start=D(2025, 11, 1),
            end=D(2026, 6, 21),
            start_odo="130000",
            end_odo=str(end_odo),
            position="RR",
        )

    @staticmethod
    def _fl(start_odo: Decimal, *, closed: bool) -> TireMountPeriod:
        return _period(
            2,
            start=D(2026, 6, 21),
            end=D(2026, 9, 1) if closed else None,
            start_odo=str(start_odo),
            end_odo="150000" if closed else None,
        )

    @pytest.mark.parametrize("closed", [False, True], ids=["open", "closed"])
    def test_a_mount_at_the_old_mile_after_a_dismount_at_the_exact_one(self, closed: bool):
        """The refusal found on real data. Open, rule 4a judges the pair in date
        order; closed, rule 4b also judges the two spans by odometer."""
        assert validate_period_history([self._rr(EXACT), self._fl(OLD, closed=closed)], []) == []

    @pytest.mark.parametrize("closed", [False, True], ids=["open", "closed"])
    def test_a_mount_just_beyond_the_band_is_still_below_the_dismount(self, closed: bool):
        faults = validate_period_history([self._rr(EXACT), self._fl(BEYOND, closed=closed)], [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (2, OVERLAPPING_ODOMETER, 1)
        ]
        assert "is mounted at" in faults[0].message

    def test_a_span_just_beyond_the_band_is_caught_by_odometer_alone(self):
        """Rule 4b on its own: no mount dates, so 4a cannot see the pair."""
        rr = _period(1, start=None, end=D(2026, 6, 21), start_odo="130000", end_odo=str(EXACT))
        within = _period(2, start=None, end=D(2026, 9, 1), start_odo=str(OLD), end_odo="150000")
        beyond = _period(2, start=None, end=D(2026, 9, 1), start_odo=str(BEYOND), end_odo="150000")
        assert validate_period_history([rr, within], []) == []
        faults = validate_period_history([rr, beyond], [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (2, OVERLAPPING_ODOMETER, 1)
        ]
        assert "claims distance" in faults[0].message

    def test_a_reversed_odometer_inside_the_band_is_not_a_fault(self):
        within = _period(
            1, start=D(2026, 6, 21), end=D(2026, 6, 21), start_odo=str(EXACT), end_odo=str(OLD)
        )
        beyond = _period(
            1, start=D(2026, 6, 21), end=D(2026, 6, 21), start_odo=str(EXACT), end_odo=str(BEYOND)
        )
        assert validate_period_history([within], []) == []
        assert _codes(validate_period_history([beyond], [])) == [(1, REVERSED_ODOMETER)]

    @pytest.mark.parametrize(
        ("period_bounds", "day", "within", "beyond"),
        [
            # After the dismount, below the dismount odometer.
            ((None, EXACT), D(2026, 7, 1), OLD, BEYOND),
            # Before the mount, above the mount odometer.
            ((OLD, None), D(2026, 1, 1), EXACT, OLD + Decimal("0.45")),
            # After the mount, below the mount odometer.
            ((EXACT, None), D(2026, 3, 1), OLD, BEYOND),
            # Before the dismount, above the dismount odometer.
            ((None, OLD), D(2026, 5, 1), EXACT, OLD + Decimal("0.45")),
        ],
        ids=["after_dismount", "before_mount", "after_mount", "before_dismount"],
    )
    def test_a_reading_inside_the_band_contradicts_nothing(
        self,
        period_bounds: tuple[Decimal | None, Decimal | None],
        day: D,
        within: Decimal,
        beyond: Decimal,
    ):
        """Each of the four monotonicity implications, with only the bound it
        judges known, so no other rule can fire."""
        start_odo, end_odo = period_bounds
        p = _period(
            1,
            start=D(2026, 2, 1),
            end=D(2026, 6, 21),
            start_odo=None if start_odo is None else str(start_odo),
            end_odo=None if end_odo is None else str(end_odo),
        )
        known = start_odo if start_odo is not None else end_odo
        assert known is not None
        assert abs(within - known) < _band(max(within, known))
        assert abs(beyond - known) > _band(max(beyond, known))
        assert validate_period_history([p], [_reading(day, str(within))]) == []
        assert _codes(validate_period_history([p], [_reading(day, str(beyond))])) == [
            (1, CONTRADICTS_READING)
        ]

    def test_the_covering_maximum_is_the_true_maximum_not_the_banded_one(self):
        """Rule 4b remembers the highest dismount so far with a plain comparison.

        P2 starts and ends within the band of P1's dismount, so it touches P1
        and raises the maximum by less than the band. Q starts within the band
        of P1's dismount too, but 0.70 km below P2's, inside P2's span by more
        than the band: a genuine overlap. A maximum that only moved when a
        dismount cleared the band would still hold P1's and wave Q through.
        No mount dates, so rule 4a stays out of it.
        """
        top = Decimal("143302.00")
        p1 = _period(1, start=None, end=D(2026, 2, 1), start_odo="140000", end_odo=str(top))
        p2 = _period(
            2,
            start=None,
            end=D(2026, 3, 1),
            start_odo=str(top - Decimal("0.40")),
            end_odo=str(top + Decimal("0.40")),
        )
        q = _period(
            3, start=None, end=D(2026, 9, 1), start_odo=str(top - Decimal("0.30")), end_odo="150000"
        )
        assert Decimal("0.40") < _band(top) < Decimal("0.70")
        faults = validate_period_history([p1, p2, q], [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (3, OVERLAPPING_ODOMETER, 2)
        ]


class TestShapesThatMustPass:
    def test_same_day_dismount_and_remount_at_the_same_odometer(self):
        """A rotation: touching endpoints on both axes are not an overlap."""
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="5000")
        q = _period(2, start=D(2026, 3, 1), end=None, start_odo="5000", end_odo=None, position="FR")
        assert validate_period_history([p, q], [_reading(D(2026, 2, 1), "3000")]) == []

    def test_an_assumed_period_with_unknown_start_followed_by_a_bounded_one(self):
        """The migrated shape. Unknown is a gap, never a fault."""
        p = _period(1, start=None, end=D(2026, 1, 15), start_odo=None, end_odo="3000")
        q = _period(2, start=D(2026, 1, 15), end=None, start_odo="3000", end_odo=None)
        assert validate_period_history([q, p], []) == []

    def test_clearing_a_later_open_periods_mount_date_is_not_an_overlap(self):
        """Sorting an unknown date as earliest put the open
        period first and made every closed period "start while it is open"."""
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="2000")
        q = _period(2, start=None, end=None, start_odo="2500", end_odo=None)
        assert validate_period_history([p, q], []) == []

    def test_an_unknown_start_never_constrains_a_dated_period(self):
        p = _period(1, start=None, end=D(2026, 1, 15), start_odo=None, end_odo="3000")
        q = _period(2, start=D(2025, 12, 1), end=D(2026, 1, 10), start_odo="2500", end_odo="2800")
        assert validate_period_history([p, q], []) == []

    def test_a_lone_open_period_and_an_empty_history(self):
        assert (
            validate_period_history(
                [_period(1, start=D(2026, 1, 1), end=None, start_odo=None, end_odo=None)], []
            )
            == []
        )
        assert validate_period_history([], []) == []

    def test_one_fault_per_period_and_code(self):
        """A period that is reversed on both axes reports two faults, not four."""
        p = _period(1, start=D(2026, 4, 1), end=D(2026, 3, 1), start_odo="5000", end_odo="4000")
        assert sorted(_codes(validate_period_history([p], []))) == sorted(
            [(1, REVERSED_DATES), (1, REVERSED_ODOMETER)]
        )


class TestIncrementalPolicy:
    """Absent a strict shrink of the full fault-key
    set, a write refuses what it introduced, and any persisting fault that one
    of its touched periods participates in."""

    OLD = PeriodFault(1, REVERSED_ODOMETER, "old")
    NEW = PeriodFault(2, OVERLAPPING_DATES, "new")
    PAIR = PeriodFault(2, OVERLAPPING_DATES, "pair", counterpart_id=1)

    def test_a_pre_existing_fault_on_an_untouched_period_survives(self):
        before = {self.OLD.key: self.OLD}
        assert new_or_touched_faults(before, dict(before), touched={2}) == []

    def test_a_pre_existing_fault_on_a_touched_period_refuses(self):
        before = {self.OLD.key: self.OLD}
        assert new_or_touched_faults(before, dict(before), touched={1}) == [self.OLD]

    def test_a_new_fault_anywhere_refuses(self):
        before = {self.OLD.key: self.OLD}
        after = {**before, self.NEW.key: self.NEW}
        assert new_or_touched_faults(before, after, touched=set()) == [self.NEW]

    def test_touching_either_participant_of_a_persisting_pair_fault_refuses(self):
        """Touching either participant of a persisting overlap, with
        nothing else changing, still refuses it: the key set is unchanged,
        not a strict subset."""
        before = {self.PAIR.key: self.PAIR}
        assert new_or_touched_faults(before, dict(before), touched={1}) == [self.PAIR]
        assert new_or_touched_faults(before, dict(before), touched={2}) == [self.PAIR]
        assert new_or_touched_faults(before, dict(before), touched={3}) == []

    def test_fault_map_keys_by_period_code_and_counterpart(self):
        p = _period(1, start=D(2026, 4, 1), end=D(2026, 3, 1), start_odo="5000", end_odo="4000")
        assert set(fault_map([p], [])) == {(1, REVERSED_DATES, None), (1, REVERSED_ODOMETER, None)}

    def test_a_write_that_resolves_three_keys_but_adds_one_is_still_refused(self):
        """Kills a length-based stand-in for the strict-subset check
        (`len(after) < len(before)`): C moves from 3,000 to 9,000, resolving
        its contradiction against both A and B and A's own contradiction
        against B (three keys gone), but C's dismount date also moves to
        before its own mount, opening a REVERSED_DATES fault the write must
        still refuse, even though the key COUNT still went down."""

        def history(c_start: str, c_end: D) -> list[TireMountPeriod]:
            return [
                _period(1, start=D(2024, 1, 1), end=D(2024, 3, 1), start_odo="0", end_odo="9000"),
                _period(
                    2, start=D(2024, 3, 1), end=D(2024, 6, 1), start_odo="4000", end_odo="8000"
                ),
                _period(3, start=D(2024, 6, 1), end=c_end, start_odo=c_start, end_odo="12000"),
            ]

        before = fault_map(history("3000", D(2024, 9, 1)), [])
        after = fault_map(history("9000", D(2024, 5, 1)), [])
        assert len(after) < len(before)  # the shape a length-based check sees as safe
        refused = new_or_touched_faults(before, after, touched={3})
        assert [f.key for f in refused] == [(3, REVERSED_DATES, None)]


class TestRepairingAShadowedCounterpart:
    """Counterparts are running maxima, so a repair can re-label an untouched fault.

    A legacy FL history with two odometer typos. Truth: A 0 to 4,000, B 4,000
    to 8,000, C 8,000 to 12,000. Stored: A's dismount typed as 9,000 and C's
    mount typed as 7,000. Both B and C are reported against A, the period
    holding the highest dismount. Fixing A hands that maximum to B, so C's
    untouched fault is now reported against B: keyed by counterpart, that
    read as a NEW fault under the (period, code)-plus-participants check and
    refused the honest repair. Fixing C first instead resolves C's fault
    against B and adds no fault key, so the strict-improvement rule accepts it
    even though C is still contradicted against A afterward; A can then be
    fixed on its own turn.
    """

    @staticmethod
    def _history(a_end: str, c_start: str) -> list[TireMountPeriod]:
        return [
            _period(1, start=D(2024, 1, 1), end=D(2024, 3, 1), start_odo="0", end_odo=a_end),
            _period(2, start=D(2024, 3, 1), end=D(2024, 6, 1), start_odo="4000", end_odo="8000"),
            _period(3, start=D(2024, 6, 1), end=D(2024, 9, 1), start_odo=c_start, end_odo="12000"),
        ]

    def test_the_legacy_history_reports_each_intruder_once(self):
        """Rules 4a and 4b both name (B, A) and (C, A): one fault each. 4a also
        names (C, B), since C mounts below B's dismount too; 4b does not, B
        not holding the maximum, and nothing is reported twice."""
        faults = validate_period_history(self._history("9000", "7000"), [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (2, OVERLAPPING_ODOMETER, 1),
            (3, OVERLAPPING_ODOMETER, 1),
            (3, OVERLAPPING_ODOMETER, 2),
        ]

    def test_fixing_the_period_holding_the_maximum_first_then_the_other(self):
        legacy = fault_map(self._history("9000", "7000"), [])
        a_fixed = fault_map(self._history("4000", "7000"), [])
        # C's fault survives the repair, re-labelled against B.
        assert (3, OVERLAPPING_ODOMETER, 2) in a_fixed
        assert new_or_touched_faults(legacy, a_fixed, touched={1}) == []

        both_fixed = self._history("4000", "8000")
        assert new_or_touched_faults(a_fixed, fault_map(both_fixed, []), touched={3}) == []
        assert validate_period_history(both_fixed, []) == []

    def test_fixing_the_other_period_first_is_accepted_because_it_resolves_one(self):
        """C still sits below A's stored 9,000. But repairing C removes the fault
        C carried against B, (3, overlapping_odometer, 2), and introduces
        nothing: the full fault-key set shrinks, so the write is accepted even
        though C is still contradicted (against A) after the edit."""
        legacy = fault_map(self._history("9000", "7000"), [])
        c_fixed = fault_map(self._history("9000", "8000"), [])
        assert new_or_touched_faults(legacy, c_fixed, touched={3}) == []

    def test_one_intruder_keeps_a_fault_per_counterpart(self):
        """Deduplication is by the full triple, never by (period, code).

        Q is mounted below X's dismount in date order (4a; X has no mount
        odometer, so 4b never sees it) and inside Y's span in odometer order
        (4b; Y has no mount date, so 4a never sees it). Y is a participant of
        that one fault and nothing else. Collapsing Q's two faults into one
        would drop Y, and an edit to Y would no longer be refused.
        """
        x = _period(1, start=D(2024, 1, 1), end=D(2024, 2, 1), start_odo=None, end_odo="5000")
        q = _period(2, start=D(2024, 3, 1), end=D(2024, 4, 1), start_odo="4000", end_odo="7000")
        y = _period(3, start=None, end=None, start_odo="0", end_odo="6000")
        faults = validate_period_history([x, q, y], [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (2, OVERLAPPING_ODOMETER, 1),
            (2, OVERLAPPING_ODOMETER, 3),
        ]
        before = fault_map([x, q, y], [])
        refused = new_or_touched_faults(before, dict(before), touched={3})
        assert [(f.period_id, f.counterpart_id) for f in refused] == [(2, 3)]


class TestRepairingMutuallyContradictingPeriods:
    """Two legacy typos that contradict each other.

    Truth: A 0 to 4,000 km, B 4,000 to 8,000, C 8,000 to 12,000, dated in that
    order at FL. Stored: A's dismount typed 9,000 and C's mount typed 3,000,
    below A's TRUE dismount as well. Either single repair leaves the touched
    period still contradicted, so refusing every write a touched period
    participates in refused both orders. Each repair resolves one contradiction
    and adds no fault key, which the strict-improvement rule accepts.
    """

    @staticmethod
    def _history(a_end: str, c_start: str) -> list[TireMountPeriod]:
        return [
            _period(1, start=D(2024, 1, 1), end=D(2024, 3, 1), start_odo="0", end_odo=a_end),
            _period(2, start=D(2024, 3, 1), end=D(2024, 6, 1), start_odo="4000", end_odo="8000"),
            _period(3, start=D(2024, 6, 1), end=D(2024, 9, 1), start_odo=c_start, end_odo="12000"),
        ]

    def test_fixing_a_first_then_c(self) -> None:
        legacy = fault_map(self._history("9000", "3000"), [])
        a_fixed = fault_map(self._history("4000", "3000"), [])
        assert a_fixed, "C still contradicts A and B after A alone is fixed"
        assert new_or_touched_faults(legacy, a_fixed, touched={1}) == []
        both = fault_map(self._history("4000", "8000"), [])
        assert new_or_touched_faults(a_fixed, both, touched={3}) == []
        assert both == {}

    def test_fixing_c_first_then_a(self) -> None:
        legacy = fault_map(self._history("9000", "3000"), [])
        c_fixed = fault_map(self._history("9000", "8000"), [])
        assert c_fixed, "A still contradicts B and C after C alone is fixed"
        assert new_or_touched_faults(legacy, c_fixed, touched={3}) == []
        both = fault_map(self._history("4000", "8000"), [])
        assert new_or_touched_faults(c_fixed, both, touched={1}) == []

    def test_a_write_that_resolves_nothing_on_a_touched_period_is_still_refused(self) -> None:
        legacy = fault_map(self._history("9000", "3000"), [])
        worse = fault_map(self._history("9500", "3000"), [])
        refused = new_or_touched_faults(legacy, worse, touched={1})
        assert refused
        assert 1 in refused[0].participants


class TestEveryContradictedPredecessorIsNamed:
    """The date-order pair rules name every earlier period a later one contradicts.

    They used to sweep with a running maximum and name only the period holding
    it. A period that also contradicted the later one was then no participant
    of anything, so the incremental policy could not see a write that made it
    contradict: the fault it created was reported against someone else, under
    a (period, code) that was already faulted.
    """

    W = _period(1, start=D(2024, 1, 1), end=D(2024, 2, 1), start_odo=None, end_odo="8000")
    Y = _period(2, start=D(2024, 3, 1), end=D(2024, 4, 1), start_odo="7200", end_odo="8500")
    Z = _period(4, start=D(2024, 7, 1), end=None, start_odo="7000", end_odo=None)

    def test_a_write_hidden_behind_the_running_maximum_is_refused(self):
        """X has a mount date and a dismount odometer but no mount odometer, so
        it can hold a dismount maximum without ever being judged. The edit moves
        it to February, ending at 7,800 km, before Y mounts at 7,200 km: a
        contradiction the write creates. W's 8,000 km is the maximum Y was
        already faulted against, so the running maximum reported Y against W
        alone and the write was accepted."""
        x_before = _period(
            3, start=D(2024, 5, 1), end=D(2024, 6, 1), start_odo=None, end_odo="9000"
        )
        x_after = _period(
            3, start=D(2024, 2, 15), end=D(2024, 2, 20), start_odo=None, end_odo="7800"
        )
        before = fault_map([self.W, self.Y, x_before, self.Z], [])
        after = fault_map([self.W, self.Y, x_after, self.Z], [])
        refused = new_or_touched_faults(before, after, touched={3})
        assert refused, "the write created Y's contradiction with X and must be refused"
        assert (refused[0].period_id, refused[0].code, refused[0].counterpart_id) == (
            2,
            OVERLAPPING_ODOMETER,
            3,
        )

    def test_rule_4a_names_every_earlier_dismount_above_the_mount(self):
        x = _period(3, start=D(2024, 2, 15), end=D(2024, 2, 20), start_odo=None, end_odo="7800")
        faults = validate_period_history([self.W, self.Y, x, self.Z], [])
        assert [(f.period_id, f.code, f.counterpart_id) for f in faults] == [
            (2, OVERLAPPING_ODOMETER, 1),
            (2, OVERLAPPING_ODOMETER, 3),
            (4, OVERLAPPING_ODOMETER, 1),
            (4, OVERLAPPING_ODOMETER, 3),
            (4, OVERLAPPING_ODOMETER, 2),
        ]

    def test_rule_3_names_every_earlier_period_still_open_or_dismounted_later(self):
        """Two open periods before a third: the third starts while BOTH are open.
        And a period nested inside two closed ones overlaps both."""
        a = _period(1, start=D(2026, 1, 1), end=None, start_odo=None, end_odo=None)
        b = _period(2, start=D(2026, 2, 1), end=None, start_odo=None, end_odo=None)
        c = _period(3, start=D(2026, 3, 1), end=D(2026, 3, 5), start_odo=None, end_odo=None)
        assert [
            (f.period_id, f.code, f.counterpart_id) for f in validate_period_history([c, b, a], [])
        ] == [
            (2, OVERLAPPING_DATES, 1),
            (3, OVERLAPPING_DATES, 1),
            (3, OVERLAPPING_DATES, 2),
        ]
        outer = _period(1, start=D(2026, 1, 1), end=D(2026, 6, 1), start_odo=None, end_odo=None)
        inner = _period(2, start=D(2026, 2, 1), end=D(2026, 5, 1), start_odo=None, end_odo=None)
        nested = _period(3, start=D(2026, 3, 1), end=D(2026, 3, 5), start_odo=None, end_odo=None)
        assert [
            (f.period_id, f.counterpart_id)
            for f in validate_period_history([outer, inner, nested], [])
        ] == [(2, 1), (3, 1), (3, 2)]

    def test_a_touched_periods_fault_is_refused_first(self):
        """The 409 carries the first refused fault, so it must be about the write."""
        untouched = PeriodFault(7, OVERLAPPING_DATES, "about periods the write left alone")
        touched = PeriodFault(5, REVERSED_ODOMETER, "about the period the write changed")
        after = {untouched.key: untouched, touched.key: touched}
        assert new_or_touched_faults({}, after, touched={5}) == [touched, untouched]


class TestFaultMessages:
    """A 409 is read by someone looking at the history drawer, which shows
    corners, dates and odometers and never a period id. So every message names
    a period by corner and mount date, and a reading by its date and odometer.
    """

    @staticmethod
    def _message(periods: list[TireMountPeriod], readings: list[TireReading] | None = None) -> str:
        (fault,) = validate_period_history(periods, readings or [])
        return fault.message

    def test_reversed_dates(self):
        p = _period(1, start=D(2026, 4, 10), end=D(2026, 3, 1), start_odo=None, end_odo=None)
        assert self._message([p]) == (
            "The FL period mounted 2026-04-10 is dismounted on 2026-03-01, before it was mounted."
        )

    def test_reversed_odometer_with_thousands_separators(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="5000.00", end_odo="4000")
        assert self._message([p]) == (
            "The FL period mounted 2026-01-01 is dismounted at 4,000 km, below its mount "
            "odometer of 5,000 km."
        )

    def test_starting_while_an_earlier_period_is_open(self):
        p = _period(1, start=D(2026, 1, 1), end=None, start_odo=None, end_odo=None)
        q = _period(
            2, start=D(2026, 2, 1), end=D(2026, 3, 1), start_odo=None, end_odo=None, position="FR"
        )
        assert self._message([p, q]) == (
            "The FR period mounted 2026-02-01 starts while the FL period mounted 2026-01-01 "
            "is still open."
        )

    def test_starting_before_an_earlier_period_was_dismounted(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo=None, end_odo=None)
        q = _period(
            2, start=D(2026, 2, 15), end=D(2026, 5, 1), start_odo=None, end_odo=None, position="FR"
        )
        assert self._message([p, q]) == (
            "The FR period mounted 2026-02-15 starts before the FL period mounted 2026-01-01 "
            "was dismounted on 2026-03-01."
        )

    def test_mounted_below_an_earlier_dismount(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="12000.50")
        q = _period(
            2, start=D(2026, 4, 1), end=None, start_odo="11500", end_odo=None, position="RL"
        )
        assert self._message([p, q]) == (
            "The RL period mounted 2026-04-01 is mounted at 11,500 km, below the 12,000.5 km "
            "at which the FL period mounted 2026-01-01 was dismounted."
        )

    def test_overlapping_spans_with_unknown_mount_dates(self):
        p = _period(1, start=None, end=None, start_odo="1000", end_odo="3000")
        q = _period(2, start=None, end=None, start_odo="2000", end_odo="4000", position="FR")
        assert self._message([p, q]) == (
            "The FR period with an unknown mount date claims distance the FL period with an "
            "unknown mount date already covers: it starts at 2,000 km, before that period ended "
            "at 3,000 km."
        )

    def test_a_period_with_no_corner(self):
        p = TireMountPeriod(
            id=1,
            position=None,
            mounted_on=D(2026, 4, 10),
            dismounted_on=D(2026, 3, 1),
            is_assumed=False,
        )
        assert self._message([p]) == (
            "The period mounted 2026-04-10 is dismounted on 2026-03-01, before it was mounted."
        )

    def test_a_reading_contradiction_names_the_reading_and_the_repair(self):
        """The typo that made every honest write to one tire a 409: the message
        is the only place the user learns which reading to correct or delete."""
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 6, 1), start_odo="10000", end_odo="20000")
        assert self._message([p], [_reading(D(2026, 3, 1), "150000.00")]) == (
            "The FL period mounted 2026-01-01 contradicts the reading dated 2026-03-01 at "
            "150,000 km: the vehicle's odometer would have to run backwards. If that reading "
            "is wrong, correct or delete it in the tire's history."
        )

    def test_the_earliest_contradicting_reading_is_named_whatever_the_input_order(self):
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 6, 1), start_odo="10000", end_odo="20000")
        later = _reading(D(2026, 4, 1), "90000")
        earlier = _reading(D(2026, 2, 1), "150000")
        healthy = _reading(D(2026, 1, 15), "11000")
        message = self._message([p], [later, healthy, earlier])
        assert "the reading dated 2026-02-01 at 150,000 km" in message

    def test_no_message_carries_a_period_id(self):
        """One history that raises every code, with ids that appear nowhere else."""
        reversed_both = _period(
            9101, start=D(2026, 4, 10), end=D(2026, 3, 1), start_odo="5000", end_odo="4000"
        )
        still_open = _period(9102, start=D(2026, 5, 1), end=None, start_odo="6000", end_odo=None)
        intruder = _period(
            9103, start=D(2026, 6, 1), end=D(2026, 7, 1), start_odo="3500", end_odo="7000"
        )
        faults = validate_period_history(
            [reversed_both, still_open, intruder], [_reading(D(2026, 6, 15), "90000")]
        )
        assert {f.code for f in faults} == {
            REVERSED_DATES,
            REVERSED_ODOMETER,
            OVERLAPPING_DATES,
            OVERLAPPING_ODOMETER,
            CONTRADICTS_READING,
        }
        for fault in faults:
            assert "910" not in fault.message, fault.message
            assert "period 9" not in fault.message, fault.message


class TestDistanceFormatter:
    def test_km_prints_whole_and_tenths_values(self) -> None:
        """One decimal, trailing zeros dropped: a whole ten-thousand
        and a value with a genuine tenth both print correctly. Two odometers
        typed to the hundredth that differ by less than 0.05 km read as the
        same number in a message; that is the accepted consequence of one
        decimal, not exercised here."""
        assert format_km(Decimal("150000.00")) == "150,000 km"
        assert format_km(Decimal("12000.50")) == "12,000.5 km"

    def test_miles_convert_and_keep_one_decimal_when_it_matters(self) -> None:
        fmt = distance_formatter(ADAPTERS["mi"])
        assert fmt(Decimal("160934.4")) == "100,000 mi"
        assert fmt(Decimal("16093.44")) == "10,000 mi"
        # 16,094 km is 10,000.348 mi: whole miles would print "10,000" for it and
        # for 16,093.44 km, the same number on both sides of "below".
        assert fmt(Decimal("16094")) == "10,000.3 mi"

    def test_reversed_odometer_message_uses_the_formatter(self) -> None:
        periods = [
            _period(1, start=D(2024, 1, 1), end=D(2024, 2, 1), start_odo="10000", end_odo="9000")
        ]
        km = validate_period_history(periods, [])
        mi = validate_period_history(
            periods, [], format_distance=distance_formatter(ADAPTERS["mi"])
        )
        assert [f.key for f in km] == [f.key for f in mi]
        assert " km" in km[0].message
        assert " mi" in mi[0].message and " km" not in mi[0].message

    def test_mounted_below_message_uses_the_formatter(self) -> None:
        """4a: the "mounted below an earlier dismount" message."""
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 3, 1), start_odo="1000", end_odo="12000.50")
        q = _period(
            2, start=D(2026, 4, 1), end=None, start_odo="11500", end_odo=None, position="RL"
        )
        km = validate_period_history([p, q], [])
        mi = validate_period_history([p, q], [], format_distance=distance_formatter(ADAPTERS["mi"]))
        assert [f.key for f in km] == [f.key for f in mi]
        assert " km" in km[0].message
        assert " mi" in mi[0].message and " km" not in mi[0].message

    def test_covering_span_message_uses_the_formatter(self) -> None:
        """4b: the "claims distance already covered" message."""
        p = _period(1, start=None, end=None, start_odo="1000", end_odo="3000")
        q = _period(2, start=None, end=None, start_odo="2000", end_odo="4000", position="FR")
        km = validate_period_history([p, q], [])
        mi = validate_period_history([p, q], [], format_distance=distance_formatter(ADAPTERS["mi"]))
        assert [f.key for f in km] == [f.key for f in mi]
        assert " km" in km[0].message
        assert " mi" in mi[0].message and " km" not in mi[0].message

    def test_reading_contradiction_message_uses_the_formatter(self) -> None:
        p = _period(1, start=D(2026, 1, 1), end=D(2026, 6, 1), start_odo="10000", end_odo="20000")
        reading = _reading(D(2026, 3, 1), "150000.00")
        km = validate_period_history([p], [reading])
        mi = validate_period_history(
            [p], [reading], format_distance=distance_formatter(ADAPTERS["mi"])
        )
        assert [f.key for f in km] == [f.key for f in mi]
        assert " km" in km[0].message
        assert " mi" in mi[0].message and " km" not in mi[0].message
