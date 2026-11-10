"""Window-sticker warnings name their amounts as bare numbers.

They reach the API as `validation_warnings` (the sticker test endpoint), and a
sticker carries no currency, so there is no symbol to pick. Same bare style as
the anomaly message.
"""

from decimal import Decimal

from app.services.window_sticker_parsers.base import WindowStickerData


def _warnings(
    *,
    msrp_base: Decimal | None = None,
    msrp_options: Decimal | None = None,
    msrp_total: Decimal | None = None,
) -> list[str]:
    return WindowStickerData(
        msrp_base=msrp_base, msrp_options=msrp_options, msrp_total=msrp_total
    ).get_validation_warnings()


def test_a_price_mismatch_names_its_difference_bare():
    # Total less base is 15000 of options; the sticker says 5000.
    (warning,) = _warnings(
        msrp_base=Decimal("30000.00"),
        msrp_options=Decimal("5000.00"),
        msrp_total=Decimal("45000.00"),
    )
    assert warning.startswith("Price mismatch:"), warning
    assert warning.endswith("difference: 10000.00"), warning
    assert "$" not in warning


def test_an_unusually_low_total_is_bare():
    assert _warnings(msrp_total=Decimal("9500.00")) == ["Total MSRP seems unusually low: 9500.00"]


def test_an_unusually_high_total_is_bare():
    assert _warnings(msrp_total=Decimal("600000.00")) == [
        "Total MSRP seems unusually high: 600000.00"
    ]
