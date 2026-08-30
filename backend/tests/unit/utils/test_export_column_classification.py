"""Every column an export route emits is classified: unit-bearing, or not.

Issue #152 phase 2b, carried item 1. `csv_emission.apply_unit_set` looks each
header up in `EMITTED_COLUMNS` and, on a miss, passes the column through
untouched:

    column = EMITTED_COLUMNS.get(header)
    if column is None:
        out_headers.append(header)   # <- silent pass-through
        columns.append(None)

That is correct for a date or a cost and wrong for a unit. A future
unit-bearing column added to an export route but not to `EMITTED_COLUMNS`
emits raw canonical metric to every reader, with no token in its header, and
nothing anywhere fails.

Why the existing guard does not cover it
----------------------------------------
`tests/integration/routes/test_export_schema_coverage.py` answers a different
question -- "is every MODEL column exported?" -- for `FuelRecord` alone, the
single entry in `EXPORT_COVERAGE_SPECS`. Service, DEF, odometer and the five
dimensionless pairs have no column guard there at all. And its failure message
tells the developer to "Add to EXPORT_COVERAGE_SPECS.header_to_attr", which
routes a new unit-bearing column PAST the unit question rather than into it.

So this module asks the other question, for all nine pairs, and asks the unit
question first.

Static, not over HTTP, and deliberately so: `EMITTED_COLUMNS` is keyed by the
canonical PRE-CONVERSION header name (`Liters`, `Outside Temp (C)`), which is
exactly what these literals hold. Reading the emitted v6 spelling back over
HTTP would mean re-deriving that mapping in the test, i.e. re-implementing the
thing under test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.utils.csv_emission import EMITTED_COLUMNS

_EXPORT_SOURCE = Path(__file__).resolve().parents[3] / "app" / "routes" / "export.py"

# Every export function that declares a literal `headers = [...]`, and how many
# columns it declares. Pinned by NAME and COUNT so that a route which stops
# using a literal list -- or is deleted, or renamed -- makes this module fail
# rather than quietly checking fewer columns. A guard whose input can silently
# become empty is not a guard.
EXPECTED_HEADER_LISTS: dict[str, int] = {
    # The four unit-bearing pairs, which go through `build_csv` ->
    # `apply_unit_set`. These are the ones a miss actually corrupts.
    "export_service_records_csv": 8,
    "export_fuel_records_csv": 28,
    "export_def_records_csv": 9,
    "export_odometer_records_csv": 3,
    # The five dimensionless pairs, which call `generate_csv_stream` directly
    # and never reach `apply_unit_set`. Covered anyway: a unit-bearing column
    # added to one of these is a real hazard too, and a worse one, because
    # there is no conversion layer to have missed.
    "export_hours_records_csv": 4,
    "export_warranties_csv": 10,
    "export_insurance_csv": 9,
    "export_tax_records_csv": 5,
    "export_notes_csv": 3,
}

# Headers that carry no unit from `app.constants.units`' vocabulary. Grouped by
# WHY, because the grouping is the classification a new column has to earn.
#
# ★ Adding a name here is a decision that the column carries no unit. If it
# does carry one, it belongs in `csv_emission.EMITTED_COLUMNS` instead.
DIMENSIONLESS_HEADERS: frozenset[str] = frozenset(
    {
        # Dates and timestamps.
        "Date",
        "Filled At",
        "Start Date",
        "End Date",
        "Renewal Date",
        # Currency. Not a unit in this system: there is no currency quantity in
        # `UnitSet`, and a cost is formatted, never converted.
        "Cost",
        "Total Cost",
        "Rebate",
        "Premium",
        "Deductible",
        "Amount",
        # Free text, names and identifiers.
        "Category",
        "Description",
        "Vendor",
        "Notes",
        "Fuel Type Used",
        "Station ID",
        "Station",
        "Driver ID",
        "Driver",
        "Payment Method",
        "Trip Type",
        "Charge Level",
        "Charge Location",
        "Source",
        "Brand",
        "Provider",
        "Policy Number",
        "Type",
        "Coverage",
        "Coverage Limits",
        "Terms",
        "Title",
        "Content",
        # Booleans and counts.
        "Full Tank",
        "Missed Fill-up",
        "Is Hauling",
        "Max Claims",
        # Percentages and ratios. Unitless by definition.
        "SOC Start (%)",
        "SOC End (%)",
        "Battery SOH (%)",
        "Fill Level",
        # Engine hours: dimensionless BY DECISION (R6). Hours is outside the
        # unit system and `adapter_for` raises `KeyError` for it on purpose.
        "Engine Hours",
        # Seconds. A duration is a real physical quantity, but this codebase's
        # `UnitSet` has no duration entry, so there is no second spelling to
        # convert to and the column names its unit in prose.
        "OBC Trip Duration (s)",
    }
)


def _header_lists() -> dict[str, list[str]]:
    """Every literal `headers = [...]` in `export.py`, by enclosing function.

    An AST walk rather than a grep: a regex over source cannot tell a header
    list from a comment mentioning one, and cannot tell which function it
    belongs to.
    """
    tree = ast.parse(_EXPORT_SOURCE.read_text())
    found: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "headers"
                and isinstance(stmt.value, ast.List)
                and all(isinstance(e, ast.Constant) for e in stmt.value.elts)
            ):
                found[node.name] = [e.value for e in stmt.value.elts]
    return found


HEADER_LISTS = _header_lists()


class TestTheGuardsInputCannotSilentlyEmpty:
    """A classification test that classifies nothing passes trivially."""

    def test_every_expected_export_route_still_declares_a_literal_header_list(
        self,
    ) -> None:
        assert set(HEADER_LISTS) == set(EXPECTED_HEADER_LISTS), (
            "export.py's literal `headers = [...]` lists have moved. Found "
            f"{sorted(HEADER_LISTS)}, expected {sorted(EXPECTED_HEADER_LISTS)}. "
            "If a route now builds its headers dynamically, this module stops "
            "seeing its columns: teach `_header_lists` to find them, do not "
            "just drop the route from EXPECTED_HEADER_LISTS."
        )

    @pytest.mark.parametrize("route", sorted(EXPECTED_HEADER_LISTS))
    def test_each_route_declares_the_column_count_it_did(self, route: str) -> None:
        """A count, so a truncated or half-parsed list is visible."""
        assert len(HEADER_LISTS[route]) == EXPECTED_HEADER_LISTS[route]


class TestEveryEmittedColumnIsClassified:
    """The guard carried item 1 asked for."""

    @pytest.mark.parametrize("route", sorted(EXPECTED_HEADER_LISTS))
    def test_no_export_column_is_unclassified(self, route: str) -> None:
        unclassified = [
            header
            for header in HEADER_LISTS[route]
            if header not in EMITTED_COLUMNS and header not in DIMENSIONLESS_HEADERS
        ]
        assert not unclassified, (
            f"{route} emits {unclassified}, which is in neither "
            "csv_emission.EMITTED_COLUMNS nor DIMENSIONLESS_HEADERS.\n"
            "\n"
            "Does the column carry a unit?\n"
            "  YES -> add it to csv_emission.EMITTED_COLUMNS with its base "
            "name and per-token decimal places, and add the matching base to "
            "the importer's QuantitySpec in csv_units.py. Until you do, "
            "apply_unit_set passes it through unconverted and every reader "
            "gets raw canonical metric under a header that does not say so.\n"
            "  NO  -> add it to DIMENSIONLESS_HEADERS above, in the group that "
            "says why."
        )

    def test_every_emitted_column_key_is_actually_emitted_somewhere(self) -> None:
        """The other direction: a stale `EMITTED_COLUMNS` key is a conversion
        rule for a column that no longer exists, and reads as coverage."""
        emitted = {header for headers in HEADER_LISTS.values() for header in headers}
        orphans = sorted(set(EMITTED_COLUMNS) - emitted)
        assert not orphans, (
            f"EMITTED_COLUMNS declares {orphans}, which no export route emits. "
            "Either a route was renamed and its column with it, or the entry "
            "is stale. A rule for a column that does not exist is not coverage."
        )

    def test_the_two_sets_do_not_overlap(self) -> None:
        """A header in both would be converted AND declared unitless, and
        whichever check ran first would look satisfied."""
        overlap = sorted(set(EMITTED_COLUMNS) & DIMENSIONLESS_HEADERS)
        assert not overlap, f"classified twice, and contradictorily: {overlap}"

    def test_the_dimensionless_list_carries_no_stale_names(self) -> None:
        """A name no route emits is a decision about nothing, and it hides the
        next real column behind an allowlist that looks maintained."""
        emitted = {header for headers in HEADER_LISTS.values() for header in headers}
        stale = sorted(DIMENSIONLESS_HEADERS - emitted)
        assert not stale, (
            f"DIMENSIONLESS_HEADERS lists {stale}, which no export route emits. "
            "Probably stale after a column rename."
        )
