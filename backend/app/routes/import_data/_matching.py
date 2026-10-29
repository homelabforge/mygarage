"""How an imported row is matched against what's stored: tolerances, column scales, duplicates."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import ColumnElement, Numeric, and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.base import ExecutableOption

from app.models import (
    FuelRecord,
)
from app.models._types import ScaledNumeric
from app.routes.import_data._common import parse_decimal
from app.utils.csv_units import (
    CONSUMPTION,
    DISTANCE,
    MASS,
    PRICE_PER_VOLUME,
    PROPANE_VOLUME,
    SPEED,
    TEMPERATURE,
    VOLUME,
    CsvUnitContext,
)
from app.utils.odometer_tolerance import KM_STEP, conversion_tolerance


async def _last_id_before_import(db: AsyncSession, model: Any) -> int:
    """The highest `model.id` stored when an import begins, or 0 for an empty table.

    Ids only grow, so every row this import writes sits above it, and a row at
    or below it was stored before the import started. Taken after the vehicle
    write lock and before the first row is written.
    """
    return int((await db.execute(select(func.max(model.id)))).scalar() or 0)


def _within(
    column: InstrumentedAttribute[Any], value: Decimal, half_width: Decimal
) -> ColumnElement[bool]:
    """`column` within `half_width` of `value`, compared exactly on every dialect.

    The bounds are bound as an unscaled NUMERIC. Bound with the column's own
    type, PostgreSQL casts them to its NUMERIC(10, 2) and rounds them, so a
    half-step window around 100000.00 reached 100000.01 and swallowed the next
    step on PostgreSQL only.
    """
    return column.between(
        literal(value - half_width, Numeric()), literal(value + half_width, Numeric())
    )


def _converted_value_matches(
    column: InstrumentedAttribute[Any],
    value: Decimal | None,
    step: Decimal,
    *,
    converted: bool,
    stored_before_import: ColumnElement[bool],
) -> ColumnElement[bool]:
    """A duplicate-check condition on a column holding a unit-converted value.

    A stored row matches when it holds the same figure at the column's
    precision: within half a `step`, which covers PostgreSQL rounding the value
    on write and SQLite keeping it as given.

    Only one case can sit further away. A value converted from miles or gallons
    in this import meets a row stored with the truncated pre-v3.4.0 factors a
    few parts per million off, on top of that rounding
    (`conversion_tolerance`, shared with tire history). That band is allowed
    ONLY for a `converted` value and ONLY against a row `stored_before_import`.
    Applied to every check, it skipped a second, genuinely different same-day
    reading inside it (0.31 km at 100,000 km), including one this import had
    just written.

    An absent value still matches only NULL. More than one stored row can
    match, so a caller treats any match as the duplicate rather than asking for
    exactly one.
    """
    if value is None:
        return column.is_(None)
    half_step = step / 2
    same_figure = _within(column, value, half_step)
    if not converted:
        return same_figure
    drifted = and_(stored_before_import, _within(column, value, conversion_tolerance(value, step)))
    return or_(same_figure, drifted)


def _odometer_matches(
    model: Any, odometer_km: Decimal | None, *, converted: bool, last_id_before_import: int
) -> ColumnElement[bool]:
    """`_converted_value_matches` for `model.odometer_km`, in km."""
    return _converted_value_matches(
        model.odometer_km,
        odometer_km,
        KM_STEP,
        converted=converted,
        stored_before_import=model.id <= last_id_before_import,
    )


def _matches(column: InstrumentedAttribute[Any], value: Any) -> ColumnElement[bool]:
    """`column` equal to `value`, or NULL when `value` is None."""
    return column.is_(None) if value is None else column == value


def _text_matches(column: InstrumentedAttribute[Any], value: str | None) -> ColumnElement[bool]:
    """`_matches` for free-ish text: no value also matches a stored '', which older writes left."""
    return or_(column.is_(None), column == "") if value is None else column == value


def _same_figure(column: InstrumentedAttribute[Any], value: Decimal | None) -> ColumnElement[bool]:
    """`column` holds `value` at its scale: within half its step, or NULL for None.

    Every ORM write rounds at bind now (ScaledNumeric), so only a legacy SQLite
    row holds places past the scale: one written before migration 136, or in a
    table 136 skipped (it's not FATAL and runs per table). That row reads back,
    and exports, rounded, and an exact `=` never meets it (Fable F-1, T-20); the
    band covers a 136 that didn't finish. The step is read off the column, so a
    widened column narrows its band with it.
    """
    return column.is_(None) if value is None else _within(column, value, _column_step(column) / 2)


#: Every money column is NUMERIC(12,2) (schemas/_money.py).
_MONEY_STEP = Decimal("0.01")


def _money_matches(
    column: InstrumentedAttribute[Any], value: Decimal | None
) -> ColumnElement[bool]:
    """`column` holds the same amount to the cent; 0 and NULL match each other (v8 wrote $0 as null)."""
    if value is None or value == 0:
        return or_(column.is_(None), _within(column, Decimal(0), _MONEY_STEP / 2))
    return _within(column, value, _MONEY_STEP / 2)


def _zero_was_blank(version: str, faithful_from: int) -> bool:
    """Whether a file of schema `version` predates its export writing a 0 as 0.

    The fuel and DEF exports wrote a 0 L fill-up and a 0.00 fill level as a
    blank cell up to CSV v7 and as null up to JSON v8. A blank or unreadable
    version is an older file.
    """
    try:
        return int(version) < faithful_from
    except ValueError:
        return True


def _or_blank_zero(
    condition: ColumnElement[bool],
    column: InstrumentedAttribute[Any],
    value: Decimal | None,
    *,
    zero_was_blank: bool,
) -> ColumnElement[bool]:
    """`condition`, which a missing `value` makes `IS NULL`, or a stored 0 when that file blanked one.

    Only an older file's blank stands for a 0 (`_zero_was_blank`); a newer one's
    is a missing figure, another row than the 0.
    """
    if value is not None or not zero_was_blank:
        return condition
    return or_(condition, _within(column, Decimal(0), _column_step(column) / 2))


class _DuplicateMatcher:
    """Duplicate checks that pair the file with the stored rows one to one (R5).

    A file row is a duplicate only of a row stored before this import began,
    with the same portable content, that no earlier file row has matched; the
    lowest such id is taken and spent. So a file's identical rows all import
    into an empty target, a target holding one of them gains the rest, a
    re-import adds nothing, and a row this import wrote is never a duplicate.
    """

    def __init__(self, last_ids: Mapping[type[Any], int]) -> None:
        self._last_ids = dict(last_ids)
        self._spent: dict[type[Any], set[int]] = {}

    @classmethod
    async def before_import(cls, db: AsyncSession, *models: type[Any]) -> _DuplicateMatcher:
        """Taken after the vehicle lock and before the first write, like `_last_id_before_import`."""
        return cls({model: await _last_id_before_import(db, model) for model in models})

    def last_id(self, model: type[Any]) -> int:
        """The highest id `model` held when the import began."""
        return self._last_ids[model]

    async def take(
        self,
        db: AsyncSession,
        model: type[Any],
        *conditions: ColumnElement[bool],
        options: Sequence[ExecutableOption] = (),
        same: Callable[[Any], bool] | None = None,
    ) -> Any | None:
        """Spend the lowest unspent stored row matching `conditions` and `same`; None when none does.

        `same` compares what SQL can't, such as a visit's line items, on rows
        loaded with `options`.
        """
        spent = self._spent.setdefault(model, set())
        result = await db.execute(
            select(model)
            .where(model.id <= self._last_ids[model], *conditions)
            .options(*options)
            .order_by(model.id)
        )
        for row in result.scalars():
            if row.id in spent or (same is not None and not same(row)):
                continue
            spent.add(row.id)
            return row
        return None


def _column_step(column: InstrumentedAttribute[Any]) -> Decimal:
    """One step at `column`'s scale, read off its ScaledNumeric type."""
    column_type = column.type
    if not isinstance(column_type, ScaledNumeric):
        raise TypeError(f"{column} is not a ScaledNumeric column")
    return Decimal(1).scaleb(-column_type.scale)


#: The step of the column each converted quantity lands in, read off the model
#: so a widened column can't leave it behind (#245 did, F-1). The DEF, service,
#: odometer and warranty columns share these scales; a unit test holds them to it.
_COLUMN_SCALE: Mapping[str, Decimal] = {
    DISTANCE: _column_step(FuelRecord.odometer_km),
    VOLUME: _column_step(FuelRecord.liters),
    PRICE_PER_VOLUME: _column_step(FuelRecord.price_per_unit),
    TEMPERATURE: _column_step(FuelRecord.outside_temp_c),
    CONSUMPTION: _column_step(FuelRecord.obc_l_per_100km),
    SPEED: _column_step(FuelRecord.obc_avg_speed_kmh),
    PROPANE_VOLUME: _column_step(FuelRecord.propane_liters),
    MASS: _column_step(FuelRecord.tank_size_kg),
}


def _at_scale(value: Decimal | None, scale: Decimal) -> Decimal | None:
    """`value` rounded to its column's scale, half up, as PostgreSQL rounds NUMERIC.

    The bind rounds the same way (ScaledNumeric); rounding here first means the
    bounds check and the duplicate key see the figure that gets stored (G5a-80).
    A value that can't be rounded (Infinity, NaN, more digits than the context
    holds) passes through, and the bounds check after it refuses it.
    """
    if value is None or not value.is_finite():
        return value
    try:
        return value.quantize(scale, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return value


def _canonical_cell(units: CsvUnitContext, row: Mapping[str, Any], quantity: str) -> Decimal | None:
    """One row's `quantity`, converted into canonical metric storage.

    None when the file has no column for that quantity, so an importer can
    ask for every quantity it supports without first checking which the file
    happens to carry. The unit comes from the file alone (see
    `app.utils.csv_units`), never from the importing account's preferences.
    """
    header = units.column(quantity)
    if header is None:
        return None
    value = units.to_canonical(quantity, parse_decimal(row.get(header, "")))
    # R7: a converted figure is rounded to its column's scale here, so the bounds
    # check and the key see what the bind will store; a canonical one is left as given.
    return _at_scale(value, _COLUMN_SCALE[quantity]) if units.converts(quantity) else value
