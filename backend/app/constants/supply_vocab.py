"""Supply vocabularies that a DB CHECK pins.

They live here, not in the schemas, so the ORM columns can carry them as
`Mapped[...]` types without the models importing the schema layer.
"""

from typing import Literal

#: `supplies.unit_type` (CHECK `check_supply_unit_type`).
SupplyUnitType = Literal["volume", "count"]
