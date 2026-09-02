"""One bad row must not take the whole import down with it.

Each importer wraps its row in `try/except Exception` and records a per-row
error, but the `db.commit()` that actually writes is OUTSIDE that loop. So a
constraint violation is not raised where the handler can see it: it surfaces at
commit, escapes the route, and returns **500** -- discarding every valid row in
the file along with the bad one.

Nobody hit this before v3.3.0 for warranty, insurance or tax, because those
constructors raised `TypeError` on nonexistent kwargs first and every row failed
early inside the try. Fixing the kwargs let rows reach the database for the
first time, and exposed the real error path underneath.

A savepoint per row puts the write back inside the handler, so a row that
violates a CHECK is one reported row and the rest of the file still imports.
"""

from io import BytesIO

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestOneBadRowDoesNotFailTheFile:
    async def test_an_invalid_warranty_type_is_a_row_error_not_a_500(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """`Roadside` is not in the `check_warranty_type` vocabulary.

        The good row above it must still import.
        """
        csv_content = (
            "Provider,Type,Coverage Details,Start Date,End Date,Notes\n"
            "Good Co,Extended,covered,2024-01-01,2029-01-01,fine\n"
            "Bad Co,Roadside,covered,2024-01-01,2025-01-01,bad type\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/warranties/csv",
            headers=auth_headers,
            files={"file": ("w.csv", BytesIO(csv_content.encode()), "text/csv")},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success_count"] == 1, data
        assert data["error_count"] == 1, data
        assert any("3" in e for e in data["errors"]), data["errors"]

    async def test_an_invalid_policy_type_is_a_row_error_not_a_500(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        csv_content = (
            "Provider,Policy Number,Type,Start Date,End Date,Premium,Premium Frequency,"
            "Deductible,Coverage Limits,Notes\n"
            "Good,P1,Liability,2026-01-01,2027-01-01,10.00,Monthly,100.00,100/300,ok\n"
            "Bad,P2,Spaceship,2026-01-01,2027-01-01,10.00,Monthly,100.00,100/300,bad\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/insurance/csv",
            headers=auth_headers,
            files={"file": ("i.csv", BytesIO(csv_content.encode()), "text/csv")},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success_count"] == 1, data
        assert data["error_count"] == 1, data

    async def test_a_valid_file_still_imports_every_row(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Guards the guard: a savepoint that always rolled back would pass
        both tests above while importing nothing."""
        csv_content = (
            "Provider,Type,Coverage Details,Start Date,End Date,Notes\n"
            "Alpha,Extended,a,2024-02-01,2029-02-01,x\n"
            "Beta,Corrosion,b,2024-03-01,2029-03-01,y\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/warranties/csv",
            headers=auth_headers,
            files={"file": ("w.csv", BytesIO(csv_content.encode()), "text/csv")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success_count"] == 2, data
        assert data["error_count"] == 0, data
