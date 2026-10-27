"""One bound for every stored amount, whatever the viewer's currency.

Records carry no currency: an amount is a bare number shown in each viewer's
`currency_code`. So a money bound can only mean "fits the column" and "is a
number a household could mean", and the same bound serves forint and dollars.

Every money column is Numeric(12,2), every unit price Numeric(13,4), and the
supply unit-cost snapshot Numeric(15,4). Each max below is the largest value its
column holds, and each fits a double at its scale, so it round-trips through
SQLite's REAL and a JS number.

Use the aliases on input schemas only. A response carries no bounds, or a stored
value past today's bound turns every read of it into a 500.

    cost: OptionalMoney = None
    amount: Money = Field(..., decimal_places=2, description="Payment amount")

Pydantic merges an assigned `Field(...)` with the alias's, so a description or
`decimal_places` goes there.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import Field

#: The largest amount a Numeric(12,2) money column holds.
MONEY_MAX = Decimal("9999999999.99")
#: The largest price a Numeric(13,4) unit-price column holds (`price_per_unit`).
UNIT_PRICE_MAX = Decimal("999999999.9999")
#: The largest supply unit-cost snapshot a Numeric(15,4) column holds. It is
#: computed, never typed in, so it is checked before flush rather than bounded.
UNIT_COST_MAX = Decimal("99999999999.9999")

# Plain assignments on purpose. A PEP 695 `type Money = ...` alias still
# validates, but pydantic keeps its bounds inside the alias, so the FieldInfo
# metadata `_within_api_bounds` reads comes back empty and imports go unchecked.
Money = Annotated[Decimal, Field(ge=0, le=MONEY_MAX)]
OptionalMoney = Annotated[Decimal | None, Field(ge=0, le=MONEY_MAX)]
UnitPrice = Annotated[Decimal, Field(ge=0, le=UNIT_PRICE_MAX)]
OptionalUnitPrice = Annotated[Decimal | None, Field(ge=0, le=UNIT_PRICE_MAX)]
