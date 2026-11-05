"""Linking a line item to a recall or warranty, on every visit write path (Task 6).

A link to an open recall resolves it at household noon on the visit's date (D1,
D13); removing the link reopens it, unless it was resolved by hand (D10). The
recall and the warranty have to be this vehicle's (422 otherwise), and a recall
takes one item at most (409).

The client shares the test's session, so state after a write is read from a
fresh session: the test's identity map can hold rows the request already
changed underneath it.
"""

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
from app.models.vehicle import Vehicle
from app.models.warranty import WarrantyRecord

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_LINE = {"description": "Oil change", "category": "Maintenance", "cost": "50.00"}
# Household noon on 2026-11-03 in Chicago (CST, UTC-6) is 18:00 UTC.
_NOON_NOV_3 = datetime(2026, 11, 3, 18, 0)
_NOON_NOV_10 = datetime(2026, 11, 10, 18, 0)
_YESTERDAY = datetime(2026, 11, 4, 15, 30)

Sessions = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def chicago(db_session: AsyncSession, keep_rows: Callable[..., Awaitable[None]]) -> None:
    """The household lives in Chicago, so noon isn't noon UTC."""
    await keep_rows("timezone")
    row = await db_session.get(Setting, "timezone")
    if row is None:
        db_session.add(Setting(key="timezone", value="America/Chicago"))
    else:
        row.value = "America/Chicago"
    await db_session.commit()


@pytest_asyncio.fixture
async def vin(new_vehicle: Callable[..., Awaitable[str]], chicago: None) -> str:
    return await new_vehicle()


@pytest_asyncio.fixture
async def other_vin(new_vehicle: Callable[..., Awaitable[str]]) -> str:
    """A second vehicle of the same user: its recalls and warranties are off limits."""
    return await new_vehicle()


async def _recall(
    db: AsyncSession,
    vin: str,
    *,
    campaign: str = "24V100000",
    resolved_via: str | None = None,
    resolved_at: datetime | None = None,
) -> int:
    recall = Recall(
        vin=vin,
        nhtsa_campaign_number=campaign,
        component="AIR BAGS",
        summary="The inflator may rupture.",
        is_resolved=resolved_at is not None,
        resolved_at=resolved_at,
        resolved_via=resolved_via,
    )
    db.add(recall)
    await db.commit()
    return recall.id


async def _warranty(db: AsyncSession, vin: str, provider: str = "Acme Cover") -> int:
    warranty = WarrantyRecord(
        vin=vin, warranty_type="Powertrain", provider=provider, start_date=date(2025, 1, 1)
    )
    db.add(warranty)
    await db.commit()
    return warranty.id


async def _state(sessions: Sessions, recall_id: int) -> tuple[bool, datetime | None, str | None]:
    """A recall's (is_resolved, resolved_at, resolved_via), read fresh."""
    async with sessions() as s:
        recall = await s.get(Recall, recall_id)
        assert recall is not None
        return bool(recall.is_resolved), recall.resolved_at, recall.resolved_via


async def _links(sessions: Sessions, visit_id: int) -> dict[str, tuple[bool, Any, bool, Any]]:
    """Each item's (is_recall, recall_id, is_warranty, warranty_id) by description, read fresh."""
    async with sessions() as s:
        rows = (
            (await s.execute(select(ServiceLineItem).where(ServiceLineItem.visit_id == visit_id)))
            .scalars()
            .all()
        )
        return {
            r.description: (r.is_recall, r.recall_id, r.is_warranty, r.warranty_id) for r in rows
        }


async def _create(
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


async def _put(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int, body: dict[str, Any]
) -> Any:
    return await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}", json=body, headers=headers
    )


def _keep(item: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """An existing item as an API client sends it back: id and description, plus changes."""
    return {"id": item["id"], "description": item["description"], **changes}


def _by_desc(visit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["description"]: i for i in visit["line_items"]}


# --- Resolving and reopening ------------------------------------------------


async def test_linking_an_open_recall_resolves_it_at_household_noon(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    await _create(client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}])
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")


