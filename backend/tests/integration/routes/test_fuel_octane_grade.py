"""Octane + diesel grade on fuel records (#164, plan 2026-09-18 feature C).

Two per-fillup fields: ``octane`` (int, gasoline/E85 — AKI or RON, so the
band is 50-150) and ``diesel_grade`` ('onroad' | 'offroad', the US
clear-vs-dyed distinction). Both nullable, validated on the INPUT schemas
only (FuelRecordBase stays tolerant, the schemas/fuel.py convention), and
the import paths run the same validators because they construct ORM rows
directly and bypass Pydantic (codex R1-M2).
"""

from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.fuel import FuelRecord
from app.models.settings import Setting

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _create(
    client: AsyncClient, headers: dict, vin: str, *, odometer_km: float, **extra
) -> dict:
    payload = {
        "vin": vin,
        "date": "2026-05-01",
        "liters": 40.0,
        "cost": 45.00,
        "odometer_km": odometer_km,
        "is_full_tank": True,
        **extra,
    }
    r = await client.post(f"/api/vehicles/{vin}/fuel", headers=headers, json=payload)
    return r


class TestOctaneGradeApi:
    async def test_create_returns_and_persists_both_fields(
        self, client, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        r = await _create(
            client, auth_headers, vin, odometer_km=200100, octane=91, diesel_grade="offroad"
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["octane"] == 91
        assert body["diesel_grade"] == "offroad"

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        mine = [x for x in r.json()["records"] if x["id"] == body["id"]]
        assert mine and mine[0]["octane"] == 91 and mine[0]["diesel_grade"] == "offroad"

    async def test_update_sets_and_null_clears(self, client, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        record = (await _create(client, auth_headers, vin, odometer_km=200200, octane=87)).json()

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            headers=auth_headers,
            json={"octane": 93, "diesel_grade": "onroad"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["octane"] == 93
        assert r.json()["diesel_grade"] == "onroad"

        # Issue-#108 convention: an explicit null clears, absent leaves alone.
        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            headers=auth_headers,
            json={"octane": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["octane"] is None
        assert r.json()["diesel_grade"] == "onroad"

    async def test_out_of_range_octane_and_bogus_grade_422(
        self, client, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        for bad in ({"octane": 49}, {"octane": 151}, {"diesel_grade": "red"}):
            r = await _create(client, auth_headers, vin, odometer_km=200300, **bad)
            assert r.status_code == 422, (bad, r.text)

        record = (await _create(client, auth_headers, vin, odometer_km=200301)).json()
        for bad in ({"octane": 893}, {"diesel_grade": "farm"}):
            r = await client.put(
                f"/api/vehicles/{vin}/fuel/{record['id']}", headers=auth_headers, json=bad
            )
            assert r.status_code == 422, (bad, r.text)


class TestFuelGradeApi:
    """#211 — `fuel_grade`, the EN 16942 pump label (E5, E10, B7, XTL…)."""

    async def test_create_round_trips_and_normalises_case(self, client, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        r = await _create(client, auth_headers, vin, odometer_km=210100, fuel_grade="E10")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["fuel_grade"] == "E10"

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        mine = [x for x in r.json()["records"] if x["id"] == body["id"]]
        assert mine and mine[0]["fuel_grade"] == "E10"

        # Lowercase and surrounding whitespace are tolerated and stored upper.
        r = await _create(client, auth_headers, vin, odometer_km=210150, fuel_grade=" xtl ")
        assert r.status_code == 201, r.text
        assert r.json()["fuel_grade"] == "XTL"

    async def test_update_sets_and_null_clears(self, client, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        record = (await _create(client, auth_headers, vin, odometer_km=210200)).json()
        assert record["fuel_grade"] is None

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            headers=auth_headers,
            json={"fuel_grade": "b7"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["fuel_grade"] == "B7"

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            headers=auth_headers,
            json={"fuel_grade": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["fuel_grade"] is None

    async def test_unknown_label_422(self, client, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        for bad in ("E95", "SP98", "diesel"):
            r = await _create(client, auth_headers, vin, odometer_km=210300, fuel_grade=bad)
            assert r.status_code == 422, (bad, r.text)

        record = (await _create(client, auth_headers, vin, odometer_km=210301)).json()
        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            headers=auth_headers,
            json={"fuel_grade": "E95"},
        )
        assert r.status_code == 422, r.text

    async def test_webhook_carries_and_validates_fuel_grade(
        self, client, auth_headers, test_vehicle, db_session
    ):
        key = "webhook_ingest_token"
        existing = await db_session.scalar(select(Setting).where(Setting.key == key))
        if existing is None:
            db_session.add(Setting(key=key, value="grade-hook"))
        else:
            existing.value = "grade-hook"
        await db_session.commit()
        try:
            vin = test_vehicle["vin"]
            r = await client.post(
                "/api/v1/webhooks/fuel",
                json={"vin": vin, "date": "2026-05-06", "liters": "38", "fuel_grade": "e10"},
                headers={"X-Webhook-Token": "grade-hook"},
            )
            assert r.status_code == 200, r.text
            row = await db_session.scalar(select(FuelRecord).where(FuelRecord.id == r.json()["id"]))
            assert row is not None and row.fuel_grade == "E10"

            r = await client.post(
                "/api/v1/webhooks/fuel",
                json={"vin": vin, "liters": "38", "fuel_grade": "E95"},
                headers={"X-Webhook-Token": "grade-hook"},
            )
            assert r.status_code == 422, r.text
        finally:
            existing = await db_session.scalar(select(Setting).where(Setting.key == key))
            if existing is not None:
                existing.value = ""
                await db_session.commit()

    async def test_csv_round_trip_and_unknown_label_fails_its_row(
        self, client, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        created = (
            await _create(client, auth_headers, vin, odometer_km=210400, fuel_grade="E10")
        ).json()

        r = await client.get(f"/api/export/vehicles/{vin}/fuel/csv", headers=auth_headers)
        assert r.status_code == 200, r.text
        text = r.text
        header = text.splitlines()[0].split(",")
        assert header.index("Fuel Grade") == header.index("Diesel Grade") + 1

        r = await client.delete(f"/api/vehicles/{vin}/fuel/{created['id']}", headers=auth_headers)
        assert r.status_code in (200, 204), r.text
        r = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(text.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["error_count"] == 0
        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        mine = [x for x in r.json()["records"] if x["odometer_km"] == "210400.00"]
        assert mine and mine[0]["fuel_grade"] == "E10"

        # The import path builds ORM rows directly, so the validator must run
        # there too: a bad label fails its row alone, an empty cell is NULL.
        csv_content = (
            "Date,Odometer (km),Liters,Price Per Liter,Total Cost,Full Tank,Fuel Grade\n"
            "2026-05-07,210500,41.0,1.50,61.50,True,E95\n"
            "2026-05-08,210600,41.0,1.50,61.50,True,\n"
            "2026-05-09,210700,41.0,1.50,61.50,True,b10\n"
        )
        r = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(csv_content.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["error_count"] == 1, body
        assert body["success_count"] == 2, body
        records = (await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)).json()[
            "records"
        ]
        assert not [x for x in records if x["date"] == "2026-05-07"]
        assert [x["fuel_grade"] for x in records if x["date"] == "2026-05-08"] == [None]
        assert [x["fuel_grade"] for x in records if x["date"] == "2026-05-09"] == ["B10"]

    async def test_json_round_trip(self, client, auth_headers, test_vehicle):
        import json as jsonlib

        vin = test_vehicle["vin"]
        created = (
            await _create(client, auth_headers, vin, odometer_km=210800, fuel_grade="LPG")
        ).json()
        backup = (await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)).json()
        mine = [x for x in backup["fuel_records"] if x.get("odometer_km") == 210800.0]
        assert mine and mine[0]["fuel_grade"] == "LPG"

        r = await client.delete(f"/api/vehicles/{vin}/fuel/{created['id']}", headers=auth_headers)
        assert r.status_code in (200, 204), r.text
        r = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={
                "file": ("backup.json", BytesIO(jsonlib.dumps(backup).encode()), "application/json")
            },
        )
        assert r.status_code == 200, r.text
        records = (await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)).json()[
            "records"
        ]
        mine = [x for x in records if x["odometer_km"] == "210800.00"]
        assert mine and mine[0]["fuel_grade"] == "LPG"


class TestOctaneGradeWebhook:
    async def test_webhook_carries_and_validates_both_fields(
        self, client, auth_headers, test_vehicle, db_session
    ):
        key = "webhook_ingest_token"
        existing = await db_session.scalar(select(Setting).where(Setting.key == key))
        if existing is None:
            db_session.add(Setting(key=key, value="octane-hook"))
        else:
            existing.value = "octane-hook"
        await db_session.commit()
        try:
            vin = test_vehicle["vin"]
            r = await client.post(
                "/api/v1/webhooks/fuel",
                json={
                    "vin": vin,
                    "date": "2026-05-02",
                    "odometer_km": "200400",
                    "liters": "38",
                    "octane": 89,
                    "diesel_grade": "onroad",
                },
                headers={"X-Webhook-Token": "octane-hook"},
            )
            assert r.status_code == 200, r.text
            record_id = r.json()["id"]
            row = await db_session.scalar(select(FuelRecord).where(FuelRecord.id == record_id))
            assert row is not None and row.octane == 89 and row.diesel_grade == "onroad"

            r = await client.post(
                "/api/v1/webhooks/fuel",
                json={"vin": vin, "liters": "38", "octane": 999},
                headers={"X-Webhook-Token": "octane-hook"},
            )
            assert r.status_code == 422, r.text
        finally:
            existing = await db_session.scalar(select(Setting).where(Setting.key == key))
            if existing is not None:
                existing.value = ""
                await db_session.commit()


class TestOctaneGradeRoundTrip:
    async def test_csv_export_import_round_trip(self, client, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        created = (
            await _create(
                client,
                auth_headers,
                vin,
                odometer_km=200500,
                octane=93,
                diesel_grade="offroad",
            )
        ).json()

        r = await client.get(f"/api/export/vehicles/{vin}/fuel/csv", headers=auth_headers)
        assert r.status_code == 200, r.text
        text = r.text
        header = text.splitlines()[0]
        assert "Octane" in header and "Diesel Grade" in header

        # Import the exported CSV back (skip_duplicates default skips the
        # original; import into the same vehicle with dedup off would double
        # rows, so re-import WITH duplicates skipped and assert the fields on
        # a fresh parse instead: delete the original first).
        r = await client.delete(f"/api/vehicles/{vin}/fuel/{created['id']}", headers=auth_headers)
        assert r.status_code in (200, 204), r.text

        r = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(text.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["error_count"] == 0

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        mine = [x for x in r.json()["records"] if x["date"] == "2026-05-01"]
        assert mine, r.json()
        assert any(x["octane"] == 93 and x["diesel_grade"] == "offroad" for x in mine)

    async def test_csv_import_of_an_old_file_without_the_columns_is_null(
        self, client, auth_headers, test_vehicle
    ):
        vin = test_vehicle["vin"]
        csv_content = (
            "Date,Odometer (km),Liters,Price Per Liter,Total Cost,Full Tank\n"
            "2026-05-03,200600,41.0,1.50,61.50,True\n"
        )
        r = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(csv_content.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["success_count"] == 1

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        mine = [x for x in r.json()["records"] if x["date"] == "2026-05-03"]
        assert mine and mine[0]["octane"] is None and mine[0]["diesel_grade"] is None

    async def test_csv_import_rejects_an_invalid_octane_row_alone(
        self, client, auth_headers, test_vehicle
    ):
        """R1-M2: the import path constructs ORM rows directly, so the shared
        validators must run there too — a fat-fingered 893 fails that ROW
        through the per-row error mechanism, never silently persisted."""
        vin = test_vehicle["vin"]
        csv_content = (
            "Date,Odometer (km),Liters,Price Per Liter,Total Cost,Full Tank,Octane,Diesel Grade\n"
            "2026-05-04,200700,41.0,1.50,61.50,True,893,\n"
            "2026-05-05,200800,41.0,1.50,61.50,True,91,onroad\n"
        )
        r = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(csv_content.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["error_count"] == 1, body
        assert body["success_count"] == 1, body

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        records = r.json()["records"]
        assert not [x for x in records if x["date"] == "2026-05-04"]
        good = [x for x in records if x["date"] == "2026-05-05"]
        assert good and good[0]["octane"] == 91 and good[0]["diesel_grade"] == "onroad"

    async def test_json_export_import_round_trip(self, client, auth_headers, test_vehicle):
        vin = test_vehicle["vin"]
        created = (
            await _create(
                client,
                auth_headers,
                vin,
                odometer_km=200900,
                octane=87,
                diesel_grade="onroad",
                fuel_type_used="gasoline",
                is_hauling=True,
            )
        ).json()

        r = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
        assert r.status_code == 200, r.text
        backup = r.json()
        mine = [x for x in backup["fuel_records"] if x.get("odometer_km") == 200900.0]
        assert mine and mine[0]["octane"] == 87 and mine[0]["diesel_grade"] == "onroad"

        r = await client.delete(f"/api/vehicles/{vin}/fuel/{created['id']}", headers=auth_headers)
        assert r.status_code in (200, 204), r.text

        import json as jsonlib

        r = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={
                "file": ("backup.json", BytesIO(jsonlib.dumps(backup).encode()), "application/json")
            },
        )
        assert r.status_code == 200, r.text

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        mine = [x for x in r.json()["records"] if x["odometer_km"] == "200900.00"]
        assert mine, r.json()
        assert mine[0]["octane"] == 87 and mine[0]["diesel_grade"] == "onroad"
        # Pins the adjacent fix: the JSON export always wrote these two but
        # the import constructor silently dropped them until this change.
        assert mine[0]["fuel_type_used"] == "gasoline"
        assert mine[0]["is_hauling"] is True


class TestJsonOctaneCoercion:
    async def test_a_fractional_octane_fails_its_row_instead_of_truncating(
        self, client, auth_headers, test_vehicle
    ):
        """Codex code review R1-M1: a bare int() stored 91.9 as 91 and let
        150.9 sneak under the API's 150 bound. A fractional octane must fail
        that row like any other bad field, never persist rounded."""
        import json as jsonlib

        vin = test_vehicle["vin"]
        backup = {
            "fuel_records": [
                {"date": "2026-05-10", "odometer_km": 201000.0, "liters": 40.0, "octane": 91.9},
                {"date": "2026-05-11", "odometer_km": 201100.0, "liters": 40.0, "octane": 150.9},
                {"date": "2026-05-12", "odometer_km": 201200.0, "liters": 40.0, "octane": 91.0},
            ]
        }
        r = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={
                "file": ("backup.json", BytesIO(jsonlib.dumps(backup).encode()), "application/json")
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fuel_records"]["errors"] == 2, body
        assert body["fuel_records"]["success"] == 1, body

        r = await client.get(f"/api/vehicles/{vin}/fuel", headers=auth_headers)
        records = r.json()["records"]
        assert not [x for x in records if x["date"] in ("2026-05-10", "2026-05-11")]
        # An integral float is fine: 91.0 is 91, not a truncation.
        good = [x for x in records if x["date"] == "2026-05-12"]
        assert good and good[0]["octane"] == 91
