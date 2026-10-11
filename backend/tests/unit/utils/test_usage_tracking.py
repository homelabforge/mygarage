"""`tracks_distance` / `tracks_hours`: the backend twin of `utils/usageTracking.ts`."""

import pytest

from app.utils.usage_tracking import tracks_distance, tracks_hours


@pytest.mark.parametrize(
    ("usage_unit", "secondary", "distance", "hours"),
    [
        ("distance", False, True, False),
        ("distance", True, True, True),
        ("hours", False, False, True),
        ("hours", True, True, True),
        # Unset and unknown read as the column default, like the client does.
        (None, None, True, False),
        ("furlongs", False, True, False),
    ],
)
def test_matches_the_client_rule(usage_unit, secondary, distance, hours):
    assert tracks_distance(usage_unit, secondary) is distance
    assert tracks_hours(usage_unit, secondary) is hours
