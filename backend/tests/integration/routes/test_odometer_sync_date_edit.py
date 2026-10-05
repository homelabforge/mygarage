"""Issue #171: editing a source record's date must MOVE its auto-synced
odometer row, not orphan it and insert a second one.

`sync_odometer_from_record` used to look the source's own row up by
`(vin, NEW date)` only, so after a date edit the old-date row was never
found: the edit left it in place, inserted a duplicate on the new date,
and, when the new date already held another source's auto-synced row,
claimed that row instead (rewriting its marker and `fuel_record_id`, so
deleting the edited record cascade-deleted the hijacked row too).

Every test here was observed red on the pre-fix code.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _odometer_rows(client: AsyncClient, headers: dict, vin: str) -> list[dict]:
    r = await client.get(f"/api/vehicles/{vin}/odometer?limit=500", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["records"]


def _auto_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("notes") and "[AUTO-SYNC from" in r["notes"]]


def _marked(rows: list[dict], source_type: str, source_id: int) -> list[dict]:
    marker = f"[AUTO-SYNC from {source_type} #{source_id}]"
    return [r for r in rows if r.get("notes") == marker]


async def _fuel(
    client: AsyncClient, headers: dict, vin: str, *, on: str, odometer_km: float
) -> dict:
    r = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json={
            "vin": vin,
            "date": on,
            "liters": 40.0,
            "cost": 45.00,
            "odometer_km": odometer_km,
            "is_full_tank": True,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def sync_test_vehicle(client: AsyncClient, auth_headers) -> AsyncGenerator[dict]:
    vin = "SYN171XEDT0000001"
    await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)
    r = await client.post(
        "/api/vehicles",
        json={
            "vin": vin,
            "nickname": "sync-171",
            "vehicle_type": "Car",
            "fuel_type": "Gasoline",
            "year": 2018,
            "make": "Honda",
            "model": "Accord",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    vehicle = r.json()
    try:
        yield vehicle
    finally:
        await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)


class TestFuelDateEdit:
    async def test_editing_the_date_moves_the_synced_row(
        self, client: AsyncClient, auth_headers, sync_test_vehicle
    ):
        """The report's exact reproduction: 08-06 -> 08-03, one row, moved."""
        vin = sync_test_vehicle["vin"]
        record = await _fuel(client, auth_headers, vin, on="2026-08-06", odometer_km=166111)

        rows = _marked(await _odometer_rows(client, auth_headers, vin), "fuel", record["id"])
        assert len(rows) == 1 and rows[0]["date"] == "2026-08-06"

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            json={"date": "2026-08-03"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = _marked(await _odometer_rows(client, auth_headers, vin), "fuel", record["id"])
        assert len(rows) == 1, rows
        assert rows[0]["date"] == "2026-08-03"
        assert float(rows[0]["odometer_km"]) == 166111

    async def test_moving_onto_an_occupied_date_does_not_hijack_the_residents_row(
        self, client: AsyncClient, auth_headers, sync_test_vehicle
    ):
        """The report's side effect: the 08-03 fill-up must keep its reading."""
        vin = sync_test_vehicle["vin"]
        resident = await _fuel(client, auth_headers, vin, on="2026-08-03", odometer_km=166059)
        mover = await _fuel(client, auth_headers, vin, on="2026-08-06", odometer_km=166111)

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{mover['id']}",
            json={"date": "2026-08-03"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = await _odometer_rows(client, auth_headers, vin)
        resident_rows = _marked(rows, "fuel", resident["id"])
        assert len(resident_rows) == 1, rows
        assert resident_rows[0]["date"] == "2026-08-03"
        assert float(resident_rows[0]["odometer_km"]) == 166059
        mover_rows = _marked(rows, "fuel", mover["id"])
        assert len(mover_rows) == 1, rows
        assert mover_rows[0]["date"] == "2026-08-03"
        assert float(mover_rows[0]["odometer_km"]) == 166111

        # Deleting the edited record takes ONLY its own row with it.
        r = await client.delete(f"/api/vehicles/{vin}/fuel/{mover['id']}", headers=auth_headers)
        assert r.status_code in (200, 204), r.text
        rows = await _odometer_rows(client, auth_headers, vin)
        assert len(_marked(rows, "fuel", resident["id"])) == 1, rows
        assert _marked(rows, "fuel", mover["id"]) == [], rows

    async def test_an_update_after_losing_its_row_never_claims_a_third_records(
        self, client: AsyncClient, auth_headers, sync_test_vehicle
    ):
        """R1-H1: ownership loss is a designed same-day outcome.

        B's same-day create claims A's row (the one-reading-per-day policy
        for automatic rows). A's own marker row then no longer exists, so
        a later edit of A must CREATE a fresh row, never claim whatever
        automatic row happens to live on the destination date (here C's).
        """
        vin = sync_test_vehicle["vin"]
        rec_a = await _fuel(client, auth_headers, vin, on="2026-08-03", odometer_km=1000)
        await _fuel(client, auth_headers, vin, on="2026-08-03", odometer_km=1010)
        rec_c = await _fuel(client, auth_headers, vin, on="2026-08-10", odometer_km=2000)

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{rec_a['id']}",
            json={"date": "2026-08-10"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = await _odometer_rows(client, auth_headers, vin)
        c_rows = _marked(rows, "fuel", rec_c["id"])
        assert len(c_rows) == 1, rows
        assert float(c_rows[0]["odometer_km"]) == 2000
        a_rows = _marked(rows, "fuel", rec_a["id"])
        assert len(a_rows) == 1, rows
        assert a_rows[0]["date"] == "2026-08-10"
        assert float(a_rows[0]["odometer_km"]) == 1000

        r = await client.delete(f"/api/vehicles/{vin}/fuel/{rec_a['id']}", headers=auth_headers)
        assert r.status_code in (200, 204), r.text
        rows = await _odometer_rows(client, auth_headers, vin)
        assert len(_marked(rows, "fuel", rec_c["id"])) == 1, rows

    async def test_a_mileage_only_edit_still_updates_in_place(
        self, client: AsyncClient, auth_headers, sync_test_vehicle
    ):
        """Regression guard: the pre-fix same-day path already handled this."""
        vin = sync_test_vehicle["vin"]
        record = await _fuel(client, auth_headers, vin, on="2026-08-06", odometer_km=166111)
        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            json={"odometer_km": 166200},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        rows = _marked(await _odometer_rows(client, auth_headers, vin), "fuel", record["id"])
        assert len(rows) == 1, rows
        assert float(rows[0]["odometer_km"]) == 166200


class TestServiceVisitDateEdit:
    async def test_editing_the_date_moves_the_synced_row(
        self, client: AsyncClient, auth_headers, sync_test_vehicle
    ):
        vin = sync_test_vehicle["vin"]
        r = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-08-06",
                "odometer_km": 5000,
                "line_items": [{"description": "Air filter"}],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        visit = r.json()

        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            json={"date": "2026-08-03"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = _marked(
            await _odometer_rows(client, auth_headers, vin), "service_visit", visit["id"]
        )
        assert len(rows) == 1, rows
        assert rows[0]["date"] == "2026-08-03"


class TestLegacyServiceMarkerDateEdit:
    async def test_a_legacy_marked_row_moves_instead_of_duplicating(
        self, client: AsyncClient, auth_headers, sync_test_vehicle, db_session
    ):
        """Codex PR review P1: databases predating the service_visit marker
        rename hold rows marked ``[AUTO-SYNC from service #N]`` (the delete
        path still recognizes the alias). The ownership lookup must too, or
        a date edit misses the legacy row and re-creates the #171 duplicate
        for exactly the oldest data. The move also normalizes the note to
        the current marker."""
        from sqlalchemy import update

        from app.models.odometer import OdometerRecord

        vin = sync_test_vehicle["vin"]
        r = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-08-06",
                "odometer_km": 6100,
                "line_items": [{"description": "Cabin filter"}],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        visit = r.json()

        legacy = f"[AUTO-SYNC from service #{visit['id']}]"
        current = f"[AUTO-SYNC from service_visit #{visit['id']}]"
        await db_session.execute(
            update(OdometerRecord)
            .where(OdometerRecord.vin == vin)
            .where(OdometerRecord.notes == current)
            .values(notes=legacy)
        )
        await db_session.commit()

        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            json={"date": "2026-08-03"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = [
            row
            for row in await _odometer_rows(client, auth_headers, vin)
            if row.get("notes") in (legacy, current)
        ]
        assert len(rows) == 1, rows
        assert rows[0]["date"] == "2026-08-03"
        assert rows[0]["notes"] == current


class TestDefDateEdit:
    async def test_editing_the_date_moves_the_synced_row(self, client: AsyncClient, auth_headers):
        r = await client.post(
            "/api/vehicles",
            json={
                "vin": "DEF171XEDT0000001",
                "nickname": "def-171",
                "vehicle_type": "Truck",
                "fuel_type": "Diesel",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        vin = r.json()["vin"]
        try:
            r = await client.post(
                f"/api/vehicles/{vin}/def",
                json={"vin": vin, "date": "2026-08-06", "odometer_km": 5000},
                headers=auth_headers,
            )
            assert r.status_code == 201, r.text
            record = r.json()

            r = await client.put(
                f"/api/vehicles/{vin}/def/{record['id']}",
                json={"date": "2026-08-03"},
                headers=auth_headers,
            )
            assert r.status_code == 200, r.text

            rows = _marked(await _odometer_rows(client, auth_headers, vin), "def", record["id"])
            assert len(rows) == 1, rows
            assert rows[0]["date"] == "2026-08-03"
        finally:
            await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)


class TestTirePublishesKeepPerDateRows:
    async def test_backdated_tire_reading_leaves_earlier_published_rows_alone(
        self, client: AsyncClient, auth_headers
    ):
        """Codex R1-H1 (code review pass 1): tire markers are keyed by TIRE,
        not by reading — `[AUTO-SYNC from tire #N]` legitimately marks one
        odometer row per reading date. The vin-wide own-row lookup the #171
        fix introduced must therefore stay scoped to the one-row-per-source
        types (fuel, service_visit, def); applied to a tire publish it
        collapses the tire's whole history into the newest row and a
        backdated reading rewinds the vehicle's current mileage."""
        r = await client.post(
            "/api/vehicles",
            json={
                "vin": "TRE171XSYNC000001",
                "nickname": "tire-171",
                "vehicle_type": "Car",
                "fuel_type": "Gasoline",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        vin = r.json()["vin"]
        try:
            r = await client.post(
                f"/api/vehicles/{vin}/tires/create-and-mount",
                headers=auth_headers,
                json={
                    "vin": vin,
                    "position": "FR",
                    "brand": "Continental",
                    "tread_depth_mm": "7.0",
                    "min_tread_mm": "2.0",
                    "mounted_on": "2026-01-01",
                    "mounted_odometer_km": "10000",
                },
            )
            assert r.status_code == 201, r.text
            tire_id = r.json()["id"]

            for recorded_at, odo, tread in (
                ("2026-03-01", "12000", "6.0"),
                ("2026-06-01", "15000", "5.5"),
                # The backdated one: with the vin-wide lookup this MOVED the
                # 06-01 row to 04-15 and deleted the 03-01 row.
                ("2026-04-15", "13000", "5.8"),
            ):
                r = await client.post(
                    f"/api/vehicles/{vin}/tires/{tire_id}/readings",
                    headers=auth_headers,
                    json={
                        "recorded_at": recorded_at,
                        "odometer_km": odo,
                        "tread_depth_mm": tread,
                    },
                )
                assert r.status_code == 201, r.text

            rows = _marked(await _odometer_rows(client, auth_headers, vin), "tire", tire_id)
            by_date = {row["date"]: row["odometer_km"] for row in rows}
            assert by_date == {
                "2026-03-01": "12000.00",
                "2026-04-15": "13000.00",
                "2026-06-01": "15000.00",
            }, rows
        finally:
            r = await client.delete(f"/api/vehicles/{vin}", headers=auth_headers)
            assert r.status_code in (200, 204), r.text
