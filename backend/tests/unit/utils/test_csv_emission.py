"""What a v6 CSV export puts in a header cell and in a value cell.

Issue #152 phase 2b task 3. `app.utils.csv_emission` is the emitting half of
the pair whose reading half is `app.utils.csv_units` (task 2). The two must
agree exactly, so the last class here drives a header this module emits back
through the importer's own context builder and asserts it binds to the same
quantity and the same token.

Every expected header and every expected cell below is a HAND-WRITTEN
literal. Deriving them through `format_label`, `ADAPTERS[token].label` or the
emission table itself would put both sides of the assertion on one
definition, which is this project's most common test defect.
"""

from __future__ import annotations

from decimal import Decimal
from typing import get_args

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.utils.csv_emission import (
    EMITTED_COLUMNS,
    apply_unit_set,
    cell_for,
    header_for,
    marker_for,
    token_for,
)
from app.utils.csv_safe import sanitize_csv_cell
from app.utils.csv_units import (
    DEF_PRICE,
    FUEL_CONSUMPTION,
    FUEL_PRICE,
    FUEL_SPEED,
    FUEL_TEMPERATURE,
    FUEL_VOLUME,
    ODOMETER_DISTANCE,
    READING_DISTANCE,
    QuantitySpec,
    build_csv_unit_context,
)
from app.utils.unit_adapters import ADAPTERS

# The UK imperial set: imperial with UK gallons. Written out rather than
# imported from `default_unit_prefs`, so this file pins the shape it means.
UK_IMPERIAL = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump()
    | {"volume": "gal_uk", "consumption": "mpg_uk", "secondary_gallon": "uk"}
)


class TestVocabularyIsBijectiveWithAdapters:
    """Header tokens are the phase-1 vocabulary, and it is a bijection.

    `len(ADAPTERS) == len(set(ADAPTERS))` is vacuous: dict keys are unique by
    construction. The real property is that flattening every physical-unit
    `Literal` on `UnitSet` yields a set with no cross-field duplicates, and
    that this set is exactly `ADAPTERS`' key set. That is what makes a header
    token identify its unit on its own.
    """

    def test_no_token_appears_in_two_quantities(self) -> None:
        """A token shared by two quantities could not identify its unit."""
        flattened: list[str] = []
        for field, info in UnitSet.model_fields.items():
            if field == "secondary_gallon":
                # `us` / `uk` are a gallon-flavour preference, not a unit, and
                # never appear in a header. They are also not adapter keys.
                continue
            flattened.extend(get_args(info.annotation))
        duplicates = sorted({t for t in flattened if flattened.count(t) > 1})
        assert duplicates == []

    def test_the_physical_vocabulary_is_exactly_the_adapter_key_set(self) -> None:
        """Every token has an adapter, and every adapter has a token."""
        flattened: set[str] = set()
        for field, info in UnitSet.model_fields.items():
            if field == "secondary_gallon":
                continue
            flattened.update(get_args(info.annotation))
        assert flattened == set(ADAPTERS)

    def test_secondary_gallon_values_are_not_adapter_keys(self) -> None:
        """Pins the exclusion above rather than leaving it as a comment."""
        assert set(get_args(UnitSet.model_fields["secondary_gallon"].annotation)) == {"us", "uk"}
        assert "us" not in ADAPTERS
        assert "uk" not in ADAPTERS


