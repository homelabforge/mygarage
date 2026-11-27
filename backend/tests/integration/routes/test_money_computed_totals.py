"""Money the server computes is checked before it is written.

Every input fits its column (B3), but a sum of inputs may not: a visit total,
a supply cost snapshot, a first spot-rental bill, a policy premium. Past the
column that was a 500 on PostgreSQL and was stored silently on SQLite. Now it's
a 422 that says why, and nothing from the refused request is kept.

"Nothing is kept" is checked with a FRESH session, never the route's own: the
route and these tests share one session, and its identity map would happily
show a value the database never got.
"""

import logging
import uuid
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import Select, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.spot_rental import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.supply import SupplyUsage
from app.models.vehicle import Vehicle
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

CENT = Decimal("0.01")
DAY = "2026-01-15"


async def _new_vehicle(db: AsyncSession, user_id: object, vehicle_type: str) -> str:
    vin = "SUM" + uuid.uuid4().hex[:14].upper()
    db.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname="Big Sums",
            vehicle_type=vehicle_type,
            year=2020,
            make="Winnebago",
            model="View",
            fuel_type="diesel",
        )
    )
    await db.commit()
    return vin


async def _drop_vehicle(db: AsyncSession, vin: str) -> None:
    await db.rollback()
    stored = await db.get(Vehicle, vin)
    if stored is not None:
        await db.delete(stored)
        await db.commit()


@pytest_asyncio.fixture
async def own_vin(db_session: AsyncSession, test_user: dict[str, object]) -> AsyncGenerator[str]:
    """A fresh RV, deleted afterwards with everything on it (supplies are pinned
    to it, so they go too). A VIN, not the row: a refused request rolls the
    shared session back, and an expired row can't be read from async code."""
    vin = await _new_vehicle(db_session, test_user["id"], "RV")
    yield vin
    await _drop_vehicle(db_session, vin)


async def _fresh(sessionmaker: async_sessionmaker[AsyncSession], stmt: Select[Any]) -> Any:
    """One scalar, read through a session the route never touched."""
    async with sessionmaker() as session:
        return (await session.execute(stmt)).scalar()


def _visits_on(vin: str) -> Select[Any]:
    return select(func.count()).select_from(ServiceVisit).where(ServiceVisit.vin == vin)


def _detail(response: Any) -> str:
    return str(response.json().get("detail"))


async def _visit(client: AsyncClient, headers: dict[str, str], vin: str, **body: Any) -> Any:
    payload = {"date": DAY, "service_category": "Maintenance", **body}
    return await client.post(f"/api/vehicles/{vin}/service-visits", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# The visit total
# ---------------------------------------------------------------------------


async def test_a_visit_total_past_the_column_is_a_422_and_nothing_is_kept(
    client, auth_headers, own_vin, test_sessionmaker
):
    # Each line item fits; the two together don't.
    refused = await _visit(
        client,
        auth_headers,
        own_vin,
        line_items=[
            {"description": "Engine", "cost": str(MONEY_MAX)},
            {"description": "Labor", "cost": "0.01"},
        ],
    )
    assert refused.status_code == 422, refused.text
    assert "visit total would exceed the largest amount" in _detail(refused)
    assert await _fresh(test_sessionmaker, _visits_on(own_vin)) == 0

    # The largest total that fits still saves.
    saved = await _visit(
        client,
        auth_headers,
        own_vin,
        line_items=[{"description": "Engine", "cost": str(MONEY_MAX)}],
    )
    assert saved.status_code == 201, saved.text
    assert Decimal(str(saved.json()["total_cost"])) == MONEY_MAX


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"tax_amount": "20.00"}, id="a-fee"),
        pytest.param({"new_item": {"description": "Extra", "cost": "20.00"}}, id="a-new-item"),
    ],
)
async def test_an_edit_past_the_column_changes_nothing(
    client, auth_headers, own_vin, test_sessionmaker, change
):
    start = MONEY_MAX - Decimal("10.00")
    created = await _visit(
        client, auth_headers, own_vin, line_items=[{"description": "Engine", "cost": str(start)}]
    )
    assert created.status_code == 201, created.text
    visit = created.json()
    body: dict[str, Any] = {k: v for k, v in change.items() if k != "new_item"}
    if "new_item" in change:
        item = visit["line_items"][0]
        body["line_items"] = [
            {"id": item["id"], "description": item["description"], "cost": item["cost"]},
            change["new_item"],
        ]

    refused = await client.put(
        f"/api/vehicles/{own_vin}/service-visits/{visit['id']}", json=body, headers=auth_headers
    )
    assert refused.status_code == 422, refused.text
    assert "visit total would exceed the largest amount" in _detail(refused)

    by_id = ServiceVisit.id == visit["id"]
    assert await _fresh(test_sessionmaker, select(ServiceVisit.total_cost).where(by_id)) == start
    assert await _fresh(test_sessionmaker, select(ServiceVisit.tax_amount).where(by_id)) is None
    items = select(func.count()).where(ServiceLineItem.visit_id == visit["id"])
    assert await _fresh(test_sessionmaker, items) == 1


