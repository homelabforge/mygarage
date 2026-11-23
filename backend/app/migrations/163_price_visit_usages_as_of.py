"""Price stranded visit usages as of their visit's date (#307).

A visit usage with no cost and no frozen unit was logged before its supply had
a cost. 161 used to price those at the supply's average over every costed
purchase, so a receipt dated a year after the visit set its price. Now:

- the as-of price is the weighted average of the supply's costed purchases
  dated on or before the visit, Σ total_cost / Σ quantity, rounded as the app
  rounds an average;
- with none there, the all-time costed average, and ``cost_estimated`` is set
  so the app settles it once an on/before purchase shows up;
- with no costed purchase at all, the usage stays unpriced.

Everything else is left alone: a usage with a cost, one with a frozen unit
(161 prices that), and a standalone adjustment (161 prices that, date-blind).
Each visit it prices gets its cached ``total_cost`` recomputed, the same sum as
``ServiceVisit.calculated_total_cost``. A row whose unit or cost won't fit its
column, a visit whose total wouldn't, and a line item whose visit is gone are
left as they were.

Reads and writes go through typed table constructs with the columns' own
types, as in 161. ``upgrade(conn)``: the work and the stamp commit together.
Not FATAL: the app prices these by itself as they're touched.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import (
    Boolean,
    Connection,
    Date,
    Integer,
    column,
    inspect,
    select,
    table,
    update,
)

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
    column("cost_estimated", Boolean),
)
_purchases = table(
    "supply_purchases",
    column("supply_id", Integer),
    column("date", Date),
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
    column("date", Date),
    column("total_cost", _MONEY),
    column("tax_amount", _MONEY),
    column("shop_supplies", _MONEY),
    column("misc_fees", _MONEY),
)

#: supply id -> its costed purchases as (date, quantity, total_cost).
_Costed = dict[int, list[tuple[dt.date, Decimal, Decimal]]]


def _costed_purchases(conn: Connection) -> _Costed:
    """Every costed purchase, by supply. An uncosted one is in no average."""
    rows = conn.execute(
        select(
            _purchases.c.supply_id,
            _purchases.c.date,
            _purchases.c.quantity,
            _purchases.c.total_cost,
        ).where(_purchases.c.total_cost.isnot(None))
    ).all()
    costed: _Costed = defaultdict(list)
    for supply_id, day, quantity, total_cost in rows:
        costed[supply_id].append((day, Decimal(quantity), Decimal(total_cost)))
    return costed


def _average(purchases: list[tuple[dt.date, Decimal, Decimal]]) -> Decimal | None:
    """Σ cost / Σ quantity, as the app rounds an average. None with no quantity."""
    cost = sum((c for _, _, c in purchases), Decimal(0))
    qty = sum((q for _, q, _ in purchases), Decimal(0))
    if qty <= 0:
        return None
    return (cost / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _as_of(
    purchases: list[tuple[dt.date, Decimal, Decimal]], visit_date: dt.date
) -> tuple[Decimal, bool] | None:
    """(unit, estimated) for a usage on `visit_date`, or None with nothing to price from."""
    on_or_before = [p for p in purchases if p[0] <= visit_date]
    unit = _average(on_or_before) if on_or_before else None
    if unit is not None:
        return unit, False
    fallback = _average(purchases)
    return None if fallback is None else (fallback, True)


def _price(unit: Decimal, quantity: Decimal) -> Decimal | None:
    """The usage's cost at `unit`, or None if the unit or cost won't fit its column."""
    if unit > UNIT_COST_MAX:
        return None
    cost = (unit * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return None if cost > MONEY_MAX else cost


def _visit_total(conn: Connection, visit_id: int, priced: dict[int, Decimal]) -> Decimal:
    """The visit's total with `priced` costs in place: calculated_total_cost's sum."""
    fees = conn.execute(
        select(_visits.c.tax_amount, _visits.c.shop_supplies, _visits.c.misc_fees).where(
            _visits.c.id == visit_id
        )
    ).one()
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
    """Price stranded visit usages as of their visit and refresh those visits' totals."""
    inspector = inspect(conn)
    if not set(inspector.get_table_names()).issuperset(_TABLES):
        logger.info("163: supply or visit tables missing, nothing to price")
        return
    if "cost_estimated" not in {c["name"] for c in inspector.get_columns("supply_usages")}:
        # 162 runs first and is FATAL, so only a hand-run out of order lands here.
        # Fail rather than stamp: the stranded rows would never be priced.
        raise RuntimeError("163: supply_usages.cost_estimated is missing; run 162 first")

    costed = _costed_purchases(conn)
    # The inner joins drop a line item whose visit is gone: it has no date.
    rows = conn.execute(
        select(
            _usages.c.id,
            _usages.c.supply_id,
            _usages.c.quantity,
            _visits.c.id,
            _visits.c.date,
        )
        .select_from(
            _usages.join(_items, _usages.c.service_line_item_id == _items.c.id).join(
                _visits, _items.c.visit_id == _visits.c.id
            )
        )
        .where(_usages.c.cost_snapshot.is_(None), _usages.c.unit_cost_snapshot.is_(None))
        .order_by(_usages.c.id)
    ).all()

    # visit id -> {usage id: (unit, cost, estimated)}
    by_visit: dict[int, dict[int, tuple[Decimal, Decimal, bool]]] = defaultdict(dict)
    skipped = 0
    for usage_id, supply_id, quantity, visit_id, visit_date in rows:
        found = _as_of(costed.get(supply_id, []), visit_date)
        cost = None if found is None else _price(found[0], Decimal(quantity))
        if found is None or cost is None:
            skipped += 1
            continue
        by_visit[visit_id][usage_id] = (found[0], cost, found[1])

    priced = estimated = visits_done = 0
    for visit_id, prices in by_visit.items():
        total = _visit_total(conn, visit_id, {uid: cost for uid, (_, cost, _) in prices.items()})
        if total > MONEY_MAX:
            skipped += len(prices)
            continue
        for usage_id, (unit, cost, flag) in prices.items():
            conn.execute(
                update(_usages)
                .where(
                    _usages.c.id == usage_id,
                    _usages.c.cost_snapshot.is_(None),
                    _usages.c.unit_cost_snapshot.is_(None),
                )
                .values(unit_cost_snapshot=unit, cost_snapshot=cost, cost_estimated=flag)
            )
            estimated += flag
        priced += len(prices)
        conn.execute(update(_visits).where(_visits.c.id == visit_id).values(total_cost=total))
        visits_done += 1

    logger.info(
        "163: priced %d visit supply usages (%d estimated), left %d unpriced, "
        "refreshed %d visit totals",
        priced,
        estimated,
        skipped,
        visits_done,
    )