class TestEmittedHeaders:
    """`Base (token)`, case-significant, one hand-written literal per token."""

    def test_distance_headers(self) -> None:
        column = EMITTED_COLUMNS["Odometer (km)"]
        assert header_for(column, "km") == "Odometer (km)"
        assert header_for(column, "mi") == "Odometer (mi)"

    def test_reading_headers(self) -> None:
        column = EMITTED_COLUMNS["Reading (km)"]
        assert header_for(column, "km") == "Reading (km)"
        assert header_for(column, "mi") == "Reading (mi)"

    def test_volume_headers_distinguish_the_two_gallons(self) -> None:
        """The whole reason a header carries a token and not a label: both
        gallons render as the label `gal` (`unit_adapters.py`), so a labelled
        header could not say which one it holds."""
        column = EMITTED_COLUMNS["Liters"]
        assert header_for(column, "L") == "Volume (L)"
        assert header_for(column, "gal_us") == "Volume (gal_us)"
        assert header_for(column, "gal_uk") == "Volume (gal_uk)"
        assert ADAPTERS["gal_us"].label == ADAPTERS["gal_uk"].label

    def test_fuel_price_headers(self) -> None:
        column = EMITTED_COLUMNS["Price Per Liter"]
        assert header_for(column, "L") == "Price Per Unit (L)"
        assert header_for(column, "gal_us") == "Price Per Unit (gal_us)"
        assert header_for(column, "gal_uk") == "Price Per Unit (gal_uk)"

    def test_def_price_headers_use_the_same_spelling_as_fuel(self) -> None:
        column = EMITTED_COLUMNS["Price Per Unit"]
        assert header_for(column, "L") == "Price Per Unit (L)"
        assert header_for(column, "gal_us") == "Price Per Unit (gal_us)"

    def test_temperature_headers_use_the_lowercase_token(self) -> None:
        """`(c)` and `(f)`, not the `(C)` / `(F)` display labels v5 emitted."""
        column = EMITTED_COLUMNS["Outside Temp (C)"]
        assert header_for(column, "c") == "Outside Temp (c)"
        assert header_for(column, "f") == "Outside Temp (f)"

    def test_consumption_headers_share_one_base_name(self) -> None:
        """v5 changed the BASE name on imperial export (`OBC L/100km` ->
        `OBC MPG`). v6 has one base and a token, so all four fit."""
        column = EMITTED_COLUMNS["OBC L/100km"]
        assert header_for(column, "l_100km") == "OBC Economy (l_100km)"
        assert header_for(column, "km_l") == "OBC Economy (km_l)"
        assert header_for(column, "mpg_us") == "OBC Economy (mpg_us)"
        assert header_for(column, "mpg_uk") == "OBC Economy (mpg_uk)"

    def test_speed_headers_use_the_token_not_the_display_label(self) -> None:
        """`kmh`, not `km/h`."""
        column = EMITTED_COLUMNS["OBC Avg Speed (km/h)"]
        assert header_for(column, "kmh") == "OBC Avg Speed (kmh)"
        assert header_for(column, "mph") == "OBC Avg Speed (mph)"

    def test_token_comes_from_the_units_field_the_column_declares(self) -> None:
        assert token_for(EMITTED_COLUMNS["Odometer (km)"], IMPERIAL_PRESET) == "mi"
        assert token_for(EMITTED_COLUMNS["Liters"], UK_IMPERIAL) == "gal_uk"
        # Price is denominated in a volume, so it follows `volume`.
        assert token_for(EMITTED_COLUMNS["Price Per Liter"], UK_IMPERIAL) == "gal_uk"
        assert token_for(EMITTED_COLUMNS["Outside Temp (C)"], METRIC_PRESET) == "c"


