"""Which settings are switches, and how a stored switch is tidied.

`app.services.setting_switches` is light on purpose: migration 160 imports it,
so it must not drag the whole settings rule set into the migration runner.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.services import setting_rules
from app.services.setting_switches import SWITCH_SETTING_KEYS, stored_switch_value, switch_keys
from app.services.settings_init import DEFAULT_SETTINGS

_BACKEND = Path(__file__).resolve().parents[3]


@pytest.mark.unit
def test_the_switch_keys_derive_from_the_seed() -> None:
    """A newly seeded switch is canonicalized without a second edit; an entry with
    no `value` (as `default_unit_prefs` is seeded) is skipped, not a KeyError."""
    seed: dict[str, dict[str, str]] = {
        "fake_feature_enabled": {"value": "false", "category": "general"},
        "fake_other_switch": {"value": "true", "category": "general"},
        "fake_number": {"value": "0", "category": "general"},
        "fake_derived": {"category": "general"},
    }
    assert switch_keys(seed) == {"fake_feature_enabled", "fake_other_switch"}


@pytest.mark.unit
def test_the_live_switch_set_is_the_seeds() -> None:
    assert SWITCH_SETTING_KEYS == switch_keys(DEFAULT_SETTINGS)
    assert "nhtsa_enabled" in SWITCH_SETTING_KEYS


@pytest.mark.unit
def test_setting_rules_hands_out_the_same_set() -> None:
    # The routes and the restore still import it from setting_rules.
    assert setting_rules.SWITCH_SETTING_KEYS is SWITCH_SETTING_KEYS


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", "true"),
        ("TRUE", "true"),
        ("1", "true"),
        ("Yes", "true"),
        (" On ", "true"),
        ("false", "false"),
        ("False", "false"),
        ("0", "false"),
        ("NO", "false"),
        ("\toff\n", "false"),
    ],
)
def test_a_switch_word_is_stored_as_its_canonical_spelling(raw: str, expected: str) -> None:
    assert stored_switch_value("nhtsa_enabled", raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["maybe", "2", "enabled", " Enabled ", "-1"])
def test_any_other_switch_text_is_stored_as_off(raw: str) -> None:
    """`parse_bool` already reads these as off, so nothing anyone sees changes."""
    assert stored_switch_value("nhtsa_enabled", raw) == "false"


@pytest.mark.unit
@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_a_blank_switch_is_left_alone(raw: str | None) -> None:
    """Blank means "use the default" to the reader, which isn't always off."""
    assert stored_switch_value("nhtsa_enabled", raw) == raw


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("auth_mode", "Yes"),
        ("auto_archive_inactive_days", "1"),
        ("ntfy_topic", "enabled"),
        ("not_a_seeded_key", "off"),
        ("auth_mode", None),
    ],
)
def test_a_non_switch_key_is_left_alone(key: str, raw: str | None) -> None:
    assert key not in SWITCH_SETTING_KEYS
    assert stored_switch_value(key, raw) == raw


@pytest.mark.unit
def test_importing_it_leaves_the_heavy_rule_modules_alone() -> None:
    # Migration 160 imports this, and the runner shouldn't load the LLM client
    # or the recall providers just to tidy some switches.
    heavy = (
        "app.services.setting_rules",
        "app.schemas.livelink",
        "app.services.fuel_prices.france",
        "app.services.llm_client",
        "app.services.recalls.rappelconso",
    )
    code = (
        "import sys\n"
        "import app.services.setting_switches\n"
        f"print(','.join(m for m in {heavy!r} if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""
