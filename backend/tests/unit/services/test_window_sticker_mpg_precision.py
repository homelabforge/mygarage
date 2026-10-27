"""A sticker's MPG comes back as printed once it's converted to L/100km.

The parser reads US MPG and the column is L/100km, so the converted figure has
to keep enough places for the trip back. At 2 places a hybrid's 58 MPG stored
4.06 and showed 57.9, and an EV's 133 MPGe showed 132.9.
"""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.services.window_sticker_ocr import WindowStickerOCRService
from app.services.window_sticker_parsers import WindowStickerData

US_MPG = 100 * Decimal("3.785411784") / Decimal("1.609344")


@pytest.mark.parametrize("printed", [58, 133])
def test_a_parsed_sticker_mpg_reads_back_as_printed(printed: int) -> None:
    data = WindowStickerData(
        fuel_economy_city=printed, fuel_economy_highway=printed, fuel_economy_combined=printed
    )
    result = WindowStickerOCRService()._sticker_data_to_dict(data)
    for field in (
        "fuel_economy_city_l_per_100km",
        "fuel_economy_highway_l_per_100km",
        "fuel_economy_combined_l_per_100km",
    ):
        shown = (US_MPG / result[field]).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        assert shown == printed, field
