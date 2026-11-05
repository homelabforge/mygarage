"""Recall and warranty links in the JSON backup (Task 8).

An item names its recall and warranty by their place in the file's lists, the
way `triggered_by_inspection` names an item. A restore keeps each recall's own
resolution, except to hold I1 (linked means resolved) and I2 (resolved by a
visit means linked). A link never lands on another vehicle's row.

The client shares the test's session, so state after an import is read from a
fresh session.
"""

import copy
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.recall import Recall
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.warranty import WarrantyRecord
from app.routes.import_data import json_links
from app.routes.import_data.json_links import PendingLink, restore_links
from app.services.recall_links import resolved_at_for
from tests.integration.routes._json_backup import V9, export_json, import_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NewVehicle = Callable[..., Awaitable[str]]
Sessions = async_sessionmaker[AsyncSession]

_FILE_RESOLVED_AT = datetime(2026, 3, 4, 15, 30)
_DROPPED = "so it was saved without the link"


@pytest_asyncio.fixture
async def chicago(db_session: AsyncSession, keep_rows: Callable[..., Awaitable[None]]) -> None:
    """The household lives in Chicago, so noon on the visit date isn't noon UTC."""
    await keep_rows("timezone")
    row = await db_session.get(Setting, "timezone")
    if row is None:
        db_session.add(Setting(key="timezone", value="America/Chicago"))
    else:
        row.value = "America/Chicago"
    await db_session.commit()


async def _recall(
    db: AsyncSession, vin: str, campaign: str, *, resolved: bool = False, notes: str | None = None
) -> int:
    recall = Recall(
        vin=vin,
        nhtsa_campaign_number=campaign,
        component="AIR BAGS",
        summary="The inflator may rupture.",
        is_resolved=resolved,
        resolved_at=_FILE_RESOLVED_AT if resolved else None,
        notes=notes,
    )
    db.add(recall)
    await db.commit()
    return recall.id


async def _warranty(db: AsyncSession, vin: str, provider: str, start: date) -> int:
    warranty = WarrantyRecord(
        vin=vin, warranty_type="Powertrain", provider=provider, start_date=start
    )
    db.add(warranty)
    await db.commit()
    return warranty.id


async def _create_visit(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    items: list[dict[str, Any]],
    visit_date: str = "2026-11-03",
) -> dict[str, Any]:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={"date": visit_date, "line_items": items},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _state(sessions: Sessions, recall_id: int) -> tuple[bool, datetime | None, str | None]:
    """A recall's (is_resolved, resolved_at, resolved_via), read fresh."""
    async with sessions() as s:
        recall = await s.get(Recall, recall_id)
        assert recall is not None
        return bool(recall.is_resolved), recall.resolved_at, recall.resolved_via


async def _items(sessions: Sessions, vin: str) -> dict[str, tuple[bool, Any, bool, Any]]:
    """Each of the vehicle's items as (is_recall, recall_id, is_warranty, warranty_id), by
    description, read fresh."""
    async with sessions() as s:
        rows = (
            (
                await s.execute(
                    select(ServiceLineItem)
                    .join(ServiceVisit, ServiceVisit.id == ServiceLineItem.visit_id)
                    .where(ServiceVisit.vin == vin)
                )
            )
            .scalars()
            .all()
        )
        return {
            r.description: (r.is_recall, r.recall_id, r.is_warranty, r.warranty_id) for r in rows
        }


async def _ids_by(sessions: Sessions, vin: str) -> tuple[dict[str | None, int], dict[Any, int]]:
    """The vehicle's recall ids by campaign and warranty ids by provider, read fresh."""
    async with sessions() as s:
        recalls = (await s.execute(select(Recall).where(Recall.vin == vin))).scalars().all()
        warranties = (
            (await s.execute(select(WarrantyRecord).where(WarrantyRecord.vin == vin)))
            .scalars()
            .all()
        )
        return (
            {r.nhtsa_campaign_number: r.id for r in recalls},
            {w.provider: w.id for w in warranties},
        )


