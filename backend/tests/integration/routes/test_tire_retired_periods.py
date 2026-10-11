"""G4-71: a retired tire's mount history ends at its retirement.

Add past period and the period editor both took a period that ran past
`retired_on`, which describes a tire on the car after it was thrown away.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.vehicle import Vehicle


@pytest_asyncio.fixture
async def retired(client, auth_headers, db_session, test_user):
    vin = f"RET{uuid.uuid4().hex[:14].upper()}"
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname="Retired",
            vehicle_type="Car",
            year=2019,
            make="Kia",
            model="Soul",
        )
    )
    await db_session.commit()
    tire = (
        await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "FL", "mounted_on": "2026-01-01"},
        )
    ).json()
    gone = await client.post(
        f"/api/vehicles/{vin}/tires/{tire['id']}/retire",
        headers=auth_headers,
        json={"dismounted_on": "2026-03-01"},
    )
    assert gone.status_code == 200, gone.text
    yield vin, gone.json()
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest.mark.asyncio
class TestRetiredHistory:
    async def test_a_past_period_cannot_end_after_retirement(self, client, auth_headers, retired):
        vin, tire = retired
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods",
            headers=auth_headers,
            json={"position": "RL", "mounted_on": "2026-03-05", "dismounted_on": "2026-03-10"},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == (
            "This tire was retired on 2026-03-01. A mount period can't run past that."
        )

    async def test_older_history_is_still_welcome(self, client, auth_headers, retired):
        vin, tire = retired
        added = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods",
            headers=auth_headers,
            json={"position": "RL", "mounted_on": "2025-05-01", "dismounted_on": "2025-09-01"},
        )
        assert added.status_code == 201, added.text

    async def test_an_edit_cannot_move_a_period_past_retirement(
        self, client, auth_headers, retired
    ):
        vin, tire = retired
        period_id = tire["mount_periods"][0]["id"]
        refused = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-10"},
        )
        assert refused.status_code == 409, refused.text
        assert "retired on 2026-03-01" in refused.json()["detail"]

    async def test_an_edit_cannot_move_the_mount_past_retirement(
        self, client, auth_headers, retired
    ):
        vin, tire = retired
        period_id = tire["mount_periods"][0]["id"]
        refused = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-03-05"},
        )
        assert refused.status_code == 409, refused.text
        assert "retired on 2026-03-01" in refused.json()["detail"]

    async def test_an_unknown_mount_date_still_saves(self, client, auth_headers, retired):
        """Migration 097 left most periods with no mount date, and the editor can
        clear one too. Nothing to compare is not past the retirement."""
        vin, tire = retired
        period_id = tire["mount_periods"][0]["id"]
        saved = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": None, "notes": "Fitted before we bought it"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["mount_periods"][0]["mounted_on"] is None

    async def test_an_edit_may_keep_the_retirement_day(self, client, auth_headers, retired):
        """Retire closed this period on the retirement day, and the editor sends
        both dates back with every save. A notes fix has to go through."""
        vin, tire = retired
        period_id = tire["mount_periods"][0]["id"]
        saved = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
            headers=auth_headers,
            json={
                "mounted_on": "2026-01-01",
                "dismounted_on": "2026-03-01",
                "notes": "Sidewall cut",
            },
        )
        assert saved.status_code == 200, saved.text

    async def test_a_past_period_may_end_on_the_retirement_day(self, client, auth_headers, retired):
        """Off the front in February, a last month on the back, retired the day it came off."""
        vin, tire = retired
        period_id = tire["mount_periods"][0]["id"]
        shortened = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"dismounted_on": "2026-02-01"},
        )
        assert shortened.status_code == 200, shortened.text
        added = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods",
            headers=auth_headers,
            json={"position": "RL", "mounted_on": "2026-02-01", "dismounted_on": "2026-03-01"},
        )
        assert added.status_code == 201, added.text
