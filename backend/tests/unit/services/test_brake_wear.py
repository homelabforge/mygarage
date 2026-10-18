"""Brake wear (#202): the segment rule, the estimate and the corner's condition."""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement
from app.services.brake_wear import (
    BrakeCondition,
    BrakeWear,
    BrakeWearStatus,
    after_job,
    axle_setup,
    brake_condition,
    pad_thickness,
    project_brake_wear,
    reminder_due,
    surface_reading,
)
from app.services.usage_axis import DISTANCE, HOURS

_VIN = "V" * 17
DISC = axle_setup("front", None)
DRUM = axle_setup(
    "rear",
    BrakeAxle(
        vin=_VIN,
        axle="rear",
        brake_type="drum",
        min_thickness_mm=Decimal("1.50"),
        new_thickness_mm=Decimal("5.00"),
        drum_max_mm=Decimal("230.00"),
    ),
)
_ids = iter(range(1, 10_000))


def m(
    day: str,
    km: str | None = None,
    *,
    inner: str | None = None,
    outer: str | None = None,
    shoe: str | None = None,
    rotor: str | None = None,
    drum: str | None = None,
    hours: str | None = None,
    job: BrakeJob | None = None,
) -> BrakeMeasurement:
    def d(v: str | None) -> Decimal | None:
        return Decimal(v) if v is not None else None

    return BrakeMeasurement(
        id=next(_ids),
        vin=_VIN,
        position="FL",
        recorded_at=dt.date.fromisoformat(day),
        odometer_km=d(km),
        engine_hours=d(hours),
        inner_pad_mm=d(inner),
        outer_pad_mm=d(outer),
        shoe_mm=d(shoe),
        rotor_mm=d(rotor),
        drum_mm=d(drum),
        brake_job_id=job.id if job is not None else None,
    )


def job(day: str, *, friction: bool = True, surface: str | None = None) -> BrakeJob:
    return BrakeJob(
        id=next(_ids),
        vin=_VIN,
        position="FL",
        brake_type="disc",
        performed_on=dt.date.fromisoformat(day),
        friction_replaced=friction,
        surface=surface,
    )


def wear(ms: list[BrakeMeasurement], jobs: list[BrakeJob] | None = None, setup=DISC, axis=DISTANCE):
    return project_brake_wear(ms, jobs or [], setup, axis)


class TestSetup:
    def test_no_row_is_the_disc_defaults(self):
        assert (DISC.brake_type, DISC.min_thickness_mm, DISC.new_thickness_mm) == (
            "disc",
            Decimal("3.00"),
            Decimal("10.00"),
        )
        assert DISC.configured is False

    def test_due_soon_band_is_the_last_quarter_of_usable_pad(self):
        assert DISC.due_soon_mm == Decimal("4.75")
        # Rounded to the hundredth the figures are stored at, so the band shown is the band judged.
        assert DRUM.due_soon_mm == Decimal("2.38")


class TestPadThickness:
    def test_disc_reads_the_thinner_pad(self):
        assert pad_thickness(m("2026-01-01", inner="6.0", outer="7.5"), "disc") == Decimal("6.0")

    def test_disc_reads_one_pad_when_only_one_was_measured(self):
        assert pad_thickness(m("2026-01-01", outer="7.5"), "disc") == Decimal("7.5")

    def test_drum_reads_the_shoe_and_ignores_pads(self):
        reading = m("2026-01-01", inner="6.0", shoe="3.1")
        assert pad_thickness(reading, "drum") == Decimal("3.1")
        assert pad_thickness(m("2026-01-01", shoe="3.1"), "disc") is None


class TestSegment:
    def test_a_measurement_written_by_the_job_counts_after_it(self):
        j = job("2026-03-01")
        assert after_job(m("2026-03-01", inner="10", job=j), j)

    def test_a_same_day_measurement_the_job_did_not_write_is_the_old_pads(self):
        j = job("2026-03-01")
        assert not after_job(m("2026-03-01", inner="2.5"), j)
        assert after_job(m("2026-03-02", inner="9.9"), j)

    def test_a_measurement_written_by_an_older_job_is_before_the_newer_one(self):
        old, new = job("2026-01-01"), job("2026-01-01")
        assert not after_job(m("2026-01-01", inner="10", job=old), new)