async def test_a_hand_resolved_recall_keeps_manual_and_moves_to_the_visit_date(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin, resolved_via="manual", resolved_at=_YESTERDAY)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "manual")

    # Unlinking a recall the link didn't resolve leaves it resolved.
    item = visit["line_items"][0]
    r = await _put(
        client, auth_headers, vin, visit["id"], {"line_items": [_keep(item, recall_id=None)]}
    )
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "manual")


async def test_a_legacy_resolved_recall_reads_as_manual(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    """resolved_via NULL is a row from before migration 158: never reopened by an unlink."""
    rid = await _recall(db_session, vin, resolved_at=_YESTERDAY)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, None)
    r = await client.delete(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}", headers=auth_headers
    )
    assert r.status_code == 204, r.text
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, None)


@pytest.mark.parametrize("with_items", (False, True), ids=("date_only", "form_save"))
async def test_changing_the_visit_date_moves_resolved_at(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    with_items: bool,
) -> None:
    """Both ways a date changes: alone, and in a form save that resends every item."""
    auto = await _recall(db_session, vin, campaign="24V100001")
    manual = await _recall(
        db_session, vin, campaign="24V100002", resolved_via="manual", resolved_at=_YESTERDAY
    )
    visit = await _create(
        client,
        auth_headers,
        vin,
        [
            {**_LINE, "is_recall": True, "recall_id": auto},
            {**_LINE, "description": "Tie rod", "is_recall": True, "recall_id": manual},
        ],
    )
    body: dict[str, Any] = {"date": "2026-11-10"}
    if with_items:
        body["line_items"] = [
            _keep(i, is_recall=True, recall_id=i["recall_id"]) for i in visit["line_items"]
        ]
    r = await _put(client, auth_headers, vin, visit["id"], body)
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, auto) == (True, _NOON_NOV_10, "service_visit")
    assert await _state(test_sessionmaker, manual) == (True, _NOON_NOV_10, "manual")


async def test_clearing_the_link_reopens_the_recall(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    item = visit["line_items"][0]
    r = await _put(
        client, auth_headers, vin, visit["id"], {"line_items": [_keep(item, recall_id=None)]}
    )
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, rid) == (False, None, None)
    # The flag stays: it was still recall work.
    assert await _links(test_sessionmaker, visit["id"]) == {"Oil change": (True, None, False, None)}


async def test_is_recall_false_with_the_link_still_sent_is_a_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    item = visit["line_items"][0]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {"line_items": [_keep(item, is_recall=False, recall_id=rid)]},
    )
    assert r.status_code == 422, r.text
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")


async def test_is_recall_false_with_the_link_omitted_unlinks_and_reopens(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    wid = await _warranty(db_session, vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": rid, "is_warranty": True, "warranty_id": wid}],
    )
    item = visit["line_items"][0]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {"line_items": [_keep(item, is_recall=False, is_warranty=False)]},
    )
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, rid) == (False, None, None)
    assert await _links(test_sessionmaker, visit["id"]) == {
        "Oil change": (False, None, False, None)
    }
    got = r.json()["line_items"][0]
    assert (got["recall_id"], got["recall_summary"]) == (None, None)
    assert (got["warranty_id"], got["warranty_summary"]) == (None, None)


async def test_a_link_sent_against_a_stored_false_flag_is_a_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    """The schema lets {id, recall_id} through (an omitted flag keeps the stored one);
    the stored flag is false, so the link has nothing to hang on."""
    rid = await _recall(db_session, vin)
    visit = await _create(client, auth_headers, vin, [_LINE])
    item = visit["line_items"][0]
    r = await _put(
        client, auth_headers, vin, visit["id"], {"line_items": [_keep(item, recall_id=rid)]}
    )
    assert r.status_code == 422, r.text
    assert await _state(test_sessionmaker, rid) == (False, None, None)


