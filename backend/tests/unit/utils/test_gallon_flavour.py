"""Tests for the instance gallon-flavour resolver."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.utils.gallon_flavour import resolve_gallon_flavour


async def _seed_gallon_standard(db_session: AsyncSession, value: str) -> None:
    """Upsert the `imperial_gallon_standard` row.

    The test DB is shared across the whole run and never rolled back between
    tests (see reference_mygarage_test_isolation), so a bare `db_session.add()`
    here would collide with the row a previous test in this module already
    committed. Upserting keeps each test independent of what the last one left
    behind, and cleaning up afterward keeps this module from leaking state into
    whatever test file runs next.
    """
    existing = (
        await db_session.execute(select(Setting).where(Setting.key == "imperial_gallon_standard"))
    ).scalar_one_or_none()
    if existing is None:
        db_session.add(Setting(key="imperial_gallon_standard", value=value))
    else:
        existing.value = value
    await db_session.commit()


async def _clear_gallon_standard(db_session: AsyncSession) -> None:
    """Delete the `imperial_gallon_standard` row, restoring the "row absent" state."""
    existing = (
        await db_session.execute(select(Setting).where(Setting.key == "imperial_gallon_standard"))
    ).scalar_one_or_none()
    if existing is not None:
        await db_session.delete(existing)
        await db_session.commit()


@pytest.mark.asyncio
async def test_defaults_to_us_when_row_absent(db_session: AsyncSession) -> None:
    assert await resolve_gallon_flavour(db_session) == "us"


@pytest.mark.asyncio
async def test_reads_uk_from_the_setting(db_session: AsyncSession) -> None:
    await _seed_gallon_standard(db_session, "uk")
    try:
        assert await resolve_gallon_flavour(db_session) == "uk"
    finally:
        await _clear_gallon_standard(db_session)


@pytest.mark.asyncio
async def test_unrecognised_value_falls_back_to_us(db_session: AsyncSession) -> None:
    await _seed_gallon_standard(db_session, "banana")
    try:
        assert await resolve_gallon_flavour(db_session) == "us"
    finally:
        await _clear_gallon_standard(db_session)


def test_intrinsically_us_conversions_ignore_the_setting() -> None:
    """EPA and window-sticker figures are US-gallon by definition.

    They are not a user preference and must not follow the instance flavour.

    This exercises the real class-3 call site -- `WindowStickerOCRService.
    _sticker_data_to_dict`'s MPG -> L/100km conversion -- rather than
    `UnitConverter.mpg_to_l100km(..., flavour="us")` directly. That call site
    never resolves a flavour at all; it multiplies by a fixed US numerator
    unconditionally. Asserting against `UnitConverter` with `flavour="us"`
    pinned in the *test* would still pass even if phase 1 rewired the call
    site itself to resolve a per-user flavour, so it would not catch that
    regression. Pinning the actual call site is what stops phase 1 from
    "fixing" it into the preference path.
    """
    from decimal import Decimal

    from app.services.window_sticker_ocr import WindowStickerOCRService
    from app.services.window_sticker_parsers import WindowStickerData

    # A window-sticker combined MPG figure is always a US MPG figure.
    data = WindowStickerData(fuel_economy_combined=30)
    result = WindowStickerOCRService()._sticker_data_to_dict(data)
    assert result["fuel_economy_combined_l_per_100km"] == Decimal("7.84")
