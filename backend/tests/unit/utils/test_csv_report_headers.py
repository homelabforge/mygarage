"""The two report CSV header rows, and the guard derived from them.

Issue #152 phase 2b task 5. `routes/reports.py` emits two printable summaries
that are NOT importable, and whose unit-bearing columns now carry v6
vocabulary tokens like every other CSV the app writes.

Why the guard is derived rather than listed
-------------------------------------------
Hand-maintaining the rejected tuples next to a separate emitter is the exact
failure shape task 3 flagged: a future column lands in the emitter, nobody
adds it to the list, and the guard silently stops matching. So
`csv_units.SERVICE_HISTORY_REPORT_HEADERS` / `ALL_RECORDS_REPORT_HEADERS` are
the one source, `reports.py` emits from them, and `REJECTED_HEADER_TUPLES`
expands them over every unit set the app can resolve.

The historical half cannot be derived, because the emitters that wrote those
four shapes no longer exist. `test_the_pre_v6_mileage_report_is_still_rejected`
is what stops the next reader deleting those literals as redundant, and
`test_the_v2_backups_whose_names_overlap_a_report_still_import` is what stops
the guard being widened into the backups sitting next to them.

Every era, not only the ambiguous ones
--------------------------------------
The guard covered only unit-AMBIGUOUS shapes until 2026-08-26, which left the
all-records report importable in both its pre-v6 forms. That is the shape that
actually corrupts: importing one writes a service visit per fuel fill-up,
stamped `service_category='Maintenance'` and indistinguishable from real
maintenance. The rule is now flat, a report CSV is never importable in any
era, so the guard holds twelve tuples: four historical literals and eight
derived.

Every expected header row below is a HAND-WRITTEN literal. Deriving the
expectation from `report_header_row` would make the exhaustiveness assertions
tautologies.
"""

from __future__ import annotations

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.utils.csv_emission import (
    EMITTED_COLUMNS,
    ODOMETER_COLUMN,
    VOLUME_COLUMN,
    token_for,
)
from app.utils.csv_units import (
    ALL_RECORDS_REPORT_HEADERS,
    DISTANCE,
    FUEL_VOLUME,
    ODOMETER_DISTANCE,
    QUANTITY_TOKENS,
    REJECTED_HEADER_TUPLES,
    SERVICE_HISTORY_REPORT_HEADERS,
    VOLUME,
    ReportColumn,
    build_csv_unit_context,
    report_header_row,
)

# --- hand-written: every header row either report can emit -----------------

SERVICE_HISTORY_METRIC = (
    "Date",
    "Odometer (km)",
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
)
SERVICE_HISTORY_IMPERIAL = (
    "Date",
    "Odometer (mi)",
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
)
ALL_RECORDS_METRIC = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (km)",
    "Vendor",
    "Volume (L)",
)
ALL_RECORDS_IMPERIAL = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (mi)",
    "Vendor",
    "Volume (gal_us)",
)

# The pre-v6 shape. Its `Mileage` column survived the metric migration
# unchanged, so a miles file and a kilometres file are byte-identical.
PRE_V6_SERVICE_HISTORY = (
    "Date",
    "Mileage",
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
)

# The two BACKUP shapes whose names overlap a report's. Both must stay OUT of
# the guard: they are the reason the signature is an ordered tuple rather than
# a column set, and each is a real v2-era backup restore.
V2_PRIMARY_SERVICE_BACKUP = (
    "Date",
    "Category",
    "Description",
    "Mileage",
    "Cost",
    "Vendor",
    "Notes",
)
V2_INITIAL_SERVICE_BACKUP = (
    "Date",
    "Service Type",
    "Description",
    "Mileage",
    "Cost",
    "Vendor Name",
    "Vendor Location",
    "Notes",
)

# The other three report eras. Every one of them imported until 2026-08-26 and
# every one is now refused: a report CSV is not a backup, in any era.
PRE_V6_SERVICE_HISTORY_EIGHT_COLUMN = (
    "Date",
    "Mileage",
    "Service Type",
    "Description",
    "Cost",
    "Vendor Name",
    "Vendor Phone",
    "Notes",
)
PRE_V6_ALL_RECORDS_V2 = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Mileage",
    "Vendor",
)
PRE_V6_ALL_RECORDS_V3 = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (km)",
    "Vendor",
)

