"""The OBC suggestion's L/100km comes at the column's four places.

It was quantized to 0.01, the old NUMERIC(5,2) grain, so accepting the
suggestion stored a figure two places coarser than the column holds.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_the_suggestion_keeps_four_places(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    own_vehicle: Vehicle,
) -> None:
    ended = datetime(2026, 9, 1, 12, 0)
    db_session.add(
        DriveSession(
            vin=own_vehicle.vin,
            device_id="obcscale0001",
            started_at=ended - timedelta(hours=1),
            ended_at=ended,
            distance_km=57.3,
            # 4.0 / 57.3 * 100 = 6.98080279...
            fuel_used_estimate=4.0,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/api/vehicles/{own_vehicle.vin}/fuel/obc-suggestion",
        # With an offset, so the household zone doesn't move the window.
        params={"at": (ended + timedelta(minutes=5)).isoformat() + "+00:00"},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["obc_l_per_100km"] == "6.9808"
