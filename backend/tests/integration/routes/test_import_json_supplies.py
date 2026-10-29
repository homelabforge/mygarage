"""Supplies in the JSON backup: pinned supplies whole, and what each line item used (task 9, K12)."""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ServiceLineItem, ServiceVisit
from app.models.address_book import AddressBookEntry
from app.models.settings import Setting
from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.models.vehicle import Vehicle
from tests.integration.routes._json_backup import V9, export_json, import_json

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _tag() -> str:
    # Shared supplies and address-book rows outlive the test's vehicles.
    return uuid.uuid4().hex[:8]


async def _seed(db_session: AsyncSession, vin: str, tag: str) -> dict[str, Any]:
    """A pinned oil with two purchases and an adjustment, and a visit that used it and a shared filter."""
    shop = AddressBookEntry(business_name=f"B3 Parts {tag}")
    oil = Supply(
        name=f"Mobil 1 {tag}",
        part_number="M1-5W30",
        barcode="0071924",
        category="oil",
        unit_type="volume",
        volume_unit="qt_us",
        vin=vin,
        notes="the good stuff",
    )
    shared = Supply(name=f"Filter {tag}", part_number="PH7317", unit_type="count")
    visit = ServiceVisit(
        vin=vin,
        date=date(2026, 5, 1),
        odometer_km=Decimal("40000.00"),
        service_category="Maintenance",
        tax_amount=Decimal("2.00"),
        total_cost=Decimal("0"),
    )
    db_session.add_all([shop, oil, shared, visit])
    await db_session.flush()
    item = ServiceLineItem(visit_id=visit.id, description="Oil change", cost=Decimal("20.00"))
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(
                supply_id=oil.id,
                date=date(2026, 4, 1),
                quantity=Decimal("4.7317647"),
                total_cost=Decimal("30.00"),
                supplier_id=shop.id,
                part_number="M1-5W30-5QT",
                notes="jug",
            ),
            SupplyPurchase(supply_id=oil.id, date=date(2026, 4, 20), quantity=Decimal("0.946353")),
            SupplyPurchase(supply_id=shared.id, date=date(2026, 4, 1), quantity=Decimal("3")),
            # A spill: a standalone usage, dated by when it was logged.
            SupplyUsage(
                supply_id=oil.id,
                quantity=Decimal("0.25"),
                unit_cost_snapshot=Decimal("6.3400"),
                cost_snapshot=Decimal("1.59"),
                created_at=datetime(2026, 4, 25, 10, 0),
            ),
            SupplyUsage(
                supply_id=oil.id,
                service_line_item_id=item.id,
                quantity=Decimal("4.4"),
                unit_cost_snapshot=Decimal("6.3400"),
                cost_snapshot=Decimal("27.90"),
            ),
            SupplyUsage(
                supply_id=shared.id,
                service_line_item_id=item.id,
                quantity=Decimal("1"),
                unit_cost_snapshot=Decimal("8.5000"),
                cost_snapshot=Decimal("8.50"),
            ),
        ]
    )
    await db_session.commit()
    return {"oil": oil.id, "shared": shared.id, "shop": shop.id}


_SUPPLY_SKIP = {"id", "vin", "created_by_user_id", "created_at", "updated_at"}


def _columns(row: Any, skip: set[str]) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key not in skip}


async def _pinned(db_session: AsyncSession, vin: str) -> list[dict[str, Any]]:
    """The vehicle's pinned supplies with their purchases and adjustments, ids out."""
    db_session.expire_all()
    supplies = (
        (
            await db_session.execute(
                select(Supply)
                .where(Supply.vin == vin)
                .options(selectinload(Supply.purchases), selectinload(Supply.usages))
                .order_by(Supply.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            **_columns(s, _SUPPLY_SKIP),
            "purchases": sorted(
                (_columns(p, {"id", "supply_id", "created_at"}) for p in s.purchases),
                key=lambda p: (p["date"], p["quantity"]),
            ),
            "adjustments": sorted(
                (
                    _columns(u, {"id", "supply_id", "service_line_item_id"})
                    for u in s.usages
                    if u.service_line_item_id is None
                ),
                key=lambda u: u["quantity"],
            ),
        }
        for s in supplies
    ]


async def _visit(db_session: AsyncSession, vin: str) -> ServiceVisit:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(ServiceVisit)
            .where(ServiceVisit.vin == vin)
            .options(
                selectinload(ServiceVisit.line_items).selectinload(ServiceLineItem.supply_usages)
            )
        )
    ).scalar_one()


async def _usages_of(db_session: AsyncSession, supply_id: int) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(SupplyUsage).where(SupplyUsage.supply_id == supply_id)
        )
    ).scalar_one()


# -- K12: pinned supplies whole, usages under their line item --------------------


