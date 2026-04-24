"""Tests for backend currency-symbol helper used by PDF generators."""

import pytest

from app.utils.currency import (
    get_currency_symbol,
    is_valid_currency_code,
    is_valid_locale,
    normalize_pdf_currency_params,
)


class TestIsValidCurrencyCode:
    @pytest.mark.parametrize("code", ["USD", "EUR", "GBP", "PLN", "JPY"])
    def test_accepts_valid_iso_codes(self, code: str) -> None:
        assert is_valid_currency_code(code) is True

    @pytest.mark.parametrize(
        "code",
        ["usd", "US", "USDD", "US$", "", "   ", None, "U$D", "123"],
    )
    def test_rejects_malformed_codes(self, code: str | None) -> None:
        assert is_valid_currency_code(code) is False


class TestIsValidLocale:
    @pytest.mark.parametrize("locale", ["en-US", "de-DE", "pl-PL", "en", "zh-Hans-CN"])
    def test_accepts_bcp47_shapes(self, locale: str) -> None:
        assert is_valid_locale(locale) is True

    @pytest.mark.parametrize(
        "locale",
        ["", None, "en_US", "bogus!", "<script>", "--"],
    )
    def test_rejects_malformed_locales(self, locale: str | None) -> None:
        assert is_valid_locale(locale) is False


class TestGetCurrencySymbol:
    def test_usd_returns_dollar(self) -> None:
        assert get_currency_symbol("USD") == "$"

    def test_eur_returns_euro(self) -> None:
        assert get_currency_symbol("EUR") == "€"

    def test_gbp_returns_pound(self) -> None:
        assert get_currency_symbol("GBP") == "£"

    def test_pln_returns_zloty(self) -> None:
        assert get_currency_symbol("PLN") == "zł"

    def test_uah_returns_hryvnia(self) -> None:
        assert get_currency_symbol("UAH") == "₴"

    def test_jpy_returns_yen(self) -> None:
        assert get_currency_symbol("JPY") == "¥"

    def test_invalid_code_falls_back(self) -> None:
        # Non-ISO-shape input echoes the uppercased code so the user sees the mistake.
        assert get_currency_symbol("BADX") == "BADX"

    def test_malformed_code_echoes_uppercased(self) -> None:
        # Lowercase / wrong-length codes are malformed; we echo uppercase rather than guess.
        assert get_currency_symbol("us") == "US"

    def test_empty_or_none_defaults_to_dollar(self) -> None:
        # Empty / None inputs use the pre-hotfix default symbol.
        assert get_currency_symbol(None) == "$"
        assert get_currency_symbol("") == "$"

    def test_unknown_but_valid_shape_returns_code(self) -> None:
        # Valid ISO-4217 shape but not in our allowlist or symbol map.
        result = get_currency_symbol("ZZZ")
        assert result == "ZZZ"


class TestNormalizePdfCurrencyParams:
    def test_valid_params_passthrough(self) -> None:
        code, locale = normalize_pdf_currency_params("EUR", "de-DE")
        assert code == "EUR"
        assert locale == "de-DE"

    def test_malformed_currency_defaults_usd(self) -> None:
        code, _ = normalize_pdf_currency_params("bogus", "en-US")
        assert code == "USD"

    def test_malformed_locale_defaults_en_us(self) -> None:
        _, locale = normalize_pdf_currency_params("USD", "en_US")
        assert locale == "en-US"

    def test_any_bcp47_locale_retained(self) -> None:
        # Valid BCP-47 shapes pass through unchanged; currency symbol selection
        # is code-driven, not locale-driven, so we don't need an allowlist.
        _, locale = normalize_pdf_currency_params("USD", "fr-FR")
        assert locale == "fr-FR"
        _, locale = normalize_pdf_currency_params("PLN", "pl-PL")
        assert locale == "pl-PL"
        _, locale = normalize_pdf_currency_params("EUR", "de-DE")
        assert locale == "de-DE"

    def test_both_invalid_defaults_to_usd_en_us(self) -> None:
        code, locale = normalize_pdf_currency_params("bad", "bad_locale")
        assert code == "USD"
        assert locale == "en-US"

    def test_none_inputs_default_safely(self) -> None:
        code, locale = normalize_pdf_currency_params(None, None)
        assert code == "USD"
        assert locale == "en-US"
