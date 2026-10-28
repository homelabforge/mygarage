"""Unit tests for the CSV formula-injection sanitizer (utils/csv_safe.py)."""

import pytest

from app.utils.csv_safe import sanitize_csv_cell, sanitize_csv_row, unquote_csv_cell


class TestSanitizeCsvCell:
    @pytest.mark.parametrize(
        "payload",
        [
            "=cmd|'/c calc'!A1",
            "=1+1",
            "+1+1+cmd",
            "-2+3+cmd",
            "@SUM(A1:A9)",
            "\tinjected",
            "\rinjected",
        ],
    )
    def test_dangerous_strings_are_prefixed(self, payload):
        out = sanitize_csv_cell(payload)
        assert out == "'" + payload

    @pytest.mark.parametrize(
        "value",
        ["-12.5", "-1000", "+3.14", "-0", "42", "3.0"],
    )
    def test_numeric_strings_untouched(self, value):
        # A leading -/+ that forms a genuine number must NOT be quoted (R5).
        assert sanitize_csv_cell(value) == value

    @pytest.mark.parametrize(
        "value",
        ["Honda Accord", "", "P0420", "2018", "regular text", "a=b"],
    )
    def test_safe_strings_untouched(self, value):
        assert sanitize_csv_cell(value) == value

    @pytest.mark.parametrize("value", [123, -12.5, 0, None, True, 3.14])
    def test_non_strings_untouched(self, value):
        # Numeric/None/bool are written verbatim by csv.writer and can't carry a
        # formula; they must pass through unchanged (and keep their type).
        assert sanitize_csv_cell(value) is value or sanitize_csv_cell(value) == value
        assert not isinstance(sanitize_csv_cell(value), str)

    def test_sanitize_row_applies_per_cell(self):
        row = ["=evil()", "-12.5", "safe", 99]
        assert sanitize_csv_row(row) == ["'=evil()", "-12.5", "safe", 99]


class TestRoundTrip:
    """What the export quotes, the import unquotes back to exactly what was typed (C-3)."""

    @pytest.mark.parametrize(
        "typed",
        ["=x", "'=x", "''=x", "'hello", "-12.5", "'-12.5", "'", "''", "plain", "@SUM(A1)"],
    )
    def test_a_cell_comes_back_as_typed(self, typed):
        # a354f33a: "'=x" exported unquoted and came back "=x"
        assert unquote_csv_cell(sanitize_csv_cell(typed)) == typed

    @pytest.mark.parametrize(
        ("typed", "written"), [("'=x", "''=x"), ("''+1+cmd", "'''+1+cmd"), ("'hello", "'hello")]
    )
    def test_a_quote_before_a_formula_is_quoted_again(self, typed, written):
        # Still text to a spreadsheet, and now the import can tell it from a quoted formula.
        assert sanitize_csv_cell(typed) == written

    def test_an_old_file_reads_a_single_quote_as_the_escape(self):
        # Written before the change, "'=x" can't say which it was; it reads as the formula's text.
        assert unquote_csv_cell("'=x") == "=x"
