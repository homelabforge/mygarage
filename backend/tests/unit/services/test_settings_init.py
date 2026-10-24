"""Unit tests for default settings seeding.

Covers the DEF-low notification settings (Task 14 of the fuel-type
hardening plan): `notify_def_low` and `notify_def_low_threshold_percent`.

Also covers `default_unit_prefs`'s reseed derivation (task-3 review, Fix 1):
see `TestDefaultUnitPrefsReseed` below.

And the six seeds batch 5 retired (Task 5): see `TestRetiredSeeds` below.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, configure_sqlite_engine
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


@pytest.mark.asyncio
class TestDefaultSettingLogLine:
    """Seeding a default logs the key and its value, except a secret's value (Task 2 review, M4).

    Every secret default is "" today, so the test patches `DEFAULT_SETTINGS`
    down to one secret key with a non-empty default and one plain key, and
    deletes their rows first so both are seeded.
    """

    async def test_a_seeded_secret_default_logs_no_value(
        self, db_session, keep_rows, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        import logging

        from sqlalchemy import delete

        secret_default = "seeded-default-secret-value"
        plain_default = "seeded-plain-default"
        monkeypatch.setattr(
            settings_init,
            "DEFAULT_SETTINGS",
            {
                "ntfy_token": {**DEFAULT_SETTINGS["ntfy_token"], "value": secret_default},
                "oidc_provider_name": {
                    **DEFAULT_SETTINGS["oidc_provider_name"],
                    "value": plain_default,
                },
            },
        )
        await keep_rows("ntfy_token", "oidc_provider_name")
        await db_session.execute(
            delete(Setting).where(Setting.key.in_(["ntfy_token", "oidc_provider_name"]))
        )
        await db_session.commit()

        with caplog.at_level(logging.INFO, logger=settings_init.logger.name):
            await initialize_default_settings(db_session)

        assert secret_default not in caplog.text
        assert "Added default setting: ntfy_token = <secret>" in caplog.text
        assert f"Added default setting: oidc_provider_name = {plain_default}" in caplog.text


# Seeded, and read by nothing (batch 5, Task 5): uploads follow the server's
# configuration (sizes from the environment, each kind's file types from
# defaults in code the environment can override), and the three display
# settings were never read at all.
RETIRED_SEED_KEYS = (
    "max_upload_size_mb",
    "allowed_photo_types",
    "allowed_attachment_types",
    "date_format",
    "distance_unit",
    "fuel_unit",
)


@pytest_asyncio.fixture
async def fresh_db(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    """A session on a brand-new SQLite database: every table, no rows.

    The shared test database persists for the whole run and never sees the
    full seed, so "a fresh install" needs its own file. Seeding the whole
    `DEFAULT_SETTINGS` here touches nothing another test reads.
    """
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "fresh.db"))
    configure_sqlite_engine(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
class TestRetiredSeeds:
    """Six settings nothing reads are no longer seeded.

    Existing rows stay as orphans: the seeder only adds and re-describes, it
    never deletes, and no migration removes them.
    """

    async def test_a_fresh_install_seeds_none_of_them(self, fresh_db: AsyncSession) -> None:
        await initialize_default_settings(fresh_db)

        seeded = set((await fresh_db.execute(select(Setting.key))).scalars())
        # The seed ran: a key it still carries is there.
        assert "window_sticker_enabled" in seeded
        assert seeded.isdisjoint(RETIRED_SEED_KEYS), sorted(seeded & set(RETIRED_SEED_KEYS))

    async def test_a_row_already_stored_survives_startup(self, fresh_db: AsyncSession) -> None:
        """Regression guard, passes on main by design: the seeder never deletes a
        row, so an upgraded instance keeps its old value as an orphan row."""
        fresh_db.add(
            Setting(key="max_upload_size_mb", value="25", category="files", description="old")
        )
        await fresh_db.commit()

        await initialize_default_settings(fresh_db)

        row = await fresh_db.get(Setting, "max_upload_size_mb")
        assert row is not None
        assert row.value == "25"