def _file(
    recalls: list[dict[str, Any]],
    items: list[dict[str, Any]],
    *,
    warranties: list[dict[str, Any]] | None = None,
    visit_date: str = "2026-11-03",
    **extra: Any,
) -> dict[str, Any]:
    """A v9 file with one visit holding `items`."""
    return {
        **V9,
        "recalls": recalls,
        "warranties": warranties or [],
        "service_visits": [{"date": visit_date, "line_items": items}],
        **extra,
    }


def _file_recall(campaign: str, *, resolved: bool, via: str | None = None) -> dict[str, Any]:
    return {
        "nhtsa_campaign_number": campaign,
        "is_resolved": resolved,
        "resolved_at": _FILE_RESOLVED_AT.isoformat() if resolved else None,
        "resolved_via": via,
    }


# --- export -------------------------------------------------------------------


async def test_the_export_writes_each_link_as_its_place_in_the_file(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    await _recall(db_session, vin, "24V500001")
    second = await _recall(db_session, vin, "24V500002")
    # Warranties go out newest start first, so the older one is index 1.
    older = await _warranty(db_session, vin, "Older Cover", date(2024, 1, 1))
    await _warranty(db_session, vin, "Newer Cover", date(2025, 1, 1))
    await _create_visit(
        client,
        auth_headers,
        vin,
        [
            {
                "description": "Inflator swap",
                "is_recall": True,
                "recall_id": second,
                "is_warranty": True,
                "warranty_id": older,
            },
            {"description": "Wipers"},
        ],
    )

    exported = await export_json(client, auth_headers, vin)
    campaigns = [r["nhtsa_campaign_number"] for r in exported["recalls"]]
    providers = [w["provider"] for w in exported["warranties"]]
    linked, plain = exported["service_visits"][0]["line_items"]
    # main: KeyError, no recall key on the item
    assert (linked["recall"], linked["warranty"]) == (
        campaigns.index("24V500002"),
        providers.index("Older Cover"),
    )
    assert (linked["is_recall"], linked["is_warranty"]) == (True, True)
    assert (plain["recall"], plain["warranty"]) == (None, None)
    assert "recall_id" not in linked and "warranty_id" not in linked


# --- round trip ---------------------------------------------------------------


async def test_a_round_trip_keeps_every_link_and_resolution_exactly(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    chicago: None,
):
    source = await new_vehicle()
    by_visit = await _recall(db_session, source, "24V510001")
    by_hand = await _recall(db_session, source, "24V510002")
    r = await client.put(
        f"/api/vehicles/{source}/recalls/{by_hand}",
        json={"is_resolved": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    warranty = await _warranty(db_session, source, "Acme Cover", date(2025, 1, 1))
    await _create_visit(
        client,
        auth_headers,
        source,
        [
            {"description": "Inflator swap", "is_recall": True, "recall_id": by_visit},
            {
                "description": "Seat belt",
                "is_recall": True,
                "recall_id": by_hand,
                "is_warranty": True,
                "warranty_id": warranty,
            },
            {"description": "Recall work, recall not in MyGarage", "is_recall": True},
        ],
    )
    source_states = [await _state(test_sessionmaker, rid) for rid in (by_visit, by_hand)]
    assert [s[2] for s in source_states] == ["service_visit", "manual"]

    exported = await export_json(client, auth_headers, source)
    target = await new_vehicle()
    data = await import_json(client, auth_headers, target, exported)
    assert data["errors"] == [] and data["warnings"] == [], data

    recall_ids, warranty_ids = await _ids_by(test_sessionmaker, target)
    expected = {
        "Inflator swap": (True, recall_ids["24V510001"], False, None),
        "Seat belt": (True, recall_ids["24V510002"], True, warranty_ids["Acme Cover"]),
        "Recall work, recall not in MyGarage": (True, None, False, None),
    }
    # main: no links at all, and is_recall comes back false
    assert await _items(test_sessionmaker, target) == expected
    assert [
        await _state(test_sessionmaker, recall_ids[c]) for c in ("24V510001", "24V510002")
    ] == source_states

    # The same file again adds nothing and moves nothing.
    again = await import_json(client, auth_headers, target, exported)
    assert again["errors"] == [] and again["warnings"] == [], again
    assert again["service_records"]["skipped_count"] == 1, again
    assert await _items(test_sessionmaker, target) == expected
    assert [
        await _state(test_sessionmaker, recall_ids[c]) for c in ("24V510001", "24V510002")
    ] == source_states


async def test_a_file_without_the_keys_imports_with_no_links(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V520001", resolved=True, via="manual")],
            [{"description": "Inflator swap", "is_recall": True, "is_warranty": True}],
            warranties=[
                {"warranty_type": "Powertrain", "provider": "Acme", "start_date": "2025-01-01"}
            ],
        ),
    )
    assert data["errors"] == [] and data["warnings"] == [], data
    # main: is_recall and is_warranty are dropped
    assert await _items(test_sessionmaker, vin) == {"Inflator swap": (True, None, True, None)}


# --- I2: a service_visit recall nothing links ---------------------------------


async def test_a_newer_backup_onto_the_visit_leaves_the_new_recall_reopenable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    source = await new_vehicle()
    rid = await _recall(db_session, source, "24V530001")
    # A sibling resolved by hand, so the test can't pass on an import that
    # drops resolved_via.
    by_hand = await _recall(db_session, source, "24V530003")
    r = await client.put(
        f"/api/vehicles/{source}/recalls/{by_hand}",
        json={"is_resolved": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    await _create_visit(
        client,
        auth_headers,
        source,
        [{"description": "Inflator swap", "is_recall": True, "recall_id": rid}],
    )
    exported = await export_json(client, auth_headers, source)
    resolved_at = (await _state(test_sessionmaker, rid))[1]

    # The instance has the visit already (an older backup), not the recall.
    target = await new_vehicle()
    older: dict[str, Any] = copy.deepcopy(exported)
    older["recalls"] = []
    visits: list[dict[str, Any]] = older["service_visits"]
    for visit in visits:
        items: list[dict[str, Any]] = visit["line_items"]
        visit["line_items"] = [{**i, "recall": None} for i in items]
    await import_json(client, auth_headers, target, older)

    data = await import_json(client, auth_headers, target, exported)
    assert data["service_records"]["skipped_count"] == 1, data
    assert data["recalls"]["success_count"] == 2, data
    recall_ids, _ = await _ids_by(test_sessionmaker, target)
    new_id = recall_ids["24V530001"]
    # main: the manual sibling comes back NULL
    assert (await _state(test_sessionmaker, recall_ids["24V530003"]))[2] == "manual"
    # Without I2 this one would stay service_visit and stuck.
    assert await _state(test_sessionmaker, new_id) == (True, resolved_at, None)
    assert (await _items(test_sessionmaker, target))["Inflator swap"][1] is None

    r = await client.put(
        f"/api/vehicles/{target}/recalls/{new_id}",
        json={"is_resolved": False},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert (await _state(test_sessionmaker, new_id))[0] is False


async def test_a_service_visit_recall_with_no_link_in_the_file_is_cleared(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        {
            **V9,
            "recalls": [
                _file_recall("24V530002", resolved=True, via="service_visit"),
                _file_recall("24V530004", resolved=True, via="manual"),
            ],
        },
    )
    assert data["errors"] == [], data
    recall_ids, _ = await _ids_by(test_sessionmaker, vin)
    # main: the manual one comes back NULL
    assert await _state(test_sessionmaker, recall_ids["24V530004"]) == (
        True,
        _FILE_RESOLVED_AT,
        "manual",
    )
    # Without the I2 pass this one stays service_visit with nothing linking it.
    assert await _state(test_sessionmaker, recall_ids["24V530002"]) == (
        True,
        _FILE_RESOLVED_AT,
        None,
    )


async def test_a_duplicate_fill_with_the_visit_skipped_is_cleared(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    # Open with no notes, so the file fills it with service_visit.
    stored = await _recall(db_session, vin, "24V530005")
    # The visit's here already with no link, so the file's copy is skipped and
    # nothing links the filled recall.
    await _create_visit(
        client, auth_headers, vin, [{"description": "Inflator swap", "is_recall": True}]
    )
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V530005", resolved=True, via="service_visit")],
            [{"description": "Inflator swap", "is_recall": True, "recall": 0}],
        ),
    )
    assert data["errors"] == [], data
    assert data["service_records"]["skipped_count"] == 1, data
    assert data["recalls"]["skipped_count"] == 1, data
    # Fails with the I2 pass off: the fill leaves service_visit on the stored row.
    assert await _state(test_sessionmaker, stored) == (True, _FILE_RESOLVED_AT, None)
    assert (await _items(test_sessionmaker, vin))["Inflator swap"][1] is None


async def test_the_duplicate_fill_lands_resolved_via_and_an_unlink_reopens(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    # The nightly check put it back, open with no notes, so the file fills it.
    stored = await _recall(db_session, vin, "24V540001")
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V540001", resolved=True, via="service_visit")],
            [{"description": "Inflator swap", "is_recall": True, "recall": 0}],
        ),
    )
    assert data["errors"] == [] and data["warnings"] == [], data
    assert data["recalls"]["skipped_count"] == 1, data
    # main: no link, and the fill leaves resolved_via NULL
    assert await _state(test_sessionmaker, stored) == (True, _FILE_RESOLVED_AT, "service_visit")
    assert (await _items(test_sessionmaker, vin))["Inflator swap"] == (True, stored, False, None)

    listed = await client.get(f"/api/vehicles/{vin}/service-visits", headers=auth_headers)
    visit = listed.json()["visits"][0]
    item = visit["line_items"][0]
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}",
        json={
            "line_items": [
                {"id": item["id"], "description": item["description"], "recall_id": None}
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, stored) == (False, None, None)


# --- I1: a link onto an open recall resolves it --------------------------------


async def test_a_link_onto_an_open_stored_recall_resolves_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    chicago: None,
):
    vin = await new_vehicle()
    # Notes, so the duplicate fill leaves it alone and it stays open.
    stored = await _recall(db_session, vin, "24V550001", notes="Parts on order")
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V550001", resolved=True, via="service_visit")],
            [{"description": "Inflator swap", "is_recall": True, "recall": 0}],
        ),
    )
    assert data["errors"] == [] and data["warnings"] == [], data
    assert (await _items(test_sessionmaker, vin))["Inflator swap"][1] == stored
    # main: linked and open, I1 broken
    assert await _state(test_sessionmaker, stored) == (
        True,
        resolved_at_for(date(2026, 11, 3)),
        "service_visit",
    )


