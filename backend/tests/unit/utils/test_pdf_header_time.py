"""The PDF header's date and time are the household's, labelled with its zone.

It used to print the container's local clock with a hard-coded "CST", so every
install outside US Central got a wrong label, and a UTC container got UTC
digits called CST.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.utils import pdf_components
from app.utils.household_time import household_zone_var


def frozen_at(instant: datetime) -> type[datetime]:
    """A datetime class whose now() is `instant` (aware, UTC).

    A bare now() gets the UTC wall clock, naive, like a container with no TZ.
    """

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Frozen:
            moment = instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)
            return cls(
                moment.year,
                moment.month,
                moment.day,
                moment.hour,
                moment.minute,
                moment.second,
                moment.microsecond,
                tzinfo=moment.tzinfo,
                fold=moment.fold,
            )

    return Frozen


def header_strings(monkeypatch: pytest.MonkeyPatch, zone: str, instant: datetime) -> list[str]:
    """Draw the first-page header in `zone` at `instant`; return the right-aligned text."""
    monkeypatch.setattr(pdf_components, "datetime", frozen_at(instant))
    household_zone_var.set(ZoneInfo(zone))
    canvas = MagicMock()
    pdf_components.draw_branded_header(canvas, SimpleNamespace(page=1))
    return [call.args[2] for call in canvas.drawRightString.call_args_list]


@pytest.mark.parametrize(
    ("zone", "instant", "date_str", "time_str"),
    [
        # London in summer: BST, an hour ahead of UTC.
        (
            "Europe/London",
            datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
            "July 15, 2026",
            "07:30 PM BST",
        ),
        # London in winter: GMT.
        (
            "Europe/London",
            datetime(2026, 1, 15, 18, 30, tzinfo=UTC),
            "January 15, 2026",
            "06:30 PM GMT",
        ),
        ("UTC", datetime(2026, 7, 15, 18, 30, tzinfo=UTC), "July 15, 2026", "06:30 PM UTC"),
        # Chicago gets CST or CDT by date, not a fixed label.
        (
            "America/Chicago",
            datetime(2026, 1, 15, 18, 30, tzinfo=UTC),
            "January 15, 2026",
            "12:30 PM CST",
        ),
        # After midnight UTC it's still the evening before in Chicago.
        (
            "America/Chicago",
            datetime(2026, 7, 16, 3, 30, tzinfo=UTC),
            "July 15, 2026",
            "10:30 PM CDT",
        ),
    ],
)
def test_header_shows_the_household_time_and_zone(
    monkeypatch: pytest.MonkeyPatch, zone: str, instant: datetime, date_str: str, time_str: str
) -> None:
    assert header_strings(monkeypatch, zone, instant) == [date_str, time_str]


def test_a_non_central_household_never_says_cst(monkeypatch: pytest.MonkeyPatch) -> None:
    drawn = header_strings(monkeypatch, "Europe/London", datetime(2026, 1, 15, 18, 30, tzinfo=UTC))
    assert not any("CST" in text for text in drawn), drawn


def footer_strings(monkeypatch: pytest.MonkeyPatch, zone: str, instant: datetime) -> list[str]:
    """Draw the footer in `zone` at `instant`; return the right-aligned text."""
    monkeypatch.setattr(pdf_components, "datetime", frozen_at(instant))
    household_zone_var.set(ZoneInfo(zone))
    canvas = MagicMock()
    pdf_components.draw_branded_footer(canvas, SimpleNamespace(page=1))
    return [call.args[2] for call in canvas.drawRightString.call_args_list]


def test_the_footer_report_id_is_the_household_time_like_the_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 23:30 UTC is already the next morning in Auckland, so a footer on the
    # container's clock would be dated a day before the header.
    instant = datetime(2026, 7, 15, 23, 30, tzinfo=UTC)
    [footer] = footer_strings(monkeypatch, "Pacific/Auckland", instant)
    assert footer.endswith("MG-20260716-113000"), footer
    assert header_strings(monkeypatch, "Pacific/Auckland", instant)[0] == "July 16, 2026"


def test_the_footer_carries_the_running_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """It printed a hard-coded v2.21 on every release since."""
    from app.config import get_version

    [footer] = footer_strings(monkeypatch, "UTC", datetime(2026, 7, 15, 18, 30, tzinfo=UTC))
    assert footer.startswith(f"v{get_version()} · "), footer
