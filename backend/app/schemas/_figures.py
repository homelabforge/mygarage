"""Round a figure to the scale its column keeps, as it's parsed.

`ScaledNumeric` rounds every bind, so an unrounded figure is checked against
one number and saved as another. Rounding in the schema means the checks see
what the column will hold. Put the AfterValidator after the bounds, so a value
just past one is refused instead of rounded back inside it:

    engine_hours: Annotated[Decimal | None, AfterValidator(to_stored_tenth)] = Field(
        None, ge=0, le=9999999.9
    )

Pydantic runs the assigned Field's bounds before the Annotated validator.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_TENTH = Decimal("0.1")
_HUNDREDTH = Decimal("0.01")


def _rounded(value: Decimal | None, step: Decimal) -> Decimal | None:
    if value is None:
        return None
    try:
        return value.quantize(step, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        # Too many digits to round. Every request field's `le` refuses this first;
        # past that, hand it on unrounded like ScaledNumeric, not a 500 from here.
        return value


def to_stored_tenth(value: Decimal | None) -> Decimal | None:
    """Round to the tenth a NUMERIC(p, 1) column keeps. A null passes through."""
    return _rounded(value, _TENTH)


def to_stored_positive_tenth(value: Decimal | None) -> Decimal | None:
    """Round to the tenth, then refuse a figure the rounding took down to zero.

    For a `gt=0` field. 0.04 clears the bound and rounds to 0.0, which the
    column's > 0 CHECK answered with a 500.
    """
    rounded = to_stored_tenth(value)
    if rounded is not None and rounded <= 0:
        raise ValueError("Input should be greater than 0 once rounded to a tenth")
    return rounded


def to_stored_hundredth(value: Decimal | None) -> Decimal | None:
    """Round to the hundredth a NUMERIC(p, 2) column keeps. A null passes through."""
    return _rounded(value, _HUNDREDTH)
