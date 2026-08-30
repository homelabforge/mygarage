"""Tests for the shared KPI-card component in app/utils/pdf_components.py.

This file exists because `_fit_kpi_value_font` is rendered through by every
KPI card in every analytics report, and until it was written no test in the
repository observed a font size at all. Every other PDF assertion is on
extracted TEXT, which is completely insensitive to font size: forcing every
card in the app to the minimum size leaves the whole suite green.

So the assertions here are on the returned numbers, not on rendered text.
Both paths are pinned deliberately:

- the UNCHANGED path, which is the safety property ("a card whose value
  already fits does not move"), and
- the SHRUNK path, which is the feature.

The unchanged path is the one worth the most care. It is what makes this a
contained fix to one overflowing card rather than a silent restyle of every
report in the app.
"""

import pytest
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.utils.pdf_components import KPI_VALUE_MIN_FONT_SIZE, _fit_kpi_value_font
from app.utils.pdf_styles import CONTENT_WIDTH, get_styles, register_fonts

# `make_kpi_row` measures against `card_width - 20`, where `card_width` is
# `CONTENT_WIDTH / len(cards)`. Four cards is the common case for both
# analytics reports, and it is the tightest, so it is the case that decides
# whether anything shrinks at all.
_FOUR_CARD_WIDTH = CONTENT_WIDTH / 4 - 20
_TWO_CARD_WIDTH = CONTENT_WIDTH / 2 - 20


@pytest.fixture(scope="module")
def kpi_value_style():
    """The real KPIValue style, with fonts registered.

    Deliberately the production style rather than a stand-in: the whole
    point of these tests is what happens to the cards users actually see,
    and `stringWidth` depends on the real registered font.
    """
    register_fonts()
    return get_styles()["KPIValue"]


class TestKpiCardGeometry:
    """The widths `_fit_kpi_value_font` is measured against are real."""

    def test_four_card_available_width_is_what_make_kpi_row_passes(self) -> None:
        """Anchors the literal widths used throughout this file to the real
        page geometry, so a page-size change cannot leave these tests
        quietly measuring against a width the app never uses."""
        assert _FOUR_CARD_WIDTH == pytest.approx(111.4)
        assert _TWO_CARD_WIDTH == pytest.approx(242.8)


