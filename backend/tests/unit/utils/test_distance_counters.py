"""Which telemetry keys measure distance, and which of them describes a drive best.

The hardware measurements that motivate this, and the reason an odometer and a
distance counter are kept as disjoint sets, are argued in the module under test.
Tested here: that the classification holds at its edges (an unprefixed autopid,
a subset counter, an odometer) and that the selection arithmetic is right, both
without a database.
"""

import pytest

from app.utils.distance_counters import (
    is_distance_counter_param_key,
    is_distance_source_param_key,
    measure_travelled,
    select_distance_source,
)


class TestIsDistanceCounterParamKey:
    """Standard cumulative-distance PIDs, and nothing that merely reads like one."""

    @pytest.mark.parametrize(
        "key",
        [
            "31-DISTANCESINCECODECLEAR",
            "31-distancesincecodeclear",
        ],
    )
    def test_standard_distance_pids_are_counters(self, key):
        assert is_distance_counter_param_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "DISTANCESINCECODECLEAR",
            "distancesincecodeclear",
        ],
    )
    def test_an_unprefixed_name_is_refused(self, key):
        """No PID prefix means an autopid, and an autopid's units are unknowable.

        The odometer survives the same ambiguity only because
        `LiveLinkDevice.odometer_unit` lets a device declare its units. Nothing
        declares units for a distance counter, so the ambiguous case is dropped
        instead of assumed metric.
        """
        assert is_distance_counter_param_key(key) is False

    @pytest.mark.parametrize(
        "key",
        [
            "A6-ODOMETER",
            "ODOMETER",
            "0D-VEHICLESPEED",
            "0C-ENGINERPM",
            "31-DISTANCE",
            "DISTANCE_TO_EMPTY",
            "",
        ],
    )
    def test_non_counters_are_refused(self, key):
        assert is_distance_counter_param_key(key) is False

    def test_distance_with_the_mil_on_is_refused(self):
        """PID 0x21 is metric, standard, and 1 km resolution, and still wrong here.

        It counts only the distance driven with the malfunction light lit, so it
        measures a subset of the journey and starts mid-drive when a fault
        appears. On a vehicle whose odometer does not tick within a drive it
        would out-resolve the odometer, win the selection, and report the 5 km
        since the light came on as the length of a 12 km trip.
        """
        assert is_distance_counter_param_key("21-DISTANCEMILON") is False
        assert is_distance_source_param_key("21-DISTANCEMILON") is False

    def test_an_odometer_is_not_a_distance_counter(self):
        """They are different quantities and only one may stamp the odometer columns.

        `31-DISTANCESINCECODECLEAR` resets when a technician clears a code, so
        writing it into `start_odometer` would report a vehicle with 3,000 km on
        it. The two sets stay disjoint so that mistake needs a deliberate edit.
        """
        assert is_distance_counter_param_key("A6-ODOMETER") is False
        assert is_distance_counter_param_key("ODOMETER") is False


class TestIsDistanceSourceParamKey:
    """The union: anything whose increase measures distance travelled."""

    @pytest.mark.parametrize(
        "key",
        ["A6-ODOMETER", "ODOMETER", "ODO", "MILEAGE", "31-DISTANCESINCECODECLEAR"],
    )
    def test_odometers_and_counters_are_both_sources(self, key):
        assert is_distance_source_param_key(key) is True

    @pytest.mark.parametrize(
        "key", ["0D-VEHICLESPEED", "2F-FUELTANKLEVEL", "DISTANCESINCECODECLEAR"]
    )
    def test_everything_else_is_not(self, key):
        assert is_distance_source_param_key(key) is False


class TestMeasureTravelled:
    """Reducing one source's readings to what they say about a drive."""

    def test_a_monotonic_source_sums_to_its_span(self):
        """The odometer case, unchanged by any of this.

        Sum-of-rises and `max - min` are identical for a source that only ever
        increases, which is what lets the same function serve both without the
        odometer computing anything different from what it always did.
        """
        span = measure_travelled([9195.0, 9197.0, 9203.0, 9210.0])

        assert span.distance_km == pytest.approx(15.0)
        assert span.high - span.low == pytest.approx(span.distance_km)
        assert span.steps == 3

    def test_a_reset_counts_only_the_rises(self):
        """A code clear mid-window. `max - min` would read 806 on a 15 km drive."""
        span = measure_travelled([800.0, 810.0, 4.0, 9.0])

        assert span.distance_km == pytest.approx(15.0)
        assert span.high - span.low == pytest.approx(806.0), "which is why span is not distance"
        assert span.steps == 2, "the reset itself is a fall, so it is not a step"

    def test_one_reading_is_no_distance_rather_than_no_answer(self):
        """A single sample proves the vehicle was somewhere, never that it moved."""
        span = measure_travelled([141300.0])

        assert span.steps == 0
        assert span.distance_km == 0.0
        assert span.low == span.high == 141300.0

    def test_a_flat_source_reports_zero(self):
        """The Mirage's odometer across a trip shorter than one of its steps."""
        span = measure_travelled([141300.0, 141300.0, 141300.0])

        assert span.steps == 0
        assert span.distance_km == 0.0


class TestSelectDistanceSource:
    """Which source describes the window most finely."""

    def test_more_steps_wins(self):
        spans = {
            "ODOMETER": measure_travelled([141300.0, 141300.0]),
            "31-DISTANCESINCECODECLEAR": measure_travelled([500.0, 504.0, 509.0, 512.0]),
        }

        assert select_distance_source(spans, {"ODOMETER"}) == "31-DISTANCESINCECODECLEAR"

    def test_an_odometer_wins_its_own_ties(self):
        """What keeps the change additive.

        Equal resolution means the odometer keeps the job, so a device that was
        already being measured correctly is never quietly restated.
        """
        spans = {
            "A6-ODOMETER": measure_travelled([9195.0, 9200.0, 9205.0]),
            "31-DISTANCESINCECODECLEAR": measure_travelled([100.0, 108.0, 118.0]),
        }

        assert select_distance_source(spans, {"A6-ODOMETER"}) == "A6-ODOMETER"

    def test_a_counter_wins_only_by_resolving_strictly_finer(self):
        """One more step is enough, and one fewer is not."""
        odo = measure_travelled([9195.0, 9200.0, 9205.0])
        assert (
            select_distance_source(
                {"A6-ODOMETER": odo, "31-X": measure_travelled([1.0, 2.0, 3.0, 4.0])},
                {"A6-ODOMETER"},
            )
            == "31-X"
        )
        assert (
            select_distance_source(
                {"A6-ODOMETER": odo, "31-X": measure_travelled([1.0, 2.0])},
                {"A6-ODOMETER"},
            )
            == "A6-ODOMETER"
        )

    def test_nothing_measured_selects_nothing(self):
        """So the caller can fall through to the GPS breadcrumb."""
        assert select_distance_source({}, set()) is None