async def test_a_link_onto_an_open_recall_from_the_file_resolves_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    chicago: None,
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V550002", resolved=False)],
            [{"description": "Inflator swap", "is_recall": True, "recall": 0}],
        ),
    )
    assert data["errors"] == [] and data["warnings"] == [], data
    recall_ids, _ = await _ids_by(test_sessionmaker, vin)
    assert await _state(test_sessionmaker, recall_ids["24V550002"]) == (
        True,
        resolved_at_for(date(2026, 11, 3)),
        "service_visit",
    )


async def test_a_link_onto_a_warranty_already_here_lands_on_the_stored_one(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    vin = await new_vehicle()
    stored = await _warranty(db_session, vin, "Acme Cover", date(2025, 1, 1))
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [],
            [{"description": "Under cover", "is_warranty": True, "warranty": 0}],
            warranties=[
                {
                    "warranty_type": "Powertrain",
                    "provider": "Acme Cover",
                    "start_date": "2025-01-01",
                }
            ],
        ),
    )
    assert data["errors"] == [] and data["warnings"] == [], data
    assert data["warranties"]["skipped_count"] == 1, data
    # main: is_warranty dropped and no link
    assert await _items(test_sessionmaker, vin) == {"Under cover": (False, None, True, stored)}


# --- dropped links ------------------------------------------------------------


