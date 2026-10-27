"""Column types shared by the models."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Numeric
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class ScaledNumeric(TypeDecorator[Decimal]):
    """`Numeric(precision, scale)` that rounds every bind to the column's scale.

    PostgreSQL rounds a number to the column's scale on the way in, half away
    from zero; SQLite keeps whatever it's handed. So SQLite rounds here the same
    way, and both store the same number. Comparison binds take the column's type
    too, so `WHERE odometer_km > :x` compares what's stored on both.
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int) -> None:
        super().__init__(precision, scale)
        # Named after __init__'s arguments so they're in the cache key: a
        # cached statement keeps its bind processors and asyncpg's cast.
        self.precision = precision
        self.scale = scale
        self._step = Decimal(1).scaleb(-scale)

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        """The value rounded to the column's scale, ROUND_HALF_UP like PG.

        A float goes through its repr, so 1.005 rounds as the 1.005 that was
        typed, not as the double just below it. None and NaN/infinity go
        through untouched.
        """
        if value is None:
            return None
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
        if not number.is_finite():
            return value
        try:
            return number.quantize(self._step, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            # Too many digits to round. Let the database refuse it with its own
            # overflow (a 422) instead of a StatementError (a 500) from here.
            return value
