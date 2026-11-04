"""Day-first or month-first dates in what the backend renders (the PDFs).

The PDFs are English for everyone (the backend isn't translated), so the order
follows the reader: month-first only for an English reader who kept the
default, day-first for anyone who picked it and for every other language,
whose own convention is day-first.
"""

from datetime import date, datetime
from typing import Literal, Protocol

DateOrder = Literal["mdy", "dmy"]
DateStyle = Literal["numeric", "short", "long"]

# For a Query(pattern=...). `users.date_format` holds the same two values.
DATE_ORDER_PATTERN = "^(mdy|dmy)$"

_FORMATS: dict[DateStyle, dict[DateOrder, str]] = {
    "numeric": {"mdy": "%m/%d/%Y", "dmy": "%d/%m/%Y"},
    "short": {"mdy": "%b %d, %Y", "dmy": "%d %b %Y"},
    "long": {"mdy": "%B %d, %Y", "dmy": "%d %B %Y"},
}


class DateOrderSource(Protocol):
    """The two account fields the order comes from; the ORM `User` fits."""

    @property
    def date_format(self) -> str: ...

    @property
    def language(self) -> str: ...


def resolve_date_order(requested: str | None, user: DateOrderSource | None) -> DateOrder:
    """The order a PDF should print its dates in.

    Args:
        requested: What the page asked for. The app sends what it shows, which
            is the only answer on an auth-none instance (no account to read).
        user: The caller, or None when auth is off.

    Returns:
        'mdy' or 'dmy'.
    """
    if requested == "mdy" or requested == "dmy":
        return requested
    if user is None:
        return "mdy"
    if user.language != "en":
        return "dmy"
    return "dmy" if user.date_format == "dmy" else "mdy"


def format_date(value: date, order: DateOrder, style: DateStyle = "numeric") -> str:
    """Format a date as 10/24/2026 or 24/10/2026, Oct 24, 2026 or 24 Oct 2026, and so on.

    Args:
        value: The date (a datetime prints its date part).
        order: 'mdy' or 'dmy'.
        style: numeric, short month name, or full month name.

    Returns:
        The formatted date.
    """
    return value.strftime(_FORMATS[style][order])


def format_datetime(value: datetime, order: DateOrder) -> str:
    """A numeric date and a 12-hour clock: 10/24/2026 02:30 PM or 24/10/2026 02:30 PM.

    Args:
        value: The moment, already in the zone it should read in.
        order: 'mdy' or 'dmy'.

    Returns:
        The formatted date and time.
    """
    return f"{format_date(value, order)} {value.strftime('%I:%M %p')}"
