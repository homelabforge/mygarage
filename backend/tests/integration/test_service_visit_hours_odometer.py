"""Integration tests: service-visit engine_hours auto-sync + odometer-orphan
fix on visit delete (Phase 4 + folded Phase 4b of the hours-usage model).

Phase 4 mirrors fuel's engine_hours wiring (see test_fuel_hours_sync.py):
- creating/updating a service visit with engine_hours syncs a hours_records
  row (source='service_visit', service_visit_id set); clearing it deletes
  that row; the existing odometer auto-sync stays unchanged (regression).

Phase 4b fixes a pre-existing bug: deleting a service visit never cleaned up
the odometer_records row it auto-synced (only fuel-linked odometer rows
cascade, via odometer_records.fuel_record_id; service-sourced rows have no
FK). The fix is marker-guarded — it must NEVER delete a manual odometer
reading, even one sharing the exact same (vin, date) as the synced row.
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
            nickname="Service Hours Test",
            vehicle_type="ATV",
            year=2024,
            make="Test",
            model="ServiceHours",
        )
    )
    await db_session.commit()


async def _hours_rows(db_session: AsyncSession, vin: str) -> list[HoursRecord]:
    result = await db_session.execute(select(HoursRecord).where(HoursRecord.vin == vin))
    return list(result.scalars().all())


async def _odometer_rows(db_session: AsyncSession, vin: str) -> list[OdometerRecord]:
    result = await db_session.execute(select(OdometerRecord).where(OdometerRecord.vin == vin))
    return list(result.scalars().all())


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceVisitHoursAutoSync:
    """engine_hours on a service visit drives a source-identity hours_records row."""

    async def test_create_with_hours_creates_hours_row_and_keeps_odometer(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "SVCHOURS000000001"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        resp = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-03-01",
                "odometer_km": 1000.0,
                "engine_hours": 120.5,
                "line_items": [{"description": "Oil change", "cost": 45.0}],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert Decimal(str(data["engine_hours"])) == Decimal("120.5")
        visit_id = data["id"]

        rows = await _hours_rows(db_session, vin)
        assert len(rows) == 1
        row = rows[0]
        assert row.engine_hours == Decimal("120.5")
        assert row.source == "service_visit"
        assert row.service_visit_id == visit_id
        assert row.fuel_record_id is None
        assert row.date == date(2026, 3, 1)

        # Odometer auto-sync still fires (distance regression).
        odo = (
            await db_session.execute(select(OdometerRecord).where(OdometerRecord.vin == vin))
        ).scalar_one()
        assert odo.odometer_km == Decimal("1000.00")

    async def test_update_moves_the_same_hours_row(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "SVCHOURS000000002"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        created = (
            await client.post(
                f"/api/vehicles/{vin}/service-visits",
                json={
                    "date": "2026-03-01",
                    "odometer_km": 1000.0,
                    "engine_hours": 100.0,
                    "line_items": [{"description": "Oil change", "cost": 45.0}],
                },
                headers=auth_headers,
            )
        ).json()
        visit_id = created["id"]

        resp = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit_id}",
            json={"engine_hours": 155.5},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        rows = await _hours_rows(db_session, vin)
        assert len(rows) == 1, "the reading moved on the SAME row, not a duplicate"
        assert rows[0].engine_hours == Decimal("155.5")
        assert rows[0].service_visit_id == visit_id

    async def test_update_clearing_hours_deletes_the_row(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "SVCHOURS000000003"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        created = (
            await client.post(
                f"/api/vehicles/{vin}/service-visits",
                json={
                    "date": "2026-03-01",
                    "odometer_km": 1000.0,
                    "engine_hours": 100.0,
                    "line_items": [{"description": "Oil change", "cost": 45.0}],
                },
                headers=auth_headers,
            )
        ).json()
        visit_id = created["id"]
        assert len(await _hours_rows(db_session, vin)) == 1

        resp = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit_id}",
            json={"engine_hours": None},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        assert await _hours_rows(db_session, vin) == []

    async def test_pure_distance_visit_creates_no_hours_row(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "SVCHOURS000000004"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        resp = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-03-01",
                "odometer_km": 1000.0,
                "line_items": [{"description": "Oil change", "cost": 45.0}],
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

        assert await _hours_rows(db_session, vin) == []
        # Odometer still synced -- the distance path is untouched.
        odo = (
            await db_session.execute(select(OdometerRecord).where(OdometerRecord.vin == vin))
        ).scalar_one()
        assert odo.odometer_km == Decimal("1000.00")


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceVisitDeleteCleansUpSyncedRecords:
    """Phase 4b: delete_service_visit cleans up what it auto-synced, never a manual row."""

    async def test_delete_removes_synced_odometer_and_hours_but_spares_manual_rows(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        vin = "SVCHOURS000000005"
        await _make_vehicle(db_session, int(test_user["id"]), vin)
        visit_date = date(2026, 3, 5)

        created = (
            await client.post(
                f"/api/vehicles/{vin}/service-visits",
                json={
                    "date": visit_date.isoformat(),
                    "odometer_km": 2000.0,
                    "engine_hours": 200.0,
                    "line_items": [{"description": "Oil change", "cost": 45.0}],
                },
                headers=auth_headers,
            )
        ).json()
        visit_id = created["id"]

        # The synced odometer row for this visit.
        synced_odo = (
            await db_session.execute(
                select(OdometerRecord).where(
                    OdometerRecord.vin == vin, OdometerRecord.date == visit_date
                )
            )
        ).scalar_one()
        assert synced_odo.notes == f"[AUTO-SYNC from service_visit #{visit_id}]"
        synced_odo_id = synced_odo.id

        # A manual odometer row sharing the EXACT same (vin, date) as the
        # synced row -- must survive the marker guard even under a direct
        # (vin, date) collision (deliberately constructed to prove the
        # guard matches on the marker, not just (vin, date)).
        db_session.add(
            OdometerRecord(
                vin=vin,
                date=visit_date,
                odometer_km=Decimal("1999.00"),
                notes="Manual reading from dash photo",
                source="manual",
            )
        )
        # A manual odometer row at an unrelated date -- never a candidate.
        db_session.add(
            OdometerRecord(
                vin=vin,
                date=date(2026, 1, 1),
                odometer_km=Decimal("500.00"),
                notes="Manual reading, unrelated date",
                source="manual",
            )
        )
        # A manual hours row at the same (vin, date) -- not linked by source
        # identity, so it must never be touched either.
        db_session.add(
            HoursRecord(
                vin=vin,
                date=visit_date,
                engine_hours=Decimal("999.9"),
                notes="Manual reading from dash photo",
                source="manual",
            )
        )
        await db_session.commit()

        assert len(await _hours_rows(db_session, vin)) == 2  # synced + manual
        assert len(await _odometer_rows(db_session, vin)) == 3  # synced + 2 manual

        resp = await client.delete(
            f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=auth_headers
        )
        assert resp.status_code == 204, resp.text

        # The synced odometer row is gone.
        remaining_odo = await _odometer_rows(db_session, vin)
        assert synced_odo_id not in {r.id for r in remaining_odo}
        # Both manual odometer rows survive.
        assert len(remaining_odo) == 2
        assert {r.notes for r in remaining_odo} == {
            "Manual reading from dash photo",
            "Manual reading, unrelated date",
        }

        # The synced hours row is gone (via FK cascade and/or
        # remove_synced_hours); the manual hours row survives.
        remaining_hours = await _hours_rows(db_session, vin)
        assert len(remaining_hours) == 1
        assert remaining_hours[0].source == "manual"
        assert remaining_hours[0].service_visit_id is None

    async def test_delete_after_date_edit_removes_synced_odometer_row_at_old_date(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        """A date edit MOVES the visit's synced row (issue #171), and delete
        cleans by marker alone, without a date predicate.

        Pre-#171 the sync matched on (vin, date), so a date edit left the
        old-date row behind and created a second one; this test used to pin
        that duplication to prove delete cleaned BOTH. The duplication is
        fixed, but the marker-only delete still matters for rows the buggy
        era left in the wild (migration 106 repairs stocks, this guards the
        path), so a legacy duplicate is seeded directly."""
        vin = "SVCHOURS000000007"
        await _make_vehicle(db_session, int(test_user["id"]), vin)
        old_date = date(2026, 3, 5)
        new_date = date(2026, 4, 10)

        created = (
            await client.post(
                f"/api/vehicles/{vin}/service-visits",
                json={
                    "date": old_date.isoformat(),
                    "odometer_km": 3000.0,
                    "line_items": [{"description": "Oil change", "cost": 45.0}],
                },
                headers=auth_headers,
            )
        ).json()
        visit_id = created["id"]
        marker = f"[AUTO-SYNC from service_visit #{visit_id}]"

        # Synced row lands at the ORIGINAL date.
        old_odo = (
            await db_session.execute(
                select(OdometerRecord).where(
                    OdometerRecord.vin == vin, OdometerRecord.date == old_date
                )
            )
        ).scalar_one()
        assert old_odo.notes == marker

        # A manual odometer row at an unrelated date -- never a candidate,
        # must survive the eventual delete.
        db_session.add(
            OdometerRecord(
                vin=vin,
                date=date(2026, 1, 1),
                odometer_km=Decimal("111.00"),
                notes="Manual reading, unrelated date",
                source="manual",
            )
        )
        await db_session.commit()

        # A legacy duplicate from the pre-#171 era: same marker, stranded on
        # an in-between date, as the (vin, date) lookup used to leave behind.
        db_session.add(
            OdometerRecord(
                vin=vin,
                date=date(2026, 3, 20),
                odometer_km=Decimal("3000.00"),
                notes=marker,
                source="service_visit",
            )
        )
        await db_session.commit()

        # Edit only the visit's date: the synced row MOVES (issue #171), and
        # the sync's self-heal drops the stranded legacy duplicate.
        resp = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit_id}",
            json={"date": new_date.isoformat()},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        synced_after_edit = {
            r.date for r in await _odometer_rows(db_session, vin) if r.notes == marker
        }
        assert synced_after_edit == {new_date}, (
            "a date edit must move the visit's one synced row to the new date "
            "and clean up any stranded duplicate"
        )

        resp = await client.delete(
            f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=auth_headers
        )
        assert resp.status_code == 204, resp.text

        remaining = await _odometer_rows(db_session, vin)
        # The synced row is gone wherever it sat -- delete filters on the
        # marker with no date predicate, so a row a pre-fix edit stranded on
        # another date would be caught too.
        assert all(r.notes != marker for r in remaining)
        # The unrelated manual row survives.
        assert len(remaining) == 1
        assert remaining[0].notes == "Manual reading, unrelated date"

    async def test_delete_visit_with_no_synced_odometer_leaves_manual_rows_alone(
        self, client: AsyncClient, auth_headers, test_user, db_session: AsyncSession
    ) -> None:
        """A visit with no odometer_km never synced a row -- delete must be a no-op
        against any manual odometer rows for the vehicle."""
        vin = "SVCHOURS000000006"
        await _make_vehicle(db_session, int(test_user["id"]), vin)

        db_session.add(
            OdometerRecord(
                vin=vin,
                date=date(2026, 2, 1),
                odometer_km=Decimal("42.00"),
                notes="Manual reading, created independently",
                source="manual",
            )
        )
        await db_session.commit()

        created = (
            await client.post(
                f"/api/vehicles/{vin}/service-visits",
                json={
                    "date": "2026-02-15",
                    "line_items": [{"description": "Inspection", "cost": 0}],
                },
                headers=auth_headers,
            )
        ).json()
        visit_id = created["id"]

        resp = await client.delete(
            f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=auth_headers
        )
        assert resp.status_code == 204, resp.text

        remaining = await _odometer_rows(db_session, vin)
        assert len(remaining) == 1
        assert remaining[0].source == "manual"