class TestProjection:
    def test_nothing_measured(self):
        assert wear([]).status is BrakeWearStatus.NO_MEASUREMENTS

    def test_replaced_and_nothing_measured_since(self):
        old = m("2026-01-01", "10000", inner="2.0", outer="2.2")
        result = wear([old], [job("2026-02-01")])
        assert result.status is BrakeWearStatus.REPLACED_NOT_MEASURED
        # The worn-out pads that came off say nothing about the new ones.
        assert result.thinnest_mm is None

    def test_at_or_below_minimum_needs_no_rate_and_is_dated_by_the_measurement(self):
        result = wear([m("2026-05-01", inner="3.0", outer="4.0")])
        assert result.status is BrakeWearStatus.AT_OR_BELOW_MINIMUM
        assert result.usage_remaining == Decimal("0.00")
        assert result.wear_date == dt.date(2026, 5, 1)

    def test_one_measurement_is_not_enough(self):
        result = wear([m("2026-01-01", "1000", inner="9.0")])
        assert result.status is BrakeWearStatus.INSUFFICIENT_MEASUREMENTS
        assert result.thinnest_mm == Decimal("9.0")

    def test_projects_from_the_oldest_and_newest(self):
        # 10.0 -> 9.0 over 10,000 km and 100 days: 0.1 mm per 1,000 km, 100 km a day.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-02-10", "14000", inner="9.2", outer="9.9"),
            m("2026-04-11", "20000", inner="9.0", outer="9.5"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.PROJECTED
        # (9.0 - 3.0) mm left at 0.1 mm per 1,000 km.
        assert result.usage_remaining == Decimal("60000.0")
        assert result.wear_date == dt.date(2026, 4, 11) + dt.timedelta(days=600)

    def test_the_longest_baseline_beats_a_noisy_last_pair(self):
        # The newest two read the same, which alone would say "not wearing".
        ms = [
            m("2026-01-01", "10000", inner="10.0"),
            m("2026-02-01", "15000", inner="9.0"),
            m("2026-03-01", "20000", inner="9.0"),
        ]
        assert wear(ms).status is BrakeWearStatus.PROJECTED

    def test_only_measurements_after_the_latest_pad_job_count(self):
        ms = [
            m("2026-01-01", "10000", inner="4.0"),
            m("2026-02-01", "12000", inner="3.5"),
            m("2026-03-01", "14000", inner="3.4"),  # the old pads, on the way off
            m("2026-04-01", "18000", inner="9.5"),
            m("2026-05-01", "20000", inner="9.3"),
        ]
        j = job("2026-03-01")
        new_pads = m("2026-03-01", "14000", inner="10.0", outer="10.0", job=j)
        result = wear([*ms, new_pads], [j])
        assert result.status is BrakeWearStatus.PROJECTED
        # 10.0 -> 9.3 over 6,000 km: from the job's own figure, not the old pads.
        assert result.usage_remaining == Decimal("54000.0")

    def test_a_rotor_only_job_does_not_restart_the_pads(self):
        ms = [m("2026-01-01", "10000", inner="8.0"), m("2026-03-01", "20000", inner="7.0")]
        result = wear(ms, [job("2026-02-01", friction=False, surface="replaced")])
        assert result.status is BrakeWearStatus.PROJECTED

    def test_a_one_pad_check_keeps_the_other_pads_last_figure(self):
        # The inner pad was low in April; October's quick look read the outer one only.
        ms = [
            m("2026-04-01", "20000", inner="3.2", outer="6.0"),
            m("2026-10-01", "26000", outer="5.6"),
        ]
        result = wear(ms)
        assert result.thinnest_mm == Decimal("3.2")
        assert (result.inner_pad_mm, result.outer_pad_mm) == (Decimal("3.2"), Decimal("5.6"))
        # Each figure keeps its own date, and the thinnest is April's.
        assert (result.inner_measured_on, result.outer_measured_on) == (
            dt.date(2026, 4, 1),
            dt.date(2026, 10, 1),
        )
        assert result.thinnest_measured_on == dt.date(2026, 4, 1)
        assert cond(result) is BrakeCondition.DUE_SOON
        # The recheck runs from April, when the low pad was seen, not October.
        assert reminder_due(result, BrakeCondition.DUE_SOON, DISC) == dt.date(2026, 6, 30)
        # The inner pad has no rate, and the outer pad's 39,000 km would
        # overstate a corner whose inner pad is at 3.2 mm.
        assert result.status is BrakeWearStatus.NOT_DECREASING
        assert result.usage_remaining is None

    def test_a_carried_pad_at_the_minimum_is_dated_when_it_was_seen(self):
        ms = [
            m("2026-04-01", "20000", inner="2.8", outer="6.0"),
            m("2026-10-01", "26000", outer="5.6"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.AT_OR_BELOW_MINIMUM
        assert result.wear_date == dt.date(2026, 4, 1)
        assert reminder_due(result, BrakeCondition.REPLACE_NOW, DISC) == dt.date(2026, 4, 1)

    def test_the_carried_pad_does_not_outlive_a_pad_job(self):
        j = job("2026-05-01")
        ms = [
            m("2026-04-01", "20000", inner="3.2", outer="6.0"),
            m("2026-10-01", "26000", outer="9.6"),
        ]
        result = wear(ms, [j])
        assert result.thinnest_mm == Decimal("9.6")
        assert result.inner_pad_mm is None

    def test_a_carried_pad_is_projected_from_where_it_was_measured(self):
        # October read the outer pad only. The inner pad's 4.0 mm is April's, at
        # 20,000 km: 6 mm in 10,000 km leaves 1,667 km from there, all of it gone
        # by 40,000 km. Read at October's odometer it said 5,000 km left.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-04-01", "20000", inner="4.0", outer="7.0"),
            m("2026-10-01", "40000", outer="6.0"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.PROJECTED
        assert result.usage_remaining == Decimal("0.0")
        # Gone by October's check: nothing left, so due that day.
        assert result.wear_date == dt.date(2026, 10, 1)

    def test_a_carried_pad_above_the_band_is_not_read_as_healthy(self):
        # 6.0 mm is above the 4.75 band, but at April's rate it reached the
        # minimum before October's check. Read at October's odometer it lasted into 2027: OK.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-04-01", "20000", inner="6.0", outer="8.0"),
            m("2026-10-01", "40000", outer="7.5"),
        ]
        result = wear(ms)
        assert result.usage_remaining == Decimal("0.0")
        assert result.wear_date == dt.date(2026, 10, 1)
        assert brake_condition(result, DISC, dt.date(2026, 10, 2)) is BrakeCondition.DUE_SOON

    def test_use_since_a_carried_pad_was_measured_comes_off_what_is_left(self):
        # 2 mm in 10,000 km: 25,000 km left at April's 20,000, 5,000 of them run since.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-04-01", "20000", inner="8.0", outer="9.0"),
            m("2026-05-01", "25000", outer="8.8"),
        ]
        result = wear(ms)
        assert result.usage_remaining == Decimal("20000.0")
        # Dated from May's check, the use since off too: 20,000 km at 111 km a day.
        assert result.wear_date == dt.date(2026, 10, 28)

    def test_an_odometer_entered_lower_later_never_adds_wear_back(self):
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-04-01", "20000", inner="8.0", outer="9.0"),
            m("2026-05-01", "19000", outer="8.8"),
        ]
        assert wear(ms).usage_remaining == Decimal("25000.0")

    def test_a_pad_measured_once_and_carried_has_no_rate_yet(self):
        # The inner pad was read in January only; April read the outer one.
        ms = [
            m("2026-01-01", "10000", inner="6.0", outer="8.0"),
            m("2026-04-01", "20000", outer="7.0"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.NOT_DECREASING
        assert result.usage_remaining is None
        # The outer pad's own date still bounds the corner: 40,000 km at 111 a day.
        assert result.worn_by == dt.date(2027, 3, 27)

    def test_the_carried_pads_measurement_must_carry_the_odometer(self):
        # Two earlier odometers, so it is the carried pad's own missing one that stops it.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-02-01", "15000", inner="9.0", outer="9.5"),
            m("2026-04-01", None, inner="5.0", outer="7.0"),
            m("2026-10-01", "40000", outer="6.0"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.NO_USAGE_FIGURES
        # April's, not the newest: the card names the one to fix.
        assert result.reading_needed_on == dt.date(2026, 4, 1)

    def test_the_newest_measurement_must_carry_the_odometer(self):
        ms = [
            m("2026-01-01", "10000", inner="10.0"),
            m("2026-02-01", "15000", inner="9.0"),
            m("2026-03-01", None, inner="5.0"),
        ]
        # Counting what is left from 15,000 km would hand back distance the pads
        # already used; the estimate waits for an odometer instead.
        result = wear(ms)
        assert result.status is BrakeWearStatus.NO_USAGE_FIGURES
        assert result.reading_needed_on == dt.date(2026, 3, 1)

    def test_an_older_odometer_never_stands_in_for_the_newest(self):
        # Counted from 30,000 km the 3.5 mm pads would read 15,000 km left;
        # from where they really are it is nearer 2,500.
        ms = [
            m("2026-01-01", "10000", inner="10.0"),
            m("2026-07-01", "30000", inner="6.0"),
            m("2026-10-01", None, inner="3.5"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.NO_USAGE_FIGURES
        assert result.usage_remaining is None
        assert cond(result) is BrakeCondition.DUE_SOON

    def test_two_measurements_but_only_one_odometer(self):
        ms = [m("2026-01-01", None, inner="10.0"), m("2026-02-01", "15000", inner="9.0")]
        result = wear(ms)
        assert result.status is BrakeWearStatus.NO_USAGE_FIGURES
        # The newest has one; it is an earlier one with an odometer that's missing.
        assert result.reading_needed_on is None

    def test_same_odometer(self):
        ms = [m("2026-01-01", "15000", inner="10.0"), m("2026-02-01", "15000", inner="9.0")]
        assert wear(ms).status is BrakeWearStatus.NO_USAGE_BETWEEN

    def test_thicker_than_before(self):
        ms = [m("2026-01-01", "10000", inner="8.0"), m("2026-02-01", "15000", inner="8.5")]
        assert wear(ms).status is BrakeWearStatus.NOT_DECREASING

    def test_same_day_measurements_project_without_a_date(self):
        ms = [m("2026-01-01", "10000", inner="8.0"), m("2026-01-01", "12000", inner="7.0")]
        result = wear(ms)
        assert result.status is BrakeWearStatus.PROJECTED
        assert result.wear_date is None

    def test_a_crawl_of_a_rate_lands_past_the_calendar_without_a_date(self):
        # 0.01 mm over 0.01 km and twenty years: 6 km left, at 2,000 years a mm.
        ms = [
            m("2006-01-01", "10000", inner="9.00"),
            m("2026-01-01", "10000.01", inner="8.99"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.PROJECTED
        assert result.usage_remaining == Decimal("6.0")
        assert result.wear_date is None

    def test_drum_corners_run_on_the_shoe(self):
        # A disc figure left on the row says nothing about the shoe.
        ms = [
            m("2026-01-01", "10000", shoe="5.0", inner="9.0"),
            m("2026-03-01", "20000", shoe="4.0", inner="2.0"),
        ]
        result = wear(ms, setup=DRUM)
        assert result.status is BrakeWearStatus.PROJECTED
        assert result.usage_remaining == Decimal("25000.0")
        assert (result.thinnest_mm, result.inner_pad_mm) == (Decimal("4.0"), None)

    def test_measurements_of_the_other_type_are_ignored(self):
        # The axle was set up as drum after these disc readings.
        ms = [m("2026-01-01", "10000", inner="8.0"), m("2026-03-01", "20000", inner="7.0")]
        assert wear(ms, setup=DRUM).status is BrakeWearStatus.NO_MEASUREMENTS

    def test_a_tie_goes_to_the_older_figure(self):
        # Both pads read 6.0, the inner one in April: it has worn since October's look at the outer.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-04-01", "20000", inner="6.0", outer="8.0"),
            m("2026-10-01", "40000", outer="6.0"),
        ]
        result = wear(ms)
        assert result.thinnest_measured_on == dt.date(2026, 4, 1)
        assert (result.usage_remaining, result.wear_date) == (Decimal("0.0"), dt.date(2026, 10, 1))

    def test_the_thicker_pad_runs_out_first_when_it_wears_faster(self):
        # Inner 8.0 -> 7.8, outer 10.0 -> 8.0 over 10,000 km. The thinner pad
        # lasts 240,000 km; the outer one 25,000.
        ms = [
            m("2026-01-01", "10000", inner="8.0", outer="10.0"),
            m("2026-07-01", "20000", inner="7.8", outer="8.0"),
        ]
        result = wear(ms)
        assert result.thinnest_mm == Decimal("7.8")
        assert result.usage_remaining == Decimal("25000.0")
        assert result.wear_date == dt.date(2027, 9, 26)

    def test_a_season_parked_does_not_bring_the_date_forward(self):
        # 2 mm in 5,000 km over the summer, then parked: April's outer-only
        # check is 200 km on. The date runs from April, not from September.
        ms = [
            m("2026-06-01", "10000", inner="10.0", outer="10.0"),
            m("2026-09-01", "15000", inner="8.0", outer="9.0"),
            m("2027-04-15", "15200", outer="8.9"),
        ]
        result = wear(ms)
        assert result.usage_remaining == Decimal("12300.0")
        assert result.wear_date == dt.date(2027, 11, 27)
        assert brake_condition(result, DISC, dt.date(2027, 4, 16)) is BrakeCondition.OK

    def test_a_newest_check_without_an_odometer_still_dates_a_carried_pad(self):
        # October's outer-only look has no odometer. The inner pad's own
        # checks still date it, June at April's pace; the distance is unknown.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-04-01", "20000", inner="6.0", outer="8.0"),
            m("2026-10-01", None, outer="7.5"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.PROJECTED
        assert result.usage_remaining is None
        assert result.wear_date == dt.date(2026, 6, 7)
        assert brake_condition(result, DISC, dt.date(2026, 10, 2)) is BrakeCondition.DUE_SOON

    def test_the_other_pads_date_counts_when_the_thinnest_has_no_rate(self):
        # The inner pad, above the band, was read once. The outer one is going
        # fast, gone by late April: the corner can't outlast it.
        ms = [
            m("2026-01-01", "10000", inner="5.0", outer="9.0"),
            m("2026-03-01", "16000", outer="6.0"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.NOT_DECREASING
        assert result.usage_remaining is None
        assert result.worn_by == dt.date(2026, 4, 29)
        assert cond(result) is BrakeCondition.DUE_SOON

    def test_a_same_day_baseline_on_one_pad_leaves_the_date_to_the_other(self):
        # Two inner checks on New Year's Day, 1,000 km apart, then an outer-only
        # look. The inner pad has a distance and no pace: 2,000 km or the
        # outer pad's date, whichever comes first.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-01-01", "11000", inner="9.0", outer="10.0"),
            m("2026-03-01", "15000", outer="9.8"),
        ]
        result = wear(ms)
        assert result.usage_remaining == Decimal("2000.0")
        assert result.wear_date == dt.date(2031, 8, 28)

    def test_a_pad_worn_down_with_no_pace_is_dated_at_the_anchor(self):
        # As above, but 9,000 km on by March: the inner pad's 6,000 km ran out
        # by then, and the outer pad's far date must not read OK beside it.
        ms = [
            m("2026-01-01", "10000", inner="10.0", outer="10.0"),
            m("2026-01-01", "11000", inner="9.0", outer="10.0"),
            m("2026-03-01", "20000", outer="9.8"),
        ]
        result = wear(ms)
        assert result.usage_remaining == Decimal("0.0")
        assert result.wear_date == result.worn_by == dt.date(2026, 3, 1)
        condition = brake_condition(result, DISC, dt.date(2026, 3, 1))
        assert condition is BrakeCondition.DUE_SOON
        assert reminder_due(result, condition, DISC) == dt.date(2026, 3, 1)

    def test_whichever_comes_first_distance_and_date_from_different_pads(self):
        # Parked Jan to Apr, then 1,000 km in ten days. The inner pad's pace
        # runs over all of it, the outer's over the ten days alone: the inner
        # has the least distance left, the outer the earliest date.
        ms = [
            m("2026-01-01", "10000", inner="10"),
            m("2026-04-01", "10000", outer="10"),
            m("2026-04-11", "11000", inner="7", outer="8"),
        ]
        result = wear(ms)
        assert (result.usage_remaining, result.wear_date) == (
            Decimal("1333.3"),
            dt.date(2026, 5, 6),
        )
        assert result.worn_by == dt.date(2026, 5, 6)
        assert brake_condition(result, DISC, dt.date(2026, 4, 11)) is BrakeCondition.DUE_SOON

    def test_the_thinnest_pad_can_have_the_later_date(self):
        # Inner 30,000 km left at its Jan-Oct pace (Jul 1); the outer, read
        # from April on, runs faster and is gone by Jun 2.
        ms = [
            m("2026-01-01", "10000", inner="10.0"),
            m("2026-04-01", "10500", inner="9.5", outer="10.0"),
            m("2026-10-01", "40000", inner="6.5", outer="7.0"),
        ]
        result = wear(ms)
        assert (result.usage_remaining, result.wear_date) == (
            Decimal("30000.0"),
            dt.date(2027, 6, 2),
        )
        assert brake_condition(result, DISC, dt.date(2027, 3, 10)) is BrakeCondition.DUE_SOON

    def test_the_use_since_comes_from_the_newest_check_with_a_reading(self):
        # The inner pad had 25,000 km left in April. August's outer look at
        # 45,000 says that's gone; October's has no odometer, so a date alone.
        ms = [
            m("2026-01-01", "10000", inner="10", outer="10"),
            m("2026-04-01", "20000", inner="8.0", outer="9.0"),
            m("2026-08-01", "45000", outer="8.5"),
            m("2026-10-01", None, outer="8.4"),
        ]
        result = wear(ms)
        assert result.status is BrakeWearStatus.PROJECTED
        assert (result.usage_remaining, result.wear_date) == (None, dt.date(2026, 8, 1))

    def test_a_carried_pad_on_the_hours_axis(self):
        ms = [
            m("2026-01-01", None, inner="10.0", outer="10.0", hours="100.0"),
            m("2026-04-01", None, inner="8.0", outer="9.0", hours="200.0"),
            m("2026-05-01", None, outer="8.8", hours="250.0"),
        ]
        # 250 hours left at April's 200, 50 of them run since.
        assert wear(ms, axis=HOURS).usage_remaining == Decimal("200.0")

    def test_hours_axis_reads_the_hour_meter(self):
        ms = [
            m("2026-01-01", None, inner="10.0", hours="100.0"),
            m("2026-03-01", None, inner="9.0", hours="200.0"),
        ]
        result = wear(ms, axis=HOURS)
        assert result.status is BrakeWearStatus.PROJECTED
        assert result.usage_remaining == Decimal("600.0")
        # The same rows on the distance axis have no odometer to run on.
        assert wear(ms).status is BrakeWearStatus.NO_USAGE_FIGURES


TODAY = dt.date(2026, 6, 1)


def cond(result: BrakeWear, setup=DISC) -> BrakeCondition:
    return brake_condition(result, setup, TODAY)


class TestCondition:
    def test_replace_now(self):
        assert cond(BrakeWear(BrakeWearStatus.AT_OR_BELOW_MINIMUM)) is BrakeCondition.REPLACE_NOW

    def test_unknown_only_when_nothing_was_measured(self):
        assert cond(BrakeWear(BrakeWearStatus.NO_MEASUREMENTS)) is BrakeCondition.UNKNOWN

    def test_a_pad_job_with_nothing_measured_since_is_ok(self):
        assert cond(BrakeWear(BrakeWearStatus.REPLACED_NOT_MEASURED)) is BrakeCondition.OK

    @pytest.mark.parametrize(
        "status",
        [
            BrakeWearStatus.INSUFFICIENT_MEASUREMENTS,
            BrakeWearStatus.NO_USAGE_FIGURES,
            BrakeWearStatus.NO_USAGE_BETWEEN,
            BrakeWearStatus.NOT_DECREASING,
            BrakeWearStatus.PROJECTED,
        ],
    )
    def test_in_the_band_is_due_soon_whatever_the_estimate_says(self, status):
        assert cond(BrakeWear(status, thinnest_mm=Decimal("4.75"))) is BrakeCondition.DUE_SOON
        assert cond(BrakeWear(status, thinnest_mm=Decimal("4.76"))) is BrakeCondition.OK

    def test_a_wear_date_within_ninety_days_is_due_soon(self):
        soon = BrakeWear(
            BrakeWearStatus.PROJECTED,
            thinnest_mm=Decimal("8.0"),
            worn_by=TODAY + dt.timedelta(days=90),
        )
        later = BrakeWear(
            BrakeWearStatus.PROJECTED,
            thinnest_mm=Decimal("8.0"),
            worn_by=TODAY + dt.timedelta(days=91),
        )
        assert cond(soon) is BrakeCondition.DUE_SOON
        assert cond(later) is BrakeCondition.OK

    def test_a_wear_date_already_past_is_due_soon(self):
        past = BrakeWear(
            BrakeWearStatus.PROJECTED, thinnest_mm=Decimal("8.0"), worn_by=dt.date(2026, 1, 1)
        )
        assert cond(past) is BrakeCondition.DUE_SOON


class TestSurface:
    def test_rotor_since_the_last_rotor_job(self):
        ms = [m("2026-01-01", rotor="20.0"), m("2026-03-01", rotor="27.9")]
        reading = surface_reading(ms, [job("2026-02-01", friction=False, surface="replaced")], DISC)
        assert reading is not None and reading.value_mm == Decimal("27.9")

    def test_rotor_at_its_minimum_is_past_the_limit(self):
        setup = axle_setup(
            "front",
            BrakeAxle(
                vin=_VIN,
                axle="front",
                brake_type="disc",
                min_thickness_mm=Decimal("3.00"),
                new_thickness_mm=Decimal("10.00"),
                rotor_min_mm=Decimal("26.00"),
            ),
        )
        reading = surface_reading([m("2026-01-01", rotor="26.0")], [], setup)
        assert reading is not None and reading.past_limit

    def test_drum_past_its_maximum(self):
        reading = surface_reading([m("2026-01-01", drum="230.1")], [], DRUM)
        assert reading is not None and reading.past_limit
        reading = surface_reading([m("2026-01-01", drum="229.9")], [], DRUM)
        assert reading is not None and not reading.past_limit

    def test_nothing_measured_since_the_rotor_changed(self):
        ms = [m("2026-01-01", rotor="20.0")]
        assert (
            surface_reading(ms, [job("2026-02-01", friction=False, surface="resurfaced")], DISC)
            is None
        )


class TestReminderDue:
    def test_replace_now_is_due_the_day_it_was_measured(self):
        result = wear([m("2026-05-01", inner="2.5")])
        assert reminder_due(result, cond(result), DISC) == dt.date(2026, 5, 1)

    def test_due_soon_without_a_projection_is_due_ninety_days_after_the_measurement(self):
        result = wear([m("2026-05-01", inner="4.0")])
        assert reminder_due(result, cond(result), DISC) == dt.date(2026, 7, 30)

    def test_due_soon_takes_the_projection_when_it_is_sooner(self):
        result = BrakeWear(
            BrakeWearStatus.PROJECTED,
            latest=m("2026-05-01", inner="4.0"),
            thinnest_mm=Decimal("4.0"),
            thinnest_measured_on=dt.date(2026, 5, 1),
            worn_by=dt.date(2026, 6, 1),
        )
        assert reminder_due(result, BrakeCondition.DUE_SOON, DISC) == dt.date(2026, 6, 1)

    def test_a_slow_projection_is_capped_at_the_recheck(self):
        result = BrakeWear(
            BrakeWearStatus.PROJECTED,
            latest=m("2026-05-01", inner="4.0"),
            thinnest_mm=Decimal("4.0"),
            thinnest_measured_on=dt.date(2026, 5, 1),
            worn_by=dt.date(2029, 5, 1),
        )
        assert reminder_due(result, BrakeCondition.DUE_SOON, DISC) == dt.date(2026, 7, 30)

    def test_due_soon_by_the_date_alone_is_due_that_day(self):
        # Above the band, due soon only because of the date. The 90-day recheck
        # from May would date it before the day time alone raised it.
        result = BrakeWear(
            BrakeWearStatus.PROJECTED,
            latest=m("2026-05-01", inner="8.0"),
            thinnest_mm=Decimal("8.0"),
            thinnest_measured_on=dt.date(2026, 5, 1),
            worn_by=dt.date(2026, 10, 1),
        )
        assert reminder_due(result, BrakeCondition.DUE_SOON, DISC) == dt.date(2026, 10, 1)

    def test_ok_and_unknown_corners_have_no_due_date(self):
        result = wear([m("2026-05-01", inner="8.0")])
        assert reminder_due(result, cond(result), DISC) is None
        assert reminder_due(wear([]), BrakeCondition.UNKNOWN, DISC) is None