async def test_supplies_round_trip_into_an_empty_vehicle(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    source = await new_vehicle()
    target = await new_vehicle()
    ids = await _seed(db_session, source, tag)

    backup = await export_json(client, auth_headers, source)
    data = await import_json(client, auth_headers, target, backup)

    assert data["errors"] == []
    # The filter is shared and already here: looked up, not added.
    assert data["warnings"] == []
    # main: KeyError, no supplies bucket.
    assert data["supplies"]["success_count"] == 1
    assert await _pinned(db_session, target) == await _pinned(db_session, source)

    [copy_id] = (
        (await db_session.execute(select(Supply.id).where(Supply.vin == target))).scalars().all()
    )
    visit = await _visit(db_session, target)
    [item] = visit.line_items
    assert sorted(
        (u.supply_id, u.quantity, u.unit_cost_snapshot, u.cost_snapshot) for u in item.supply_usages
    ) == sorted(
        [
            (copy_id, Decimal("4.4"), Decimal("6.3400"), Decimal("27.90")),
            (ids["shared"], Decimal("1"), Decimal("8.5000"), Decimal("8.50")),
        ]
    )
    # The item, the supplies used on it and the tax.
    assert visit.total_cost == Decimal("58.40")


async def test_the_export_names_a_supply_by_index_or_by_key(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    vin = await new_vehicle()
    await _seed(db_session, vin, tag)
    backup = await export_json(client, auth_headers, vin)
    # main: KeyError, no supplies section.
    [oil] = backup["supplies"]
    assert oil["purchases"][0]["supplier_name"] == f"B3 Parts {tag}"
    assert [u["created_at"] for u in oil["usages"]] == ["2026-04-25T10:00:00"]
    # 29e738c9: KeyError. Nothing else used it, so there's nothing to point at.
    assert oil["used_elsewhere"] == []
    usages = backup["service_visits"][0]["line_items"][0]["supply_usages"]
    assert [u["supply"] for u in usages] == [
        {"index": 0},
        {
            "name": f"Filter {tag}",
            "part_number": "PH7317",
            "unit_type": "count",
            "volume_unit": None,
        },
    ]


async def test_a_shared_supply_missing_here_is_added_with_no_stock(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Mobil 1 5W-30 {_tag()}"
    vin = await new_vehicle()
    payload = {
        **V9,
        "service_visits": [
            {
                "date": "2026-05-01",
                "line_items": [
                    {
                        "description": "Oil change",
                        "cost": 20,
                        "supply_usages": [
                            {
                                "supply": {
                                    "name": name,
                                    "part_number": None,
                                    "unit_type": "volume",
                                    "volume_unit": "qt_us",
                                },
                                "quantity": 4.7,
                                "unit_cost_snapshot": 2.5,
                                "cost_snapshot": 11.75,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    data = await import_json(client, auth_headers, vin, payload)
    # main: no warning, the usage is never read.
    assert data["warnings"] == [
        f"Supply \"{name}\" wasn't in this household's supplies, so it was added with no stock"
    ]
    [added] = (await db_session.execute(select(Supply).where(Supply.name == name))).scalars().all()
    assert (added.vin, added.unit_type, added.volume_unit) == (None, "volume", "qt_us")
    assert await _usages_of(db_session, added.id) == 1
    assert (await _visit(db_session, vin)).total_cost == Decimal("31.75")


async def test_a_reimport_into_the_source_takes_no_stock_twice(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    vin = await new_vehicle()
    ids = await _seed(db_session, vin, tag)
    before = await _pinned(db_session, vin)
    backup = await export_json(client, auth_headers, vin)

    data = await import_json(client, auth_headers, vin, backup)
    # main: KeyError, no supplies bucket.
    assert data["supplies"]["skipped_count"] == 1
    assert data["service_records"]["skipped_count"] == 1
    assert data["warnings"] == [
        "Supplies: this vehicle already has supplies pinned to it, "
        "so the file's pinned supplies weren't imported"
    ]
    assert await _pinned(db_session, vin) == before
    assert await _usages_of(db_session, ids["shared"]) == 1
    assert await _usages_of(db_session, ids["oil"]) == 2


async def test_a_new_visit_links_to_the_pinned_supply_already_here(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    vin = await new_vehicle()
    ids = await _seed(db_session, vin, tag)
    backup = await export_json(client, auth_headers, vin)
    # A second visit in the file that this vehicle doesn't have yet.
    second = {**backup["service_visits"][0], "date": "2026-08-01", "odometer_km": 45000}
    second["line_items"] = [
        {**second["line_items"][0], "supply_usages": [second["line_items"][0]["supply_usages"][0]]}
    ]
    backup["service_visits"].append(second)

    data = await import_json(client, auth_headers, vin, backup)
    assert data["service_records"]["success_count"] == 1
    # The pinned family skipped, so index 0 resolves to the oil pinned here.
    assert await _usages_of(db_session, ids["oil"]) == 3


_SUPPLY = {"name": "Rags", "unit_type": "count", "purchases": [], "usages": []}

_REFUSED = [
    pytest.param(
        {**_SUPPLY, "volume_unit": "qt_us"},
        "Supply 1: A count supply cannot carry a volume unit",
        id="count-with-volume-unit",
    ),
    pytest.param(
        {**_SUPPLY, "unit_type": "box"},
        "Supply 1: unit_type must be one of volume, count",
        id="unit-type-word",
    ),
    pytest.param(
        {**_SUPPLY, "purchases": [{"date": "2026-01-01", "quantity": 0}]},
        "Supply 1, purchase 0: quantity must be more than 0, not 0",
        id="purchase-quantity",
    ),
    pytest.param(
        {**_SUPPLY, "usages": "none"},
        "Supply 1: usages must be a list",
        id="usages-not-a-list",
    ),
]


@pytest.mark.parametrize(("supply", "reason"), _REFUSED)
async def test_a_bad_pinned_supply_refuses_the_family(
    supply: dict[str, Any],
    reason: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    vin = await new_vehicle()
    data = await import_json(client, auth_headers, vin, {**V9, "supplies": [_SUPPLY, supply]})
    # main: the section is never read.
    assert data["errors"] == [f"{reason}, so the file's pinned supplies weren't imported"]
    assert data["supplies"]["error_count"] == 2
    assert await _pinned(db_session, vin) == []


_RAGS = {"name": "Rags", "part_number": None, "unit_type": "count", "volume_unit": None}

_BAD_USAGES = [
    pytest.param(
        {"supply": {"index": 0}, "quantity": 1},
        "index must be the index of a supply in this file",
        id="index-out-of-range",
    ),
    pytest.param(
        {"supply": _RAGS, "quantity": 1, "cost_snapshot": "NaN"},
        "cost_snapshot must be a number",
        id="nan-cost-snapshot",
    ),
    pytest.param(
        {"supply": _RAGS, "quantity": 1, "unit_cost_snapshot": -1},
        "unit_cost_snapshot must be at least 0, not -1",
        id="negative-unit-cost-snapshot",
    ),
    pytest.param(
        {"supply": {**_RAGS, "volume_unit": "qt_us"}, "quantity": 1},
        "A count supply cannot carry a volume unit",
        id="keyed-count-with-volume-unit",
    ),
]


@pytest.mark.parametrize(("usage", "reason"), _BAD_USAGES)
async def test_a_bad_usage_is_its_visits_row_error(
    usage: dict[str, Any],
    reason: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    vin = await new_vehicle()
    item = {"description": "Oil change", "supply_usages": [usage]}
    data = await import_json(
        client,
        auth_headers,
        vin,
        {**V9, "service_visits": [{"date": "2026-05-01", "line_items": [item]}]},
    )
    # main: the usage is never read, so the visit imports.
    assert data["errors"] == [f"Service visit 0: line item 0, supply usage 0: {reason}"]
    assert data["service_records"]["error_count"] == 1


async def test_a_refused_familys_bad_row_says_refused_without_duplicate_checks(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    payload = {
        **V9,
        "supplies": [{"name": "Rags", "unit_type": "box"}],
        "service_visits": [_visit_using("2026-05-01", ({"index": 0}, 1))],
    }
    data = await import_json(client, auth_headers, vin, payload, skip_duplicates=False)
    # No key to build, so the row's own reason doesn't come up; the refusal does.
    # main: neither section is read, so no errors.
    assert data["errors"] == [
        "Supply 0: unit_type must be one of volume, count, "
        "so the file's pinned supplies weren't imported",
        'Service visit 0: line item 0, supply usage 0: the pinned supply "Rags" '
        "was refused with its family",
    ]


async def test_a_supplier_missing_here_is_left_off_with_a_warning(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    purchase = {"date": "2026-01-01", "quantity": 2, "supplier_name": f"Nowhere {_tag()}"}
    data = await import_json(
        client, auth_headers, vin, {**V9, "supplies": [{**_SUPPLY, "purchases": [purchase]}]}
    )
    # main: no warning; the section is never read.
    assert data["warnings"] == [
        "Supply 0, purchase 0: its supplier isn't in this address book, so it was saved without one"
    ]
    [supply] = await _pinned(db_session, vin)
    assert [p["supplier_id"] for p in supply["purchases"]] == [None]


def _added(name: str) -> str:
    return f"Supply \"{name}\" wasn't in this household's supplies, so it was added with no stock"


def _shared_ref(name: str) -> dict[str, Any]:
    return {"name": name, "part_number": None, "unit_type": "count", "volume_unit": None}


def _visit_using(day: str, *usages: tuple[dict[str, Any], int]) -> dict[str, Any]:
    return {
        "date": day,
        "line_items": [
            {
                "description": "Shop job",
                "cost": 10,
                "supply_usages": [{"supply": ref, "quantity": qty} for ref, qty in usages],
            }
        ],
    }


async def _usages_by_name(db_session: AsyncSession, vin: str) -> list[tuple[str, Decimal]]:
    db_session.expire_all()
    rows = await db_session.execute(
        select(Supply.name, SupplyUsage.quantity)
        .join(SupplyUsage, SupplyUsage.supply_id == Supply.id)
        .join(ServiceLineItem, SupplyUsage.service_line_item_id == ServiceLineItem.id)
        .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
        .where(ServiceVisit.vin == vin)
    )
    return sorted((name, quantity) for name, quantity in rows.all())


# -- R1-H1: a failed visit takes its added supply, and its warning, with it -------


async def test_a_failed_visit_leaves_nothing_behind_for_the_next(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    first, second = f"Added one {tag}", f"Added two {tag}"
    vin = await new_vehicle()
    payload = {
        **V9,
        # A refused family, so a usage that points into it fails its visit.
        "supplies": [
            {
                "name": f"Rags {tag}",
                "unit_type": "count",
                "purchases": [{"date": "2026-01-01", "quantity": 0}],
            }
        ],
        "service_visits": [
            # Adds `first`, then fails on the refused supply: `first` goes back.
            _visit_using("2026-05-01", (_shared_ref(first), 1), ({"index": 0}, 1)),
            # SQLite hands `second` the id `first` had. A stale cache would point
            # the `first` usage at it.
            _visit_using("2026-06-01", (_shared_ref(second), 2), (_shared_ref(first), 3)),
        ],
    }
    data = await import_json(client, auth_headers, vin, payload)
    # main: neither the supplies nor the usages are read, so no errors.
    assert data["errors"] == [
        "Supply 0, purchase 0: quantity must be more than 0, not 0, "
        "so the file's pinned supplies weren't imported",
        f'Service visit 0: line item 0, supply usage 1: the pinned supply "Rags {tag}" '
        "was refused with its family",
    ]
    assert data["service_records"]["success_count"] == 1
    # Each added once, each warned about once: the first visit's warning went back with it.
    assert data["warnings"] == [_added(second), _added(first)]
    assert await _usages_by_name(db_session, vin) == [
        (first, Decimal("3")),
        (second, Decimal("2")),
    ]
    for name in (first, second):
        assert (
            await db_session.execute(
                select(func.count()).select_from(Supply).where(Supply.name == name)
            )
        ).scalar_one() == 1, name


# -- R1-H2: a refused family stays refused --------------------------------------


async def test_a_refused_family_leaves_no_fragment_and_a_fixed_file_restores_it(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    oil = f"Oil {_tag()}"
    vin = await new_vehicle()
    supply = {"name": oil, "unit_type": "volume", "volume_unit": "qt_us"}
    visit = _visit_using("2026-05-01", ({"index": 0}, 4))

    bad = {**supply, "purchases": [{"date": "2026-04-01", "quantity": 0}]}
    data = await import_json(
        client, auth_headers, vin, {**V9, "supplies": [bad], "service_visits": [visit]}
    )
    # main: the supplies and usages are never read, so the visit imports bare.
    assert data["errors"] == [
        "Supply 0, purchase 0: quantity must be more than 0, not 0, "
        "so the file's pinned supplies weren't imported",
        f'Service visit 0: line item 0, supply usage 0: the pinned supply "{oil}" '
        "was refused with its family",
    ]
    assert await _pinned(db_session, vin) == []
    assert (
        await db_session.execute(select(func.count()).select_from(Supply).where(Supply.name == oil))
    ).scalar_one() == 0

    good = {**supply, "purchases": [{"date": "2026-04-01", "quantity": 5}]}
    data = await import_json(
        client, auth_headers, vin, {**V9, "supplies": [good], "service_visits": [visit]}
    )
    assert (data["errors"], data["warnings"]) == ([], [])
    assert data["supplies"]["success_count"] == 1
    assert data["service_records"]["success_count"] == 1
    [restored] = await _pinned(db_session, vin)
    assert [p["quantity"] for p in restored["purchases"]] == [Decimal("5")]
    assert await _usages_by_name(db_session, vin) == [(oil, Decimal("4"))]


# -- A supply used on another vehicle's visit travels as a reference -----------


async def _start_over(db_session: AsyncSession, *vins: str, gone: tuple[str, ...] = ()) -> None:
    """Delete the vehicles, then add `vins` back empty, as a fresh instance has them.

    A vehicle takes its visits and pinned supplies with it, and their usages.
    The session forgets every row, so a test reads its ids before this.
    """
    owners = dict(
        (
            await db_session.execute(
                select(Vehicle.vin, Vehicle.user_id).where(Vehicle.vin.in_(vins))
            )
        ).all()
    )
    await db_session.execute(
        delete(Vehicle).where(Vehicle.vin.in_((*vins, *gone))),
        execution_options={"synchronize_session": False},
    )
    db_session.expunge_all()
    db_session.add_all(
        Vehicle(
            vin=vin,
            user_id=owners[vin],
            nickname=vin,
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Backup",
        )
        for vin in vins
    )
    await db_session.commit()


async def _jug_used_on_b(db_session: AsyncSession, name: str, a: str, b: str) -> int:
    """Bought 10 while shared, 3 used on B's visit, then pinned to A. Hands back B's item."""
    jug = Supply(name=name, unit_type="count")
    job = ServiceVisit(vin=b, date=date(2026, 3, 1), service_category="Maintenance")
    db_session.add_all([jug, job])
    await db_session.flush()
    item = ServiceLineItem(visit_id=job.id, description="Top up")
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=jug.id, date=date(2026, 2, 1), quantity=Decimal("10")),
            SupplyUsage(
                supply_id=jug.id,
                service_line_item_id=item.id,
                quantity=Decimal("3"),
                unit_cost_snapshot=Decimal("1.5000"),
                cost_snapshot=Decimal("4.50"),
            ),
        ]
    )
    await db_session.flush()
    jug.vin = a
    await db_session.commit()
    return item.id


async def _supply_ids(db_session: AsyncSession, name: str) -> list[int]:
    db_session.expire_all()
    rows = await db_session.execute(
        select(Supply.id).where(Supply.name == name).order_by(Supply.id)
    )
    return list(rows.scalars().all())


async def _balance(db_session: AsyncSession, supply_id: int) -> Decimal:
    """Bought less used, over the supply's whole ledger."""
    db_session.expire_all()
    bought = (
        await db_session.execute(
            select(func.coalesce(func.sum(SupplyPurchase.quantity), 0)).where(
                SupplyPurchase.supply_id == supply_id
            )
        )
    ).scalar_one()
    used = (
        await db_session.execute(
            select(func.coalesce(func.sum(SupplyUsage.quantity), 0)).where(
                SupplyUsage.supply_id == supply_id
            )
        )
    ).scalar_one()
    return Decimal(str(bought)) - Decimal(str(used))


def _not_counted(name: str, quantity: str, vin: str, day: str) -> str:
    return (
        f'{quantity} of supply "{name}" was used on {vin}\'s service on {day}, '
        "which isn't here, so it isn't counted"
    )


async def test_a_use_on_another_vehicles_visit_travels_as_a_reference(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    await _jug_used_on_b(db_session, name, a, b)

    backup = await export_json(client, auth_headers, a)
    [exported] = backup["supplies"]
    # 29e738c9: KeyError, B's use went out as a standalone usage.
    used = exported["used_elsewhere"]
    assert [{**u, "quantity": Decimal(u["quantity"])} for u in used] == [
        {
            "vin": b,
            "date": "2026-03-01",
            "description": "Top up",
            "quantity": Decimal("3"),
            "unit_cost_snapshot": 1.5,
            "cost_snapshot": 4.5,
        }
    ]
    # Only the purchase is A's own ledger; the use is B's, by reference.
    assert exported["usages"] == []
    assert [Decimal(p["quantity"]) for p in exported["purchases"]] == [Decimal("10")]
    assert backup["service_visits"] == []


async def test_restoring_only_the_supplys_vehicle_warns_about_the_use_it_cant_count(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    await _jug_used_on_b(db_session, name, a, b)
    backup_a = await export_json(client, auth_headers, a)

    await _start_over(db_session, a, gone=(b,))
    data = await import_json(client, auth_headers, a, backup_a)

    assert data["errors"] == []
    # 29e738c9: [], the use came back as a standalone usage and the balance read 7.
    assert data["warnings"] == [_not_counted(name, "3", b, "2026-03-01")]
    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("10")
    assert await _usages_of(db_session, copy_id) == 0


async def test_restoring_the_supplys_vehicle_then_the_one_that_used_it_counts_the_use_once(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    await _jug_used_on_b(db_session, name, a, b)
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    await _start_over(db_session, a, b)
    first = await import_json(client, auth_headers, a, backup_a)
    second = await import_json(client, auth_headers, b, backup_b)

    # 29e738c9: A's restore said nothing and wrote B's use as its own.
    assert (first["errors"], first["warnings"]) == (
        [],
        [_not_counted(name, "3", b, "2026-03-01")],
    )
    # B's visit finds A's supply by its key and writes its use there.
    assert (second["errors"], second["warnings"]) == ([], [])
    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("7")
    assert await _usages_of(db_session, copy_id) == 1
    assert await _usages_by_name(db_session, b) == [(name, Decimal("3"))]


async def test_restoring_the_vehicle_that_used_it_then_the_supplys_counts_the_use_once(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    await _jug_used_on_b(db_session, name, a, b)
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    await _start_over(db_session, a, b)
    first = await import_json(client, auth_headers, b, backup_b)
    # A isn't here yet, so B's use lands on a bare shared jug.
    assert (first["errors"], first["warnings"]) == ([], [_added(name)])
    second = await import_json(client, auth_headers, a, backup_a)
    assert (second["errors"], second["warnings"]) == ([], [])

    # 29e738c9: two jugs, the bare one at -3 and A's at 7 with B's use again.
    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("7")
    assert await _usages_of(db_session, copy_id) == 1
    assert await _usages_by_name(db_session, b) == [(name, Decimal("3"))]
    [restored] = await _pinned(db_session, a)
    assert restored["adjustments"] == []


async def test_restoring_a_deleted_supplys_vehicle_gives_the_other_visit_its_use_back(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    item_id = await _jug_used_on_b(db_session, name, a, b)
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    # Deleting A takes its jug, and B's use of it, with it.
    await _start_over(db_session, a)
    data = await import_json(client, auth_headers, a, backup_a)
    assert (data["errors"], data["warnings"]) == ([], [])

    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("7")
    # 29e738c9: 0, the use came back standalone and B's item stayed bare.
    assert (
        await db_session.execute(
            select(SupplyUsage.supply_id, SupplyUsage.quantity).where(
                SupplyUsage.service_line_item_id == item_id
            )
        )
    ).all() == [(copy_id, Decimal("3"))]

    # B's own backup now matches what's stored, so a re-import adds nothing.
    again = await import_json(client, auth_headers, b, backup_b)
    assert (
        again["service_records"]["success_count"],
        again["service_records"]["skipped_count"],
    ) == (
        0,
        1,
    )
    assert await _usages_of(db_session, copy_id) == 1


async def test_each_use_elsewhere_takes_one_stored_usage(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Can {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    # Two jobs of 2 on B's visit with one name, and A's own adjustment of 2 that day.
    can = Supply(name=name, unit_type="count")
    job = ServiceVisit(vin=b, date=date(2026, 3, 1), service_category="Maintenance")
    db_session.add_all([can, job])
    await db_session.flush()
    items = [ServiceLineItem(visit_id=job.id, description="Job") for _ in range(2)]
    db_session.add_all(items)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=can.id, date=date(2026, 2, 1), quantity=Decimal("10")),
            SupplyUsage(
                supply_id=can.id,
                quantity=Decimal("2"),
                created_at=datetime(2026, 3, 1, 12, 0),
            ),
            *(
                SupplyUsage(supply_id=can.id, service_line_item_id=i.id, quantity=Decimal("2"))
                for i in items
            ),
        ]
    )
    await db_session.flush()
    can.vin = a
    await db_session.commit()
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    await _start_over(db_session, a, b)
    await import_json(client, auth_headers, b, backup_b)
    data = await import_json(client, auth_headers, a, backup_a)
    assert (data["errors"], data["warnings"]) == ([], [])

    # 29e738c9: the bare can kept both jobs and A's took two standalone copies.
    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("4")
    [restored] = await _pinned(db_session, a)
    assert [(u["quantity"], u["created_at"]) for u in restored["adjustments"]] == [
        (Decimal("2"), datetime(2026, 3, 1, 12, 0))
    ]
    visit = await _visit(db_session, b)
    assert sorted([u.supply_id for u in i.supply_usages] for i in visit.line_items) == [
        [copy_id],
        [copy_id],
    ]


_TARGET = (Decimal("2"), Decimal("1.5000"), Decimal("3.00"))

_DECOYS = [
    pytest.param((Decimal("3"), Decimal("1.5000"), Decimal("3.00")), id="quantity"),
    pytest.param((Decimal("2"), Decimal("2.0000"), Decimal("3.00")), id="unit-cost-snapshot"),
    pytest.param((Decimal("2"), Decimal("1.5000"), Decimal("4.00")), id="cost-snapshot"),
]


@pytest.mark.parametrize("decoy", _DECOYS)
async def test_a_use_elsewhere_takes_the_stored_usage_with_its_own_figures(
    decoy: tuple[Decimal, Decimal, Decimal],
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    # A real shared jug with the same key as A's, and B's visit used both.
    shared = Supply(name=name, unit_type="count")
    ours = Supply(name=name, unit_type="count", vin=a)
    job = ServiceVisit(vin=b, date=date(2026, 3, 1), service_category="Maintenance")
    db_session.add_all([shared, ours, job])
    await db_session.flush()
    items = [ServiceLineItem(visit_id=job.id, description="Job") for _ in range(2)]
    db_session.add_all(items)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=shared.id, date=date(2026, 2, 1), quantity=Decimal("5")),
            SupplyPurchase(supply_id=ours.id, date=date(2026, 2, 1), quantity=Decimal("10")),
        ]
    )
    # The shared jug's use first, so it's the first one A's reference meets.
    for item, supply, (quantity, unit_cost, cost) in (
        (items[0], shared, decoy),
        (items[1], ours, _TARGET),
    ):
        db_session.add(
            SupplyUsage(
                supply_id=supply.id,
                service_line_item_id=item.id,
                quantity=quantity,
                unit_cost_snapshot=unit_cost,
                cost_snapshot=cost,
            )
        )
        await db_session.flush()
    await db_session.commit()
    shared_id = shared.id
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    await _start_over(db_session, a, b)
    # Both of B's uses name the key, so both land on the shared jug first.
    await import_json(client, auth_headers, b, backup_b)
    data = await import_json(client, auth_headers, a, backup_a)
    assert (data["errors"], data["warnings"]) == ([], [])

    [_shared, copy_id] = await _supply_ids(db_session, name)
    figures = (
        SupplyUsage.quantity,
        SupplyUsage.unit_cost_snapshot,
        SupplyUsage.cost_snapshot,
    )
    # 29e738c9: A's copy kept a standalone copy and the shared jug both uses.
    assert (
        await db_session.execute(select(*figures).where(SupplyUsage.supply_id == copy_id))
    ).all() == [_TARGET]
    # The shared jug keeps the use that was its own, and it stays: it has stock.
    assert (
        await db_session.execute(select(*figures).where(SupplyUsage.supply_id == shared_id))
    ).all() == [decoy]
    assert await _balance(db_session, copy_id) == Decimal("8")


async def test_a_genuine_adjustment_with_the_jobs_day_and_figures_is_never_taken(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    await _jug_used_on_b(db_session, name, a, b)
    [jug_id] = await _supply_ids(db_session, name)
    # A's own spill of 3, logged the day of B's job at its prices.
    spill = SupplyUsage(
        supply_id=jug_id,
        quantity=Decimal("3"),
        unit_cost_snapshot=Decimal("1.5000"),
        cost_snapshot=Decimal("4.50"),
        created_at=datetime(2026, 3, 1, 12, 0),
    )
    db_session.add(spill)
    await db_session.commit()
    spill_id = spill.id
    backup_b = await export_json(client, auth_headers, b)

    await _start_over(db_session, b)
    data = await import_json(client, auth_headers, b, backup_b)
    assert (data["errors"], data["warnings"]) == ([], [])

    db_session.expire_all()
    # 29e738c9: the spill was handed to B's visit and the balance read 7.
    assert (
        await db_session.execute(
            select(SupplyUsage.service_line_item_id).where(SupplyUsage.id == spill_id)
        )
    ).scalar_one() is None
    assert await _usages_by_name(db_session, b) == [(name, Decimal("3"))]
    assert await _balance(db_session, jug_id) == Decimal("4")


async def _household_zone(db_session: AsyncSession, zone: str) -> None:
    await db_session.execute(delete(Setting).where(Setting.key == "timezone"))
    db_session.add(Setting(key="timezone", value=zone))
    await db_session.commit()


async def test_the_day_a_use_elsewhere_names_doesnt_move_with_the_zone(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle, keep_rows
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    await _jug_used_on_b(db_session, name, a, b)
    await keep_rows("timezone")
    # Tokyo's midnight is the day before in UTC.
    await _household_zone(db_session, "Asia/Tokyo")
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    await _start_over(db_session, a, b)
    await _household_zone(db_session, "UTC")
    await import_json(client, auth_headers, a, backup_a)
    data = await import_json(client, auth_headers, b, backup_b)
    assert (data["errors"], data["warnings"]) == ([], [])

    # 29e738c9: 4, the use read as Feb 28 here and counted twice.
    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("7")
    assert await _usages_by_name(db_session, b) == [(name, Decimal("3"))]
    [restored] = await _pinned(db_session, a)
    assert restored["adjustments"] == []


_WRONG_PLACE = ["vin", "date", "description"]


@pytest.mark.parametrize("differs", _WRONG_PLACE)
async def test_a_use_elsewhere_takes_only_a_usage_on_the_item_it_names(
    differs: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    new_vehicle,
):
    name = f"Jug {_tag()}"
    a, b, d = await new_vehicle(), await new_vehicle(), await new_vehicle()
    # A real shared jug with A's key. A use of it that's right but for one thing
    # is restored ahead of B's real use of A's jug, so it's the first one met.
    shared = Supply(name=name, unit_type="count")
    ours = Supply(name=name, unit_type="count", vin=a)
    decoy_visit = ServiceVisit(
        vin=d if differs == "vin" else b,
        # The export writes the latest visit first.
        date=date(2026, 4, 1) if differs == "date" else date(2026, 3, 1),
        service_category="Maintenance",
    )
    db_session.add_all([shared, ours, decoy_visit])
    await db_session.flush()
    decoy_item = ServiceLineItem(
        visit_id=decoy_visit.id, description="Rinse" if differs == "description" else "Top up"
    )
    db_session.add(decoy_item)
    await db_session.flush()
    if differs == "description":
        target_item = ServiceLineItem(visit_id=decoy_visit.id, description="Top up")
    else:
        job = ServiceVisit(vin=b, date=date(2026, 3, 1), service_category="Maintenance")
        db_session.add(job)
        await db_session.flush()
        target_item = ServiceLineItem(visit_id=job.id, description="Top up")
    db_session.add(target_item)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=shared.id, date=date(2026, 2, 1), quantity=Decimal("5")),
            SupplyPurchase(supply_id=ours.id, date=date(2026, 2, 1), quantity=Decimal("10")),
            SupplyUsage(supply_id=shared.id, service_line_item_id=decoy_item.id, quantity=3),
            SupplyUsage(supply_id=ours.id, service_line_item_id=target_item.id, quantity=3),
        ]
    )
    await db_session.commit()
    shared_id = shared.id
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    # D, when it holds the decoy, stays as it is.
    await _start_over(db_session, a, b)
    await import_json(client, auth_headers, b, backup_b)
    data = await import_json(client, auth_headers, a, backup_a)
    assert (data["errors"], data["warnings"]) == ([], [])

    [_shared, copy_id] = await _supply_ids(db_session, name)
    where_used = (
        select(ServiceVisit.vin, ServiceVisit.date, ServiceLineItem.description)
        .join(ServiceLineItem, ServiceLineItem.visit_id == ServiceVisit.id)
        .join(SupplyUsage, SupplyUsage.service_line_item_id == ServiceLineItem.id)
    )
    # 29e738c9: A's copy kept a standalone copy and the shared jug both uses.
    assert (await db_session.execute(where_used.where(SupplyUsage.supply_id == copy_id))).all() == [
        (b, date(2026, 3, 1), "Top up")
    ]
    # The decoy, live on D or restored with B, stays on the shared jug.
    assert await _usages_of(db_session, shared_id) == 1


@pytest.mark.parametrize("path", ["b-then-a", "a-deleted"])
async def test_a_use_elsewhere_never_mistakes_another_supply_on_the_item(
    path: str, client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    name, rag_name = f"Jug {tag}", f"Rag {tag}"
    a, b = await new_vehicle(), await new_vehicle()
    # B's item used a shared rag first, then A's jug, the same figures each.
    rag = Supply(name=rag_name, unit_type="count")
    jug = Supply(name=name, unit_type="count", vin=a)
    job = ServiceVisit(vin=b, date=date(2026, 3, 1), service_category="Maintenance")
    db_session.add_all([rag, jug, job])
    await db_session.flush()
    item = ServiceLineItem(visit_id=job.id, description="Top up")
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=rag.id, date=date(2026, 2, 1), quantity=Decimal("5")),
            SupplyPurchase(supply_id=jug.id, date=date(2026, 2, 1), quantity=Decimal("10")),
        ]
    )
    for supply in (rag, jug):
        db_session.add(
            SupplyUsage(supply_id=supply.id, service_line_item_id=item.id, quantity=Decimal("3"))
        )
        await db_session.flush()
    await db_session.commit()
    rag_id = rag.id
    backup_a = await export_json(client, auth_headers, a)
    backup_b = await export_json(client, auth_headers, b)

    if path == "b-then-a":
        await _start_over(db_session, a, b)
        await import_json(client, auth_headers, b, backup_b)
    else:
        # The rag's use stays on B's item; the jug's goes with A.
        await _start_over(db_session, a)
    data = await import_json(client, auth_headers, a, backup_a)
    assert (data["errors"], data["warnings"]) == ([], [])

    # 29e738c9: the jug's use came back standalone on A's copy.
    [copy_id] = await _supply_ids(db_session, name)
    assert await _usages_by_name(db_session, b) == [(name, Decimal("3")), (rag_name, Decimal("3"))]
    assert await _balance(db_session, copy_id) == Decimal("7")
    assert await _usages_of(db_session, rag_id) == 1


async def test_a_copy_of_the_supplys_vehicle_never_takes_the_use_from_the_original(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    item_id = await _jug_used_on_b(db_session, name, a, b)
    [jug_id] = await _supply_ids(db_session, name)
    backup_a = await export_json(client, auth_headers, a)

    # A's backup into another vehicle, with A and B still here.
    c = await new_vehicle()
    data = await import_json(client, auth_headers, c, backup_a)

    # 29e738c9: [], the copy took B's use as a standalone usage of its own.
    assert data["warnings"] == [_not_counted(name, "3", b, "2026-03-01")]
    [_jug, copy_id] = await _supply_ids(db_session, name)
    # B's use stays on A's jug, and the copy keeps its whole purchase.
    assert (
        await db_session.execute(
            select(SupplyUsage.supply_id).where(SupplyUsage.service_line_item_id == item_id)
        )
    ).scalars().all() == [jug_id]
    assert await _balance(db_session, copy_id) == Decimal("10")


async def test_a_use_elsewhere_never_writes_to_a_vehicle_the_importer_cant_edit(
    client: AsyncClient,
    auth_headers,
    non_admin_headers,
    non_admin_user,
    db_session: AsyncSession,
    new_vehicle,
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    item_id = await _jug_used_on_b(db_session, name, a, b)
    backup_a = await export_json(client, auth_headers, a)

    # A goes to someone who can't touch B, then comes back from the backup.
    await _start_over(db_session, a)
    await db_session.execute(
        update(Vehicle).where(Vehicle.vin == a).values(user_id=non_admin_user["id"])
    )
    await db_session.commit()
    data = await import_json(client, non_admin_headers, a, backup_a)

    # 29e738c9: [], the use came back as A's standalone usage.
    assert data["warnings"] == [_not_counted(name, "3", b, "2026-03-01")]
    db_session.expire_all()
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(SupplyUsage)
            .where(SupplyUsage.service_line_item_id == item_id)
        )
    ).scalar_one() == 0
    [copy_id] = await _supply_ids(db_session, name)
    assert await _balance(db_session, copy_id) == Decimal("10")


async def test_a_restore_never_takes_another_visits_job_usage(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    name = f"Jug {tag}"
    a, b = await new_vehicle(), await new_vehicle()
    # Pinned to A, used on B's visit and logged that day.
    jug = Supply(name=name, unit_type="count", vin=a)
    job = ServiceVisit(vin=b, date=date(2026, 3, 1), service_category="Maintenance")
    db_session.add_all([jug, job])
    await db_session.flush()
    item = ServiceLineItem(visit_id=job.id, description="Top up")
    db_session.add(item)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=jug.id, date=date(2026, 2, 1), quantity=Decimal("10")),
            SupplyUsage(
                supply_id=jug.id,
                service_line_item_id=item.id,
                quantity=Decimal("3"),
                created_at=datetime(2026, 3, 1, 12, 0),
            ),
        ]
    )
    await db_session.commit()
    jug_id, item_id = jug.id, item.id

    backup_b = await export_json(client, auth_headers, b)
    new_b = await new_vehicle()
    await import_json(client, auth_headers, new_b, backup_b)

    # B's own job keeps its usage; the restored visit gets its own.
    db_session.expire_all()
    assert (
        await db_session.execute(
            select(func.count())
            .select_from(SupplyUsage)
            .where(SupplyUsage.service_line_item_id == item_id)
        )
    ).scalar_one() == 1
    # main: KeyError, the export writes no supply_usages.
    assert await _usages_by_name(db_session, new_b) == [(name, Decimal("3"))]
    assert await _usages_of(db_session, jug_id) == 2


# -- D-5, D-15: where a supply the file names is looked up -----------------------


async def test_a_supply_pinned_to_another_vehicle_is_found_by_its_key(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    a, b, c = await new_vehicle(), await new_vehicle(), await new_vehicle()
    # A's visit used oil pinned to B, so A's file names it by key.
    theirs = Supply(name=f"B's oil {tag}", unit_type="volume", volume_unit="qt_us", vin=b)
    job = ServiceVisit(vin=a, date=date(2026, 5, 1), service_category="Maintenance")
    db_session.add_all([theirs, job])
    await db_session.flush()
    item = ServiceLineItem(visit_id=job.id, description="Top up")
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        SupplyUsage(supply_id=theirs.id, service_line_item_id=item.id, quantity=Decimal("1"))
    )
    await db_session.commit()
    theirs_id = theirs.id

    backup = await export_json(client, auth_headers, a)
    # main: KeyError, the export writes no supply_usages.
    assert backup["service_visits"][0]["line_items"][0]["supply_usages"][0]["supply"] == {
        "name": f"B's oil {tag}",
        "part_number": None,
        "unit_type": "volume",
        "volume_unit": "qt_us",
    }
    data = await import_json(client, auth_headers, c, backup)
    # Found pinned to B, not added again as a shared one.
    assert data["warnings"] == []
    assert await _usages_of(db_session, theirs_id) == 2
    assert (
        await db_session.execute(
            select(func.count()).select_from(Supply).where(Supply.name == f"B's oil {tag}")
        )
    ).scalar_one() == 1


async def test_a_key_never_finds_this_vehicles_own_pinned_supply(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Jug {_tag()}"
    a, b = await new_vehicle(), await new_vehicle()
    # Same key on both, A's the older. A key means "not pinned here" (F-5).
    mine = Supply(name=name, unit_type="count", vin=a)
    db_session.add(mine)
    await db_session.flush()
    theirs = Supply(name=name, unit_type="count", vin=b)
    db_session.add(theirs)
    await db_session.commit()
    mine_id, theirs_id = mine.id, theirs.id

    data = await import_json(
        client,
        auth_headers,
        a,
        {**V9, "service_visits": [_visit_using("2026-05-01", (_shared_ref(name), 1))]},
    )
    assert (data["errors"], data["warnings"]) == ([], [])
    # 29e738c9: A's own jug took it, the lowest id pinned anywhere.
    assert (await _usages_of(db_session, mine_id), await _usages_of(db_session, theirs_id)) == (
        0,
        1,
    )


async def test_a_skipped_familys_index_is_looked_up_here_then_shared_then_added(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    vin = await new_vehicle()
    oil, rag, new = f"Oil {tag}", f"Rag {tag}", f"New {tag}"
    # The vehicle has its own oil, so the file's pinned supplies are skipped.
    # A shared oil with the same key sits there too, and a shared rag.
    ours = Supply(name=oil, unit_type="count", vin=vin)
    shared_oil = Supply(name=oil, unit_type="count")
    shared_rag = Supply(name=rag, unit_type="count")
    db_session.add_all([shared_oil, shared_rag, ours])
    await db_session.commit()
    ids = {"ours": ours.id, "shared_oil": shared_oil.id, "shared_rag": shared_rag.id}

    payload = {
        **V9,
        "supplies": [
            {"name": oil, "unit_type": "count"},
            {"name": rag, "unit_type": "count"},
            {"name": new, "unit_type": "count"},
        ],
        "service_visits": [
            _visit_using("2026-05-01", ({"index": 0}, 1), ({"index": 1}, 2), ({"index": 2}, 3))
        ],
    }
    data = await import_json(client, auth_headers, vin, payload)
    # main: no warnings, neither section is read.
    assert data["warnings"] == [
        "Supplies: this vehicle already has supplies pinned to it, "
        "so the file's pinned supplies weren't imported",
        _added(new),
    ]
    [added] = (await db_session.execute(select(Supply).where(Supply.name == new))).scalars().all()
    # Added pinned here, like the pinned supply it stands in for.
    assert added.vin == vin
    added_id = added.id
    db_session.expire_all()
    rows = await db_session.execute(
        select(SupplyUsage.supply_id, SupplyUsage.quantity)
        .join(ServiceLineItem, SupplyUsage.service_line_item_id == ServiceLineItem.id)
        .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
        .where(ServiceVisit.vin == vin)
    )
    # This vehicle's oil before the shared one; the rag is only shared.
    assert sorted(rows.all(), key=lambda r: r[1]) == [
        (ids["ours"], Decimal("1")),
        (ids["shared_rag"], Decimal("2")),
        (added_id, Decimal("3")),
    ]


async def test_a_skipped_familys_bad_row_is_the_using_visits_row_error(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    db_session.add(Supply(name=f"Ours {_tag()}", unit_type="count", vin=vin))
    await db_session.commit()
    payload = {
        **V9,
        # Never parsed, since the family is skipped; the usage reads it.
        "supplies": [{"name": "Rags", "unit_type": "box"}],
        "service_visits": [_visit_using("2026-05-01", ({"index": 0}, 1))],
    }
    data = await import_json(client, auth_headers, vin, payload)
    # main: neither section is read.
    assert data["errors"] == [
        "Service visit 0: line item 0, supply usage 0: supply 0: "
        "unit_type must be one of volume, count"
    ]
    assert data["service_records"]["error_count"] == 1


async def test_a_blank_stored_part_number_is_found_by_a_key_with_none(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    name = f"Blank part {_tag()}"
    vin = await new_vehicle()
    # An older write left '' where the file says null.
    shared = Supply(name=name, part_number="", unit_type="count")
    db_session.add(shared)
    await db_session.commit()
    shared_id = shared.id

    ref = {"name": name, "part_number": None, "unit_type": "count", "volume_unit": None}
    data = await import_json(
        client,
        auth_headers,
        vin,
        {**V9, "service_visits": [_visit_using("2026-05-01", (ref, 1))]},
    )
    # main: no warning either, the usage is never read.
    assert data["warnings"] == []
    assert await _usages_of(db_session, shared_id) == 1
    assert (
        await db_session.execute(
            select(func.count()).select_from(Supply).where(Supply.name == name)
        )
    ).scalar_one() == 1


# -- R1-H4: what a visit used is part of which visit it is ----------------------


async def test_visits_that_differ_only_in_what_they_used_are_told_apart(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    vin = await new_vehicle()
    ids = await _seed(db_session, vin, tag)
    backup = await export_json(client, auth_headers, vin)
    same = backup["service_visits"][0]

    def variant(change: Any) -> dict[str, Any]:
        visit = json.loads(json.dumps(same))
        change(visit["line_items"][0]["supply_usages"])
        return visit

    def more_oil(usages: list[dict[str, Any]]) -> None:
        usages[0]["quantity"] = 5

    def other_filter(usages: list[dict[str, Any]]) -> None:
        usages[1]["supply"] = {**usages[1]["supply"], "name": f"Other filter {tag}"}

    def dearer_oil(usages: list[dict[str, Any]]) -> None:
        usages[0]["cost_snapshot"] = 30.0

    # No exact copy in the file: without the usages in the key, the first
    # variant takes the stored visit and its own consumption is dropped.
    # main: KeyError, the export writes no supply_usages.
    backup["service_visits"] = [variant(more_oil), variant(other_filter), variant(dearer_oil)]
    data = await import_json(client, auth_headers, vin, backup)
    assert (
        data["service_records"]["success_count"],
        data["service_records"]["skipped_count"],
    ) == (3, 0)
    used = await _usages_of(db_session, ids["oil"])
    # The spill, the stored visit, and each variant's oil.
    assert used == 5

    again = await import_json(client, auth_headers, vin, backup)
    assert (
        again["service_records"]["success_count"],
        again["service_records"]["skipped_count"],
    ) == (0, 3)
    assert await _usages_of(db_session, ids["oil"]) == used


async def test_a_visit_restored_from_a_3a_file_isnt_taken_for_one_with_supplies(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    tag = _tag()
    source = await new_vehicle()
    target = await new_vehicle()
    await _seed(db_session, source, tag)
    backup = await export_json(client, auth_headers, source)
    # The same visit as a 3a file wrote it: no supplies, no supply_usages key.
    three_a = {**V9, "service_visits": json.loads(json.dumps(backup["service_visits"]))}
    for item in three_a["service_visits"][0]["line_items"]:
        item.pop("supply_usages", None)
    first = await import_json(client, auth_headers, target, three_a)
    assert first["service_records"]["success_count"] == 1

    data = await import_json(client, auth_headers, target, backup)
    # main: the 3b visit matches the bare one, and its supplies are lost.
    assert data["service_records"]["success_count"] == 1
    assert len(await _usages_by_name(db_session, target)) == 2

    again = await import_json(client, auth_headers, target, backup)
    assert again["service_records"]["skipped_count"] == 1
    assert len(await _usages_by_name(db_session, target)) == 2
    # And the 3a file still finds its own visit (T-16: no key, not compared).
    bare = await import_json(client, auth_headers, target, three_a)
    assert (bare["service_records"]["success_count"], bare["service_records"]["skipped_count"]) == (
        0,
        1,
    )


# -- R1-M1: quantities travel as decimal text -----------------------------------


async def test_supply_quantities_travel_as_decimal_text(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    vin = await new_vehicle()
    await _seed(db_session, vin, _tag())
    backup = await export_json(client, auth_headers, vin)
    # main: KeyError, no supplies section.
    [oil] = backup["supplies"]
    quantities = [
        *(p["quantity"] for p in oil["purchases"]),
        *(u["quantity"] for u in oil["usages"]),
        *(u["quantity"] for u in backup["service_visits"][0]["line_items"][0]["supply_usages"]),
    ]
    # A float holds about 16 digits and the column 25.
    assert all(isinstance(q, str) for q in quantities), quantities
    assert [Decimal(q) for q in quantities] == [
        Decimal("4.7317647"),
        Decimal("0.946353"),
        Decimal("0.25"),
        Decimal("4.4"),
        Decimal("1"),
    ]


async def test_quantities_past_a_float_keep_every_digit_on_postgresql(
    client: AsyncClient, auth_headers, db_session: AsyncSession, new_vehicle
):
    if db_session.get_bind().dialect.name == "sqlite":
        pytest.skip("SQLite keeps a NUMERIC as a REAL; only PostgreSQL holds 25 digits")
    from app.schemas.supply import SUPPLY_QUANTITY_MAX

    source = await new_vehicle()
    target = await new_vehicle()
    fine = Decimal("10000.0000000000001")
    supply = Supply(name=f"Bulk {_tag()}", unit_type="count", vin=source)
    db_session.add(supply)
    await db_session.flush()
    db_session.add_all(
        [
            SupplyPurchase(supply_id=supply.id, date=date(2026, 1, 1), quantity=fine),
            SupplyPurchase(
                supply_id=supply.id, date=date(2026, 1, 2), quantity=SUPPLY_QUANTITY_MAX
            ),
        ]
    )
    await db_session.commit()

    backup = await export_json(client, auth_headers, source)
    # main: KeyError, no supplies section.
    assert [Decimal(p["quantity"]) for p in backup["supplies"][0]["purchases"]] == [
        fine,
        SUPPLY_QUANTITY_MAX,
    ]
    data = await import_json(client, auth_headers, target, backup)
    # As floats: 10000.0 and 1e12, past the import's bound, so the family was refused.
    assert data["errors"] == []
    [copy] = await _pinned(db_session, target)
    assert sorted(p["quantity"] for p in copy["purchases"]) == [fine, SUPPLY_QUANTITY_MAX]
