"""Migration 163: price stranded visit usages as of their visit's date (#307).

A visit usage with no cost and no frozen unit takes the weighted average of
its supply's costed purchases dated on or before the visit. With none, it takes
the all-time average and is flagged ``cost_estimated``. The scenario numbers
are shared with the app's date-aware pricing tests: a July 2025 purchase of 5
for $30.00, a June 2026 purchase of 5 for $37.45, and a visit on 2025-07-17
that uses 5.
"""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.schemas._money import MONEY_MAX
from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations

_NAME = "163_price_visit_usages_as_of"
_BOTH = pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)

_JULY_2025 = "2025-07-10"
_VISIT_DAY = "2025-07-17"
_JUNE_2026 = "2026-06-02"


def _load():
    return load_migration(_NAME)


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


_DDL = {
    "supply_purchases": "CREATE TABLE supply_purchases (id INTEGER PRIMARY KEY, supply_id INTEGER "
    "NOT NULL, date DATE NOT NULL, quantity NUMERIC(25, 13) NOT NULL, total_cost NUMERIC(12, 2))",
    "service_visits": "CREATE TABLE service_visits (id INTEGER PRIMARY KEY, date DATE NOT NULL, "
    "total_cost NUMERIC(12, 2), tax_amount NUMERIC(12, 2), shop_supplies NUMERIC(12, 2), "
    "misc_fees NUMERIC(12, 2))",
    "service_line_items": "CREATE TABLE service_line_items (id INTEGER PRIMARY KEY, visit_id "
    "INTEGER NOT NULL, cost NUMERIC(12, 2))",
    "supply_usages": "CREATE TABLE supply_usages (id INTEGER PRIMARY KEY, supply_id INTEGER NOT "
    "NULL, service_line_item_id INTEGER, quantity NUMERIC(25, 13) NOT NULL, unit_cost_snapshot "
    "NUMERIC(15, 4), cost_snapshot NUMERIC(12, 2), cost_estimated BOOLEAN NOT NULL DEFAULT FALSE)",
}


def _tables(engine: Engine, skip: str | None = None) -> None:
    with engine.begin() as conn:
        for name, ddl in _DDL.items():
            if name != skip:
                conn.execute(text(ddl))


def _run(engine: Engine, sql: str, **params: object) -> None:
    """Seed with raw SQL. Amounts and dates go as text: sqlite3 has no Decimal
    adapter, and both databases read the text into the column's type."""
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def _purchase(engine: Engine, supply_id: int, day: str, quantity: str, cost: str | None) -> None:
    # An explicit id: a bare INTEGER PRIMARY KEY only numbers itself on SQLite.
    with engine.connect() as conn:
        next_id = conn.execute(text("SELECT COUNT(*) FROM supply_purchases")).scalar_one() + 1
    _run(
        engine,
        "INSERT INTO supply_purchases (id, supply_id, date, quantity, total_cost) "
        "VALUES (:id, :s, :d, :q, :c)",
        id=next_id,
        s=supply_id,
        d=day,
        q=quantity,
        c=cost,
    )


def _visit(engine: Engine, vid: int, day: str, total: str, labour: str = "0") -> None:
    _run(
        engine,
        "INSERT INTO service_visits (id, date, total_cost) VALUES (:id, :d, :t)",
        id=vid,
        d=day,
        t=total,
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


def _row(engine: Engine, uid: int) -> tuple[Decimal | None, Decimal | None, bool]:
    """(unit, cost, estimated) of one usage."""
    with engine.connect() as conn:
        unit, cost, estimated = conn.execute(
            text(
                "SELECT unit_cost_snapshot, cost_snapshot, cost_estimated "
                "FROM supply_usages WHERE id = :id"
            ),
            {"id": uid},
        ).one()
    return (
        None if unit is None else Decimal(str(unit)),
        None if cost is None else Decimal(str(cost)),
        bool(estimated),
    )


def _total(engine: Engine, vid: int) -> Decimal:
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT total_cost FROM service_visits WHERE id = :id"), {"id": vid}
        ).scalar_one()
    return Decimal(str(value))


