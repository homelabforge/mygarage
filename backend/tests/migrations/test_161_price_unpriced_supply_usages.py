"""Migration 161: price the supply usages logged before their supply had a cost (#301).

A visit usage with neither a cost nor a frozen unit is left for 163, which
prices it as of its visit's date (#307).
"""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.schemas._money import MONEY_MAX
from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations

_NAME = "161_price_unpriced_supply_usages"
_BOTH = pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)

# 5 US quarts in litres, the issue's oil.
_FIVE_QT = "4.73176473"


def _load():
    return load_migration(_NAME)


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


_DDL = {
    "supply_purchases": "CREATE TABLE supply_purchases (id INTEGER PRIMARY KEY, supply_id INTEGER "
    "NOT NULL, quantity NUMERIC(25, 13) NOT NULL, total_cost NUMERIC(12, 2))",
    "service_visits": "CREATE TABLE service_visits (id INTEGER PRIMARY KEY, total_cost "
    "NUMERIC(12, 2), tax_amount NUMERIC(12, 2), shop_supplies NUMERIC(12, 2), misc_fees "
    "NUMERIC(12, 2))",
    "service_line_items": "CREATE TABLE service_line_items (id INTEGER PRIMARY KEY, visit_id "
    "INTEGER NOT NULL, cost NUMERIC(12, 2))",
    "supply_usages": "CREATE TABLE supply_usages (id INTEGER PRIMARY KEY, supply_id INTEGER NOT "
    "NULL, service_line_item_id INTEGER, quantity NUMERIC(25, 13) NOT NULL, unit_cost_snapshot "
    "NUMERIC(15, 4), cost_snapshot NUMERIC(12, 2))",
}


def _tables(engine: Engine, skip: str | None = None) -> None:
    with engine.begin() as conn:
        for name, ddl in _DDL.items():
            if name != skip:
                conn.execute(text(ddl))


def _run(engine: Engine, sql: str, **params: object) -> None:
    """Seed with raw SQL. Amounts go as text: sqlite3 has no Decimal adapter, and
    the NUMERIC columns store the number either way."""
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def _purchase(engine: Engine, supply_id: int, quantity: str, cost: str | None) -> None:
    # An explicit id: a bare INTEGER PRIMARY KEY only numbers itself on SQLite.
    with engine.connect() as conn:
        next_id = conn.execute(text("SELECT COUNT(*) FROM supply_purchases")).scalar_one() + 1
    _run(
        engine,
        "INSERT INTO supply_purchases (id, supply_id, quantity, total_cost) "
        "VALUES (:id, :s, :q, :c)",
        id=next_id,
        s=supply_id,
        q=quantity,
        c=cost,
    )


def _visit(engine: Engine, vid: int, total: str, *fees: str | None, labour: str = "0") -> None:
    tax, shop, misc = (*fees, None, None, None)[:3]
    _run(
        engine,
        "INSERT INTO service_visits (id, total_cost, tax_amount, shop_supplies, misc_fees) "
        "VALUES (:id, :t, :tax, :shop, :misc)",
        id=vid,
        t=total,
        tax=tax,
        shop=shop,
        misc=misc,
    )
    _run(
        engine,
        "INSERT INTO service_line_items (id, visit_id, cost) VALUES (:id, :v, :c)",
        id=vid,
        v=vid,
        c=labour,
    )


def _usage(
    engine: Engine,
    uid: int,
    supply_id: int,
    item: int | None,
    quantity: str,
    unit: str | None = None,
    cost: str | None = None,
) -> None:
    _run(
        engine,
        "INSERT INTO supply_usages (id, supply_id, service_line_item_id, quantity, "
        "unit_cost_snapshot, cost_snapshot) VALUES (:id, :s, :i, :q, :u, :c)",
        id=uid,
        s=supply_id,
        i=item,
        q=quantity,
        u=unit,
        c=cost,
    )


def _snapshots(engine: Engine, uid: int) -> tuple[Decimal | None, Decimal | None]:
    with engine.connect() as conn:
        unit, cost = conn.execute(
            text("SELECT unit_cost_snapshot, cost_snapshot FROM supply_usages WHERE id = :id"),
            {"id": uid},
        ).one()
    return (
        None if unit is None else Decimal(str(unit)),
        None if cost is None else Decimal(str(cost)),
    )


def _total(engine: Engine, vid: int) -> Decimal:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT total_cost FROM service_visits WHERE id = :id"), {"id": vid}
        ).scalar_one()
    return Decimal(str(value))


def _issue_301(engine: Engine) -> None:
    """The issue's visit: 35.95 labour, 4.11 / 4.94 / 1.00 fees, oil and filter unpriced."""
    _tables(engine)
    _purchase(engine, 1, _FIVE_QT, "37.45")
    _purchase(engine, 2, "1", "9.00")
    _visit(engine, 1, "46.00", "4.11", "4.94", "1.00", labour="35.95")
    _usage(engine, 1, 1, 1, _FIVE_QT)
    _usage(engine, 2, 2, 1, "1")


def test_the_migration_is_not_fatal() -> None:
    assert _load().FATAL is False


@_BOTH
def test_a_visit_usage_with_no_unit_is_left_for_163(engine_for_migration) -> None:
    # 3.11.2 priced these at the date-blind average, and 162 then froze them.
    _dialect, engine, _url = engine_for_migration
    _issue_301(engine)
    _upgrade(engine)
    assert _snapshots(engine, 1) == (None, None)
    assert _snapshots(engine, 2) == (None, None)
    assert _total(engine, 1) == Decimal("46.00")