async def test_adding_a_line_item_past_the_column_changes_nothing(
    client, auth_headers, own_vin, test_sessionmaker
):
    created = await _visit(
        client,
        auth_headers,
        own_vin,
        line_items=[{"description": "Engine", "cost": str(MONEY_MAX)}],
    )
    assert created.status_code == 201, created.text
    visit_id = created.json()["id"]

    refused = await client.post(
        f"/api/vehicles/{own_vin}/service-visits/{visit_id}/line-items",
        json={"description": "Labor", "cost": "0.01"},
        headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text
    assert "visit total would exceed the largest amount" in _detail(refused)

    items = select(func.count()).where(ServiceLineItem.visit_id == visit_id)
    assert await _fresh(test_sessionmaker, items) == 1
    total = select(ServiceVisit.total_cost).where(ServiceVisit.id == visit_id)
    assert await _fresh(test_sessionmaker, total) == MONEY_MAX


async def test_linking_a_reminder_past_the_column_changes_nothing(
    client, auth_headers, own_vin, test_sessionmaker
):
    """The reminder's link_visit adds a line item to an existing visit."""
    created = await _visit(
        client, auth_headers, own_vin, line_items=[{"description": "Labor", "cost": str(MONEY_MAX)}]
    )
    assert created.status_code == 201, created.text
    visit_id = created.json()["id"]
    reminder = await client.post(
        f"/api/vehicles/{own_vin}/reminders",
        json={"title": "Oil change", "reminder_type": "date", "due_date": "2026-06-01"},
        headers=auth_headers,
    )
    assert reminder.status_code == 201, reminder.text
    reminder_id = reminder.json()["id"]

    refused = await client.post(
        f"/api/vehicles/{own_vin}/reminders/{reminder_id}/complete",
        json={
            "completed_date": DAY,
            "mode": "link_visit",
            "service_visit_id": visit_id,
            "cost": "0.01",
        },
        headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text
    assert "visit total would exceed the largest amount" in _detail(refused)

    status = select(Reminder.status).where(Reminder.id == reminder_id)
    assert await _fresh(test_sessionmaker, status) == "pending"
    items = select(func.count()).where(ServiceLineItem.visit_id == visit_id)
    assert await _fresh(test_sessionmaker, items) == 1


@contextmanager
def _flushed_visit_totals() -> Iterator[list[Decimal | None]]:
    """Every total_cost a flush writes to service_visits, in order."""
    seen: list[Decimal | None] = []

    def record(_mapper: Any, _connection: Any, target: ServiceVisit) -> None:
        seen.append(target.total_cost)

    event.listen(ServiceVisit, "before_insert", record)
    event.listen(ServiceVisit, "before_update", record)
    try:
        yield seen
    finally:
        event.remove(ServiceVisit, "before_insert", record)
        event.remove(ServiceVisit, "before_update", record)


async def test_a_client_visit_total_is_never_written(client, auth_headers, own_vin):
    """The server always computes the total, so the client's is ignored, not
    written and then overwritten. That holds with no line items left, too."""
    sent = Decimal("12345.67")
    with _flushed_visit_totals() as flushed:
        created = await _visit(
            client,
            auth_headers,
            own_vin,
            total_cost=str(sent),
            line_items=[{"description": "Oil", "cost": "10.00"}],
        )
    assert created.status_code == 201, created.text
    assert Decimal(str(created.json()["total_cost"])) == Decimal("10.00")
    assert sent not in flushed, flushed

    url = f"/api/vehicles/{own_vin}/service-visits/{created.json()['id']}"
    with _flushed_visit_totals() as flushed:
        edited = await client.put(url, json={"total_cost": str(sent)}, headers=auth_headers)
    assert edited.status_code == 200, edited.text
    assert Decimal(str(edited.json()["total_cost"])) == Decimal("10.00")
    assert sent not in flushed, flushed

    # Every line item removed: the total is the fees alone.
    with _flushed_visit_totals() as flushed:
        emptied = await client.put(
            url,
            json={"total_cost": str(sent), "line_items": [], "tax_amount": "5.00"},
            headers=auth_headers,
        )
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["line_items"] == []
    assert Decimal(str(emptied.json()["total_cost"])) == Decimal("5.00")
    assert sent not in flushed, flushed


# ---------------------------------------------------------------------------
# Supply snapshots
# ---------------------------------------------------------------------------


async def _supply(
    client: AsyncClient, headers: dict[str, str], vin: str, quantity: str, total_cost: str
) -> int:
    """A supply pinned to `vin` with one purchase: avg cost = total / quantity."""
    created = await client.post(
        "/api/supplies",
        json={"name": "Gold oil", "unit_type": "volume", "vin": vin},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    supply_id = created.json()["id"]
    bought = await client.post(
        f"/api/supplies/{supply_id}/purchases",
        json={"date": DAY, "quantity": quantity, "total_cost": total_cost},
        headers=headers,
    )
    assert bought.status_code == 201, bought.text
    return supply_id


def _usages_of(supply_id: int) -> Select[Any]:
    return select(func.count()).select_from(SupplyUsage).where(SupplyUsage.supply_id == supply_id)


async def test_a_unit_cost_past_its_column_is_a_422(
    client, auth_headers, own_vin, test_sessionmaker
):
    # MONEY_MAX for a thousandth of a litre: 9,999,999,999,990 a litre.
    supply_id = await _supply(client, auth_headers, own_vin, "0.001", str(MONEY_MAX))

    refused = await client.post(
        f"/api/supplies/{supply_id}/adjustments", json={"quantity": "1"}, headers=auth_headers
    )
    assert refused.status_code == 422, refused.text
    assert f"unit cost of supply {supply_id} would exceed" in _detail(refused)
    assert str(UNIT_COST_MAX) in _detail(refused)

    used = await _visit(
        client,
        auth_headers,
        own_vin,
        line_items=[
            {
                "description": "Oil",
                "cost": "0",
                "supplies_used": [{"supply_id": supply_id, "quantity": "0.001"}],
            }
        ],
    )
    assert used.status_code == 422, used.text
    assert f"unit cost of supply {supply_id} would exceed" in _detail(used)

    assert await _fresh(test_sessionmaker, _usages_of(supply_id)) == 0
    assert await _fresh(test_sessionmaker, _visits_on(own_vin)) == 0


async def test_a_cost_snapshot_past_its_column_is_a_422(
    client, auth_headers, own_vin, test_sessionmaker
):
    supply_id = await _supply(client, auth_headers, own_vin, "1", str(MONEY_MAX))

    refused = await client.post(
        f"/api/supplies/{supply_id}/adjustments", json={"quantity": "2"}, headers=auth_headers
    )
    assert refused.status_code == 422, refused.text
    assert f"cost of this much of supply {supply_id} would exceed" in _detail(refused)
    assert await _fresh(test_sessionmaker, _usages_of(supply_id)) == 0

    # Exactly the column's largest amount fits.
    saved = await client.post(
        f"/api/supplies/{supply_id}/adjustments", json={"quantity": "1"}, headers=auth_headers
    )
    assert saved.status_code == 201, saved.text
    assert Decimal(str(saved.json()["cost_snapshot"])) == MONEY_MAX


async def test_a_new_quantity_on_an_existing_usage_past_the_column_changes_nothing(
    client, auth_headers, own_vin, test_sessionmaker
):
    """Codex R1-F2: the visit edit recomputes an existing usage's cost itself,
    not through SupplyService, so it needs its own check."""
    # 4,999,999,999.995 a litre: one litre costs 5,000,000,000.00, three don't fit.
    supply_id = await _supply(client, auth_headers, own_vin, "2", str(MONEY_MAX))
    created = await _visit(
        client,
        auth_headers,
        own_vin,
        line_items=[
            {
                "description": "Oil",
                "cost": "0",
                "supplies_used": [{"supply_id": supply_id, "quantity": "1"}],
            }
        ],
    )
    assert created.status_code == 201, created.text
    visit = created.json()
    item = visit["line_items"][0]
    before = Decimal("5000000000.00")
    assert Decimal(str(item["supply_usages"][0]["cost_snapshot"])) == before

    refused = await client.put(
        f"/api/vehicles/{own_vin}/service-visits/{visit['id']}",
        json={
            "line_items": [
                {
                    "id": item["id"],
                    "description": item["description"],
                    "cost": item["cost"],
                    "supplies_used": [{"supply_id": supply_id, "quantity": "3"}],
                }
            ]
        },
        headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text
    # The usage's own check, ahead of the visit total's.
    assert f"cost of this much of supply {supply_id} would exceed" in _detail(refused)

    usage = SupplyUsage.supply_id == supply_id
    assert await _fresh(test_sessionmaker, select(SupplyUsage.quantity).where(usage)) == 1
    assert await _fresh(test_sessionmaker, select(SupplyUsage.cost_snapshot).where(usage)) == before
    total = select(ServiceVisit.total_cost).where(ServiceVisit.id == visit["id"])
    assert await _fresh(test_sessionmaker, total) == before


# ---------------------------------------------------------------------------
# The first spot-rental bill (Codex R1-H1)
# ---------------------------------------------------------------------------


def _rentals_on(vin: str) -> Select[Any]:
    return select(func.count()).select_from(SpotRental).where(SpotRental.vin == vin)


def _bills_on(vin: str) -> Select[Any]:
    return (
        select(func.count())
        .select_from(SpotRentalBilling)
        .join(SpotRental, SpotRentalBilling.spot_rental_id == SpotRental.id)
        .where(SpotRental.vin == vin)
    )


async def test_a_first_bill_past_the_column_keeps_no_rental(
    client, auth_headers, own_vin, test_sessionmaker
):
    """The rental used to be committed before its bill was built, so a bill that
    failed left a rental with no bill, and a retry made a second rental."""
    url = f"/api/vehicles/{own_vin}/spot-rentals"
    body = {"location_name": "Lakeside", "check_in_date": DAY, "monthly_rate": str(MONEY_MAX)}

    refused = await client.post(url, json={**body, "electric": "0.01"}, headers=auth_headers)
    assert refused.status_code == 422, refused.text
    assert "first bill" in _detail(refused)
    assert "would exceed the largest amount" in _detail(refused)
    assert await _fresh(test_sessionmaker, _rentals_on(own_vin)) == 0
    assert await _fresh(test_sessionmaker, _bills_on(own_vin)) == 0

    retried = await client.post(url, json=body, headers=auth_headers)
    assert retried.status_code == 201, retried.text
    assert await _fresh(test_sessionmaker, _rentals_on(own_vin)) == 1
    assert await _fresh(test_sessionmaker, _bills_on(own_vin)) == 1
    (bill,) = retried.json()["billings"]
    assert Decimal(str(bill["total"])) == MONEY_MAX


# ---------------------------------------------------------------------------
# The window-sticker OCR upload
# ---------------------------------------------------------------------------


async def test_a_parsed_amount_outside_its_column_is_dropped(
    client, auth_headers, own_vin, test_sessionmaker, caplog
):
    """An OCR misread is not a price. It used to be written, a 500 on PostgreSQL
    after the upload was already on disk."""
    parsed = {
        "msrp_total": Decimal("1e12"),
        "msrp_base": Decimal("-1.00"),
        "msrp_options": Decimal("1500.00"),
        "destination_charge": MONEY_MAX,
        # Not a number at all: Decimal() raises on it, and the drop catches that.
        "fuel_economy_combined_l_per_100km": "twelve",
        "exterior_color": "Blue",
    }
    with patch("app.services.window_sticker_service.WindowStickerOCRService") as ocr_class:
        ocr = MagicMock()
        ocr.extract_data_from_file = AsyncMock(return_value=parsed)
        ocr_class.return_value = ocr
        with caplog.at_level(logging.WARNING, logger="app.services.window_sticker_service"):
            uploaded = await client.post(
                f"/api/vehicles/{own_vin}/window-sticker/upload",
                files={"file": ("sticker.pdf", b"%PDF-1.4 sticker", "application/pdf")},
                headers=auth_headers,
            )

    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["msrp_total"] is None
    assert body["msrp_base"] is None
    assert Decimal(str(body["msrp_options"])) == Decimal("1500.00")
    assert Decimal(str(body["destination_charge"])) == MONEY_MAX
    assert body["fuel_economy_combined_l_per_100km"] is None
    assert body["exterior_color"] == "Blue"

    row = Vehicle.vin == own_vin
    assert await _fresh(test_sessionmaker, select(Vehicle.msrp_total).where(row)) is None
    assert await _fresh(test_sessionmaker, select(Vehicle.msrp_base).where(row)) is None
    dropped = " ".join(r.getMessage() for r in caplog.records)
    for key in ("msrp_total", "msrp_base", "fuel_economy_combined_l_per_100km"):
        assert key in dropped, dropped


# ---------------------------------------------------------------------------
# A policy premium grown by an attached vehicle's share
# ---------------------------------------------------------------------------


async def test_attaching_a_share_past_the_column_changes_nothing(
    client, auth_headers, own_vin, db_session, test_user, test_sessionmaker
):
    second = await _new_vehicle(db_session, test_user["id"], "Car")
    policy_id = None
    try:
        created = await client.post(
            "/api/insurance/policies",
            json={
                "provider": "Big Sums Mutual",
                "policy_number": "BIG-" + uuid.uuid4().hex[:8],
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "premium_amount": str(MONEY_MAX),
                "vehicles": [{"vin": own_vin, "policy_type": "Liability"}],
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["id"]

        refused = await client.post(
            f"/api/insurance/policies/{policy_id}/vehicles",
            json={"vin": second, "policy_type": "Liability", "premium_share": "0.01"},
            headers=auth_headers,
        )
        assert refused.status_code == 422, refused.text
        assert "policy premium would exceed the largest amount" in _detail(refused)

        premium = select(InsurancePolicy.premium_amount).where(InsurancePolicy.id == policy_id)
        assert await _fresh(test_sessionmaker, premium) == MONEY_MAX
        links = select(func.count()).where(InsurancePolicyVehicle.policy_id == policy_id)
        assert await _fresh(test_sessionmaker, links) == 1
    finally:
        await db_session.rollback()
        if policy_id is not None:
            policy = await db_session.get(InsurancePolicy, policy_id)
            if policy is not None:
                await db_session.delete(policy)
                await db_session.commit()
        await _drop_vehicle(db_session, second)
