"""Every model Numeric column rounds its binds to its own scale.

PostgreSQL rounds a number to the column's scale on the way in; SQLite keeps
whatever it's handed. `ScaledNumeric` does PG's rounding in Python so both store
the same number, and a column declared as a bare `Numeric` skips it. No
database needed.
"""

from typing import Any

from sqlalchemy import Column, Numeric

import app.main  # noqa: F401 (registers every model on Base.metadata)
from app.database import Base


def _columns() -> dict[str, Column[Any]]:
    return {
        f"{table.name}.{column.name}": column
        for table in Base.metadata.tables.values()
        for column in table.columns
    }


def test_no_model_column_is_a_bare_numeric():
    bare = sorted(
        qualified for qualified, column in _columns().items() if isinstance(column.type, Numeric)
    )
    assert bare == [], "use ScaledNumeric(p, s) so SQLite rounds like PG"


def test_every_scaled_column_has_a_precision_and_scale():
    # Imported here so the bare-Numeric scan above still runs on its own.
    from app.models._types import ScaledNumeric

    scaled = {
        qualified: column.type
        for qualified, column in _columns().items()
        if isinstance(column.type, ScaledNumeric)
    }
    # A floor, so a scan that sees no models can't pass as all clear.
    assert len(scaled) >= 126
    unscaled = sorted(
        qualified
        for qualified, kind in scaled.items()
        if kind.impl.precision is None or kind.impl.scale is None
    )
    assert unscaled == []
