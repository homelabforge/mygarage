"""Service-visit vocabularies that a DB CHECK pins.

They live here, not in the schemas, so the ORM columns can carry them as
`Mapped[...]` types without the models importing the schema layer.
"""

from typing import Literal, TypeIs, get_args

#: `service_visits.service_category` (CHECK `check_service_visit_category`).
ServiceCategory = Literal["Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"]

_SERVICE_CATEGORIES: frozenset[str] = frozenset(get_args(ServiceCategory))


def is_service_category(value: str | None) -> TypeIs[ServiceCategory]:
    """Whether a stored string is one the visit's CHECK takes. A line item's
    category has no CHECK, so one restored from an old backup may not be."""
    return value in _SERVICE_CATEGORIES


#: `service_line_items.inspection_result` (CHECK `check_inspection_result`).
InspectionResult = Literal["passed", "failed", "needs_attention"]

#: `service_line_items.inspection_severity` (CHECK `check_inspection_severity`).
InspectionSeverity = Literal["green", "yellow", "red"]