async def test_two_items_on_one_recall_import_one_link_and_a_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    chicago: None,
):
    vin = await new_vehicle()
    payload = {
        **V9,
        "recalls": [_file_recall("24V560001", resolved=False)],
        "service_visits": [
            {
                "date": "2026-11-03",
                "line_items": [{"description": "First", "is_recall": True, "recall": 0}],
            },
            {
                "date": "2026-11-10",
                "line_items": [{"description": "Second", "is_recall": True, "recall": 0}],
            },
        ],
        "notes": [{"date": "2026-11-04", "title": "Still here", "content": "kept"}],
    }
    data = await import_json(client, auth_headers, vin, payload)
    assert data["errors"] == [], data
    assert data["service_records"]["success_count"] == 2, data
    assert data["notes"]["success_count"] == 1, data
    assert data["warnings"] == [
        f"Service visit 1: line item 0: its recall is already linked to another "
        f"line item, {_DROPPED}"
    ], data
    recall_ids, _ = await _ids_by(test_sessionmaker, vin)
    rid = recall_ids["24V560001"]
    assert await _items(test_sessionmaker, vin) == {
        "First": (True, rid, False, None),
        "Second": (True, None, False, None),
    }
    # The dropped link didn't move the date to the second visit's.
    assert await _state(test_sessionmaker, rid) == (
        True,
        resolved_at_for(date(2026, 11, 3)),
        "service_visit",
    )


