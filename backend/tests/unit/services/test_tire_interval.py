"""`distance_between`: what a tire rolled BETWEEN two tread readings.

Distinct from `distance_on_tire`, which answers the lifetime question and is
correct. The defect this file exists for: `project_wear` called
`distance_on_tire`, read its STATUS as a gate, discarded its VALUE, and then
used `newer.odometer_km - older.odometer_km`, the vehicle's raw odometer
span. For a two-set owner that counts distance driven on the OTHER set.

Every test here fails against 95b65b7 unless its docstring says otherwise.

Dates matter even in the tests that are about odometers. C5b compares a
reading's date against the period whose odometer range contains it, so the
fixtures below keep the two coordinates coherent: periods run in sequence
through 2026 and readings sit inside the period they belong to.
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

    def test_a_later_period_starting_at_or_after_the_newer_reading_does_not_block(self):
        """Case 3. Same proof from the other side, with a null END."""
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
