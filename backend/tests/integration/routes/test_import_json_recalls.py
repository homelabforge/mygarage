"""Recalls in the JSON backup: every column, the campaign key, the fill-only merge (batch 3b task 10)."""

from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recall import Recall
from tests.integration.routes._json_backup import V9, export_json, import_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NewVehicle = Callable[..., Awaitable[str]]


def _v9(*recalls: dict[str, Any]) -> dict[str, Any]:
    return {**V9, "recalls": list(recalls)}


async def _recalls(sessionmaker: Any, vin: str) -> list[tuple[Any, ...]]:
    """The vehicle's recalls as plain tuples, oldest first, through a fresh session."""
    async with sessionmaker() as fresh:
        rows = (
            (await fresh.execute(select(Recall).where(Recall.vin == vin).order_by(Recall.id)))
            .scalars()
            .all()
        )
    return [
        (
            r.nhtsa_campaign_number,
            r.component,
            r.summary,
            r.consequence,
            r.remedy,
            r.date_announced,
            r.is_resolved,
            r.resolved_at,
            r.notes,
        )
        for r in rows
    ]


_RESOLVED_AT = datetime(2026, 3, 4, 15, 30, 0)

_SOURCE_ROWS = [
    (
        "24V123000",
        "FUEL SYSTEM, GASOLINE:DELIVERY:FUEL PUMP",
        "The fuel pump may fail.",
        "An engine stall increases the risk of a crash.",
        "Dealers will replace the pump.",
        date(2024, 2, 1),
        True,
        _RESOLVED_AT,
        "Done at the dealer, invoice 4411",
    ),
    (None, "Wiper arm", "Hand-entered recall", None, None, None, False, None, None),
]


async def test_a_backup_round_trip_restores_every_recall_column(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    source = await new_vehicle()
    target = await new_vehicle()
    for row in _SOURCE_ROWS:
        db_session.add(
            Recall(
                vin=source,
                nhtsa_campaign_number=row[0],
                component=row[1],
                summary=row[2],
                consequence=row[3],
                remedy=row[4],
                date_announced=row[5],
                is_resolved=row[6],
                resolved_at=row[7],
                notes=row[8],
            )
        )
    await db_session.commit()

    exported = await export_json(client, auth_headers, source)
    data = await import_json(client, auth_headers, target, exported)
    # main: KeyError, the import has no recalls bucket
    assert data["recalls"]["success_count"] == 2, data
    assert data["errors"] == [] and data["warnings"] == [], data
    assert await _recalls(test_sessionmaker, target) == _SOURCE_ROWS

    # A re-import into the same vehicle adds nothing (R5).
    again = await import_json(client, auth_headers, target, exported)
    assert again["recalls"]["skipped_count"] == 2, again
    assert await _recalls(test_sessionmaker, target) == _SOURCE_ROWS


async def test_a_restore_after_the_nhtsa_check_fills_in_the_resolution(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    # What the nightly check writes before the restore runs: same campaign,
    # unresolved, no notes.
    db_session.add(
        Recall(
            vin=vin,
            nhtsa_campaign_number="24V123000",
            component="FUEL SYSTEM, GASOLINE:DELIVERY:FUEL PUMP",
            summary="The fuel pump may fail.",
            is_resolved=False,
        )
    )
    await db_session.commit()

    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            {
                "nhtsa_campaign_number": "24V123000",
                # NHTSA reworded it since; the campaign number is the key.
                "component": "FUEL PUMP",
                "summary": "Older wording",
                "is_resolved": True,
                "resolved_at": "2026-03-04T15:30:00",
                "notes": "Done at the dealer",
            }
        ),
    )
    # main: KeyError, and the stored recall keeps no resolution
    counts = data["recalls"]
    assert (counts["success_count"], counts["skipped_count"], counts["error_count"]) == (0, 1, 0)
    assert await _recalls(test_sessionmaker, vin) == [
        (
            "24V123000",
            "FUEL SYSTEM, GASOLINE:DELIVERY:FUEL PUMP",
            "The fuel pump may fail.",
            None,
            None,
            None,
            True,
            _RESOLVED_AT,
            "Done at the dealer",
        )
    ]