async def _linked_elsewhere(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    sessions: Sessions,
    new_vehicle: NewVehicle,
) -> tuple[str, int, tuple[bool, datetime | None, str | None]]:
    """A vehicle whose recall a visit already links; its id and state."""
    vin = await new_vehicle()
    rid = await _recall(db, vin, "24V570001")
    await _create_visit(
        client, headers, vin, [{"description": "Held", "is_recall": True, "recall_id": rid}]
    )
    return vin, rid, await _state(sessions, rid)


def _onto_the_taken_recall() -> dict[str, Any]:
    return {
        **_file(
            [_file_recall("24V570001", resolved=True, via="service_visit")],
            [{"description": "Newcomer", "is_recall": True, "recall": 0}],
            visit_date="2026-10-01",
        ),
        "notes": [{"date": "2026-11-04", "title": "Still here", "content": "kept"}],
    }


async def test_a_link_onto_a_recall_already_linked_is_dropped_with_a_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    vin, rid, before = await _linked_elsewhere(
        client, auth_headers, db_session, test_sessionmaker, new_vehicle
    )
    data = await import_json(client, auth_headers, vin, _onto_the_taken_recall())
    assert data["errors"] == [], data
    assert data["notes"]["success_count"] == 1, data
    assert data["warnings"] == [
        f"Service visit 0: line item 0: its recall is already linked to another "
        f"line item, {_DROPPED}"
    ], data
    assert await _items(test_sessionmaker, vin) == {
        "Held": (True, rid, False, None),
        "Newcomer": (True, None, False, None),
    }
    assert await _state(test_sessionmaker, rid) == before


async def test_a_link_the_database_refuses_rolls_back_alone(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    monkeypatch: pytest.MonkeyPatch,
):
    vin, rid, before = await _linked_elsewhere(
        client, auth_headers, db_session, test_sessionmaker, new_vehicle
    )

    async def nothing_taken(db: AsyncSession, ids: set[int]) -> set[int]:
        return set()

    # With the pre-check blind, the unique index refuses the link at the flush.
    monkeypatch.setattr(json_links, "_taken_recalls", nothing_taken)
    data = await import_json(client, auth_headers, vin, _onto_the_taken_recall())
    assert data["errors"] == [], data
    assert data["notes"]["success_count"] == 1, data
    assert data["warnings"] == [
        f"Service visit 0: line item 0: its recall couldn't be linked, {_DROPPED}"
    ], data
    assert await _items(test_sessionmaker, vin) == {
        "Held": (True, rid, False, None),
        "Newcomer": (True, None, False, None),
    }
    assert await _state(test_sessionmaker, rid) == before


@pytest.mark.parametrize("kind", ["recall", "warranty"])
async def test_a_link_with_its_flag_false_is_dropped_with_a_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    kind: str,
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V580001", resolved=False)],
            [{"description": "Not recall work", f"is_{kind}": False, kind: 0}],
            warranties=[
                {"warranty_type": "Powertrain", "provider": "Acme", "start_date": "2025-01-01"}
            ],
        ),
    )
    assert data["errors"] == [], data
    assert data["warnings"] == [
        f"Service visit 0: line item 0: {kind} is set but is_{kind} is false, {_DROPPED}"
    ], data
    assert await _items(test_sessionmaker, vin) == {"Not recall work": (False, None, False, None)}
    recall_ids, _ = await _ids_by(test_sessionmaker, vin)
    assert await _state(test_sessionmaker, recall_ids["24V580001"]) == (False, None, None)


