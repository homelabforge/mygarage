"""Widen the 14 columns a typed value couldn't round-trip through, on PostgreSQL.

Unit prices go to (13,4), outside temp to (5,2), OBC and sticker consumption to
(7,4), propane tank size to (7,3), trailer dims and GVWR to scale 3, and supply
quantities to (25,13). At the old scales a UK 6.000/gal came back 6.001 and a
US fl oz didn't survive the trip. SQLite ignores declared precision, so there's
nothing to do there; migration 136 rounds what SQLite already holds.

FATAL = True, for 122's reason. The API now takes the wider values, so a PG
install where the ALTER failed would round or reject them against the old
columns.

The column list is hard-coded: a historical migration can't follow the models
that come after it.

A column is altered only when it's a bounded NUMERIC whose scale and integer
digits are both at or below the target's, so widening can't round or overflow a
stored value. One already at its target is skipped quietly (a fresh install
gets there from create_all, and a rerun is a no-op). Anything else (wider,
unbounded, a float, a bigger scale) is named in the log and left alone.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Numeric, create_engine, inspect, text
from sqlalchemy.types import TypeEngine

FATAL = True

logger = logging.getLogger(__name__)

_UNIT_PRICE = (13, 4)
_CONSUMPTION = (7, 4)
_QUANTITY = (25, 13)
_TRAILER_LENGTH = (6, 3)

#: table -> {column: (precision, scale)} it should end up at.
COLUMNS: dict[str, dict[str, tuple[int, int]]] = {
    "def_records": {"price_per_unit": _UNIT_PRICE},
    "fuel_records": {
        "price_per_unit": _UNIT_PRICE,
        "outside_temp_c": (5, 2),
        "obc_l_per_100km": _CONSUMPTION,
        "tank_size_kg": (7, 3),
    },
    "supply_purchases": {"quantity": _QUANTITY},
    "supply_usages": {"quantity": _QUANTITY},
    "trailer_details": {
        "length_m": _TRAILER_LENGTH,
        "width_m": _TRAILER_LENGTH,
        "height_m": _TRAILER_LENGTH,
        "gvwr_kg": (8, 3),
    },
    "vehicles": {
        "fuel_economy_city_l_per_100km": _CONSUMPTION,
        "fuel_economy_highway_l_per_100km": _CONSUMPTION,
        "fuel_economy_combined_l_per_100km": _CONSUMPTION,
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


def _widens(found: tuple[int, int], target: tuple[int, int]) -> bool:
    """Whether target holds every value found does: no fewer places, no fewer whole digits."""
    precision, scale = found
    to_precision, to_scale = target
    return scale <= to_scale and precision - scale <= to_precision - to_scale


def upgrade(engine: Engine | None = None) -> None:
    """Widen each listed column that's narrower than its target, in one transaction."""
    if engine is None:
        engine = _get_fallback_engine()

    if engine.dialect.name != "postgresql":
        logger.info("135: SQLite ignores NUMERIC precision; nothing to widen")
        return

    inspector = inspect(engine)
    statements: list[str] = []
    widened = 0
    for table, targets in COLUMNS.items():
        if not inspector.has_table(table):
            logger.info("135: %s missing; skip", table)
            continue
        current = {c["name"]: c["type"] for c in inspector.get_columns(table)}
        clauses: list[str] = []
        for column, target in targets.items():
            if column not in current:
                logger.info("135: %s.%s missing; skip", table, column)
                continue
            found = _numeric(current[column])
            if found == target:
                continue
            if found is not None and _widens(found, target):
                clauses.append(f"ALTER COLUMN {column} TYPE NUMERIC({target[0]}, {target[1]})")
                continue
            logger.warning(
                "135: %s.%s is %s, not something NUMERIC%s holds exactly; left alone",
                table,
                column,
                current[column],
                target,
            )
        if clauses:
            statements.append(f"ALTER TABLE {table} " + ", ".join(clauses))
            widened += len(clauses)

    if not statements:
        logger.info("135: every column already at its type")
        return

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    logger.info("135: widened %s column(s)", widened)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 135 is forward-only.")


if __name__ == "__main__":
    upgrade()