# All twelve, spelled out: four historical literals nothing can derive, plus
# two distance tokens for the v6 service-history report and two distance x
# three volume for the v6 all-records report.
EVERY_REJECTED_TUPLE = {
    PRE_V6_SERVICE_HISTORY,
    PRE_V6_SERVICE_HISTORY_EIGHT_COLUMN,
    PRE_V6_ALL_RECORDS_V2,
    PRE_V6_ALL_RECORDS_V3,
    SERVICE_HISTORY_METRIC,
    SERVICE_HISTORY_IMPERIAL,
    ALL_RECORDS_METRIC,
    ALL_RECORDS_IMPERIAL,
    (
        "Date",
        "Type",
        "Category",
        "Description",
        "Cost",
        "Odometer (km)",
        "Vendor",
        "Volume (gal_us)",
    ),
    (
        "Date",
        "Type",
        "Category",
        "Description",
        "Cost",
        "Odometer (km)",
        "Vendor",
        "Volume (gal_uk)",
    ),
    (
        "Date",
        "Type",
        "Category",
        "Description",
        "Cost",
        "Odometer (mi)",
        "Vendor",
        "Volume (L)",
    ),
    (
        "Date",
        "Type",
        "Category",
        "Description",
        "Cost",
        "Odometer (mi)",
        "Vendor",
        "Volume (gal_uk)",
    ),
}

# The exact 400 detail each family is refused with, hand-written. Compared in
# FULL, never by substring: the pre-v6 message CONTAINS the v6 one's
# distinguishing phrase ("...unversioned service-history report export..."),
# so a substring assertion cannot tell the two apart and passes when the
# property it names is false.
PRE_V6_REFUSAL = (
    "This header row matches the unversioned service-history report export. "
    "Its 'Mileage' column is miles in older files and kilometres in newer ones, "
    "with nothing in the file to tell them apart, so importing it could "
    "silently store the wrong distance. Re-export the vehicle from "
    "Export > Service records instead, which carries a units marker."
)
SERVICE_HISTORY_REFUSAL = (
    "This header row matches the service-history report export, which is a "
    "printable summary rather than a backup: it flattens each service visit "
    "into one row per line item and carries columns the importer does not "
    "consume, so importing it would create malformed records. Re-export the "
    "vehicle from Export > Service records instead."
)
ALL_RECORDS_REFUSAL = (
    "This header row matches the all-records report export, which is a "
    "printable summary rather than a backup: it interleaves fuel rows with "
    "service rows in one file, so importing it would create a service visit "
    "out of every fill-up. Re-export the vehicle from Export instead, one "
    "record type at a time."
)


class TestTheEmittedHeaderRows:
    """What each endpoint puts on the wire, under each unit system."""

    def test_service_history_metric(self) -> None:
        assert report_header_row(SERVICE_HISTORY_REPORT_HEADERS, {DISTANCE: "km"}) == list(
            SERVICE_HISTORY_METRIC
        )

    def test_service_history_imperial(self) -> None:
        assert report_header_row(SERVICE_HISTORY_REPORT_HEADERS, {DISTANCE: "mi"}) == list(
            SERVICE_HISTORY_IMPERIAL
        )

    def test_all_records_metric(self) -> None:
        row = report_header_row(ALL_RECORDS_REPORT_HEADERS, {DISTANCE: "km", VOLUME: "L"})
        assert row == list(ALL_RECORDS_METRIC)

    def test_all_records_imperial(self) -> None:
        row = report_header_row(ALL_RECORDS_REPORT_HEADERS, {DISTANCE: "mi", VOLUME: "gal_us"})
        assert row == list(ALL_RECORDS_IMPERIAL)

    def test_the_volume_column_is_appended_last(self) -> None:
        """Under metric the seven pre-v6 columns keep their exact positions,
        so a spreadsheet reading columns 0..6 of an all-records export is
        unaffected by v6. Inserting the new column anywhere else breaks that.
        """
        row = report_header_row(ALL_RECORDS_REPORT_HEADERS, {DISTANCE: "km", VOLUME: "L"})
        assert row[:7] == list(PRE_V6_ALL_RECORDS_V3)
        assert row[7] == "Volume (L)"

    def test_a_missing_quantity_raises_rather_than_falling_back_to_metric(self) -> None:
        """A silently-canonical column inside an imperial file is the defect
        this phase exists to remove, so the absent token is a hard error."""
        with pytest.raises(KeyError):
            report_header_row(ALL_RECORDS_REPORT_HEADERS, {DISTANCE: "mi"})


