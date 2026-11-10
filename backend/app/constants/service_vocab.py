"""Service-visit vocabularies that a DB CHECK pins.

They live here, not in the schemas, so the ORM columns can carry them as
`Mapped[...]` types without the models importing the schema layer.
"""

from typing import Literal

#: `service_visits.service_category` (CHECK `check_service_visit_category`).
ServiceCategory = Literal["Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"]

#: `service_line_items.inspection_result` (CHECK `check_inspection_result`).
InspectionResult = Literal["passed", "failed", "needs_attention"]

#: `service_line_items.inspection_severity` (CHECK `check_inspection_severity`).
InspectionSeverity = Literal["green", "yellow", "red"]
