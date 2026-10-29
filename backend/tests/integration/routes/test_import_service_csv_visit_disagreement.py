"""A v8 service CSV whose rows of one Visit disagree is refused, not guessed (batch 3b task 12, K8)."""

from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceVisit, Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_V8_HEADER = (
    "units_version,unit_system,Visit,Date,Category,Description,Odometer (km),Engine Hours,"
    "Cost,Vendor,Item Notes,Tax,Shop Supplies,Misc Fees,Insurance Claim,Visit Notes"
)

# The visit-level cells in header order, as a v8 export repeats them on every row.
_VISIT = {
    "Date": "2026-05-01",
    "Category": "Maintenance",
    "Odometer (km)": "1000.00",
    "Engine Hours": "12.5",
    "Vendor": "B3B Disagree Shop",
    "Tax": "5.00",
    "Shop Supplies": "2.00",
    "Misc Fees": "1.00",
    "Insurance Claim": "CLM-1",
    "Visit Notes": "Spring service",
}

# One changed cell per field, and the column name the error uses for it.
_CHANGED = [
    ("Date", "2026-05-02", "Date"),
    ("Category", "Repair", "Category"),
    ("Odometer (km)", "1001.00", "Odometer"),
    ("Engine Hours", "12.6", "Engine Hours"),
    ("Vendor", "Another Shop", "Vendor"),
    ("Tax", "6.00", "Tax"),
    ("Shop Supplies", "3.00", "Shop Supplies"),
    ("Misc Fees", "1.50", "Misc Fees"),
    ("Insurance Claim", "CLM-2", "Insurance Claim"),
    ("Visit Notes", "Autumn service", "Visit Notes"),
]


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Disagree",
        )
    )
    await db_session.commit()
    return vin


def _row(visit: str, description: str, cost: str, **visit_cells: str) -> str:
    cells = {**_VISIT, **visit_cells}
    return ",".join(
        [
            "8",
            "metric",
            visit,
            cells["Date"],
            cells["Category"],
            description,
            cells["Odometer (km)"],
            cells["Engine Hours"],
            cost,
            cells["Vendor"],
            "",
            cells["Tax"],
            cells["Shop Supplies"],
            cells["Misc Fees"],
            cells["Insurance Claim"],
            cells["Visit Notes"],
        ]
    )


async def _post_csv(client: AsyncClient, headers: dict, vin: str, body: str) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/service/csv",
        headers=headers,
        files={"file": ("service.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _visit_dates(sessionmaker: Any, vin: str) -> list[str]:
    async with sessionmaker() as fresh:
        result = await fresh.execute(
            select(ServiceVisit.date).where(ServiceVisit.vin == vin).order_by(ServiceVisit.id)
        )
        return [d.isoformat() for d in result.scalars().all()]


@pytest.mark.parametrize(("cell", "value", "column"), _CHANGED, ids=[c[2] for c in _CHANGED])
async def test_rows_of_one_visit_that_disagree_refuse_the_visit(
    cell: str,
    value: str,
    column: str,
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
):
    vin = await _vehicle(
        db_session, test_user["id"], f"B3BSVCDIS{_CHANGED.index((cell, value, column)):08d}"
    )
    body = "\n".join(
        [
            _V8_HEADER,
            _row("1", "Oil change", "40.00"),
            _row("1", "Filters", "20.00", **{cell: value}),
            # Another visit in the same file still imports.
            _row("2", "Wipers", "15.00", Date="2026-06-01"),
        ]
    )
    data = await _post_csv(client, auth_headers, vin, body + "\n")

    # main: the first row wins, so 3 imported and no error
    reason = f"Visit 1: rows 3 and 2 disagree on {column}"
    assert data["errors"] == [f"Row 2: {reason}", f"Row 3: {reason}"], data
    assert (data["success_count"], data["error_count"], data["skipped_count"]) == (1, 2, 0)
    assert await _visit_dates(test_sessionmaker, vin) == ["2026-06-01"]


async def test_a_later_row_that_disagrees_refuses_the_visit_too(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Every row gets held to the first, not just the second one."""
    vin = await _vehicle(db_session, test_user["id"], "B3BSVCDISAGREE02")
    body = "\n".join(
        [
            _V8_HEADER,
            _row("1", "Oil change", "40.00"),
            _row("1", "Filters", "20.00"),
            _row("1", "Wipers", "15.00", Vendor="Another Shop"),
        ]
    )
    data = await _post_csv(client, auth_headers, vin, body + "\n")

    reason = "Visit 1: rows 4 and 2 disagree on Vendor"
    assert data["errors"] == [f"Row {n}: {reason}" for n in (2, 3, 4)], data
    assert (data["success_count"], data["error_count"]) == (0, 3)
    assert await _visit_dates(test_sessionmaker, vin) == []


async def test_the_same_figure_written_two_ways_still_agrees(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Guard (passes on main): figures compare as numbers, so 1000 and 1000.00 are one odometer.

    It kills a check that compares the raw cells as strings, which would refuse
    every hand-typed 1000 next to an exported 1000.00.
    """
    vin = await _vehicle(db_session, test_user["id"], "B3BSVCDISAGREE01")
    body = "\n".join(
        [
            _V8_HEADER,
            _row("1", "Oil change", "40.00"),
            _row("1", "Filters", "20.00", **{"Odometer (km)": "1000", "Tax": "5"}),
        ]
    )
    data = await _post_csv(client, auth_headers, vin, body + "\n")

    assert data["errors"] == [], data
    assert data["success_count"] == 2, data
    assert await _visit_dates(test_sessionmaker, vin) == ["2026-05-01"]