class TestTheDerivedGuard:
    """`REJECTED_HEADER_TUPLES`, and what must and must not be in it."""

    def test_the_guard_is_exactly_these_twelve_tuples(self) -> None:
        assert set(REJECTED_HEADER_TUPLES) == EVERY_REJECTED_TUPLE

    @pytest.mark.parametrize("distance", sorted(QUANTITY_TOKENS[DISTANCE]))
    @pytest.mark.parametrize("volume", sorted(QUANTITY_TOKENS[VOLUME]))
    def test_every_all_records_row_the_app_can_emit_is_rejected(
        self, distance: str, volume: str
    ) -> None:
        row = report_header_row(ALL_RECORDS_REPORT_HEADERS, {DISTANCE: distance, VOLUME: volume})
        assert tuple(row) in REJECTED_HEADER_TUPLES

    @pytest.mark.parametrize("distance", sorted(QUANTITY_TOKENS[DISTANCE]))
    def test_every_service_history_row_the_app_can_emit_is_rejected(self, distance: str) -> None:
        row = report_header_row(SERVICE_HISTORY_REPORT_HEADERS, {DISTANCE: distance})
        assert tuple(row) in REJECTED_HEADER_TUPLES

    def test_the_pre_v6_mileage_report_is_still_rejected(self) -> None:
        """Nothing can derive this tuple: the emitter that wrote it is gone.
        Deleting the literal as redundant un-rejects every v2.21-era report.
        """
        assert PRE_V6_SERVICE_HISTORY in REJECTED_HEADER_TUPLES

    def test_the_pre_v6_report_keeps_its_own_ambiguity_message(self) -> None:
        """It is the one shape that is ALSO unit-ambiguous, and its message is
        the only one that can say so."""
        assert REJECTED_HEADER_TUPLES[PRE_V6_SERVICE_HISTORY] == PRE_V6_REFUSAL

    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            (PRE_V6_SERVICE_HISTORY, PRE_V6_REFUSAL),
            (PRE_V6_SERVICE_HISTORY_EIGHT_COLUMN, SERVICE_HISTORY_REFUSAL),
            (SERVICE_HISTORY_METRIC, SERVICE_HISTORY_REFUSAL),
            (SERVICE_HISTORY_IMPERIAL, SERVICE_HISTORY_REFUSAL),
            (PRE_V6_ALL_RECORDS_V2, ALL_RECORDS_REFUSAL),
            (PRE_V6_ALL_RECORDS_V3, ALL_RECORDS_REFUSAL),
            (ALL_RECORDS_METRIC, ALL_RECORDS_REFUSAL),
            (ALL_RECORDS_IMPERIAL, ALL_RECORDS_REFUSAL),
        ],
    )
    def test_each_shape_carries_its_whole_expected_message(
        self, headers: tuple[str, ...], expected: str
    ) -> None:
        """Whole message, never a substring.

        The previous version of this test asserted
        `"service-history report export" in <detail>`, which the PRE-V6
        message also contains ("...unversioned service-history report
        export..."). It therefore survived a mutation mapping the v6
        service-history tuples to the pre-v6 message: the exact substring trap
        this task caught and fixed one file over, repeated here. Equality
        cannot be satisfied by the wrong message.
        """
        assert REJECTED_HEADER_TUPLES[headers] == expected

    @pytest.mark.parametrize("headers", [V2_PRIMARY_SERVICE_BACKUP, V2_INITIAL_SERVICE_BACKUP])
    def test_the_v2_backups_whose_names_overlap_a_report_still_import(
        self, headers: tuple[str, ...]
    ) -> None:
        """The reason the signature is an ORDERED tuple and not a column set.

        `V2_PRIMARY_SERVICE_BACKUP` carries the seven-column report's exact
        names in a different order; `V2_INITIAL_SERVICE_BACKUP` overlaps the
        eight-column report's, again reordered and with `Vendor Location`
        where the report has `Vendor Phone`. Matching on membership would
        refuse every v2-era backup restore along with the reports.
        `test_import_compatibility_corpus.py` asserts both import to a
        specific canonical value.
        """
        assert headers not in REJECTED_HEADER_TUPLES