class TestEmittedPrecision:
    """The per-column decimal places, as hand-written expected cells.

    Sentinels: 500.00 km, 40.000 L, 1.500 per litre, 20.0 C, 8.00 L/100km,
    100.0 km/h. The metric cells reproduce the stored `Numeric` scale exactly;
    the non-metric cells carry at least as much information as the metric one.
    """

    def test_distance(self) -> None:
        column = EMITTED_COLUMNS["Odometer (km)"]
        assert cell_for(column, "km", Decimal("500.00")) == "500.00"
        # 500 / 1.60934 = 310.68562...; 3 dp because 0.01 mi is 16.1 m, which
        # cannot round-trip the 10 m half-step of NUMERIC(10, 2) kilometres.
        assert cell_for(column, "mi", Decimal("500.00")) == "310.686"

    def test_reading_matches_odometer(self) -> None:
        column = EMITTED_COLUMNS["Reading (km)"]
        assert cell_for(column, "km", Decimal("500.00")) == "500.00"
        assert cell_for(column, "mi", Decimal("500.00")) == "310.686"

    def test_volume(self) -> None:
        column = EMITTED_COLUMNS["Liters"]
        assert cell_for(column, "L", Decimal("40.000")) == "40.000"
        # 40 / 3.78541 = 10.566876...; 4 dp because 0.001 gal is 3.79 mL and
        # the litre cell carries 1 mL.
        assert cell_for(column, "gal_us", Decimal("40.000")) == "10.5669"
        # 40 / 4.54609 = 8.798787...
        assert cell_for(column, "gal_uk", Decimal("40.000")) == "8.7988"

    def test_price_is_denominator_aware(self) -> None:
        """A price per gallon is a price per litre MULTIPLIED by the litres in
        a gallon: the bigger the unit you buy, the more it costs. Scaling it
        the way a volume scales (dividing) is the classic sign error, and it
        is off by 14x for US gallons."""
        column = EMITTED_COLUMNS["Price Per Liter"]
        assert cell_for(column, "L", Decimal("1.500")) == "1.500"
        # 1.5 * 3.78541 = 5.678115
        assert cell_for(column, "gal_us", Decimal("1.500")) == "5.678"
        # 1.5 * 4.54609 = 6.819135
        assert cell_for(column, "gal_uk", Decimal("1.500")) == "6.819"

    def test_def_price_matches_fuel_price(self) -> None:
        column = EMITTED_COLUMNS["Price Per Unit"]
        assert cell_for(column, "L", Decimal("1.500")) == "1.500"
        assert cell_for(column, "gal_us", Decimal("1.500")) == "5.678"

    def test_temperature(self) -> None:
        column = EMITTED_COLUMNS["Outside Temp (C)"]
        assert cell_for(column, "c", Decimal("20.0")) == "20.0"
        # 20 C = 68 F. One decimal in Fahrenheit is FINER than one in Celsius,
        # so the metric precision survives without gaining a place.
        assert cell_for(column, "f", Decimal("20.0")) == "68.0"

    def test_consumption(self) -> None:
        column = EMITTED_COLUMNS["OBC L/100km"]
        assert cell_for(column, "l_100km", Decimal("8.00")) == "8.00"
        # 100 / 8 = 12.5
        assert cell_for(column, "km_l", Decimal("8.00")) == "12.500"
        # 235.214 / 8 = 29.40175
        assert cell_for(column, "mpg_us", Decimal("8.00")) == "29.402"
        # 282.481 / 8 = 35.310125
        assert cell_for(column, "mpg_uk", Decimal("8.00")) == "35.310"

    def test_speed(self) -> None:
        column = EMITTED_COLUMNS["OBC Avg Speed (km/h)"]
        assert cell_for(column, "kmh", Decimal("100.0")) == "100.0"
        # 100 / 1.60934 = 62.13723...
        assert cell_for(column, "mph", Decimal("100.0")) == "62.14"

    def test_none_is_an_empty_cell_in_every_unit(self) -> None:
        for canonical, column in EMITTED_COLUMNS.items():
            token = token_for(column, METRIC_PRESET)
            assert cell_for(column, token, None) == "", canonical

    def test_a_reciprocal_adapter_renders_zero_as_an_empty_cell(self) -> None:
        """0 L/100km has no MPG. The linear form still prints 0."""
        column = EMITTED_COLUMNS["OBC L/100km"]
        assert cell_for(column, "l_100km", Decimal("0")) == "0.00"
        assert cell_for(column, "mpg_us", Decimal("0")) == ""