def _issue_307(engine: Engine, *, july: bool = True) -> None:
    """The reporter's oil: the July 2025 visit uses 5, priced by nothing yet."""
    _tables(engine)
    if july:
        _purchase(engine, 1, _JULY_2025, "5", "30.00")
    _purchase(engine, 1, _JUNE_2026, "5", "37.45")
    _visit(engine, 1, _VISIT_DAY, "40.00", labour="40.00")
    _usage(engine, 1, 1, 1, "5")


def test_the_migration_is_not_fatal() -> None:
    assert _load().FATAL is False


@_BOTH
def test_a_purchase_on_or_before_the_visit_sets_the_price(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_307(engine)
    _upgrade(engine)
    # Not 67.45 / 10 = 6.7450 over both purchases: June 2026 is after the visit.
    assert _row(engine, 1) == (Decimal("6.0000"), Decimal("30.00"), False)
    assert _total(engine, 1) == Decimal("70.00")


@_BOTH
def test_only_a_later_purchase_prices_it_estimated(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_307(engine, july=False)
    _upgrade(engine)
    assert _row(engine, 1) == (Decimal("7.4900"), Decimal("37.45"), True)
    assert _total(engine, 1) == Decimal("77.45")


@_BOTH
def test_a_purchase_on_the_visit_day_counts(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, _VISIT_DAY, "5", "30.00")
    _purchase(engine, 1, _JUNE_2026, "5", "37.45")
    _visit(engine, 1, _VISIT_DAY, "0")
    _usage(engine, 1, 1, 1, "5")
    _upgrade(engine)
    assert _row(engine, 1) == (Decimal("6.0000"), Decimal("30.00"), False)


@_BOTH
def test_the_as_of_average_weighs_only_costed_purchases_up_to_the_visit(
    engine_for_migration,
) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "2025-01-05", "10", "80.00")
    _purchase(engine, 1, "2025-03-05", "5", "100.00")
    _purchase(engine, 1, "2025-04-05", "100", None)  # uncosted: not in the average
    _purchase(engine, 1, "2025-08-05", "5", "500.00")  # after the visit
    _visit(engine, 1, _VISIT_DAY, "0")
    _usage(engine, 1, 1, 1, "3")
    _upgrade(engine)
    # 180 / 15 = 12.0000
    assert _row(engine, 1) == (Decimal("12.0000"), Decimal("36.00"), False)
    assert _total(engine, 1) == Decimal("36.00")


@_BOTH
def test_the_estimate_is_the_all_time_costed_average(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, "2025-06-01", "100", None)  # before, but uncosted
    _purchase(engine, 1, "2026-01-05", "10", "80.00")
    _purchase(engine, 1, "2026-03-05", "5", "100.00")
    _visit(engine, 1, _VISIT_DAY, "0")
    _usage(engine, 1, 1, 1, "3")
    _upgrade(engine)
    assert _row(engine, 1) == (Decimal("12.0000"), Decimal("36.00"), True)


@_BOTH
def test_each_usage_on_a_visit_is_priced_and_totalled(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_307(engine)
    _purchase(engine, 2, _JUNE_2026, "1", "9.00")
    _usage(engine, 2, 2, 1, "1")
    _upgrade(engine)
    assert _row(engine, 1) == (Decimal("6.0000"), Decimal("30.00"), False)
    assert _row(engine, 2) == (Decimal("9.0000"), Decimal("9.00"), True)
    assert _total(engine, 1) == Decimal("79.00")


@_BOTH
def test_what_isnt_a_stranded_visit_usage_is_left_alone(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_307(engine)
    _purchase(engine, 2, _JULY_2025, "10", None)  # never costed
    _usage(engine, 2, 1, 1, "2", unit="5.0000", cost="10.00")  # priced
    _usage(engine, 3, 1, 1, "3", cost="12.00")  # cost only, an import
    _usage(engine, 4, 1, 1, "2", unit="5.0000")  # frozen unit: 161's to price
    _usage(engine, 5, 1, None, "2")  # standalone: 161's to price
    _usage(engine, 6, 2, 1, "1")  # no cost to use
    _upgrade(engine)
    assert _row(engine, 2) == (Decimal("5.0000"), Decimal("10.00"), False)
    assert _row(engine, 3) == (None, Decimal("12.00"), False)
    assert _row(engine, 4) == (Decimal("5.0000"), None, False)
    assert _row(engine, 5) == (None, None, False)
    assert _row(engine, 6) == (None, None, False)
    # Usage 1 priced at 30.00; the others' costs count as they stand.
    assert _total(engine, 1) == Decimal("92.00")


@_BOTH
def test_a_visit_that_would_overflow_is_skipped_alone(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    near_cap = str(MONEY_MAX - Decimal("1.00"))
    _purchase(engine, 1, _JULY_2025, "10", "80.00")
    _visit(engine, 1, _VISIT_DAY, near_cap, labour=near_cap)
    _visit(engine, 2, _VISIT_DAY, "0")
    _usage(engine, 1, 1, 1, "5")  # 40.00 > 1.00 of headroom
    _usage(engine, 2, 1, 2, "5")
    _upgrade(engine)
    assert _row(engine, 1) == (None, None, False)
    assert _total(engine, 1) == Decimal(near_cap)
    assert _row(engine, 2) == (Decimal("8.0000"), Decimal("40.00"), False)
    assert _total(engine, 2) == Decimal("40.00")


@_BOTH
def test_a_line_item_whose_visit_is_gone_is_skipped_alone(engine_for_migration) -> None:
    # Left by a delete from before foreign keys were enforced: no visit, no date.
    _dialect, engine, _url = engine_for_migration
    _tables(engine)
    _purchase(engine, 1, _JULY_2025, "10", "80.00")
    _visit(engine, 2, _VISIT_DAY, "0")
    _run(engine, "INSERT INTO service_line_items (id, visit_id, cost) VALUES (9, 99, 0)")
    _usage(engine, 1, 1, 9, "5")
    _usage(engine, 2, 1, 2, "5")
    _upgrade(engine)
    assert _row(engine, 1) == (None, None, False)
    assert _row(engine, 2) == (Decimal("8.0000"), Decimal("40.00"), False)
    assert _total(engine, 2) == Decimal("40.00")


@_BOTH
def test_a_second_run_changes_nothing(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_307(engine, july=False)
    _upgrade(engine)
    # An on/before purchase now exists; settling the estimate is the app's job.
    _purchase(engine, 1, _JULY_2025, "5", "30.00")
    _upgrade(engine)
    assert _row(engine, 1) == (Decimal("7.4900"), Decimal("37.45"), True)
    assert _total(engine, 1) == Decimal("77.45")


@_BOTH
@pytest.mark.parametrize("missing", list(_DDL))
def test_a_missing_table_is_skipped(engine_for_migration, missing: str) -> None:
    _dialect, engine, _url = engine_for_migration
    _tables(engine, skip=missing)
    _upgrade(engine)


@_BOTH
def test_without_the_flag_column_it_fails_instead_of_stamping(engine_for_migration) -> None:
    # 162 runs first and is FATAL, so this only guards a hand-run out of order.
    _dialect, engine, _url = engine_for_migration
    _tables(engine, skip="supply_usages")
    _run(
        engine,
        _DDL["supply_usages"].replace(", cost_estimated BOOLEAN NOT NULL DEFAULT FALSE", ""),
    )
    with pytest.raises(RuntimeError, match="cost_estimated"):
        _upgrade(engine)


@_BOTH
def test_the_work_rolls_back_with_the_runners_transaction(engine_for_migration) -> None:
    _dialect, engine, _url = engine_for_migration
    _issue_307(engine)
    with pytest.raises(RuntimeError, match="stamp failed"):
        with engine.begin() as conn:
            _load().upgrade(conn=conn)
            raise RuntimeError("stamp failed")
    assert _row(engine, 1) == (None, None, False)
    assert _total(engine, 1) == Decimal("40.00")