async def test_omitting_the_link_fields_keeps_the_link(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    wid = await _warranty(db_session, vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": rid, "is_warranty": True, "warranty_id": wid}],
    )
    item = visit["line_items"][0]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {"line_items": [_keep(item, notes="Done"), {"description": "Wipers"}]},
    )
    assert r.status_code == 200, r.text
    assert (await _links(test_sessionmaker, visit["id"]))["Oil change"] == (True, rid, True, wid)
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")


async def test_dropping_the_item_reopens_the_recall(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": rid}, {**_LINE, "description": "Wipers"}],
    )
    assert (await _state(test_sessionmaker, rid))[0] is True
    keep = _by_desc(visit)["Wipers"]
    r = await _put(client, auth_headers, vin, visit["id"], {"line_items": [_keep(keep)]})
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, rid) == (False, None, None)


async def test_moving_the_link_to_another_item_keeps_it_resolved(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": rid}, {**_LINE, "description": "Tie rod"}],
    )
    a, b = _by_desc(visit)["Oil change"], _by_desc(visit)["Tie rod"]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {
            "line_items": [
                _keep(a, is_recall=False),
                _keep(b, is_recall=True, recall_id=rid),
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")
    assert await _links(test_sessionmaker, visit["id"]) == {
        "Oil change": (False, None, False, None),
        "Tie rod": (True, rid, False, None),
    }
    got = _by_desc(r.json())
    assert got["Tie rod"]["recall_summary"]["id"] == rid
    assert got["Oil change"]["recall_summary"] is None


async def test_moving_the_link_to_a_new_item_keeps_it_resolved(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    a = visit["line_items"][0]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {
            "line_items": [
                _keep(a, recall_id=None),
                {"description": "Inflator", "is_recall": True, "recall_id": rid},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")
    assert (await _links(test_sessionmaker, visit["id"]))["Inflator"] == (True, rid, False, None)


async def test_swapping_two_recalls_between_two_items(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    """Each recall lands on the other item; neither holds the unique index twice."""
    r1 = await _recall(db_session, vin, campaign="24V100011")
    r2 = await _recall(db_session, vin, campaign="24V100012")
    visit = await _create(
        client,
        auth_headers,
        vin,
        [
            {**_LINE, "is_recall": True, "recall_id": r1},
            {**_LINE, "description": "Tie rod", "is_recall": True, "recall_id": r2},
        ],
    )
    a, b = _by_desc(visit)["Oil change"], _by_desc(visit)["Tie rod"]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {"line_items": [_keep(a, recall_id=r2), _keep(b, recall_id=r1)]},
    )
    assert r.status_code == 200, r.text
    assert await _links(test_sessionmaker, visit["id"]) == {
        "Oil change": (True, r2, False, None),
        "Tie rod": (True, r1, False, None),
    }
    got = _by_desc(r.json())
    assert got["Oil change"]["recall_summary"]["campaign"] == "24V100012"
    assert got["Tie rod"]["recall_summary"]["campaign"] == "24V100011"
    for rid in (r1, r2):
        assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")


async def test_deleting_the_line_item_reopens_the_recall(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": rid}, {**_LINE, "description": "Wipers"}],
    )
    assert (await _state(test_sessionmaker, rid))[0] is True
    item = _by_desc(visit)["Oil change"]
    r = await client.delete(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items/{item['id']}",
        headers=auth_headers,
    )
    assert r.status_code == 204, r.text
    assert await _state(test_sessionmaker, rid) == (False, None, None)


async def test_deleting_the_visit_reopens_the_recall(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    assert (await _state(test_sessionmaker, rid))[0] is True
    r = await client.delete(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}", headers=auth_headers
    )
    assert r.status_code == 204, r.text
    assert await _state(test_sessionmaker, rid) == (False, None, None)


async def test_posting_a_line_item_resolves_and_answers_like_a_get(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin, campaign="24V100021")
    wid = await _warranty(db_session, vin)
    visit = await _create(client, auth_headers, vin, [_LINE])
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
        json={
            "description": "Inflator",
            "is_recall": True,
            "recall_id": rid,
            "is_warranty": True,
            "warranty_id": wid,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    posted = r.json()
    assert (posted["is_recall"], posted["recall_id"]) == (True, rid)
    assert (posted["is_warranty"], posted["warranty_id"]) == (True, wid)
    assert posted["recall_summary"] == {"id": rid, "campaign": "24V100021", "component": "AIR BAGS"}
    assert posted["warranty_summary"] == {
        "id": wid,
        "warranty_type": "Powertrain",
        "provider": "Acme Cover",
    }
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")

    got = await client.get(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    assert next(i for i in got.json()["line_items"] if i["id"] == posted["id"]) == posted


# --- Summaries follow a changed link on an existing item -------------------


async def test_changing_an_existing_items_links_changes_its_summaries(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    r1 = await _recall(db_session, vin, campaign="24V100031")
    r2 = await _recall(db_session, vin, campaign="24V100032")
    w1 = await _warranty(db_session, vin, provider="First Cover")
    w2 = await _warranty(db_session, vin, provider="Second Cover")
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": r1, "is_warranty": True, "warranty_id": w1}],
    )
    item = visit["line_items"][0]
    assert item["recall_summary"]["campaign"] == "24V100031"

    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {"line_items": [_keep(item, recall_id=r2, warranty_id=w2)]},
    )
    assert r.status_code == 200, r.text
    got = r.json()["line_items"][0]
    assert got["recall_summary"]["campaign"] == "24V100032"
    assert got["warranty_summary"]["provider"] == "Second Cover"
    # r1 lost its only link, so it opens again; r2 is the one resolved now.
    assert await _state(test_sessionmaker, r1) == (False, None, None)
    assert await _state(test_sessionmaker, r2) == (True, _NOON_NOV_3, "service_visit")

    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {"line_items": [_keep(item, recall_id=None, warranty_id=None)]},
    )
    assert r.status_code == 200, r.text
    got = r.json()["line_items"][0]
    assert (got["recall_id"], got["recall_summary"]) == (None, None)
    assert (got["warranty_id"], got["warranty_summary"]) == (None, None)
    assert await _state(test_sessionmaker, r2) == (False, None, None)


# --- Validation ---------------------------------------------------------------


_KINDS = ("recall", "warranty")
_PATHS = ("create", "put_new", "put_existing", "post_item")


async def _write_link(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    path: str,
    link: dict[str, Any],
    visit: dict[str, Any] | None,
) -> Any:
    """Send `link` on one of the four ways a link gets written."""
    if path == "create":
        return await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={"date": "2026-11-03", "line_items": [{**_LINE, **link}]},
            headers=headers,
        )
    assert visit is not None
    if path == "put_new":
        body = {"line_items": [_keep(visit["line_items"][0]), {"description": "New", **link}]}
        return await _put(client, headers, vin, visit["id"], body)
    if path == "put_existing":
        body = {"line_items": [_keep(visit["line_items"][0], **link)]}
        return await _put(client, headers, vin, visit["id"], body)
    return await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
        json={"description": "New", **link},
        headers=headers,
    )


def _link(kind: str, target: int | None) -> dict[str, Any]:
    return {f"is_{kind}": True, f"{kind}_id": target}


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("path", _PATHS)
async def test_another_vehicles_recall_or_warranty_never_links(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    other_vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    kind: str,
    path: str,
) -> None:
    foreign = (
        await _recall(db_session, other_vin)
        if kind == "recall"
        else await _warranty(db_session, other_vin)
    )
    visit = None if path == "create" else await _create(client, auth_headers, vin, [_LINE])
    r = await _write_link(client, auth_headers, vin, path, _link(kind, foreign), visit)
    if path == "put_existing":
        # An existing item treats any id that isn't this vehicle's as cleared,
        # the same as one deleted since the form loaded.
        assert r.status_code == 200, r.text
        got = r.json()["line_items"][0]
        assert (got[f"is_{kind}"], got[f"{kind}_id"], got[f"{kind}_summary"]) == (True, None, None)
    else:
        assert r.status_code == 422, r.text

    async with test_sessionmaker() as s:
        linked = (
            await s.execute(
                select(ServiceLineItem.id).where(getattr(ServiceLineItem, f"{kind}_id") == foreign)
            )
        ).all()
        assert linked == []
    if kind == "recall":
        assert await _state(test_sessionmaker, foreign) == (False, None, None)


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("path", ("create", "put_new", "post_item"))
async def test_a_new_item_linking_a_missing_id_is_a_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    kind: str,
    path: str,
) -> None:
    missing = 2_000_000_000
    visit = None if path == "create" else await _create(client, auth_headers, vin, [_LINE])
    r = await _write_link(client, auth_headers, vin, path, _link(kind, missing), visit)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("path", ("create", "put_new", "post_item"))
async def test_a_missing_and_a_foreign_id_get_the_same_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    other_vin: str,
    db_session: AsyncSession,
    kind: str,
    path: str,
) -> None:
    """Otherwise the answer says whether id N exists in some other garage."""
    make = _recall if kind == "recall" else _warranty
    foreign = await make(db_session, other_vin)
    answers: list[tuple[int, bytes]] = []
    for target in (foreign, 2_000_000_000):
        visit = None if path == "create" else await _create(client, auth_headers, vin, [_LINE])
        r = await _write_link(client, auth_headers, vin, path, _link(kind, target), visit)
        answers.append((r.status_code, r.content))
    assert answers[0][0] == 422
    assert answers[0] == answers[1]


@pytest.mark.parametrize("kind", _KINDS)
async def test_a_foreign_id_on_an_existing_item_is_never_stored(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    other_vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    kind: str,
) -> None:
    """Not on an item that already links one of ours, and not against a stored-false
    flag either: both answer like a missing id would."""
    make = _recall if kind == "recall" else _warranty
    mine = await make(db_session, vin)
    foreign = await make(db_session, other_vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, **_link(kind, mine)}, {**_LINE, "description": "Tie rod"}],
    )
    a, b = _by_desc(visit)["Oil change"], _by_desc(visit)["Tie rod"]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {
            "line_items": [
                _keep(a, **{f"{kind}_id": foreign}),
                _keep(b, **{f"{kind}_id": foreign}),
            ]
        },
    )
    assert r.status_code == 200, r.text
    flag = (True, None, False, None) if kind == "recall" else (False, None, True, None)
    assert await _links(test_sessionmaker, visit["id"]) == {
        "Oil change": flag,
        "Tie rod": (False, None, False, None),
    }
    if kind == "recall":
        assert await _state(test_sessionmaker, foreign) == (False, None, None)
        # Ours lost its only link, so it opens again.
        assert await _state(test_sessionmaker, mine) == (False, None, None)


