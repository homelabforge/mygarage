"""Price the supply usages that were logged before their supply had a cost (#301).

A usage froze its price when it was logged, at the supply's average over costed
purchases. Logged before any costed purchase, it got no price (``cost_snapshot``
NULL) and stayed that way, so the visit total left the parts out. The app now
prices those at the next costed purchase or visit edit; this catches up the
rows already stranded:

- a usage with a frozen unit cost and no cost gets cost = unit × quantity;
- one with neither gets its supply's average over costed purchases, if any;
- a usage with a cost is never touched.

Each visit it prices gets its cached ``total_cost`` recomputed, the same sum as
``ServiceVisit.calculated_total_cost``. A row whose unit or cost won't fit its
column, or a visit whose total wouldn't, is left as it was.

Reads and writes go through typed table constructs with the columns' own
``ScaledNumeric`` types, so SQLite hands back Decimals and binds round as they
do on PostgreSQL. ``upgrade(conn)``: the work and the stamp commit together.
Not FATAL: the app prices these by itself as they're touched.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, Integer, column, inspect, select, table, update

from app.models._types import ScaledNumeric
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX

logger = logging.getLogger(__name__)

FATAL = False

_TABLES = ("supply_usages", "supply_purchases", "service_line_items", "service_visits")
_MONEY = ScaledNumeric(12, 2)

_usages = table(
    "supply_usages",
    column("id", Integer),
    column("supply_id", Integer),
    column("service_line_item_id", Integer),
    column("quantity", ScaledNumeric(25, 13)),
    column("unit_cost_snapshot", ScaledNumeric(15, 4)),
    column("cost_snapshot", _MONEY),
)
_purchases = table(
    "supply_purchases",
    column("supply_id", Integer),
    column("quantity", ScaledNumeric(25, 13)),
    column("total_cost", _MONEY),
)
_items = table(
    "service_line_items",
    column("id", Integer),
    column("visit_id", Integer),
    column("cost", _MONEY),
)
_visits = table(
    "service_visits",
    column("id", Integer),
    column("total_cost", _MONEY),
    column("tax_amount", _MONEY),
    column("shop_supplies", _MONEY),
    column("misc_fees", _MONEY),
)


def _averages(conn: Connection) -> dict[int, Decimal]:
    """Each supply's average unit cost over its costed purchases, as the app rounds it."""
    rows = conn.execute(
        select(_purchases.c.supply_id, _purchases.c.quantity, _purchases.c.total_cost).where(
            _purchases.c.total_cost.isnot(None)
        )
    ).all()
    cost: dict[int, Decimal] = defaultdict(Decimal)
    qty: dict[int, Decimal] = defaultdict(Decimal)
    for supply_id, quantity, total_cost in rows:
        cost[supply_id] += Decimal(total_cost)
        qty[supply_id] += Decimal(quantity)
    return {
        sid: (cost[sid] / qty[sid]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        for sid in cost
        if qty[sid] > 0
    }


def _price(
    unit_snapshot: Decimal | None, quantity: Decimal, avg: Decimal | None
) -> tuple[Decimal, Decimal] | None:
    """(unit, cost) for an unpriced usage, or None. Same rule as the app's ``usage_price``."""
    unit = unit_snapshot if unit_snapshot is not None else avg
    if unit is None or unit > UNIT_COST_MAX:
        return None
    cost = (unit * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if cost > MONEY_MAX:
        return None
    return unit, cost


def _visit_total(conn: Connection, visit_id: int, priced: dict[int, Decimal]) -> Decimal | None:
    """The visit's total with `priced` costs in place: calculated_total_cost's sum.

    None when the visit is gone: a line item left behind by a delete from
    before foreign keys were enforced. Its usages stay as they are.
    """
    fees = conn.execute(
        select(_visits.c.tax_amount, _visits.c.shop_supplies, _visits.c.misc_fees).where(
            _visits.c.id == visit_id
        )
    ).one_or_none()
    if fees is None:
        return None
    labour = conn.execute(select(_items.c.cost).where(_items.c.visit_id == visit_id)).scalars()
    parts = conn.execute(
        select(_usages.c.id, _usages.c.cost_snapshot)
        .join(_items, _usages.c.service_line_item_id == _items.c.id)
        .where(_items.c.visit_id == visit_id)
    ).all()
    total = sum((Decimal(c) for c in labour if c is not None), Decimal(0))
    for usage_id, cost in parts:
        cost = priced.get(usage_id, cost)
        if cost is not None:
            total += Decimal(cost)
    return total + sum((Decimal(f) for f in fees if f is not None), Decimal(0))


def upgrade(conn: Connection) -> None:
    """Price stranded usages and refresh the totals of the visits they're on."""
    present = set(inspect(conn).get_table_names())
    if not present.issuperset(_TABLES):
        logger.info("161: supply or visit tables missing, nothing to price")
        return

    averages = _averages(conn)
    rows = conn.execute(
        select(
            _usages.c.id,
            _usages.c.supply_id,
            _usages.c.quantity,
            _usages.c.unit_cost_snapshot,
            _items.c.visit_id,
        )
        .select_from(_usages.outerjoin(_items, _usages.c.service_line_item_id == _items.c.id))
        .where(_usages.c.cost_snapshot.is_(None))
        .order_by(_usages.c.id)
    ).all()

    # visit id (None for a standalone adjustment) -> {usage id: (unit, cost)}
    by_visit: dict[int | None, dict[int, tuple[Decimal, Decimal]]] = defaultdict(dict)
    skipped = 0
    for usage_id, supply_id, quantity, unit_snapshot, visit_id in rows:
        price = _price(
            None if unit_snapshot is None else Decimal(unit_snapshot),
            Decimal(quantity),
            averages.get(supply_id),
        )
        if price is None:
            skipped += 1
            continue
        by_visit[visit_id][usage_id] = price

    priced = 0
    visits_done = 0
    for visit_id, prices in by_visit.items():
        total: Decimal | None = None
        if visit_id is not None:
            total = _visit_total(conn, visit_id, {uid: cost for uid, (_, cost) in prices.items()})
            if total is None or total > MONEY_MAX:
                skipped += len(prices)
                continue
        for usage_id, (unit, cost) in prices.items():
            conn.execute(
                update(_usages)
                .where(_usages.c.id == usage_id, _usages.c.cost_snapshot.is_(None))
                .values(unit_cost_snapshot=unit, cost_snapshot=cost)
            )
        priced += len(prices)
        if visit_id is not None:
            conn.execute(update(_visits).where(_visits.c.id == visit_id).values(total_cost=total))
            visits_done += 1

    logger.info(
        "161: priced %d supply usages, left %d unpriced, refreshed %d visit totals",
        priced,
        skipped,
        visits_done,
    )
