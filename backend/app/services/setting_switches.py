"""Which settings are on/off switches, and the form a stored switch should take.

Kept apart from `app.services.setting_rules` so a migration can import it
without pulling in the LLM client, the recall providers and the LiveLink
schemas that the full rule set needs.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.services.settings_init import DEFAULT_SETTINGS
from app.services.settings_service import SWITCH_ON_VALUES


def switch_keys(seed: Mapping[str, Mapping[str, object]]) -> frozenset[str]:
    """The keys in `seed` whose seeded value is "true" or "false".

    An entry with no `value` (`default_unit_prefs` is derived at seed time) is
    not a switch; `meta["value"]` there would be a KeyError at import.
    """
    return frozenset(key for key, meta in seed.items() if meta.get("value") in ("true", "false"))


#: Every seeded on/off setting. Derived from the seed list, so a newly seeded
#: switch is stored canonically without a second edit here.
SWITCH_SETTING_KEYS: frozenset[str] = switch_keys(DEFAULT_SETTINGS)


def stored_switch_value(key: str, value: str | None) -> str | None:
    """`value` as a switch under `key` should be stored: "true", "false" or blank.

    Stricter than `canonical_setting_value`: text that isn't an on/off word
    becomes "false", which is how `parse_bool` reads it already, so nothing
    anyone sees changes. Blank stays blank, since a reader turns that into its
    own default and that isn't always off.

    Args:
        key: The settings key.
        value: The stored or submitted value.

    Returns:
        For a key in `SWITCH_SETTING_KEYS`: None, "" or whitespace unchanged;
        "true" for a word in `SWITCH_ON_VALUES` in any case and with
        surrounding whitespace; "false" for anything else. Every other key's
        value unchanged.
    """
    if key not in SWITCH_SETTING_KEYS or value is None:
        return value
    word = value.strip().lower()
    if not word:
        return value
    if word in SWITCH_ON_VALUES:
        return "true"
    return "false"