@_BOTH
def test_the_average_weighs_only_costed_purchases(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "10", "80.00")
    _purchase(engine, 1, "5", "100.00")
    _purchase(engine, 1, "100", None)  # uncosted: not in the average
    _usage(engine, 1, 1, None, "3")
    _upgrade(engine)
    # 180 / 15 = 12.0000
    assert _snapshots(engine, 1) == (Decimal("12.0000"), Decimal("36.00"))


@_BOTH
def test_what_has_a_cost_is_left_alone(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "10", "80.00")
    _purchase(engine, 2, "10", None)  # never costed
    _visit(engine, 1, "22.00")
    _usage(engine, 1, 1, 1, "2", unit="5.0000", cost="10.00")  # priced
    _usage(engine, 2, 1, 1, "3", cost="12.00")  # cost only, an import
    _usage(engine, 3, 1, 1, "1", cost="0.00")  # free
    _usage(engine, 4, 2, 1, "1")  # no cost to use
    _upgrade(engine)
    assert _snapshots(engine, 1) == (Decimal("5.0000"), Decimal("10.00"))
    assert _snapshots(engine, 2) == (None, Decimal("12.00"))
    assert _snapshots(engine, 3) == (None, Decimal("0.00"))
    assert _snapshots(engine, 4) == (None, None)
    assert _total(engine, 1) == Decimal("22.00")


@_BOTH
def test_a_frozen_unit_beats_the_average(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "10", "80.00")  # avg 8.00
    _visit(engine, 1, "0")
    _usage(engine, 1, 1, 1, "2", unit="5.0000")
    _upgrade(engine)
    assert _snapshots(engine, 1) == (Decimal("5.0000"), Decimal("10.00"))
    assert _total(engine, 1) == Decimal("10.00")


@_BOTH
def test_a_standalone_adjustment_is_priced(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "4", "30.00")
    _usage(engine, 1, 1, None, "2")
    _upgrade(engine)
    assert _snapshots(engine, 1) == (Decimal("7.5000"), Decimal("15.00"))


@_BOTH
def test_a_visit_that_would_overflow_is_skipped_alone(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    near_cap = str(MONEY_MAX - Decimal("1.00"))
    _purchase(engine, 1, "10", "80.00")
    _visit(engine, 1, near_cap, labour=near_cap)
    _visit(engine, 2, "0")
    _usage(engine, 1, 1, 1, "5", unit="8.0000")  # 40.00 > 1.00 of headroom
    _usage(engine, 2, 1, 2, "5", unit="8.0000")
    _upgrade(engine)
    assert _snapshots(engine, 1) == (Decimal("8.0000"), None)
    assert _total(engine, 1) == Decimal(near_cap)
    assert _snapshots(engine, 2) == (Decimal("8.0000"), Decimal("40.00"))
    assert _total(engine, 2) == Decimal("40.00")


@_BOTH
def test_a_line_item_whose_visit_is_gone_is_skipped_alone(engine_for_migration) -> None:
    # Left by a delete from before foreign keys were enforced. main of this
    # branch: .one() on the missing visit, and the whole migration failed.
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "10", "80.00")
    _visit(engine, 2, "0")
    _run(engine, "INSERT INTO service_line_items (id, visit_id, cost) VALUES (9, 99, 0)")
    _usage(engine, 1, 1, 9, "5", unit="8.0000")
    _usage(engine, 2, 1, 2, "5", unit="8.0000")
    _upgrade(engine)
    assert _snapshots(engine, 1) == (Decimal("8.0000"), None)
    assert _snapshots(engine, 2) == (Decimal("8.0000"), Decimal("40.00"))
    assert _total(engine, 2) == Decimal("40.00")


@_BOTH
def test_a_second_run_changes_nothing(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_301(engine)
    _usage(engine, 3, 1, None, _FIVE_QT)  # a standalone adjustment
    _usage(engine, 4, 2, 1, "1", unit="9.0000")
    _upgrade(engine)
    _purchase(engine, 1, "10", "500.00")  # a new average must not reprice anything
    _upgrade(engine)
    assert _snapshots(engine, 3) == (Decimal("7.9146"), Decimal("37.45"))
    assert _snapshots(engine, 4) == (Decimal("9.0000"), Decimal("9.00"))
    assert _snapshots(engine, 1) == (None, None)
    assert _total(engine, 1) == Decimal("55.00")


@_BOTH
@pytest.mark.parametrize("missing", list(_DDL))
def test_a_missing_table_is_skipped(engine_for_migration, missing: str) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine, skip=missing)
    _upgrade(engine)


@_BOTH
def test_the_work_rolls_back_with_the_runners_transaction(engine_for_migration) -> None:
    # The runner stamps on the same connection after upgrade(); if that fails,
    # nothing 161 did may stick.
    _dialect, engine, _url = engine_for_migration
    _issue_301(engine)
    _usage(engine, 3, 2, 1, "1", unit="9.0000")
    with pytest.raises(RuntimeError, match="stamp failed"):
        with engine.begin() as conn:
            _load().upgrade(conn=conn)
            raise RuntimeError("stamp failed")
    assert _snapshots(engine, 3) == (Decimal("9.0000"), None)
    assert _total(engine, 1) == Decimal("46.00")
