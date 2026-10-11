"""G4-71: a retired tire's mount history ends at its retirement.

Add past period and the period editor both took a period that ran past
`retired_on`, which describes a tire on the car after it was thrown away.
Retire took a date before the tire's last dismount, which made the same thing.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.odometer import OdometerRecord
from app.models.tire import Tire, TireMountPeriod
from app.models.vehicle import Vehicle


@pytest_asyncio.fixture
async def vehicle(db_session, test_user):
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
    yield vin
    await db_session.execute(delete(OdometerRecord).where(OdometerRecord.vin == vin))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _mount(client, auth_headers, vin: str) -> dict:
    made = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount",
        headers=auth_headers,
        json={"vin": vin, "position": "FL", "mounted_on": "2026-01-01"},
    )
    assert made.status_code == 201, made.text
    return made.json()


@pytest_asyncio.fixture
async def retired(client, auth_headers, vehicle):
    tire = await _mount(client, auth_headers, vehicle)
    gone = await client.post(
        f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
        headers=auth_headers,
        json={"dismounted_on": "2026-03-01"},
    )
    assert gone.status_code == 200, gone.text
    return vehicle, gone.json()


@pytest_asyncio.fixture
async def legacy(retired, db_session):
    """A period that runs past the retirement, written before G4-71 was closed."""
    vin, tire = retired
    period = TireMountPeriod(
        tire_id=tire["id"],
        position="RL",
        mounted_on=date(2026, 3, 5),
        dismounted_on=date(2026, 3, 10),
        is_assumed=False,
    )
    db_session.add(period)
    await db_session.commit()
    return vin, tire["id"], period.id


@pytest_asyncio.fixture
async def stored(client, auth_headers, vehicle):
    """A tire that came off on 2026-03-10 and sits in storage."""
    tire = await _mount(client, auth_headers, vehicle)
    off = await client.post(
        f"/api/vehicles/{vehicle}/tires/{tire['id']}/dismount",
        headers=auth_headers,
        json={"dismounted_on": "2026-03-10"},
    )
    assert off.status_code == 200, off.text
    return vehicle, tire["id"]


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

    async def test_a_legacy_period_past_retirement_still_takes_a_notes_fix(
        self, client, auth_headers, legacy
    ):
        """Junk from before the fix shouldn't lock the user out of the period.

        The editor's real payload: both dates and figures go back unchanged with every save.
        """
        vin, tire_id, period_id = legacy
        saved = await client.put(
            f"/api/vehicles/{vin}/tires/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={
                "mounted_on": "2026-03-05",
                "mounted_odometer_km": None,
                "notes": "Logged on the wrong tire",
                "dismounted_on": "2026-03-10",
                "dismounted_odometer_km": None,
            },
        )
        assert saved.status_code == 200, saved.text
        period = next(p for p in saved.json()["mount_periods"] if p["id"] == period_id)
        assert period["notes"] == "Logged on the wrong tire"

    async def test_moving_one_date_still_checks_the_other(self, client, auth_headers, legacy):
        """The mount moves back to the retirement day, but the dismount is still past it."""
        vin, tire_id, period_id = legacy
        refused = await client.put(
            f"/api/vehicles/{vin}/tires/{tire_id}/mount-periods/{period_id}",
            headers=auth_headers,
            json={"mounted_on": "2026-03-01"},
        )
        assert refused.status_code == 409, refused.text
        assert "retired on 2026-03-01" in refused.json()["detail"]


@pytest.mark.asyncio
class TestRetireAfterHistory:
    async def test_a_stored_tire_cannot_retire_before_its_last_dismount(
        self, client, auth_headers, db_session, stored
    ):
        vin, tire_id = stored
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/retire",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-01", "dismounted_odometer_km": "12000"},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == (
            "This tire's mount history runs to 2026-03-10, so it can't be retired before that."
        )
        retired_on = (
            await db_session.execute(select(Tire.retired_on).where(Tire.id == tire_id))
        ).scalar_one()
        assert retired_on is None
        published = (
            await db_session.execute(
                select(func.count()).select_from(OdometerRecord).where(OdometerRecord.vin == vin)
            )
        ).scalar_one()
        assert published == 0

    async def test_a_mounted_tire_cannot_retire_before_its_mount(
        self, client, auth_headers, vehicle
    ):
        tire = await _mount(client, auth_headers, vehicle)
        refused = await client.post(
            f"/api/vehicles/{vehicle}/tires/{tire['id']}/retire",
            headers=auth_headers,
            json={"dismounted_on": "2025-12-01"},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == (
            "This tire's mount history runs to 2026-01-01, so it can't be retired before that."
        )

    async def test_a_stored_tire_may_retire_on_its_last_dismount(
        self, client, auth_headers, stored
    ):
        vin, tire_id = stored
        gone = await client.post(
            f"/api/vehicles/{vin}/tires/{tire_id}/retire",
            headers=auth_headers,
            json={"dismounted_on": "2026-03-10"},
        )
        assert gone.status_code == 200, gone.text
        assert gone.json()["retired_on"] == "2026-03-10"
