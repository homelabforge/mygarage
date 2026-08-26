"""Unit tests for default settings seeding.

Covers the DEF-low notification settings (Task 14 of the fuel-type
hardening plan): `notify_def_low` and `notify_def_low_threshold_percent`.

Also covers `default_unit_prefs`'s reseed derivation (task-3 review, Fix 1):
see `TestDefaultUnitPrefsReseed` below.
"""

import pytest

from app.models.settings import Setting
from app.services import settings_init
from app.services.settings_init import DEFAULT_SETTINGS, initialize_default_settings
from app.utils.default_unit_prefs import (
    DEFAULT_UNIT_PREFS_KEY,
    UK_IMPERIAL_PRESET,
    parse_default_unit_prefs,
)


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


@pytest.mark.asyncio
class TestDefaultUnitPrefsReseed:
    """A `default_unit_prefs` row deleted through the generic, admin-only
    `DELETE /api/settings/{key}` endpoint (no per-key protection) must reseed
    from the instance's real gallon flavour, not the static US-imperial value
    `DEFAULT_SETTINGS` carries for this key (task-3 review, Fix 1): migration
    093 is a one-shot, stamped migration and will never re-run to repair it.

    Monkeypatches `DEFAULT_SETTINGS` down to just this one key before calling
    the real `initialize_default_settings`, so the test exercises the actual
    seeding function without writing every other default setting into the
    shared test database (no per-test rollback; see
    reference_mygarage_test_isolation).
    """

    async def test_uk_instance_reseeds_uk_not_us(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proven to catch a regression: reverting the seeding branch to the
        static `config["value"]` makes this fail (captured in the task-3
        report, Fix round 1)."""
        monkeypatch.setattr(
            settings_init,
            "DEFAULT_SETTINGS",
            {DEFAULT_UNIT_PREFS_KEY: DEFAULT_SETTINGS[DEFAULT_UNIT_PREFS_KEY]},
        )

        gallon_existing = await db_session.get(Setting, "imperial_gallon_standard")
        original_gallon_value = gallon_existing.value if gallon_existing is not None else None
        if gallon_existing is None:
            db_session.add(Setting(key="imperial_gallon_standard", value="uk", category="general"))
        else:
            gallon_existing.value = "uk"

        prefs_existing = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
        prefs_existed = prefs_existing is not None
        original_prefs_value = prefs_existing.value if prefs_existing is not None else None
        if prefs_existing is not None:
            await db_session.delete(prefs_existing)
        await db_session.commit()

        try:
            await initialize_default_settings(db_session)

            reseeded = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
            assert reseeded is not None
            assert parse_default_unit_prefs(reseeded.value) == UK_IMPERIAL_PRESET
        finally:
            gallon_row = await db_session.get(Setting, "imperial_gallon_standard")
            if original_gallon_value is None:
                if gallon_row is not None:
                    await db_session.delete(gallon_row)
            elif gallon_row is not None:
                gallon_row.value = original_gallon_value
            else:
                db_session.add(Setting(key="imperial_gallon_standard", value=original_gallon_value))

            prefs_row = await db_session.get(Setting, DEFAULT_UNIT_PREFS_KEY)
            if not prefs_existed:
                if prefs_row is not None:
                    await db_session.delete(prefs_row)
            elif prefs_row is not None:
                prefs_row.value = original_prefs_value
            else:
                db_session.add(Setting(key=DEFAULT_UNIT_PREFS_KEY, value=original_prefs_value))
            await db_session.commit()
