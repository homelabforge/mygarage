"""Tests for service history PDF report generation."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import fitz  # PyMuPDF

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET
from app.utils.pdf_generator import PDFReportGenerator
from app.utils.render_context import RenderContext

# See tests/unit/utils/test_pdf_vehicle_report.py's METRIC_CTX: the metric,
# no-counterpart context, under which every assertion written before these
# reports became unit-aware must still hold.
METRIC_CTX = RenderContext(units=METRIC_PRESET, show_both=False)


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using PyMuPDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()  # type: ignore[operator]
    doc.close()
    return text


class TestGenerateServiceHistoryPdf:
    """Tests for PDFReportGenerator.generate_service_history_pdf."""

    def test_service_history_pdf_renders_real_line_item_text(self) -> None:
        """The Description column used to print 'N/A' on every row — `description`
        was never a key the caller passes. PR #145 put service_type (which holds
        item.description) there instead.
        """
        generator = PDFReportGenerator(
            render_context=METRIC_CTX, currency_code="USD", locale="en_US"
        )
        buf = generator.generate_service_history_pdf(
            {
                "vin": "1HGBH41JXMN109186",
                "year": 2018,
                "make": "Honda",
                "model": "Accord",
                "license_plate": "TEST-123",
            },
            [
                {
                    "date": date(2024, 3, 1),
                    "odometer_km": Decimal("19312"),
                    "service_category": "Maintenance",
                    "service_type": "5W-30 synthetic, filter replaced",
                    "cost": Decimal("45.99"),
                    "vendor_name": "Jiffy Lube",
                }
            ],
            None,
            None,
        )
        text = _extract_text(buf.read())
        assert "5W-30 synthetic" in text
        assert "Maintenance" in text
        assert "N/A" not in text

    def test_service_history_pdf_does_not_branch_on_language(self) -> None:
        """The de-only branch helped one locale and left fr/pl/ru/uk on US format."""
        source = Path("app/utils/pdf_generator.py").read_text()
        assert 'if "de" in self.locale' not in source


IMPERIAL_CTX = RenderContext(units=IMPERIAL_PRESET, show_both=False)

_VEHICLE_INFO = {
    "vin": "1HGBH41JXMN109186",
    "year": 2018,
    "make": "Honda",
    "model": "Accord",
    "license_plate": "TEST-123",
}


def _normalized_text(pdf_bytes: bytes) -> str:
    """Extracted text with every whitespace run collapsed to one space.

    The odometer header is a Paragraph in a 0.9-inch column, so
    "Odometer (km)" wraps and extracts with a newline in the middle.
    Collapsing whitespace asserts on the rendered CONTENT, not the layout.
    """
    return " ".join(_extract_text(pdf_bytes).split())


def _service_record(odometer_km: Decimal | None) -> dict:
    """One service-history row carrying `odometer_km` and nothing surprising."""
    return {
        "date": date(2024, 3, 1),
        "odometer_km": odometer_km,
        "service_category": "Maintenance",
        "service_type": "Oil change",
        "cost": Decimal("45.99"),
        "vendor_name": "Jiffy Lube",
    }


class TestOdometerColumnFollowsTheRenderContext:
    """Both odometer columns name their unit once in the header and print a
    bare number in each cell.

    Expected values computed from the distance adapters, not transcribed.
    The factor is `UnitConverter.MILES_TO_KM`, which is the rounded
    `1.60934`, not the ISO-exact `1.609344`; recomputing from the exact
    value gives an intermediate this code never produces.

        19,312 / 1.60934 = 11,999.9503 -> "12,000" at precision 0
        123.90 / 1.60934 = 76.9881     -> "77"     at precision 0
    """

    def test_service_history_header_and_cell_are_metric_under_a_metric_context(self) -> None:
        generator = PDFReportGenerator(render_context=METRIC_CTX)
        buf = generator.generate_service_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Odometer (km)" in text
        assert "19,312" in text

    def test_service_history_header_and_cell_are_imperial_under_an_imperial_context(
        self,
    ) -> None:
        generator = PDFReportGenerator(render_context=IMPERIAL_CTX)
        buf = generator.generate_service_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Odometer (mi)" in text
        assert "12,000" in text
        assert "Odometer (km)" not in text
        assert "19,312" not in text

    def test_sale_history_header_and_cell_are_metric_under_a_metric_context(self) -> None:
        """The sale PDF is a separate generator method with its own header
        row, so it needs its own assertion, not the service PDF's."""
        generator = PDFReportGenerator(render_context=METRIC_CTX)
        buf = generator.generate_sale_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Vehicle History Summary" in text
        assert "Odometer (km)" in text
        assert "19,312" in text

    def test_sale_history_header_and_cell_are_imperial_under_an_imperial_context(self) -> None:
        generator = PDFReportGenerator(render_context=IMPERIAL_CTX)
        buf = generator.generate_sale_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Odometer (mi)" in text
        assert "12,000" in text
        assert "Odometer (km)" not in text
        assert "19,312" not in text

    def test_both_reports_now_round_a_fractional_odometer_identically(self) -> None:
        """AUTHORISED BEHAVIOUR CHANGE, recorded in the changelog.

        These two reports disagreed: the service history truncated with
        `int()` and rendered 123.90 as "123", while the sale history
        formatted the raw Decimal and rendered "123.90". One adapter
        precision cannot reproduce both, so both now round through the
        distance adapter (precision 0) and render "124".
        """
        record = [_service_record(Decimal("123.90"))]

        service = _normalized_text(
            PDFReportGenerator(render_context=METRIC_CTX)
            .generate_service_history_pdf(_VEHICLE_INFO, record)
            .read()
        )
        sale = _normalized_text(
            PDFReportGenerator(render_context=METRIC_CTX)
            .generate_sale_history_pdf(_VEHICLE_INFO, record)
            .read()
        )

        assert "124" in service
        assert "124" in sale
        # The two old renderings are gone from both reports.
        assert "123.90" not in service
        assert "123.90" not in sale

    def test_a_null_odometer_renders_na(self) -> None:
        """Unchanged by the unit rewrite: a null reading is a missing one.

        One record, so the "N/A" asserted below can only have come from the
        odometer cell. The zero case is a SEPARATE branch of
        `_format_odometer`'s falsy guard and gets its own test below;
        asserting one "N/A" over a two-record render would let either input
        alone satisfy the whole claim.
        """
        generator = PDFReportGenerator(render_context=IMPERIAL_CTX)
        buf = generator.generate_service_history_pdf(_VEHICLE_INFO, [_service_record(None)])
        text = _normalized_text(buf.read())

        assert "Odometer (mi)" in text
        assert "N/A" in text

    def test_a_zero_odometer_renders_na_and_not_a_real_reading(self) -> None:
        """The branch `_format_odometer`'s docstring goes out of its way to
        claim: a zero odometer is a missing reading, not a real one at the
        origin, and that predates this becoming unit-aware.

        Independently killable from the null case: flipping the guard from
        `if not odometer_km` to `if odometer_km is None` renders "0" here
        and leaves the null test above green.
        """
        generator = PDFReportGenerator(render_context=IMPERIAL_CTX)
        buf = generator.generate_service_history_pdf(_VEHICLE_INFO, [_service_record(Decimal("0"))])
        text = _normalized_text(buf.read())

        assert "Odometer (mi)" in text
        assert "N/A" in text

    def test_both_missing_odometer_forms_render_na_in_one_table(self) -> None:
        """Both rows of a mixed table, counted rather than sampled: a single
        existential "N/A" over two records is satisfied by either one."""
        generator = PDFReportGenerator(render_context=IMPERIAL_CTX)
        buf = generator.generate_service_history_pdf(
            _VEHICLE_INFO, [_service_record(None), _service_record(Decimal("0"))]
        )
        text = _normalized_text(buf.read())

        assert text.count("N/A") == 2


