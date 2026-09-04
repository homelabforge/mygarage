"""Readiness: how many tires can answer each question, and what is missing.

Spec B leads with this block because of a measurement rather than a taste. On
the instance that asked for tire analytics there were two tires, two readings
and zero readings carrying an odometer, so every analytical block would have
rendered empty. The counts here are what turns that page from an apology into
an instruction.

**The three requirements are independent, and the point of this file is that
they are counted independently.** `project_wear` short-circuits in a fixed
order, so a tire missing both a minimum tread and its reading odometers reports
only `no_minimum_set`. A readiness block built from that status alone would
name one problem and hide the other.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.schemas.analytics import TireReadiness
from app.schemas.tire import TireReadingResponse, TireResponse
from app.services.analytics_service.tires import tire_readiness

CREATED = dt.datetime(2026, 1, 1, 12, 0, 0)


def reading(
    day: int,
    *,
    tread: str | None = "8.0",
    odometer: str | None = "10000",
) -> TireReadingResponse:
    return TireReadingResponse(
        id=day,
        tire_id=1,
        vin="1HGCM82633A004352",
        position="FL",
        recorded_at=dt.date(2026, 1, day),
        odometer_km=None if odometer is None else Decimal(odometer),
        tread_depth_mm=None if tread is None else Decimal(tread),
        pressure_kpa=None,
        notes=None,
        created_at=CREATED,
    )


def tire(
    tire_id: int = 1,
    *,
    readings: list[TireReadingResponse] | None = None,
    wear_status: str = "insufficient_readings",
    distance_status: str = "no_periods",
    min_tread_mm: str | None = "2.0",
    below_threshold: bool = False,
    retired_on: dt.date | None = None,
) -> TireResponse:
    return TireResponse(
        id=tire_id,
        vin="1HGCM82633A004352",
        position="FL",
        min_tread_mm=None if min_tread_mm is None else Decimal(min_tread_mm),
        below_threshold=below_threshold,
        retired_on=retired_on,
        wear_status=wear_status,
        distance_status=distance_status,
        created_at=CREATED,
        readings=readings or [],
    )


class TestTheCapabilityCounts:
    def test_an_empty_vehicle_counts_nothing(self):
        assert tire_readiness([]) == TireReadiness()

    def test_two_tread_readings_make_a_trend(self):
        result = tire_readiness([tire(readings=[reading(1), reading(2)])])
        assert result.total == 1
        assert result.can_trend == 1
        assert result.needs_second_reading == 0

    def test_one_reading_is_a_point(self):
        """Distinct from "no distance data", and must not share its wording."""
        result = tire_readiness([tire(readings=[reading(1)])])
        assert result.can_trend == 0
        assert result.needs_second_reading == 1

    def test_a_pressure_only_reading_does_not_count_toward_a_trend(self):
        """Since #152 a reading can carry a pressure and no tread.

        Two of those are two points on a chart that has no y value.
        """
        result = tire_readiness([tire(readings=[reading(1, tread=None), reading(2, tread=None)])])
        assert result.can_trend == 0
        assert result.needs_second_reading == 1

    def test_only_a_real_figure_counts_as_projected(self):
        """`at_or_below_minimum` is the safety case and carries a number.

        The other six statuses are prompts. Counting any of them as an answer
        is how a readiness block tells someone they are done when they are not.
        """
        tires = [
            tire(1, wear_status="projected"),
            tire(2, wear_status="at_or_below_minimum"),
            tire(3, wear_status="unverified_mount_history"),
            tire(4, wear_status="no_distance_on_tire"),
        ]
        assert tire_readiness(tires).can_project == 2

    def test_a_partial_distance_is_a_prompt_not_an_answer(self):
        """`incomplete` DOES report its measurable part, and still counts as
        unfinished: there is a period the user can go and complete."""
        tires = [
            tire(1, distance_status="complete"),
            tire(2, distance_status="incomplete"),
        ]
        result = tire_readiness(tires)
        assert result.can_report_distance == 1
        assert result.needs_mount_odometer == 1


class TestThePromptsAreIndependent:
    """The failure spec B calls out by name."""

    def test_a_tire_missing_a_minimum_and_odometers_reports_both(self):
        """`project_wear` answers `no_minimum_set` and stops.

        Reading the prompts off that status would hide the odometers entirely,
        and the user would fix the minimum, come back, and find the block still
        empty with no new advice.
        """
        result = tire_readiness(
            [
                tire(
                    readings=[reading(1, odometer=None), reading(2, odometer=None)],
                    min_tread_mm=None,
                    wear_status="no_minimum_set",
                )
            ]
        )
        assert result.needs_minimum_tread == 1
        assert result.needs_reading_odometer == 1

    def test_distance_does_not_ask_for_reading_odometers(self):
        """Distance reads period bounds and the vehicle odometer, never a
        reading's odometer. Telling this owner to add odometers to their tread
        readings would be advice about the wrong data."""
        result = tire_readiness(
            [
                tire(
                    readings=[reading(1), reading(2)],
                    wear_status="projected",
                    distance_status="nothing_bounded",
                )
            ]
        )
        assert result.needs_reading_odometer == 0
        assert result.needs_mount_odometer == 1

    def test_only_the_newest_pair_of_odometers_matters(self):
        """`project_wear` differences the newest two tread-bearing readings.

        A third, older reading without an odometer costs nothing, and counting
        it would prompt for a number that changes no figure.
        """
        result = tire_readiness(
            [tire(readings=[reading(3), reading(2), reading(1, odometer=None)])]
        )
        assert result.can_trend == 1
        assert result.needs_reading_odometer == 0

    def test_a_missing_odometer_on_the_newest_pair_does_count(self):
        result = tire_readiness(
            [tire(readings=[reading(3, odometer=None), reading(2), reading(1)])]
        )
        assert result.needs_reading_odometer == 1

    def test_the_older_of_the_pair_counts_too(self):
        """Both sides, because the figure is a DIFFERENCE.

        Its pair above has the NEWEST reading missing its odometer; this one
        has the older. A check that looked at only one of the two would pass
        one of these and fail the other, which is the whole reason both exist.
        """
        result = tire_readiness(
            [tire(readings=[reading(3), reading(2, odometer=None), reading(1)])]
        )
        assert result.needs_reading_odometer == 1


class TestWhatAMountOdometerCannotFix:
    """Two distance statuses are not gaps, and must not be prompted for."""

    def test_a_spare_that_has_never_rolled_is_a_state(self):
        result = tire_readiness([tire(distance_status="spare_only")])
        assert result.needs_mount_odometer == 0

    def test_reversed_data_needs_a_correction_not_a_number(self):
        result = tire_readiness([tire(distance_status="odometer_rollback")])
        assert result.needs_mount_odometer == 0


class TestRetiredTires:
    """B10: they belong in the history blocks and in none of these counts."""

    def test_a_retired_tire_counts_toward_nothing(self):
        retired = tire(
            1,
            readings=[reading(1), reading(2)],
            wear_status="projected",
            distance_status="complete",
            below_threshold=True,
            retired_on=dt.date(2026, 2, 1),
        )
        assert tire_readiness([retired]) == TireReadiness()

    def test_a_retired_tire_does_not_dilute_the_live_ones(self):
        """The count that matters is "how many of the tires I can still act on".

        A vehicle that has replaced three sets would otherwise read as mostly
        unready forever, and the advice would never go away.
        """
        live = tire(1, readings=[reading(1), reading(2)], wear_status="projected")
        retired = tire(2, retired_on=dt.date(2026, 2, 1))
        result = tire_readiness([live, retired])
        assert result.total == 1
        assert result.can_trend == 1
        assert result.can_project == 1


class TestUnderMinimum:
    def test_a_worn_tire_is_counted_as_an_action(self):
        """What an analytics page adds over a card: the card shows a badge on
        the tire, this says how many there are without opening the tab."""
        tires = [tire(1, below_threshold=True), tire(2, below_threshold=False)]
        assert tire_readiness(tires).under_minimum == 1
