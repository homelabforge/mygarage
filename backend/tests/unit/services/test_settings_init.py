"""Unit tests for default settings seeding.

Covers the DEF-low notification settings (Task 14 of the fuel-type
hardening plan): `notify_def_low` and `notify_def_low_threshold_percent`.
"""

import pytest

from app.services.settings_init import DEFAULT_SETTINGS


@pytest.mark.unit
class TestDefLowSettingsSeeds:
    """Test that DEF-low notification settings are seeded with correct defaults."""

    def test_notify_def_low_default(self):
        """notify_def_low toggle defaults to enabled, matching sibling event toggles."""
        setting = DEFAULT_SETTINGS["notify_def_low"]
        assert setting["value"] == "true"
        assert setting["category"] == "notifications"
        assert setting["encrypted"] is False

    def test_notify_def_low_threshold_percent_default(self):
        """Threshold defaults to 25% (see comment in settings_init.py for rationale)."""
        setting = DEFAULT_SETTINGS["notify_def_low_threshold_percent"]
        assert setting["value"] == "25"
        assert setting["category"] == "notifications"
        assert setting["encrypted"] is False
