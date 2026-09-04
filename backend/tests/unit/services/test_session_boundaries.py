"""The movement predicate, in isolation from the database.

Everything here is a pure function of one telemetry batch. The stateful half --
debounce, pending drives, expiry -- lives in `SessionService` and is tested
against real rows in `tests/integration/test_session_state_machine.py`; this
file pins the part that decides what a batch of readings *means*.

The design's first revision said `speed > 0 OR rpm > 0`. Three things are wrong
with that, and each has a test below:

1. **No floor.** A single 1 km/h sample opens a session, and that sample is
   effectively unvalidatable: `validate_rate_of_change` skips entirely when the
   previous reading is older than 120 seconds, which is exactly the
   parked-heartbeat case.
2. **RPM is not movement.** An engine running with the vehicle stationary is a
   remote start, a diagnostic session, a winter warm-up, or the eleven-minute
   driveway idle that was credited 14 km and started this whole rework.
3. **No odometer signal.** The one signal that covers a device whose speed
   arrives under a name nothing recognises. Without it, C7's "refuse to
   rebuild without positive evidence" would erase that whole cohort.
"""

from __future__ import annotations

import pytest

from app.services.session_boundaries import (
    MOVEMENT_FLOOR_KMH,
    MovementSignals,
    extract_signals,
)


class TestSignalExtraction:
    def test_speed_is_read_under_every_spelling(self):
        for key in ("SPEED", "0D-VEHICLESPEED", "VEHICLE_SPEED"):
            assert extract_signals({key: 42.0}).speed_kmh == 42.0

    def test_rpm_is_read_under_every_spelling(self):
        for key in ("RPM", "ENGINE_RPM", "0C-ENGINERPM"):
            assert extract_signals({key: 800.0}).rpm == 800.0

    def test_odometer_is_read(self):
        assert extract_signals({"A6-ODOMETER": 120_345.0}).odometer_km == 120_345.0

    def test_a_battery_heartbeat_carries_no_signal_at_all(self):
        """The exact payload that opened 2,975 phantom sessions."""
        signals = extract_signals({"BATTERY_VOLTAGE": 12.4})
        assert signals == MovementSignals(speed_kmh=None, rpm=None, odometer_km=None)
        assert not signals.has_any_signal

    def test_the_highest_speed_in_a_batch_wins(self):
        """A batch can carry the same quantity under two keys during a firmware
        change. Taking the max is the safe direction: under-reading speed loses
        a real drive, over-reading it at worst opens a session a stop would."""
        assert extract_signals({"SPEED": 3.0, "0D-VEHICLESPEED": 61.0}).speed_kmh == 61.0

    def test_non_numeric_and_missing_values_are_ignored(self):
        assert extract_signals({"SPEED": None, "RPM": "n/a"}).speed_kmh is None

    def test_unrelated_keys_do_not_leak_into_signals(self):
        signals = extract_signals(
            {"COOLANT_TMP": 90.0, "THROTTLE": 30.0, "21-DISTANCEMILON": 400.0}
        )
        assert not signals.has_any_signal


class TestTheFloor:
    def test_the_floor_is_the_idle_threshold_already_in_use(self):
        """Not a new constant.

        `_calculate_driving_insights` has defined not-moving as `< 5 km/h` for
        idle accounting since the session code was written. A separate `> 0`
        movement rule would have put a second, contradictory definition of
        "moving" twelve lines from the first.
        """
        from app.services.session_service import IDLE_THRESHOLD_KMH

        assert MOVEMENT_FLOOR_KMH == IDLE_THRESHOLD_KMH

    @pytest.mark.parametrize("speed", [0.0, 0.9, 1.0, 4.9])
    def test_speed_below_the_floor_is_not_movement(self, speed: float):
        assert not extract_signals({"SPEED": speed}).is_above_floor

    @pytest.mark.parametrize("speed", [5.0, 5.1, 60.0])
    def test_speed_at_or_above_the_floor_is_movement(self, speed: float):
        assert extract_signals({"SPEED": speed}).is_above_floor

    def test_a_missing_speed_is_not_above_the_floor(self):
        assert not extract_signals({"RPM": 2200.0}).is_above_floor


class TestEngineOnIsNotMovement:
    def test_rpm_alone_is_engine_on(self):
        signals = extract_signals({"ENGINE_RPM": 780.0})
        assert signals.is_engine_on
        assert not signals.is_above_floor

    def test_zero_rpm_is_not_engine_on(self):
        assert not extract_signals({"ENGINE_RPM": 0.0}).is_engine_on

    def test_an_idling_ice_vehicle_shows_engine_on_and_no_movement(self):
        """The original complaint: a Ram idling in a driveway for eleven minutes
        at a top speed of 2 km/h, credited with 14 km."""
        signals = extract_signals({"ENGINE_RPM": 750.0, "SPEED": 2.0})
        assert signals.is_engine_on
        assert not signals.is_above_floor

    def test_an_ev_under_way_shows_movement_and_no_engine(self):
        """An EV reports no RPM at all. An RPM-only predicate gives it zero
        sessions, forever, with nothing in the log to say why."""
        signals = extract_signals({"SPEED": 55.0})
        assert signals.is_above_floor
        assert not signals.is_engine_on
