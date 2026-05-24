"""Schema↔serializer coverage tests for CSV export endpoints.

What this catches
-----------------
The rc1 CSV export shipped missing every column added by migration 054
(filled_at, station_*, driver_*, payment_method, trip_type,
outside_temp_c, obc_*). The existing fuel CSV test passed because it
only verified the response was 200 and content-type was CSV — it
didn't check WHICH columns came back, and the round-trip tests
asserted the same stale column list the exporter produces (so adding
a model column without updating the exporter was structurally
invisible to the test suite).

This module asserts the contract:

    every public column on a model with an exporter MUST be present
    in the exported CSV header set, OR explicitly excluded by name.

If a column is added to the model and the exporter is not updated,
the test fails. If a column is removed from the model, the test
fails (forces explicit decision via EXCLUDE list).

Adding new exported models
--------------------------
Append an entry to ``EXPORT_COVERAGE_SPECS`` with:
- the SQLAlchemy model
- the export URL pattern (uses ``{vin}`` placeholder)
- a ``header_to_attr`` dict mapping CSV column header → model attr
- an ``exclude`` set listing columns intentionally not exported
  (PKs, FK ids that are implied, internal timestamps, relationships)

Tests against rc1 baseline (FuelRecord) are expected to FAIL until
Phase 2.3 expands the exporter. That failure is the point: it proves
the test fires when coverage is incomplete.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect

from app.models.fuel import FuelRecord


@dataclass
class ExportCoverageSpec:
    name: str
    model: type[Any]
    url_pattern: str
    header_to_attr: dict[str, str]
    exclude: set[str] = field(default_factory=set)


# Header → model attribute mapping for each model with a CSV exporter.
# Keep this in sync with the actual headers list in app/routes/export.py.
# When adding a model column, add the corresponding entry here AND wire
# the column into the exporter's row builder. The test fails if the two
# diverge.
EXPORT_COVERAGE_SPECS: list[ExportCoverageSpec] = [
    ExportCoverageSpec(
        name="fuel",
        model=FuelRecord,
        url_pattern="/api/export/vehicles/{vin}/fuel/csv",
        header_to_attr={
            "Date": "date",
            "Filled At": "filled_at",
            "Odometer (km)": "odometer_km",
            "Liters": "liters",
            "Price Per Liter": "price_per_unit",
            "Total Cost": "cost",
            "Full Tank": "is_full_tank",
            "Missed Fill-up": "missed_fillup",
            "Is Hauling": "is_hauling",
            "Fuel Type": "fuel_type",
            "Fuel Type Used": "fuel_type_used",
            "Station ID": "station_address_book_id",
            "Station": "station_name_freetext",
            "Driver ID": "driver_user_id",
            "Driver": "driver_name_freetext",
            "Payment Method": "payment_method",
            "Trip Type": "trip_type",
            "Outside Temp (C)": "outside_temp_c",
            "OBC L/100km": "obc_l_per_100km",
            "OBC Avg Speed (km/h)": "obc_avg_speed_kmh",
            "OBC Trip Duration (s)": "obc_trip_duration_s",
            "Notes": "notes",
        },
        exclude={
            # Surrogate keys + foreign keys implied by the export URL/scope:
            "id",
            "vin",
            # Internal bookkeeping not meaningful in user-facing exports:
            "created_at",
            # Alternate-unit fields covered by Liters; format is canonical metric:
            "propane_liters",
            "tank_size_kg",
            "tank_quantity",
            "kwh",
            "price_basis",
        },
    ),
]


def _model_column_names(model: type[Any]) -> set[str]:
    """All column names on a SQLAlchemy model (excluding relationships)."""
    return {col.key for col in inspect(model).columns}


def _csv_headers(body: str) -> list[str]:
    reader = csv.reader(io.StringIO(body))
    full_header = next(reader)
    # generate_csv_stream() prepends "units_version" to every export.
    # Strip it before comparing to model attrs.
    if full_header and full_header[0] == "units_version":
        return full_header[1:]
    return full_header


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("spec", EXPORT_COVERAGE_SPECS, ids=lambda s: s.name)
async def test_export_covers_all_model_columns(
    spec: ExportCoverageSpec,
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_vehicle_with_records: dict[str, Any],
):
    """Every public model column must be either exported or explicitly
    excluded. Diverge in either direction and this fails."""
    vin = test_vehicle_with_records["vin"]
    response = await client.get(spec.url_pattern.format(vin=vin), headers=auth_headers)
    assert response.status_code == 200, (
        f"{spec.name} export endpoint returned {response.status_code}"
    )

    exported_headers = set(_csv_headers(response.text))
    spec_headers = set(spec.header_to_attr.keys())

    # 1. Headers in the CSV must match what the spec claims.
    extra_in_csv = exported_headers - spec_headers
    missing_from_csv = spec_headers - exported_headers
    assert not extra_in_csv, (
        f"{spec.name}: exporter emits headers not declared in spec: {sorted(extra_in_csv)}. "
        "Add to EXPORT_COVERAGE_SPECS.header_to_attr."
    )
    assert not missing_from_csv, (
        f"{spec.name}: spec declares headers the exporter doesn't emit: {sorted(missing_from_csv)}. "
        "Update app/routes/export.py to emit them."
    )

    # 2. Every model column must be reachable: in the spec mapping or excluded.
    model_cols = _model_column_names(spec.model)
    spec_attrs = set(spec.header_to_attr.values())
    uncovered = model_cols - spec_attrs - spec.exclude
    assert not uncovered, (
        f"{spec.name}: model columns not in any exporter header and not in EXCLUDE: "
        f"{sorted(uncovered)}. Either wire them into export.py + add to "
        f"EXPORT_COVERAGE_SPECS.header_to_attr, or add to .exclude with a comment "
        f"explaining why they're intentionally hidden."
    )

    # 3. Every excluded name must actually be a model column (catches typos
    # that would otherwise silently weaken coverage).
    bogus_excludes = spec.exclude - model_cols
    assert not bogus_excludes, (
        f"{spec.name}: EXCLUDE contains names that are not model columns: "
        f"{sorted(bogus_excludes)}. Probably stale after a model rename."
    )
