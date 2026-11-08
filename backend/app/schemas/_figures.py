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

from decimal import ROUND_HALF_UP, Decimal

_TENTH = Decimal("0.1")
_HUNDREDTH = Decimal("0.01")


def to_stored_tenth(value: Decimal | None) -> Decimal | None:
    """Round to the tenth a NUMERIC(p, 1) column keeps. A null passes through."""
    if value is None:
        return None
    return value.quantize(_TENTH, rounding=ROUND_HALF_UP)


def to_stored_hundredth(value: Decimal | None) -> Decimal | None:
    """Round to the hundredth a NUMERIC(p, 2) column keeps. A null passes through."""
    if value is None:
        return None
    return value.quantize(_HUNDREDTH, rounding=ROUND_HALF_UP)
