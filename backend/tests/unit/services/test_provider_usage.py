"""POI provider usage counters read a blank stored count as zero."""

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services.provider_usage import get_provider_usage, increment_provider_usage
from tests._keep_rows import Keep

pytestmark = pytest.mark.asyncio

KEY = "tomtom_api_usage"


async def _store(db: AsyncSession, keep: Keep, value: str | None) -> None:
    await keep(KEY)
    await db.execute(delete(Setting).where(Setting.key == KEY))
    db.add(Setting(key=KEY, value=value))
    await db.commit()


@pytest.mark.parametrize("stored", [None, ""])
async def test_a_blank_count_reads_as_zero(
    db_session: AsyncSession, keep_rows: Keep, stored: str | None
) -> None:
    # Setting.value keeps None and "" as is, and a restore can bring either back.
    await _store(db_session, keep_rows, stored)

    assert (await get_provider_usage(db_session, "tomtom"))["usage"] == 0


@pytest.mark.parametrize("stored", [None, ""])
async def test_a_blank_count_counts_up_from_zero(
    db_session: AsyncSession, keep_rows: Keep, stored: str | None
) -> None:
    await _store(db_session, keep_rows, stored)

    await increment_provider_usage(db_session, "tomtom")
    await db_session.commit()

    row = (await db_session.execute(select(Setting).where(Setting.key == KEY))).scalar_one()
    assert row.value == "1"


async def test_a_stored_count_is_read(db_session: AsyncSession, keep_rows: Keep) -> None:
    await _store(db_session, keep_rows, "41")

    assert (await get_provider_usage(db_session, "tomtom"))["usage"] == 41
    await increment_provider_usage(db_session, "tomtom")
    await db_session.commit()
    assert (await get_provider_usage(db_session, "tomtom"))["usage"] == 42
