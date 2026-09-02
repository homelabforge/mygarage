"""A repair tool must read a DATE column on either dialect.

`backfill_livelink_odometer.py` called `date.fromisoformat(row.day)` on three
columns. SQLite has no date type, so `date(timestamp)` and a `DATE` column both
come back as `str` and the call is correct. psycopg2 adapts PostgreSQL `DATE` to
`datetime.date`, and `date.fromisoformat` rejects a `date`:

    TypeError: fromisoformat: argument must be str

Before commit `96313be` this was unreachable, because the tool hardcoded
`sqlite:///{path}` and could never open a PostgreSQL database at all. Making the
tool reach PostgreSQL moved the failure from "connects to the wrong database" to
"dies on the first telemetry row", which is why the fix and this guard arrive
together rather than in the commit that added the URL resolver.
"""

from datetime import date

import pytest

from tools._tool_db import as_date


class TestAsDate:
    """Normalizes whatever the driver returns for a DATE column."""

    def test_a_sqlite_string_is_parsed(self):
        assert as_date("2026-04-25") == date(2026, 4, 25)

    def test_a_postgres_date_passes_through(self):
        """The defect. psycopg2 returns `datetime.date`, not `str`."""
        assert as_date(date(2026, 4, 25)) == date(2026, 4, 25)

    def test_a_datetime_is_narrowed_to_its_date(self):
        """`date(timestamp)` on PostgreSQL yields a date, but a raw timestamp
        column selected without the cast yields a datetime. Narrow rather than
        raise, because a datetime carries the answer."""
        from datetime import datetime

        assert as_date(datetime(2026, 4, 25, 13, 30)) == date(2026, 4, 25)

    def test_none_is_refused_rather_than_silently_dropped(self):
        """A null day would otherwise become a dict key of None and group every
        null row into one fabricated day."""
        with pytest.raises(ValueError, match="null"):
            as_date(None)

    def test_an_unparseable_string_still_raises(self):
        with pytest.raises(ValueError):
            as_date("not-a-date")