class TestRoundingIsHalfUp:
    """One rounding mode, stated once and applied everywhere.

    Python's default for `Decimal` is ROUND_HALF_EVEN, so a cell sitting
    exactly on a half-step is the discriminator: 1.005 km at two decimals is
    "1.01" half-up and "1.00" half-even.
    """

    def test_a_distance_on_the_half_step_rounds_away_from_zero(self) -> None:
        column = EMITTED_COLUMNS["Odometer (km)"]
        assert cell_for(column, "km", Decimal("1.005")) == "1.01"

    def test_a_volume_on_the_half_step_rounds_away_from_zero(self) -> None:
        column = EMITTED_COLUMNS["Liters"]
        assert cell_for(column, "L", Decimal("1.0005")) == "1.001"

    def test_a_temperature_on_the_half_step_rounds_away_from_zero(self) -> None:
        column = EMITTED_COLUMNS["Outside Temp (C)"]
        assert cell_for(column, "c", Decimal("0.25")) == "0.3"


class TestCellsAreNumericOnly:
    """No `adapter.format()` output ever reaches a cell.

    `format()` adds a thousands separator and a unit label, both of which turn
    a numeric CSV cell into text a spreadsheet will not sum.
    """

    def test_a_large_value_carries_no_thousands_separator(self) -> None:
        column = EMITTED_COLUMNS["Odometer (km)"]
        assert cell_for(column, "km", Decimal("1234567.89")) == "1234567.89"
        # What the primitive formatter would have produced instead.
        assert ADAPTERS["km"].format(Decimal("1234567.89")) == "1,234,568 km"

    def test_a_negative_value_stays_a_plain_number(self) -> None:
        """`-` is one of the CSV formula-injection lead characters.

        `sanitize_csv_cell` exempts strings that parse as a number, so a
        sub-zero temperature must reach the file as `-10.0` and not as
        `'-10.0`. Asserted through the sanitiser the export actually applies,
        because a cell this module made non-numeric would be quoted there and
        stop being a number in the spreadsheet.
        """
        column = EMITTED_COLUMNS["Outside Temp (C)"]
        assert cell_for(column, "c", Decimal("-10.0")) == "-10.0"
        # -10 C = 14 F
        assert cell_for(column, "f", Decimal("-10.0")) == "14.0"
        assert sanitize_csv_cell(cell_for(column, "c", Decimal("-10.0"))) == "-10.0"

    def test_no_cell_contains_a_letter_or_a_comma(self) -> None:
        for canonical, column in EMITTED_COLUMNS.items():
            for token in column.decimals:
                cell = cell_for(column, token, Decimal("1234.5"))
                assert "," not in cell, (canonical, token, cell)
                assert not any(ch.isalpha() for ch in cell), (canonical, token, cell)


class TestMarker:
    """`metric | imperial | custom`, decided by the RESOLVED set only.

    `marker = user.unit_preference` passes the four obvious cases and fails
    both of the discriminating ones below.
    """

    def test_the_metric_preset_is_metric(self) -> None:
        assert marker_for(METRIC_PRESET) == "metric"

    def test_the_imperial_preset_is_imperial(self) -> None:
        assert marker_for(IMPERIAL_PRESET) == "imperial"

    def test_a_set_resolving_to_metric_is_metric_however_it_was_stored(self) -> None:
        """A `custom` account whose eleven columns spell out the metric preset
        is metric. Reading `unit_preference` would say `custom` here."""
        rebuilt = UnitSet.model_validate(METRIC_PRESET.model_dump())
        assert marker_for(rebuilt) == "metric"

    def test_one_override_off_a_preset_is_custom(self) -> None:
        """Reading `unit_preference` would say `metric` here."""
        one_off = UnitSet.model_validate(METRIC_PRESET.model_dump() | {"volume": "gal_uk"})
        assert marker_for(one_off) == "custom"

    def test_uk_imperial_is_custom_because_imperial_uk_is_no_longer_emitted(self) -> None:
        """v6 stops emitting the `imperial_uk` marker: the gallon flavour now
        travels in the header token. It is still ACCEPTED on import forever."""
        assert marker_for(UK_IMPERIAL) == "custom"

    def test_the_marker_is_never_imperial_uk(self) -> None:
        assert marker_for(UK_IMPERIAL) != "imperial_uk"