@pytest.mark.parametrize("kind", _KINDS)
async def test_an_existing_item_sending_a_gone_id_clears_the_link(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    kind: str,
) -> None:
    """The form seeds the stored link; if the recall or warranty was deleted since
    (the FK already nulled it), a save goes through and the link stays empty."""
    make = _recall if kind == "recall" else _warranty
    target = await make(db_session, vin)
    live = await make(db_session, vin)
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, **_link(kind, target)}, {**_LINE, "description": "Tie rod"}],
    )
    model = Recall if kind == "recall" else WarrantyRecord
    async with test_sessionmaker() as s:
        row = await s.get(model, target)
        await s.delete(row)
        await s.commit()

    # The same save links the other item, so it isn't a save that ignores links.
    a, b = _by_desc(visit)["Oil change"], _by_desc(visit)["Tie rod"]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {
            "line_items": [
                _keep(a, notes="Edited", **_link(kind, target)),
                _keep(b, **_link(kind, live)),
            ]
        },
    )
    assert r.status_code == 200, r.text
    got = _by_desc(r.json())["Oil change"]
    assert got[f"is_{kind}"] is True
    assert got[f"{kind}_id"] is None
    assert got[f"{kind}_summary"] is None
    flag = (True, None, False, None) if kind == "recall" else (False, None, True, None)
    other = (True, live, False, None) if kind == "recall" else (False, None, True, live)
    assert await _links(test_sessionmaker, visit["id"]) == {"Oil change": flag, "Tie rod": other}


