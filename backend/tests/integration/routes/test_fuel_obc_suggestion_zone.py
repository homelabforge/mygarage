"""The OBC suggestion reads the fill-up time as household wall clock.

The form sends `filled_at` as the date and time the user typed, in the
household's zone, but drive sessions end in naive UTC. Compared as they were, a
household west of UTC missed the drive it had just finished, and one east of it
got a drive that ended after the fill-up.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.settings import Setting
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: When the drive ended, naive UTC like every stored stamp.
ENDED_UTC = datetime(2026, 9, 1, 12, 0)


async def _household(
    db_session: AsyncSession, keep_rows: Callable[..., Awaitable[None]], zone: str
) -> None:
    await keep_rows("timezone")
    await db_session.execute(delete(Setting).where(Setting.key == "timezone"))
    db_session.add(Setting(key="timezone", value=zone))
    await db_session.commit()


async def _drive(db_session: AsyncSession, vin: str) -> None:
    db_session.add(
        DriveSession(
            vin=vin,
            device_id="obczone00001",
            started_at=ENDED_UTC - timedelta(hours=1),
            ended_at=ENDED_UTC,
            distance_km=57.3,
            fuel_used_estimate=4.0,
        )
    )
    await db_session.commit()


async def _suggest(client: AsyncClient, headers: dict[str, str], vin: str, at: str) -> int:
    response = await client.get(
        f"/api/vehicles/{vin}/fuel/obc-suggestion", params={"at": at}, headers=headers
    )
    return response.status_code


async def test_a_household_west_of_utc_finds_the_drive_it_just_finished(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    own_vehicle: Vehicle,
    keep_rows: Callable[..., Awaitable[None]],
) -> None:
    # 12:00 UTC is 07:00 in Chicago (CDT); the fill-up is five minutes later.
    await _household(db_session, keep_rows, "America/Chicago")
    await _drive(db_session, own_vehicle.vin)
    assert await _suggest(client, auth_headers, own_vehicle.vin, "2026-09-01T07:05:00") == 200


async def test_a_household_east_of_utc_gets_no_drive_that_ended_later(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    own_vehicle: Vehicle,
    keep_rows: Callable[..., Awaitable[None]],
) -> None:
    # 12:00 UTC is midnight in Auckland (NZST); a 23:00 fill-up came before it.
    await _household(db_session, keep_rows, "Pacific/Auckland")
    await _drive(db_session, own_vehicle.vin)
    assert await _suggest(client, auth_headers, own_vehicle.vin, "2026-09-01T23:00:00") == 404