class TestApplyUnitSet:
    """The whole-table rewrite: headers renamed, unit cells converted, every
    other cell passed through untouched."""

    def test_dimensionless_columns_pass_through(self) -> None:
        headers = ["Date", "Odometer (km)", "Notes"]
        rows: list[list[object]] = [["2026-05-18", Decimal("500.00"), "hello, world"]]
        out_headers, out_rows = apply_unit_set(headers, rows, IMPERIAL_PRESET)
        assert out_headers == ["Date", "Odometer (mi)", "Notes"]
        assert out_rows == [["2026-05-18", "310.686", "hello, world"]]

    def test_a_table_with_no_unit_columns_is_unchanged(self) -> None:
        headers = ["Date", "Engine Hours", "Notes", "Source"]
        rows: list[list[object]] = [["2026-04-03", "200.1", "Manual reading", "manual"]]
        out_headers, out_rows = apply_unit_set(headers, rows, IMPERIAL_PRESET)
        assert out_headers == headers
        assert out_rows == rows


class TestEmissionMeetsTheImporter:
    """The join between the two halves of phase 2b, asserted behaviourally.

    Task 2 shipped the reader before this task shipped the writer, so nothing
    structural forces them to agree. Every header this module can emit is
    driven back through the importer's own context builder here, and must bind
    to the same quantity and the same token.
    """

    # Hand-written: which importer spec consumes each emitted column.
    SPECS: dict[str, tuple[QuantitySpec, str]] = {
        "Odometer (km)": (ODOMETER_DISTANCE, "distance"),
        "Reading (km)": (READING_DISTANCE, "distance"),
        "Liters": (FUEL_VOLUME, "volume"),
        "Price Per Liter": (FUEL_PRICE, "price_per_volume"),
        "Price Per Unit": (DEF_PRICE, "price_per_volume"),
        "Outside Temp (C)": (FUEL_TEMPERATURE, "temperature"),
        "OBC L/100km": (FUEL_CONSUMPTION, "consumption"),
        "OBC Avg Speed (km/h)": (FUEL_SPEED, "speed"),
    }

    def test_every_emitted_column_is_declared_here(self) -> None:
        assert set(self.SPECS) == set(EMITTED_COLUMNS)

    @pytest.mark.parametrize("canonical", sorted(SPECS))
    def test_every_emitted_header_parses_back_to_its_own_token(self, canonical: str) -> None:
        column = EMITTED_COLUMNS[canonical]
        spec, quantity = self.SPECS[canonical]
        for token in column.decimals:
            header = header_for(column, token)
            context = build_csv_unit_context(
                ["Date", header],
                [{"Date": "2026-05-18", "unit_system": "custom", "units_version": "6"}],
                (spec,),
            )
            assert context.column(quantity) == header, (canonical, token)
            assert context.token(quantity) == token, (canonical, token)

    def test_a_v6_price_cell_round_trips_through_the_importers_own_converter(self) -> None:
        """Emission multiplies by the litres in a gallon; the importer divides
        by the same factor. A sign error on either side shows up here."""
        column = EMITTED_COLUMNS["Price Per Liter"]
        emitted = cell_for(column, "gal_uk", Decimal("1.500"))
        assert emitted == "6.819"
        context = build_csv_unit_context(
            ["Date", "Price Per Unit (gal_uk)"],
            [{"Date": "2026-05-18", "unit_system": "custom", "units_version": "6"}],
            (FUEL_PRICE,),
        )
        back = context.to_canonical("price_per_volume", Decimal(emitted))
        assert back is not None
        assert back.quantize(Decimal("0.001")) == Decimal("1.500")
