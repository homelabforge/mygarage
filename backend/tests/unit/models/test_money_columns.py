"""Every money column has exactly the type the policy gives it.

Money is Numeric(12,2), a unit price Numeric(13,4), and the supply unit-cost
snapshot Numeric(15,4). Migration 122 widens an existing PostgreSQL database to
these, so a fresh create_all has to land on the same types or the two drift.

The registry (`MONEY_COLUMNS`) holds the list, and a scan of every Numeric
column keeps it complete: a money-named column the registry lacks fails here the
day it's added. A column with money's decimal places and no money word in its
name (a `surcharge`) is caught by the second scan: it's registered, or it's
listed in `NOT_MONEY_COLUMNS` with a reason. No database needed.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Float, Numeric
from sqlalchemy.types import TypeDecorator, TypeEngine

import app.main  # noqa: F401 (registers every model on Base.metadata)
from app.database import Base
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX, UNIT_PRICE_MAX
from tests.unit.schemas._money_names import (
    MONEY_COLUMNS,
    MONEY_TYPE,
    UNIT_COST_TYPE,
    UNIT_PRICE_TYPE,
    UNIT_WORDS,
    is_money_name,
)

#: Decimal places a money column has: cents, and the four a unit price and the
#: unit-cost snapshot carry.
MONEY_SCALES = frozenset({2, 4})

#: Columns with money's decimal places that aren't money.
NOT_MONEY_COLUMNS = frozenset(
    {
        "address_book.rating",  # a star rating
        "def_records.fill_level",  # a tank fraction, 0 to 1
        "location_points.speed",  # a GPS fix's speed
        "vehicles.window_sticker_confidence_score",  # the OCR parser's score
    }
)


def _stored_type(column: Column[Any]) -> TypeEngine[Any]:
    """The column's database type: a ScaledNumeric's is its `.impl`."""
    kind = column.type
    return kind.impl_instance if isinstance(kind, TypeDecorator) else kind


def _numeric_columns() -> dict[str, Column[Any]]:
    """table.column -> column, for every Numeric (and Float) column."""
    return {
        f"{table.name}.{column.name}": column
        for table in Base.metadata.tables.values()
        for column in table.columns
        # SQLAlchemy 2.1 split Float off Numeric, so it has to be named.
        if isinstance(_stored_type(column), (Numeric, Float))
    }


def test_the_column_scan_sees_the_models():
    # A floor on the scan, so an import change can't make the verdicts below a
    # pass over nothing.
    assert len(_numeric_columns()) >= 120


def test_every_numeric_column_is_money_exactly_when_registered():
    columns = _numeric_columns()
    called_money = {
        qualified for qualified, column in columns.items() if is_money_name(column.name)
    }
    assert sorted(called_money - MONEY_COLUMNS.keys()) == [], "money by name, not registered"
    assert sorted(MONEY_COLUMNS.keys() - called_money) == [], "registered, missed by name"


def _money_shaped(column: Column[Any]) -> bool:
    """Money's decimal places, and no unit word in the name."""
    words = set(column.name.lower().split("_"))
    return _stored_type(column).scale in MONEY_SCALES and not words & UNIT_WORDS


def test_every_money_shaped_column_is_registered_or_excused():
    # The name check only sees money words. A `surcharge` has none, so it would
    # pass there as not money and never get the policy type.
    columns = _numeric_columns()
    unclaimed = sorted(
        qualified
        for qualified, column in columns.items()
        if _money_shaped(column)
        and qualified not in MONEY_COLUMNS
        and qualified not in NOT_MONEY_COLUMNS
    )
    assert unclaimed == [], "money-shaped: register it, or add it to NOT_MONEY_COLUMNS"
    # Each excuse still has to be needed, so the list can't collect dead rows.
    stale = sorted(
        qualified
        for qualified in NOT_MONEY_COLUMNS
        if qualified not in columns or not _money_shaped(columns[qualified])
    )
    assert stale == [], "in NOT_MONEY_COLUMNS but not a money-shaped column"
    assert NOT_MONEY_COLUMNS.isdisjoint(MONEY_COLUMNS)


def test_every_money_column_has_its_policy_type():
    columns = _numeric_columns()
    missing = sorted(MONEY_COLUMNS.keys() - columns.keys())
    assert missing == [], "registered but not a Numeric column in the models"
    stored = {
        qualified: _stored_type(column)
        for qualified, column in columns.items()
        if qualified in MONEY_COLUMNS
    }
    wrong = {
        qualified: f"{type(kind).__name__}({kind.precision}, {kind.scale})"
        for qualified, kind in stored.items()
        # Exactly Numeric: the scan takes Floats too, and a Float stores a double.
        if type(kind) is not Numeric or (kind.precision, kind.scale) != MONEY_COLUMNS[qualified]
    }
    assert wrong == {}


def test_the_registry_gives_each_kind_its_type():
    # A unit price and the unit-cost snapshot carry extra places; every other
    # amount is plain money.
    special = {"price_per_unit": UNIT_PRICE_TYPE, "unit_cost_snapshot": UNIT_COST_TYPE}
    wrong = {
        qualified: registered
        for qualified, registered in MONEY_COLUMNS.items()
        if registered != special.get(qualified.split(".", 1)[1], MONEY_TYPE)
    }
    assert wrong == {}


def test_each_type_holds_exactly_its_input_max():
    # The input bound is the column's own largest value, no more and no less.
    for (precision, scale), maximum in [
        (MONEY_TYPE, MONEY_MAX),
        (UNIT_PRICE_TYPE, UNIT_PRICE_MAX),
        (UNIT_COST_TYPE, UNIT_COST_MAX),
    ]:
        assert Decimal(10) ** (precision - scale) - Decimal(10) ** -scale == maximum