class TestValuesThatAlreadyFitAreUntouched:
    """The safety property: no existing card moves.

    Every value below is one a card renders today at the base 20pt, and
    each must come back with the style's OWN size and leading, so the
    resulting ParagraphStyle is identical to the one built before the
    fitting existed.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "$5,000.00",  # Total Cost, vehicle report
            "$120,000",  # Garage Value, garage report
            "250.0 hr",  # Engine Hours, R6 dimensionless
            "12,000 km",  # Distance Driven, metric
            "7,456 mi",  # Distance Driven, imperial
            "N/A",  # every card's null rendering
        ],
    )
    def test_a_value_that_fits_keeps_the_styles_own_size(self, kpi_value_style, value) -> None:
        assert stringWidth(value, kpi_value_style.fontName, kpi_value_style.fontSize) <= (
            _FOUR_CARD_WIDTH
        ), "fixture error: this value does not actually fit, so it proves nothing"

        size, leading = _fit_kpi_value_font(value, kpi_value_style, _FOUR_CARD_WIDTH)

        assert size == kpi_value_style.fontSize
        assert leading == kpi_value_style.leading

    def test_the_base_size_is_still_twenty_point(self, kpi_value_style) -> None:
        """The literal the test above compares against is worth stating
        outright: if KPIValue's size changes, these tests should be reread,
        not silently keep passing against a new baseline."""
        assert kpi_value_style.fontSize == 20
        assert kpi_value_style.leading == 26

    def test_an_empty_value_keeps_the_base_size(self, kpi_value_style) -> None:
        """The `width <= 0` guard: an empty string must not reach the
        division."""
        size, leading = _fit_kpi_value_font("", kpi_value_style, _FOUR_CARD_WIDTH)

        assert size == kpi_value_style.fontSize
        assert leading == kpi_value_style.leading


class TestValuesThatOverflowAreShrunk:
    """The feature: a value too wide for its card is scaled down to fit.

    `stringWidth` is linear in font size, so the fitted size lands the
    string exactly on the available width rather than approximately.
    """

    @pytest.mark.parametrize(
        "value",
        [
            "$42.00/100 km",  # cost per distance, metric
            "$675.92/1,000 mi",  # cost per distance, imperial
            "12,000 km (7,456 mi)",  # distance under show-both
            "$1,234,568",  # a large garage value, which used to split
            # Fuel Economy, metric. 144pt against a 111.4pt card: this card
            # ALREADY overflowed before Task 5, at "9.4 L/100km", and used
            # to wrap to two lines. It is a shrunk value, not an untouched
            # one; the fixture guard on the untouched list caught it there.
            "9.40 L/100km",
        ],
    )
    def test_an_overflowing_value_is_scaled_to_exactly_fit(self, kpi_value_style, value) -> None:
        base_width = stringWidth(value, kpi_value_style.fontName, kpi_value_style.fontSize)
        assert base_width > _FOUR_CARD_WIDTH, (
            "fixture error: this value already fits, so it proves nothing"
        )

        size, _leading = _fit_kpi_value_font(value, kpi_value_style, _FOUR_CARD_WIDTH)

        assert size < kpi_value_style.fontSize
        assert size > KPI_VALUE_MIN_FONT_SIZE
        assert stringWidth(value, kpi_value_style.fontName, size) == pytest.approx(_FOUR_CARD_WIDTH)

    def test_leading_shrinks_in_proportion_to_the_font(self, kpi_value_style) -> None:
        size, leading = _fit_kpi_value_font("$42.00/100 km", kpi_value_style, _FOUR_CARD_WIDTH)

        assert leading / size == pytest.approx(kpi_value_style.leading / kpi_value_style.fontSize)

    def test_a_wider_card_shrinks_the_same_value_less(self, kpi_value_style) -> None:
        """Scaling follows the card, not a fixed table: the two-card hours
        summary has nearly twice the room of the four-card row."""
        value = "$675.92/1,000 mi ($42.00/100 km)"

        four_card, _ = _fit_kpi_value_font(value, kpi_value_style, _FOUR_CARD_WIDTH)
        two_card, _ = _fit_kpi_value_font(value, kpi_value_style, _TWO_CARD_WIDTH)

        assert two_card > four_card


class TestTheFloor:
    """Shrinking stops at a readable size rather than continuing forever."""

    def test_the_floor_is_nine_points(self) -> None:
        """Pinned outright. Nothing else in the repository observes a font
        size, so without this the floor could be lowered to 4pt, or deleted
        so values shrink without limit, and every other test would pass."""
        assert KPI_VALUE_MIN_FONT_SIZE == 9.0

    def test_a_value_too_long_for_the_floor_clamps_rather_than_shrinking_further(
        self, kpi_value_style
    ) -> None:
        """The show-both cost-per-distance value in a four-card row. Exact
        fitting would demand about 5.8pt, which is unreadable, so it clamps
        at the floor and is allowed to overflow and wrap instead."""
        value = "$675.92/1,000 mi ($42.00/100 km)"
        unclamped = (
            kpi_value_style.fontSize
            * _FOUR_CARD_WIDTH
            / stringWidth(value, kpi_value_style.fontName, kpi_value_style.fontSize)
        )
        assert unclamped < KPI_VALUE_MIN_FONT_SIZE, (
            "fixture error: this value does not reach the floor, so it proves nothing"
        )

        size, leading = _fit_kpi_value_font(value, kpi_value_style, _FOUR_CARD_WIDTH)

        assert size == KPI_VALUE_MIN_FONT_SIZE
        assert leading == pytest.approx(
            kpi_value_style.leading * KPI_VALUE_MIN_FONT_SIZE / kpi_value_style.fontSize
        )

    def test_a_clamped_value_is_allowed_to_overflow(self, kpi_value_style) -> None:
        """The honest half of the contract: once the floor binds, the value
        does NOT fit on one line. It wraps, at a space where the value has
        one. The docstring must not promise otherwise."""
        value = "$675.92/1,000 mi ($42.00/100 km)"

        size, _leading = _fit_kpi_value_font(value, kpi_value_style, _FOUR_CARD_WIDTH)

        assert stringWidth(value, kpi_value_style.fontName, size) > _FOUR_CARD_WIDTH
