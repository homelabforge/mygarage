"""The gallon setting is stored, and has no process-wide side effect."""

import inspect

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import main as main_module
from app.models.settings import Setting
from app.routes import settings as settings_module
from app.utils.gallon_flavour import resolve_gallon_flavour


def test_no_module_seeds_converter_state() -> None:
    """Startup and the settings routes must not configure the converter."""
    for module in (main_module, settings_module):
        source = inspect.getsource(module)
        assert "set_gallon_standard" not in source, f"{module.__name__} still seeds converter state"


@pytest.mark.asyncio
async def test_writing_the_setting_changes_what_the_resolver_returns(
    db_session: AsyncSession,
) -> None:
    """Behaviour is preserved: the row still drives the flavour, via the resolver.

    Upserts rather than a bare `add()`, and restores whatever state it found in
    `finally`: the test DB is shared across the whole run with no per-test
    rollback (see reference_mygarage_test_isolation), so a row left behind here
    corrupts `resolve_gallon_flavour` reads in every test that runs afterwards.
    """
    existing = (
        await db_session.execute(select(Setting).where(Setting.key == "imperial_gallon_standard"))
    ).scalar_one_or_none()
    original_value = existing.value if existing is not None else None

    try:
        if existing is None:
            existing = Setting(key="imperial_gallon_standard", value="us")
            db_session.add(existing)
        else:
            existing.value = "us"
        await db_session.commit()
        assert await resolve_gallon_flavour(db_session) == "us"

        existing.value = "uk"
        await db_session.commit()
        assert await resolve_gallon_flavour(db_session) == "uk"
    finally:
        row = (
            await db_session.execute(
                select(Setting).where(Setting.key == "imperial_gallon_standard")
            )
        ).scalar_one_or_none()
        if original_value is None:
            if row is not None:
                await db_session.delete(row)
        elif row is not None:
            row.value = original_value
        else:
            db_session.add(Setting(key="imperial_gallon_standard", value=original_value))
        await db_session.commit()
