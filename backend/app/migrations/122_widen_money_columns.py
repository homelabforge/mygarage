"""Widen every money column to its policy type on PostgreSQL.

Amounts go to NUMERIC(12,2), unit prices to (12,3), and the supply unit-cost
snapshot to (15,4). The old widths, (8,2) and (10,2), overflow on real amounts
in currencies users can pick today: a forint fill-up, a yen rental night, a
rupee down payment. On PostgreSQL that's a 500 ("numeric field overflow").
SQLite ignores declared precision, so there's nothing to do there.

FATAL = True. The models declare the new widths, so a PostgreSQL install that
skipped this would disagree with them and 500 on the first amount past the old.

The column list is hard-coded on purpose: a historical migration can't depend on
the models that come after it. The two insurance coverage limits aren't in it,
they were NUMERIC(12,2) from the start (migration 108).

Only a bounded NUMERIC narrower than its target at the same scale gets altered,
so a rerun is a no-op. Anything else (already wider, unbounded, a float, another
scale) is left alone and named in the output, since changing it could round or
narrow a stored value. Every row fits its old column, so widening can't fail. A
view on one of these columns would block ALTER TYPE; there are none, and none of
them is indexed either.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Numeric, create_engine, inspect, text
from sqlalchemy.types import TypeEngine

FATAL = True

_MONEY = (12, 2)
_UNIT_PRICE = (12, 3)
_UNIT_COST = (15, 4)

#: table -> {column: (precision, scale)} it should end up at.
COLUMNS: dict[str, dict[str, tuple[int, int]]] = {
    "def_records": {"cost": _MONEY, "price_per_unit": _UNIT_PRICE},
    "financing_records": {"amount": _MONEY},
    "fuel_records": {"cost": _MONEY, "rebate": _MONEY, "price_per_unit": _UNIT_PRICE},
    "insurance_coverages": {"deductible": _MONEY, "premium": _MONEY},
    "insurance_policies": {"premium_amount": _MONEY},
    "insurance_policy_vehicles": {"premium_share": _MONEY, "deductible": _MONEY},
    "service_line_items": {"cost": _MONEY},
    "service_visits": {
        "total_cost": _MONEY,
        "tax_amount": _MONEY,
        "shop_supplies": _MONEY,
        "misc_fees": _MONEY,
    },
    "spot_rental_billings": {
        "monthly_rate": _MONEY,
        "electric": _MONEY,
        "water": _MONEY,
        "waste": _MONEY,
        "total": _MONEY,
    },
    "spot_rentals": {
        "nightly_rate": _MONEY,
        "weekly_rate": _MONEY,
        "monthly_rate": _MONEY,
        "electric": _MONEY,
        "water": _MONEY,
        "waste": _MONEY,
        "total_cost": _MONEY,
    },
    "supply_purchases": {"total_cost": _MONEY},
    "supply_usages": {"unit_cost_snapshot": _UNIT_COST, "cost_snapshot": _MONEY},
    "tax_records": {"amount": _MONEY},
    "toll_transactions": {"amount": _MONEY},
    "vehicles": {
        "purchase_price": _MONEY,
        "sold_price": _MONEY,
        "msrp_base": _MONEY,
        "msrp_options": _MONEY,
        "msrp_total": _MONEY,
        "destination_charge": _MONEY,
        "archive_sale_price": _MONEY,
    },
}


def _get_fallback_engine() -> Engine:
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _numeric(column_type: TypeEngine[Any]) -> tuple[int, int] | None:
    """(precision, scale) of a bounded NUMERIC, or None for anything else.

    A float (DOUBLE PRECISION) isn't a Numeric, so it lands on None too.
    """
    if not isinstance(column_type, Numeric):
        return None
    precision = column_type.precision
    scale: int | None = getattr(column_type, "scale", None)
    if precision is None or scale is None:
        return None
    return precision, scale


def upgrade(engine: Engine | None = None) -> None:
    """Widen each listed column that's narrower than its target, in one transaction."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if engine.dialect.name != "postgresql":
        print("✓ SQLite ignores NUMERIC precision; nothing to widen")
        return

    inspector = inspect(engine)
    statements: list[str] = []
    widened = 0
    for table, targets in COLUMNS.items():
        if not inspector.has_table(table):
            print(f"  → {table} missing; skip")
            continue
        current = {c["name"]: c["type"] for c in inspector.get_columns(table)}
        clauses: list[str] = []
        for column, (precision, scale) in targets.items():
            if column not in current:
                print(f"  → {table}.{column} missing; skip")
                continue
            found = _numeric(current[column])
            if found == (precision, scale):
                continue
            if found is not None and found[1] == scale and found[0] < precision:
                clauses.append(f"ALTER COLUMN {column} TYPE NUMERIC({precision}, {scale})")
                continue
            print(f"  → {table}.{column} is {current[column]}; left alone")
        if clauses:
            statements.append(f"ALTER TABLE {table} " + ", ".join(clauses))
            widened += len(clauses)

    if not statements:
        print("✓ Money columns already wide enough")
        return

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    print(f"✓ Widened {widened} money column(s)")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 122 is forward-only.")


if __name__ == "__main__":
    upgrade()