@pytest.mark.parametrize("path", _PATHS)
async def test_a_recall_another_visit_links_is_a_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    path: str,
) -> None:
    rid = await _recall(db_session, vin)
    first = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    visit = None if path == "create" else await _create(client, auth_headers, vin, [_LINE])
    r = await _write_link(client, auth_headers, vin, path, _link("recall", rid), visit)
    assert r.status_code == 409, r.text
    assert "already linked" in r.json()["detail"]
    assert (await _links(test_sessionmaker, first["id"]))["Oil change"] == (
        True,
        rid,
        False,
        None,
    )


@pytest.mark.parametrize("path", _PATHS)
async def test_one_recall_on_two_items_of_one_visit_is_a_409(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
    path: str,
) -> None:
    """A sibling on the same visit already holds the recall, or gets it in the same payload."""
    rid = await _recall(db_session, vin)
    linked = {**_LINE, "is_recall": True, "recall_id": rid}
    if path == "create":
        r = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2026-11-03",
                "line_items": [linked, {**linked, "description": "Tie rod"}],
            },
            headers=auth_headers,
        )
    else:
        visit = await _create(
            client, auth_headers, vin, [linked, {**_LINE, "description": "Tie rod"}]
        )
        a, b = _by_desc(visit)["Oil change"], _by_desc(visit)["Tie rod"]
        link = _link("recall", rid)
        if path == "put_new":
            body = {"line_items": [_keep(a), _keep(b), {"description": "New", **link}]}
            r = await _put(client, auth_headers, vin, visit["id"], body)
        elif path == "put_existing":
            body = {"line_items": [_keep(a), _keep(b, **link)]}
            r = await _put(client, auth_headers, vin, visit["id"], body)
        else:
            r = await client.post(
                f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
                json={"description": "New", **link},
                headers=auth_headers,
            )
        assert r.status_code == 409, r.text
        assert await _links(test_sessionmaker, visit["id"]) == {
            "Oil change": (True, rid, False, None),
            "Tie rod": (False, None, False, None),
        }
    assert r.status_code == 409, r.text
    assert "already linked" in r.json()["detail"]


