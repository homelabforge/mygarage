"""PDF dates follow the reader's date order (#278).

The PDFs are English for everyone, so month-first is right only for an English
reader who kept the default.
"""

from dataclasses import dataclass
from datetime import date, datetime

import pytest

from app.utils.date_order import DateStyle, format_date, format_datetime, resolve_date_order


@dataclass(frozen=True)
class _User:
    """Just the two account fields `DateOrderShape` reads."""

    language: str
    date_format: str


def _user(language: str = "en", date_format: str = "mdy") -> _User:
    return _User(language=language, date_format=date_format)


class TestResolveDateOrder:
    @pytest.mark.parametrize("requested", ["mdy", "dmy"])
    def test_what_the_page_asks_for_wins(self, requested: str) -> None:
        # The page sends what it shows, so it beats the account either way.
        flipped = "dmy" if requested == "mdy" else "mdy"
        assert resolve_date_order(requested, _user(date_format=flipped)) == requested
        assert resolve_date_order(requested, None) == requested

    def test_no_request_reads_the_account(self) -> None:
        assert resolve_date_order(None, _user(date_format="dmy")) == "dmy"
        assert resolve_date_order(None, _user(date_format="mdy")) == "mdy"

    @pytest.mark.parametrize("language", ["de", "fr", "pt-BR", "uk"])
    def test_every_other_language_is_day_first(self, language: str) -> None:
        # The setting is hidden for them and stays 'mdy', but their dates are day-first.
        assert resolve_date_order(None, _user(language=language, date_format="mdy")) == "dmy"

    def test_no_account_and_no_request_is_month_first(self) -> None:
        assert resolve_date_order(None, None) == "mdy"


class TestFormatDate:
    @pytest.mark.parametrize(
        ("style", "mdy", "dmy"),
        [
            ("numeric", "10/04/2026", "04/10/2026"),
            ("short", "Oct 04, 2026", "04 Oct 2026"),
            ("long", "October 04, 2026", "04 October 2026"),
        ],
    )
    def test_each_style_in_each_order(self, style: DateStyle, mdy: str, dmy: str) -> None:
        # Day 4 of month 10, so a swapped order can't pass by accident.
        value = date(2026, 10, 4)
        assert format_date(value, "mdy", style) == mdy
        assert format_date(value, "dmy", style) == dmy

    def test_datetime_keeps_the_clock(self) -> None:
        moment = datetime(2026, 10, 4, 14, 30)
        assert format_datetime(moment, "mdy") == "10/04/2026 02:30 PM"
        assert format_datetime(moment, "dmy") == "04/10/2026 02:30 PM"
