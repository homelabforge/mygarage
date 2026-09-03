"""Every spelling of speed and RPM that can open a drive session.

This exists because the design's first revision proposed reusing
``is_odometer_param_key``'s prefix-stripping treatment for these keys. That
works for odometer by coincidence -- ``A6-ODOMETER`` strips to ``ODOMETER``,
which is the bare name -- and does not hold here: ``0D-VEHICLESPEED`` strips to
``VEHICLESPEED``, not ``SPEED``.

The consequence would have been silent and total. A standard-PID WiCAN emits
only prefixed keys, so every one of its readings would have answered "not a
speed key", no movement would ever be confirmed, and the device would record
zero sessions with nothing in the log to say why. "No movement detected" and
"key not recognised" are indistinguishable from outside, which is what makes
this worth a table rather than a spot check.

Each spelling below is one that a real ingest path produces, named with the
path, so a future edit that drops one has to argue with the source rather than
with a list.
"""

from __future__ import annotations

import pytest

from app.utils.movement_keys import is_rpm_param_key, is_speed_param_key

#: (key, path that produces it)
SPEED_KEYS = [
    ("SPEED", "WiCAN bare autopid, and torque_pid_map's k0d target"),
    ("0D-VehicleSpeed", "WiCAN standard-PID firmware, mixed case on the wire"),
    ("0D-VEHICLESPEED", "the same key after canonical_param_key uppercases it"),
    ("VEHICLE_SPEED", "canonical form of a 'Vehicle Speed' autopid"),
]

RPM_KEYS = [
    ("RPM", "WiCAN bare autopid"),
    ("ENGINE_RPM", "torque_pid_map's k0c target, and the canonical form"),
    ("0C-EngineRPM", "WiCAN standard-PID firmware"),
    ("0C-ENGINERPM", "the same key canonicalised"),
]

#: Keys that must NOT match. The odometer and trip counters matter most: a
#: loose match there would let a parked heartbeat's odometer reading count as
#: movement, which is the exact defect the movement predicate exists to fix.
NON_MOVEMENT_KEYS = [
    "BATTERY_VOLTAGE",
    "A6-ODOMETER",
    "ODOMETER",
    "21-DISTANCEMILON",
    "COOLANT_TMP",
    "THROTTLE",
    "FUEL",
    "SPEEDOMETER_CALIBRATION",
    "MAX_SPEED_LIMIT",
]


@pytest.mark.parametrize("key,source", SPEED_KEYS, ids=[k for k, _ in SPEED_KEYS])
def test_speed_spellings_are_recognised(key: str, source: str):
    assert is_speed_param_key(key), f"{key} is emitted by {source}"


@pytest.mark.parametrize("key,source", RPM_KEYS, ids=[k for k, _ in RPM_KEYS])
def test_rpm_spellings_are_recognised(key: str, source: str):
    assert is_rpm_param_key(key), f"{key} is emitted by {source}"


@pytest.mark.parametrize("key", NON_MOVEMENT_KEYS)
def test_non_movement_keys_are_rejected_by_both(key: str):
    assert not is_speed_param_key(key)
    assert not is_rpm_param_key(key)


def test_speed_and_rpm_do_not_overlap():
    """A key that answered yes to both would double-count one reading."""
    for key, _ in SPEED_KEYS:
        assert not is_rpm_param_key(key)
    for key, _ in RPM_KEYS:
        assert not is_speed_param_key(key)


def test_the_prefix_strip_alone_would_not_have_worked():
    """The specific mistake this module exists to avoid, pinned.

    ``is_odometer_param_key``'s treatment is: strip the PID prefix, compare
    against the bare name. Applied to speed that yields ``VEHICLESPEED``, which
    is not ``SPEED``. This asserts the alias set covers the stripped form, so
    an edit that trims the sets back to the bare names fails here rather than
    in production six weeks later.
    """
    from app.utils.odometer_units import OBD2_PID_PREFIX_RE

    assert OBD2_PID_PREFIX_RE.sub("", "0D-VEHICLESPEED") == "VEHICLESPEED"
    assert OBD2_PID_PREFIX_RE.sub("", "0C-ENGINERPM") == "ENGINERPM"
    # ...and both of those must still resolve, which is the whole point.
    assert is_speed_param_key("0D-VEHICLESPEED")
    assert is_rpm_param_key("0C-ENGINERPM")


class TestTheSqlListsAgreeWithThePredicates:
    """A key that can open a session must be a key the aggregates can read.

    The predicates run in Python, one key at a time. The aggregate reader runs
    in SQL over an ``IN`` list, because grouping in Python would mean loading
    every telemetry row of the window. Two representations of the same set is
    exactly the shape that drifts: a key added to the predicate but not the
    list opens sessions whose ``avg_speed`` and ``max_speed`` are then always
    NULL, and nothing anywhere reports a mismatch.

    So the list is DERIVED from the predicate's alias set rather than written
    beside it, and these tests pin that it stays derived.
    """

    def test_every_recognised_speed_spelling_is_in_the_sql_list(self):
        from app.utils.movement_keys import speed_param_key_candidates

        candidates = {k.upper() for k in speed_param_key_candidates()}
        for key, source in SPEED_KEYS:
            assert key.upper() in candidates, f"{key} ({source}) opens a session but has no stats"

    def test_every_recognised_rpm_spelling_is_in_the_sql_list(self):
        from app.utils.movement_keys import rpm_param_key_candidates

        candidates = {k.upper() for k in rpm_param_key_candidates()}
        for key, source in RPM_KEYS:
            assert key.upper() in candidates, f"{key} ({source}) opens a session but has no stats"

    def test_every_sql_candidate_is_accepted_by_its_predicate(self):
        """The other direction, so the list cannot grow a key the predicate rejects."""
        from app.utils.movement_keys import rpm_param_key_candidates, speed_param_key_candidates

        for key in speed_param_key_candidates():
            assert is_speed_param_key(key), key
        for key in rpm_param_key_candidates():
            assert is_rpm_param_key(key), key

    def test_the_candidate_lists_are_not_empty(self):
        """Guard-the-guard: both tests above pass vacuously against an empty list."""
        from app.utils.movement_keys import rpm_param_key_candidates, speed_param_key_candidates

        assert "SPEED" in {k.upper() for k in speed_param_key_candidates()}
        assert "0C-ENGINERPM" in {k.upper() for k in rpm_param_key_candidates()}

    def test_the_session_service_reads_its_lists_from_here(self):
        """`SessionService` had its own hand-written copies of both lists.

        The RPM one was inline in `_calculate_session_aggregates`, twelve lines
        from a SPEED list that was a module constant, and neither knew about
        the other. This asserts both now come from the shared helper.
        """
        from app.services.session_service import RPM_PARAM_KEYS, SPEED_PARAM_KEYS
        from app.utils.movement_keys import rpm_param_key_candidates, speed_param_key_candidates

        assert set(SPEED_PARAM_KEYS) == set(speed_param_key_candidates())
        assert set(RPM_PARAM_KEYS) == set(rpm_param_key_candidates())
