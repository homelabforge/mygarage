"""`distance_on_tire`: what a tire has actually rolled.

The defect this replaces: `_project_wear` computed
`newer.odometer_km - older.odometer_km` and called it distance driven ON THAT
TIRE. For anyone running a second seasonal set that counts the distance driven
on the OTHER set, and the reported remaining life came out at 648,000 km
against a 2.0 mm threshold -- erring high, which for a tire is the dangerous
direction.

Every status has a test, driven from the enum itself rather than a list typed
out here, so adding a member without a test fails.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.models.tire import Tire, TireMountPeriod
from app.services.tire_results import DistanceStatus
from app.services.tire_service import distance_on_tire


def _period(**kw) -> TireMountPeriod:
    defaults = dict(
        position="FL",
        mounted_on=dt.date(2026, 1, 1),
        dismounted_on=None,
        mounted_odometer_km=None,
        dismounted_odometer_km=None,
        is_assumed=False,
        observed_active_on=None,
    )
    defaults.update(kw)
    return TireMountPeriod(**defaults)


def _tire(periods: list[TireMountPeriod]) -> Tire:
    tire = Tire(vin="V" * 17, position="FL")
    tire.mount_periods = periods
    return tire


class TestDistanceOnTire:
    def test_no_periods_is_a_state_not_a_zero(self):
        result = distance_on_tire(_tire([]), current_odometer=Decimal("1000"))
        assert result.status is DistanceStatus.NO_PERIODS
        assert result.all_time_value is None
        assert result.known_value is None

    def test_a_spare_only_tire_has_never_rolled(self):
        """A tire in the trunk does not wear while the vehicle drives.

        An earlier draft returned a confident 0 here: it skipped spares before
        the odometer check and then returned the running total, still zero. So
        the one case the design forbade rendering was the one case that
        produced a number.
        """
        result = distance_on_tire(
            _tire([_period(position="SPARE", mounted_odometer_km=Decimal("100"))]),
            current_odometer=Decimal("5000"),
        )
        assert result.status is DistanceStatus.SPARE_ONLY
        assert result.all_time_value is None
        assert result.known_value is None

    def test_a_closed_bounded_period_is_complete(self):
        result = distance_on_tire(
            _tire(
                [
                    _period(
                        mounted_odometer_km=Decimal("1000"),
                        dismounted_on=dt.date(2026, 6, 1),
                        dismounted_odometer_km=Decimal("9000"),
                    )
                ]
            ),
            current_odometer=Decimal("12000"),
        )
        assert result.status is DistanceStatus.COMPLETE
        assert result.all_time_value == Decimal("8000")
        assert result.known_value == Decimal("8000")
        assert result.known_since == dt.date(2026, 1, 1)

    def test_an_open_period_is_bounded_by_the_current_odometer(self):
        result = distance_on_tire(
            _tire([_period(mounted_odometer_km=Decimal("1000"))]),
            current_odometer=Decimal("4000"),
        )
        assert result.status is DistanceStatus.COMPLETE
        assert result.all_time_value == Decimal("3000")

    def test_an_open_period_with_no_vehicle_odometer_is_incomplete(self):
        """A vehicle with no OdometerRecord makes `current_odometer` null, so
        the open period has no upper bound. Same shape as a missing lower
        bound: supply a number."""
        result = distance_on_tire(
            _tire([_period(mounted_odometer_km=Decimal("1000"))]),
            current_odometer=None,
        )
        assert result.status is DistanceStatus.NOTHING_BOUNDED

    def test_the_migrated_shape_is_nothing_bounded(self):
        """Upgrade day, for essentially every tire on every instance.

        097 gives each existing tire one assumed period with a NULL start
        odometer. Reporting `known_value=0, known_since=None` here would read
        as "we measured zero kilometres since an unknown date", which is worse
        than reporting nothing.
        """
        result = distance_on_tire(
            _tire(
                [_period(mounted_on=None, is_assumed=True, observed_active_on=dt.date(2026, 9, 2))]
            ),
            current_odometer=Decimal("5000"),
        )
        assert result.status is DistanceStatus.NOTHING_BOUNDED
        assert result.all_time_value is None
        assert result.known_value is None
        assert result.known_since is None

    def test_a_partially_known_history_still_reports_what_it_knows(self):
        """The fix for "a migrated tire reports nothing forever".

        Recording a later real mount does not give the earlier assumed period
        a start bound, so the all-time total stays unknown -- but the newer
        period IS measurable and its figure is returned.
        """
        result = distance_on_tire(
            _tire(
                [
                    _period(id=1, mounted_on=None, is_assumed=True),
                    _period(
                        id=2,
                        mounted_on=dt.date(2026, 5, 1),
                        mounted_odometer_km=Decimal("10000"),
                        dismounted_on=dt.date(2026, 8, 1),
                        dismounted_odometer_km=Decimal("14000"),
                    ),
                ]
            ),
            current_odometer=Decimal("15000"),
        )
        assert result.status is DistanceStatus.INCOMPLETE
        assert result.all_time_value is None
        assert result.known_value == Decimal("4000")
        assert result.known_since == dt.date(2026, 5, 1)
        assert result.blocking_period_ids == [1]

    def test_known_since_ignores_a_period_that_contributed_nothing(self):
        """An assumed period's `mounted_on` can be null, and folding it into a
        min() would either raise or poison the date."""
        result = distance_on_tire(
            _tire(
                [
                    _period(id=1, mounted_on=None, is_assumed=True),
                    _period(
                        id=2,
                        mounted_on=dt.date(2026, 5, 1),
                        mounted_odometer_km=Decimal("10000"),
                        dismounted_on=dt.date(2026, 8, 1),
                        dismounted_odometer_km=Decimal("14000"),
                    ),
                ]
            ),
            current_odometer=Decimal("15000"),
        )
        assert result.known_since == dt.date(2026, 5, 1)

    def test_a_backwards_period_is_a_fault_not_a_gap(self):
        result = distance_on_tire(
            _tire(
                [
                    _period(
                        id=7,
                        mounted_odometer_km=Decimal("9000"),
                        dismounted_on=dt.date(2026, 6, 1),
                        dismounted_odometer_km=Decimal("1000"),
                    )
                ]
            ),
            current_odometer=Decimal("12000"),
        )
        assert result.status is DistanceStatus.ODOMETER_ROLLBACK
        assert result.all_time_value is None
        assert result.blocking_period_ids == [7]

    def test_spare_periods_do_not_contribute_to_a_mixed_history(self):
        """The original defect, in miniature: a tire that spent part of its
        life as a spare must not be credited with the distance driven while it
        sat in the trunk."""
        result = distance_on_tire(
            _tire(
                [
                    _period(
                        position="SPARE",
                        mounted_odometer_km=Decimal("0"),
                        dismounted_on=dt.date(2026, 3, 1),
                        dismounted_odometer_km=Decimal("50000"),
                    ),
                    _period(
                        position="FL",
                        mounted_on=dt.date(2026, 3, 1),
                        mounted_odometer_km=Decimal("50000"),
                        dismounted_on=dt.date(2026, 6, 1),
                        dismounted_odometer_km=Decimal("52000"),
                    ),
                ]
            ),
            current_odometer=Decimal("52000"),
        )
        assert result.status is DistanceStatus.COMPLETE
        assert result.all_time_value == Decimal("2000"), (
            "only the FL period counts; the 50,000 km spent as a spare is not "
            "distance driven on this tire"
        )


class TestEveryStatusIsReachable:
    """Guards the guard.

    A status nothing can produce is a status no caller will ever be tested
    against, and the caller's fall-through will be found by a user instead.
    Parametrized over the ENUM, so adding a member without making it reachable
    fails here rather than passing silently.
    """

    PRODUCERS = {
        DistanceStatus.NO_PERIODS: lambda: distance_on_tire(_tire([]), Decimal("1")),
        DistanceStatus.SPARE_ONLY: lambda: distance_on_tire(
            _tire([_period(position="SPARE")]), Decimal("1")
        ),
        DistanceStatus.NOTHING_BOUNDED: lambda: distance_on_tire(
            _tire([_period(mounted_on=None)]), Decimal("1")
        ),
        DistanceStatus.INCOMPLETE: lambda: distance_on_tire(
            _tire(
                [
                    _period(id=1),
                    _period(
                        id=2,
                        mounted_odometer_km=Decimal("1"),
                        dismounted_on=dt.date(2026, 2, 1),
                        dismounted_odometer_km=Decimal("2"),
                    ),
                ]
            ),
            Decimal("3"),
        ),
        DistanceStatus.COMPLETE: lambda: distance_on_tire(
            _tire([_period(mounted_odometer_km=Decimal("1"))]), Decimal("2")
        ),
        DistanceStatus.ODOMETER_ROLLBACK: lambda: distance_on_tire(
            _tire(
                [
                    _period(
                        mounted_odometer_km=Decimal("9"),
                        dismounted_on=dt.date(2026, 2, 1),
                        dismounted_odometer_km=Decimal("1"),
                    )
                ]
            ),
            Decimal("9"),
        ),
    }

    @pytest.mark.parametrize("status", list(DistanceStatus), ids=lambda s: s.value)
    def test_status_has_a_producer(self, status: DistanceStatus):
        assert status in self.PRODUCERS, (
            f"{status} has no producer here, so nothing proves the calculation "
            f"can emit it and no caller test can be written against it"
        )
        assert self.PRODUCERS[status]().status is status
