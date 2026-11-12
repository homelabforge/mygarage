"""Integration tests: fuel engine_hours auto-sync + gal/hr + cost/hr surfaces.

Covers the Phase-3 fuel wiring of the hours-usage model:
- creating/updating a fuel record with engine_hours syncs a hours_records row
  (source='fuel', fuel_record_id set); clearing it deletes that row;
- the existing odometer auto-sync and MPG stay unchanged (regression);
- pure-distance vs dual records isolate their dimensions;
- the route round-trips engine_hours and exposes l_per_hr + the list averages.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.vehicle import Vehicle


async def _make_vehicle(db_session: AsyncSession, user_id: int, vin: str) -> None:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname="Hours Test",
            vehicle_type="ATV",
            year=2024,
            make="Test",
            model="Hours",
        )
    )
    await db_session.commit()


async def _hours_rows(db_session: AsyncSession, vin: str) -> list[HoursRecord]:
    result = await db_session.execute(select(HoursRecord).where(HoursRecord.vin == vin))
    return list(result.scalars().all())


@pytest.mark.integration
@pytest.mark.fuel
@pytest.mark.asyncio
class TestFuelHoursAutoSync:
    """engine_hours on a fuel record drives a source-identity hours_records row."""

    async def test_create_with_hours_creates_hours_row_and_keeps_odometer(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000001"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2026-03-01",
                "odometer_km": 1000.0,
                "engine_hours": 120.5,
                "liters": 20.0,
                "cost": 30.0,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert Decimal(str(data["engine_hours"])) == Decimal("120.5")
        record_id = data["id"]

        # Exactly one hours row, keyed by source identity.
        rows = await _hours_rows(db_session, vin)
        assert len(rows) == 1
        row = rows[0]
        assert row.engine_hours == Decimal("120.5")
        assert row.source == "fuel"
        assert row.fuel_record_id == record_id
        assert row.service_visit_id is None
        assert row.date == date(2026, 3, 1)

        # Odometer auto-sync still fires (distance regression).
        odo = (
            await db_session.execute(
                select(OdometerRecord).where(OdometerRecord.fuel_record_id == record_id)
            )
        ).scalar_one()
        assert odo.odometer_km == Decimal("1000.00")

    async def test_update_moves_the_same_hours_row(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000002"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        created = (
            await client.post(
                f"/api/vehicles/{vin}/fuel",
                json={
                    "vin": vin,
                    "date": "2026-03-01",
                    "odometer_km": 1000.0,
                    "engine_hours": 100.0,
                    "liters": 20.0,
                    "cost": 30.0,
                    "is_full_tank": True,
                },
                headers=auth_headers,
            )
        ).json()
        record_id = created["id"]

        resp = await client.put(
            f"/api/vehicles/{vin}/fuel/{record_id}",
            json={"engine_hours": 155.5},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        rows = await _hours_rows(db_session, vin)
        assert len(rows) == 1, "the reading moved on the SAME row, not a duplicate"
        assert rows[0].engine_hours == Decimal("155.5")
        assert rows[0].fuel_record_id == record_id

    async def test_update_clearing_hours_deletes_the_row(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000003"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        created = (
            await client.post(
                f"/api/vehicles/{vin}/fuel",
                json={
                    "vin": vin,
                    "date": "2026-03-01",
                    "odometer_km": 1000.0,
                    "engine_hours": 100.0,
                    "liters": 20.0,
                    "cost": 30.0,
                    "is_full_tank": True,
                },
                headers=auth_headers,
            )
        ).json()
        record_id = created["id"]
        assert len(await _hours_rows(db_session, vin)) == 1

        resp = await client.put(
            f"/api/vehicles/{vin}/fuel/{record_id}",
            json={"engine_hours": None},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        assert await _hours_rows(db_session, vin) == []

    async def test_pure_distance_record_creates_no_hours_row(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000004"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2026-03-01",
                "odometer_km": 1000.0,
                "liters": 20.0,
                "cost": 30.0,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        record_id = resp.json()["id"]

        assert await _hours_rows(db_session, vin) == []
        # Odometer still synced — the distance path is untouched.
        odo = (
            await db_session.execute(
                select(OdometerRecord).where(OdometerRecord.fuel_record_id == record_id)
            )
        ).scalar_one()
        assert odo.odometer_km == Decimal("1000.00")


@pytest.mark.integration
@pytest.mark.fuel
@pytest.mark.asyncio
class TestFuelHoursEconomyRoutes:
    """The route exposes l_per_hr per-record and the list-level hours averages."""

    async def _seed_two_full_tanks(
        self, client: AsyncClient, auth_headers, vin: str
    ) -> tuple[int, int]:
        first = (
            await client.post(
                f"/api/vehicles/{vin}/fuel",
                json={
                    "vin": vin,
                    "date": "2026-03-01",
                    "odometer_km": 1000.0,
                    "engine_hours": 100.0,
                    "liters": 20.0,
                    "cost": 30.0,
                    "is_full_tank": True,
                },
                headers=auth_headers,
            )
        ).json()
        second = (
            await client.post(
                f"/api/vehicles/{vin}/fuel",
                json={
                    "vin": vin,
                    "date": "2026-03-10",
                    "odometer_km": 1500.0,
                    "engine_hours": 120.0,
                    "liters": 15.0,
                    "cost": 25.0,
                    "is_full_tank": True,
                },
                headers=auth_headers,
            )
        ).json()
        return first["id"], second["id"]

    async def test_dual_record_get_exposes_l_per_hr_and_mpg(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000005"
        await _make_vehicle(db_session, int(test_user["id"]), vin)
        _, second_id = await self._seed_two_full_tanks(client, auth_headers, vin)

        resp = await client.get(f"/api/vehicles/{vin}/fuel/{second_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # gal/hr (canonical L/hr): 15 L / (120 - 100) h = 0.75.
        assert Decimal(str(data["l_per_hr"])) == Decimal("0.75")
        # MPG (L/100km) unchanged: 15 L / (1500 - 1000) km * 100 = 3.00.
        assert Decimal(str(data["l_per_100km"])) == Decimal("3.00")

    async def test_list_reports_hours_and_distance_averages(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000006"
        await _make_vehicle(db_session, int(test_user["id"]), vin)
        await self._seed_two_full_tanks(client, auth_headers, vin)

        resp = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert Decimal(str(data["average_l_per_hr"])) == Decimal("0.75")
        assert Decimal(str(data["average_cost_per_hr"])) == Decimal("1.25")  # 25 / 20
        assert Decimal(str(data["average_l_per_100km"])) == Decimal("3.00")

    async def test_pure_distance_list_has_null_hours_averages(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "FUELHOURS00000007"
        await _make_vehicle(db_session, int(test_user["id"]), vin)
        await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2026-03-01",
                "odometer_km": 1000.0,
                "liters": 20.0,
                "cost": 30.0,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )
        await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2026-03-10",
                "odometer_km": 1500.0,
                "liters": 15.0,
                "cost": 25.0,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )

        resp = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["average_l_per_hr"] is None
        assert data["average_cost_per_hr"] is None
        # MPG unaffected by the hours feature.
        assert Decimal(str(data["average_l_per_100km"])) == Decimal("3.00")
        for record in data["records"]:
            assert record["l_per_hr"] is None