SHOW_BOTH_METRIC_CTX = RenderContext(units=METRIC_PRESET, show_both=True)
SHOW_BOTH_IMPERIAL_CTX = RenderContext(units=IMPERIAL_PRESET, show_both=True)


class TestOdometerCellsStaySingleRepresentationUnderShowBoth:
    """The recorded exception to the show-both grammar (phase exit criterion 8).

    Every other distance figure in this phase gains a ` (counterpart)` when the
    reader has `show_both_units` on. These two table columns deliberately do
    not, because a table cell is a fixed-width surface: the service-history
    odometer column is 0.9 inch (64.80 pt) and `"123,457 km (76,713 mi)"` is
    95.04 pt in the 9 pt Helvetica these cells use, so the counterpart cannot
    be rendered, only spilled into the neighbouring column. The cell is a bare
    `str`, not a `Paragraph`, so ReportLab does not even wrap it.

    Pinned rather than left incidental: without these assertions, "route the
    odometer values through `format_quantity` like everything else" looks like
    a tidy-up rather than the layout regression it is. 19,312 km is 12,000 mi
    (19,312 / 1.60934 = 11,999.9503 -> "12,000" at precision 0), so each
    reader's counterpart figure is a distinct string that either appears or
    does not.
    """

    def test_service_history_metric_cell_omits_the_mile_counterpart(self) -> None:
        generator = PDFReportGenerator(render_context=SHOW_BOTH_METRIC_CTX)
        buf = generator.generate_service_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Odometer (km)" in text
        assert "19,312" in text
        assert "12,000" not in text

    def test_service_history_imperial_cell_omits_the_kilometre_counterpart(self) -> None:
        """The other direction, so an "always show the metric side" bug cannot
        hide behind the metric reader's test above."""
        generator = PDFReportGenerator(render_context=SHOW_BOTH_IMPERIAL_CTX)
        buf = generator.generate_service_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Odometer (mi)" in text
        assert "12,000" in text
        assert "19,312" not in text

    def test_sale_history_cell_omits_the_counterpart_too(self) -> None:
        """The sale report is a separate generator method with its own table,
        and a wider (1.4 inch) odometer column -- wide enough for today's
        six-figure show-both string and not for a seven-figure one. It follows
        the same rule as the narrow one rather than diverging by column width."""
        generator = PDFReportGenerator(render_context=SHOW_BOTH_METRIC_CTX)
        buf = generator.generate_sale_history_pdf(
            _VEHICLE_INFO, [_service_record(Decimal("19312"))]
        )
        text = _normalized_text(buf.read())

        assert "Odometer (km)" in text
        assert "19,312" in text
        assert "12,000" not in text

    def test_the_cell_is_byte_identical_whatever_show_both_says(self) -> None:
        """Directly on the formatter, so the claim is "`show_both` is not read
        here", not "the counterpart happened not to be extracted from the PDF".
        Both presets, because a rule that held for one would say nothing about
        the other."""
        for units in (METRIC_PRESET, IMPERIAL_PRESET):
            off = PDFReportGenerator(
                render_context=RenderContext(units=units, show_both=False)
            )._format_odometer(Decimal("19312"))
            on = PDFReportGenerator(
                render_context=RenderContext(units=units, show_both=True)
            )._format_odometer(Decimal("19312"))
            assert off == on
            assert "(" not in on
        assert (
            PDFReportGenerator(render_context=SHOW_BOTH_METRIC_CTX)._format_odometer(
                Decimal("19312")
            )
            == "19,312"
        )
        assert (
            PDFReportGenerator(render_context=SHOW_BOTH_IMPERIAL_CTX)._format_odometer(
                Decimal("19312")
            )
            == "12,000"
        )
