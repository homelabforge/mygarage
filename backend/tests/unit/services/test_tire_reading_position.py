"""A reading shows the corner the tire was on that day, worked out from its periods.

The stored `position` is whatever the tire held when the reading was logged, so a
reading backdated to before a rotation used to show today's corner. The rule reads
the mount periods instead, and keeps the stored value where the periods can't say.
"""

from __future__ import annotations

import datetime as dt

from app.models.tire import TireMountPeriod
from app.services.tire_service import reading_position

JAN = dt.date(2026, 1, 1)
MAR = dt.date(2026, 3, 1)
MAY = dt.date(2026, 5, 1)


def _period(
    pid: int | None, position: str, mounted_on: dt.date | None, dismounted_on: dt.date | None = None
) -> TireMountPeriod:
    return TireMountPeriod(
        id=pid,
        tire_id=1,
        position=position,
        mounted_on=mounted_on,
        dismounted_on=dismounted_on,
        is_assumed=mounted_on is None,
    )


# FL from January, rotated to RR on the first of March.
ROTATED = [_period(1, "FL", JAN, MAR), _period(2, "RR", MAR)]


class TestInsideAPeriod:
    def test_a_day_inside_an_open_period_gives_its_corner(self):
        assert reading_position([_period(1, "FL", JAN)], dt.date(2026, 2, 1), None) == "FL"

    def test_a_backdated_reading_gives_the_old_corner_not_todays(self):
        # Logged today, while the tire sits at RR, but dated back in February.
        assert reading_position(ROTATED, dt.date(2026, 2, 1), "RR") == "FL"

    def test_an_unsaved_period_on_the_same_mount_day_wins_without_raising(self):
        # A period not flushed yet has no id. It's the newest, and comparing its
        # None id with a saved one's used to raise.
        unsaved = [_period(1, "FL", JAN), _period(None, "RR", JAN)]
        assert reading_position(unsaved, MAR, None) == "RR"
        assert reading_position(list(reversed(unsaved)), MAR, None) == "RR"

    def test_the_newest_covering_period_wins_an_overlap(self):
        # Legacy rows can overlap; the later mount (then the higher id) is the one shown.
        overlap = [_period(1, "FL", JAN), _period(3, "RR", MAR), _period(2, "FR", MAR)]
        assert reading_position(overlap, MAY, None) == "RR"


class TestRotationDay:
    def test_stored_old_corner_is_kept(self):
        # Measured before the rotation that day.
        assert reading_position(ROTATED, MAR, "FL") == "FL"

    def test_stored_new_corner_is_kept(self):
        assert reading_position(ROTATED, MAR, "RR") == "RR"

    def test_an_unrelated_stored_corner_gives_the_new_corner(self):
        assert reading_position(ROTATED, MAR, "FR") == "RR"

    def test_stored_none_gives_the_new_corner(self):
        # Something opened that day, so "in the garage" isn't one of the answers.
        assert reading_position(ROTATED, MAR, None) == "RR"


class TestMountFromStorageDay:
    # Off FL in February, sat in the garage, fitted to RR on the first of March.
    FITTED = [_period(1, "FL", JAN, dt.date(2026, 2, 1)), _period(2, "RR", MAR)]

    def test_stored_none_is_kept(self):
        # Measured in the garage that morning, before it went on.
        assert reading_position(self.FITTED, MAR, None) is None

    def test_stored_none_is_kept_on_a_first_mount(self):
        assert reading_position([_period(1, "FL", MAR)], MAR, None) is None

    def test_stored_new_corner_is_kept(self):
        assert reading_position(self.FITTED, MAR, "RR") == "RR"

    def test_an_unrelated_stored_corner_gives_the_new_corner(self):
        assert reading_position(self.FITTED, MAR, "FR") == "RR"


class TestDismountDay:
    DISMOUNTED = [_period(1, "FL", JAN, MAR)]

    def test_stored_corner_is_kept(self):
        # The retire day is the last measurement, taken on the car.
        assert reading_position(self.DISMOUNTED, MAR, "FL") == "FL"

    def test_stored_none_is_kept(self):
        assert reading_position(self.DISMOUNTED, MAR, None) is None

    def test_an_unrelated_stored_corner_gives_none(self):
        assert reading_position(self.DISMOUNTED, MAR, "RR") is None

    def test_stored_none_holds_against_an_overlapping_open_period(self):
        # A legacy overlap: RR still covers the day, but the tire came off FL that
        # day and was logged as stored, which is one of the honest answers.
        overlap = [_period(1, "FL", JAN, MAR), _period(2, "RR", dt.date(2026, 2, 1))]
        assert reading_position(overlap, MAR, None) is None


class TestNoCoveringPeriod:
    def test_before_the_first_mount_is_none(self):
        assert reading_position([_period(1, "FL", MAR)], JAN, "FL") is None

    def test_a_gap_between_periods_is_none(self):
        gapped = [_period(1, "FL", JAN, MAR), _period(2, "RR", MAY)]
        assert reading_position(gapped, dt.date(2026, 4, 1), "RR") is None


class TestPeriodsCantSay:
    def test_no_periods_gives_stored(self):
        assert reading_position([], MAR, "FL") == "FL"

    def test_an_undated_period_gives_stored(self):
        assert reading_position([_period(1, "FL", None)], MAR, "RR") == "RR"


class TestMixedHistory:
    """What most tires look like after 097: an assumed period with no start, closed
    by a real dismount, then dated periods after it."""

    D1 = dt.date(2026, 2, 1)
    D2 = dt.date(2026, 4, 1)
    HISTORY = [
        _period(1, "FR", None, D1),
        _period(2, "FL", D1, D2),
        _period(3, "RR", D2),
    ]

    def test_between_d1_and_d2_gives_the_dated_corner(self):
        assert reading_position(self.HISTORY, MAR, "RR") == "FL"

    def test_before_d1_gives_stored(self):
        assert reading_position(self.HISTORY, JAN, "RR") == "RR"

    def test_on_d1_a_stored_closing_corner_is_kept(self):
        assert reading_position(self.HISTORY, self.D1, "FR") == "FR"

    def test_after_d2_gives_the_open_corner(self):
        assert reading_position(self.HISTORY, MAY, "FL") == "RR"

    def test_a_gap_after_the_undated_period_ended_is_none(self):
        # The undated period was over by D1, so it can't say where the tire was
        # in a gap after it: every period that could is dated, and none covers it.
        gapped = [_period(1, "FR", None, self.D1), _period(2, "FL", self.D2)]
        assert reading_position(gapped, MAR, "FR") is None

    def test_before_the_undated_period_ended_still_gives_stored(self):
        gapped = [_period(1, "FR", None, self.D1), _period(2, "FL", self.D2)]
        assert reading_position(gapped, JAN, "RR") == "RR"