class TestTheReportColumnsAreTheExportColumns:
    """One base name per quantity across every CSV the app emits (T5-R5)."""

    def test_the_report_odometer_base_matches_the_export_odometer_base(self) -> None:
        assert ReportColumn(ODOMETER_DISTANCE).base == ODOMETER_COLUMN.base

    def test_the_report_volume_base_matches_the_export_volume_base(self) -> None:
        assert ReportColumn(FUEL_VOLUME).base == VOLUME_COLUMN.base

    @pytest.mark.parametrize("canonical", sorted(EMITTED_COLUMNS))
    def test_every_emitted_column_can_emit_exactly_its_quantity_vocabulary(
        self, canonical: str
    ) -> None:
        """`EmittedColumn.decimals` IS the column's vocabulary, and it must
        equal the quantity's.

        A token in `QUANTITY_TOKENS` but missing from `decimals` makes
        `token_for` raise `ValueError` -> HTTP 500 on export for any account
        that selected it; a token in `decimals` but not in `QUANTITY_TOKENS`
        is a header the importer would refuse to parse back.

        Parametrised over ALL of `EMITTED_COLUMNS` rather than the two the
        reports happen to use. The previous version asserted only distance and
        volume, and the seam test next door iterates `column.decimals`, so a
        token missing from `decimals` was invisible to both: price,
        temperature, consumption and speed had no equivalent guard anywhere.
        """
        column = EMITTED_COLUMNS[canonical]
        assert set(column.decimals) == QUANTITY_TOKENS[column.quantity], canonical

    def test_the_report_columns_are_two_of_those_six(self) -> None:
        """The two the reports emit are the same objects the backup exports
        use, not lookalikes: same base, same decimals, same vocabulary."""
        assert EMITTED_COLUMNS["Odometer (km)"] is ODOMETER_COLUMN
        assert EMITTED_COLUMNS["Liters"] is VOLUME_COLUMN
        assert set(ODOMETER_COLUMN.decimals) == QUANTITY_TOKENS[DISTANCE]
        assert set(VOLUME_COLUMN.decimals) == QUANTITY_TOKENS[VOLUME]

    @pytest.mark.parametrize("units", [METRIC_PRESET, IMPERIAL_PRESET])
    def test_a_resolved_unit_set_spells_a_row_the_guard_holds(self, units: UnitSet) -> None:
        """The path `reports.py` actually walks: resolve a unit set, read the
        token off the shared column, spell the header. The result must be a
        row the guard already knows about.
        """
        tokens = {
            DISTANCE: token_for(ODOMETER_COLUMN, units),
            VOLUME: token_for(VOLUME_COLUMN, units),
        }
        assert tuple(report_header_row(ALL_RECORDS_REPORT_HEADERS, tokens)) in (
            REJECTED_HEADER_TUPLES
        )


class TestTheTokenSurvivesTheRoundTrip:
    """A report header is spelled with the same grammar the importer parses.

    The guard means these headers are never actually read from a report file,
    but the spelling is shared with the backup exports through
    `csv_units.spell_header`. If `spell_header` drifted from `_split_token`,
    every tokened header in the app would stop parsing, and this is the
    cheapest place that shows up.
    """

    @pytest.mark.parametrize("token", sorted(QUANTITY_TOKENS[DISTANCE]))
    def test_the_report_odometer_header_parses_back_to_its_token(self, token: str) -> None:
        header = f"Odometer ({token})"
        assert report_header_row(SERVICE_HISTORY_REPORT_HEADERS, {DISTANCE: token})[1] == header
        context = build_csv_unit_context(
            ["Date", header],
            [{"Date": "2026-08-26", "unit_system": "custom", "units_version": "6"}],
            (ODOMETER_DISTANCE,),
        )
        assert context.token(DISTANCE) == token

    @pytest.mark.parametrize("token", sorted(QUANTITY_TOKENS[VOLUME]))
    def test_the_report_volume_header_parses_back_to_its_token(self, token: str) -> None:
        header = f"Volume ({token})"
        row = report_header_row(ALL_RECORDS_REPORT_HEADERS, {DISTANCE: "km", VOLUME: token})
        assert row[7] == header
        context = build_csv_unit_context(
            ["Date", header],
            [{"Date": "2026-08-26", "unit_system": "custom", "units_version": "6"}],
            (FUEL_VOLUME,),
        )
        assert context.token(VOLUME) == token