async def test_posting_an_unlinked_item_keeps_a_siblings_recall_resolved(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    """The new item links nothing, but the sibling's link still counts as linked."""
    rid = await _recall(db_session, vin)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
        json={"description": "Wipers"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "service_visit")


async def test_a_bad_link_in_a_wider_put_changes_nothing(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    other_vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    mine = await _recall(db_session, vin, campaign="24V100041")
    foreign = await _recall(db_session, other_vin, campaign="24V100042")
    visit = await _create(
        client,
        auth_headers,
        vin,
        [{**_LINE, "is_recall": True, "recall_id": mine}, {**_LINE, "description": "Tie rod"}],
    )
    a, b = _by_desc(visit)["Oil change"], _by_desc(visit)["Tie rod"]
    r = await _put(
        client,
        auth_headers,
        vin,
        visit["id"],
        {
            "date": "2026-11-10",
            "notes": "Changed",
            "line_items": [
                _keep(a, recall_id=None, cost="99.00"),
                _keep(b),
                {"description": "New", "is_recall": True, "recall_id": foreign},
            ],
        },
    )
    assert r.status_code == 422, r.text

    async with test_sessionmaker() as s:
        stored = await s.get(ServiceVisit, visit["id"])
        assert stored is not None
        assert (stored.date, stored.notes) == (date(2026, 11, 3), None)
    assert await _links(test_sessionmaker, visit["id"]) == {
        "Oil change": (True, mine, False, None),
        "Tie rod": (False, None, False, None),
    }
    assert await _state(test_sessionmaker, mine) == (True, _NOON_NOV_3, "service_visit")
    assert await _state(test_sessionmaker, foreign) == (False, None, None)


# --- The recall going away, and who may link -------------------------------


async def test_deleting_the_recall_keeps_the_items_flag(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    rid = await _recall(db_session, vin)
    visit = await _create(
        client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}]
    )
    assert (await _state(test_sessionmaker, rid))[0] is True
    r = await client.delete(f"/api/vehicles/{vin}/recalls/{rid}", headers=auth_headers)
    assert r.status_code == 204, r.text
    assert await _links(test_sessionmaker, visit["id"]) == {"Oil change": (True, None, False, None)}


async def test_a_read_share_cannot_link(
    client: AsyncClient,
    owner_headers: dict[str, str],
    reader_headers: dict[str, str],
    owned_vehicle: Vehicle,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    vin = owned_vehicle.vin
    rid = await _recall(db_session, vin)
    visit = await _create(client, owner_headers, vin, [_LINE])
    try:
        link = _link("recall", rid)
        for path in _PATHS:
            r = await _write_link(client, reader_headers, vin, path, link, visit)
            assert r.status_code == 403, (path, r.text)
        assert await _state(test_sessionmaker, rid) == (False, None, None)
    finally:
        await db_session.rollback()
        async with test_sessionmaker() as s:
            stored = await s.get(ServiceVisit, visit["id"])
            if stored is not None:
                await s.delete(stored)
            recall = await s.get(Recall, rid)
            if recall is not None:
                await s.delete(recall)
            await s.commit()


async def test_a_changed_link_does_not_leave_the_old_relationship_loaded(
    vin: str, db_session: AsyncSession
) -> None:
    """Sessions keep objects across commits, and a load doesn't overwrite a loaded
    relationship, so apply_links has to drop the old one itself."""
    from sqlalchemy.orm import selectinload

    from app.services import recall_links

    r1 = await _recall(db_session, vin, campaign="24V100051")
    r2 = await _recall(db_session, vin, campaign="24V100052")
    visit = ServiceVisit(vin=vin, date=date(2026, 11, 3))
    db_session.add(visit)
    await db_session.flush()
    item = ServiceLineItem(visit_id=visit.id, description="Inflator", is_recall=True, recall_id=r1)
    db_session.add(item)
    await db_session.commit()

    def load() -> Any:
        return (
            select(ServiceLineItem)
            .options(selectinload(ServiceLineItem.recall))
            .where(ServiceLineItem.id == item.id)
        )

    loaded = (await db_session.execute(load())).scalar_one()
    assert loaded.recall is not None and loaded.recall.id == r1

    await recall_links.apply_links(
        db_session, vin, visit.date, [loaded], [(loaded, r2, None)], before=[r1]
    )
    await db_session.commit()

    reloaded = (await db_session.execute(load())).scalar_one()
    assert reloaded.recall is not None and reloaded.recall.id == r2


async def test_linking_reads_the_recall_fresh(
    client: AsyncClient,
    auth_headers: dict[str, str],
    vin: str,
    db_session: AsyncSession,
    test_sessionmaker: Sessions,
) -> None:
    """A copy of the recall the session already holds may be out of date: one
    resolved by hand elsewhere must stay manual when a visit links it."""
    rid = await _recall(db_session, vin)
    held = await db_session.get(Recall, rid)
    assert held is not None and not held.is_resolved
    async with test_sessionmaker() as s:
        other = await s.get(Recall, rid)
        assert other is not None
        other.is_resolved, other.resolved_at, other.resolved_via = True, _YESTERDAY, "manual"
        await s.commit()

    await _create(client, auth_headers, vin, [{**_LINE, "is_recall": True, "recall_id": rid}])
    assert await _state(test_sessionmaker, rid) == (True, _NOON_NOV_3, "manual")
