"""The secret setting keys: one explicit list, pinned to the seed metadata (D6a).

`SECRET_SETTING_KEYS` lives in a leaf module so the model can import it without
a cycle (`settings_init` imports the model). The cost of a hand-written list is
drift, so this pins it: a seed key newly flagged `encrypted: True` fails here
until it is listed, and so does one dropped from the list.
"""

import pytest

from app.services.settings_init import DEFAULT_SETTINGS, SENSITIVE_SETTING_KEYS
from app.utils.secret_setting_keys import SECRET_SETTING_KEYS

# The three POI provider keys (migration 027, the POI routes). Real, billable
# keys, but never seeded with `encrypted: True`, and served unmasked before.
POI_SECRET_KEYS = frozenset({"google_places_api_key", "yelp_api_key", "foursquare_api_key"})

pytestmark = pytest.mark.unit


def test_the_list_is_the_flagged_seed_keys_plus_the_poi_keys() -> None:
    flagged = {key for key, meta in DEFAULT_SETTINGS.items() if meta["encrypted"]}
    assert SECRET_SETTING_KEYS == flagged | POI_SECRET_KEYS


def test_there_are_seventeen() -> None:
    assert len(SECRET_SETTING_KEYS) == 17
    assert isinstance(SECRET_SETTING_KEYS, frozenset)


def test_masking_uses_the_same_set() -> None:
    """Masking covers the POI keys too, so it is the same object, not a second list."""
    assert SENSITIVE_SETTING_KEYS is SECRET_SETTING_KEYS