@pytest.mark.parametrize("index", [5, -1, True, "0"])
async def test_an_index_with_nothing_there_is_dropped_with_a_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
    index: Any,
):
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        _file(
            [_file_recall("24V590001", resolved=False)],
            [{"description": "Inflator swap", "is_recall": True, "recall": index}],
        ),
    )
    assert data["errors"] == [], data
    assert data["service_records"]["success_count"] == 1, data
    assert len(data["warnings"]) == 1 and _DROPPED in data["warnings"][0], data
    assert await _items(test_sessionmaker, vin) == {"Inflator swap": (True, None, False, None)}


# --- another vehicle's rows ------------------------------------------------------


async def test_a_crafted_file_never_links_another_vehicles_recall_or_warranty(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    """One vehicle per file: every index is into this file's lists, written to this VIN.

    The file names the other vehicle, carries its raw ids, and copies its recall
    and warranty; the links land on this vehicle's copies or nowhere.
    """
    other = await new_vehicle()
    their_recall = await _recall(db_session, other, "24V600001")
    their_warranty = await _warranty(db_session, other, "Their Cover", date(2025, 1, 1))
    vin = await new_vehicle()
    data = await import_json(
        client,
        auth_headers,
        vin,
        {
            **V9,
            "vehicle": {"vin": other},
            "recalls": [_file_recall("24V600001", resolved=False)],
            "warranties": [
                {
                    "warranty_type": "Powertrain",
                    "provider": "Their Cover",
                    "start_date": "2025-01-01",
                }
            ],
            "service_visits": [
                {
                    "date": "2026-11-03",
                    "line_items": [
                        {
                            "description": "Indexed",
                            "is_recall": True,
                            "recall": 0,
                            "recall_id": their_recall,
                            "is_warranty": True,
                            "warranty": 0,
                            "warranty_id": their_warranty,
                        },
                        {
                            "description": "Raw ids only",
                            "is_recall": True,
                            "recall_id": their_recall,
                            "is_warranty": True,
                            "warranty_id": their_warranty,
                        },
                    ],
                }
            ],
        },
    )
    assert data["errors"] == [], data
    recall_ids, warranty_ids = await _ids_by(test_sessionmaker, vin)
    assert recall_ids["24V600001"] != their_recall
    assert await _items(test_sessionmaker, vin) == {
        "Indexed": (True, recall_ids["24V600001"], True, warranty_ids["Their Cover"]),
        "Raw ids only": (True, None, True, None),
    }
    assert await _state(test_sessionmaker, their_recall) == (False, None, None)
    async with test_sessionmaker() as s:
        theirs = (
            await s.execute(
                select(ServiceLineItem.id).where(
                    (ServiceLineItem.recall_id == their_recall)
                    | (ServiceLineItem.warranty_id == their_warranty)
                )
            )
        ).all()
    assert theirs == []


async def test_restore_links_drops_a_map_entry_on_another_vehicle(
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    new_vehicle: NewVehicle,
):
    """The VIN check holds even when a map points elsewhere, however it was built."""
    other = await new_vehicle()
    their_recall = await _recall(db_session, other, "24V610001")
    their_warranty = await _warranty(db_session, other, "Their Cover", date(2025, 1, 1))
    vin = await new_vehicle()
    visit = ServiceVisit(vin=vin, date=date(2026, 11, 3))
    db_session.add(visit)
    await db_session.flush()
    item = ServiceLineItem(
        visit_id=visit.id, description="Inflator swap", is_recall=True, is_warranty=True
    )
    db_session.add(item)
    await db_session.flush()

    warnings: list[str] = []
    await restore_links(
        db_session,
        vin,
        [PendingLink(item, visit.date, 0, 0, "Service visit 0: line item 0")],
        recall_ids={0: their_recall},
        warranty_ids={0: their_warranty},
        written_recalls=(),
        warnings=warnings,
    )
    await db_session.commit()

    assert await _items(test_sessionmaker, vin) == {"Inflator swap": (True, None, True, None)}
    assert await _state(test_sessionmaker, their_recall) == (False, None, None)
    assert warnings == [
        f"Service visit 0: line item 0: its warranty wasn't imported, {_DROPPED}",
        f"Service visit 0: line item 0: its recall wasn't imported, {_DROPPED}",
    ]