async def test_a_stored_resolution_or_note_is_never_overwritten(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    resolved_here = datetime(2026, 5, 1, 9, 0, 0)
    db_session.add_all(
        [
            Recall(
                vin=vin,
                nhtsa_campaign_number="24V000001",
                component="A",
                summary="a",
                is_resolved=True,
                resolved_at=resolved_here,
            ),
            Recall(
                vin=vin,
                nhtsa_campaign_number="24V000002",
                component="B",
                summary="b",
                is_resolved=False,
                notes="Parts on order",
            ),
        ]
    )
    await db_session.commit()

    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            {
                "nhtsa_campaign_number": "24V000001",
                "component": "A",
                "summary": "a",
                "is_resolved": False,
                "resolved_at": None,
                "notes": "From the file",
            },
            {
                "nhtsa_campaign_number": "24V000002",
                "component": "B",
                "summary": "b",
                "is_resolved": True,
                "resolved_at": "2026-01-01T00:00:00",
                "notes": "From the file",
            },
        ),
    )
    # main: KeyError; the stored rows are untouched either way
    assert data["recalls"]["skipped_count"] == 2, data
    assert await _recalls(test_sessionmaker, vin) == [
        ("24V000001", "A", "a", None, None, None, True, resolved_here, None),
        ("24V000002", "B", "b", None, None, None, False, None, "Parts on order"),
    ]


async def test_a_recall_with_no_campaign_matches_on_component_summary_and_date(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    db_session.add(
        Recall(
            vin=vin,
            component="Wiper arm",
            summary="Hand-entered recall",
            date_announced=date(2025, 6, 1),
        )
    )
    await db_session.commit()

    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            # Same component and summary, another date: a different recall. It
            # goes first, so a key without the date would spend the stored row on it.
            {
                "nhtsa_campaign_number": None,
                "component": "Wiper arm",
                "summary": "Hand-entered recall",
                "date_announced": "2025-07-01",
            },
            {
                "nhtsa_campaign_number": None,
                "component": "Wiper arm",
                "summary": "Hand-entered recall",
                "date_announced": "2025-06-01",
            },
        ),
    )
    # main: KeyError, and only the stored recall is there
    assert (data["recalls"]["success_count"], data["recalls"]["skipped_count"]) == (1, 1), data
    assert [r[5] for r in await _recalls(test_sessionmaker, vin)] == [
        date(2025, 6, 1),
        date(2025, 7, 1),
    ]


async def test_a_bad_recall_row_is_a_row_error_and_the_rest_import(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9(
            # Text is read as given (NB-1, D-15); a bad boolean is the row error.
            {"component": "Hood latch", "summary": "ok", "is_resolved": "yes"},
            {"component": "Hood latch", "summary": "fine"},
        ),
    )
    # main: KeyError, nothing read
    assert data["recalls"]["success_count"] == 1, data
    assert data["errors"] == ["Recall 0: is_resolved must be true or false"], data
    assert [r[2] for r in await _recalls(test_sessionmaker, vin)] == ["fine"]


async def test_a_150_character_component_restores(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    """The NHTSA sync and the API take 200; the column took 100, so PostgreSQL refused it (K10)."""
    vin = await new_vehicle()
    component = "ELECTRICAL SYSTEM:" + "W" * 132
    assert len(component) == 150

    data = await import_json(
        client, auth_headers, vin, _v9({"component": component, "summary": "Long NHTSA name"})
    )
    # main: KeyError (no section); on PostgreSQL without the widening, a 22001 row error
    assert data["recalls"]["success_count"] == 1, data
    assert [r[1] for r in await _recalls(test_sessionmaker, vin)] == [component]


async def test_a_recall_that_isnt_an_object_says_so(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    data = await import_json(
        client, auth_headers, vin, _v9("not a recall", {"component": "Hood latch"})
    )
    # main: nothing read, so no error; without the object check, "could not be imported"
    assert data["errors"] == ["Recall 0: must be an object"], data
    assert data["recalls"]["success_count"] == 1, data
    assert [r[1] for r in await _recalls(test_sessionmaker, vin)] == ["Hood latch"]


async def test_a_hand_entered_recall_never_matches_a_campaign_row(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Any,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    db_session.add(
        Recall(vin=vin, nhtsa_campaign_number="24V000003", component="Wiper arm", summary="s")
    )
    await db_session.commit()

    data = await import_json(
        client,
        auth_headers,
        vin,
        _v9({"nhtsa_campaign_number": None, "component": "Wiper arm", "summary": "s"}),
    )
    # main: KeyError; with no campaign filter in the key, the NHTSA row is spent instead
    assert (data["recalls"]["success_count"], data["recalls"]["skipped_count"]) == (1, 0), data
    assert [r[0] for r in await _recalls(test_sessionmaker, vin)] == ["24V000003", None]
