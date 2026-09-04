"""The maintenance tools must reach whichever database the instance actually uses.

`backfill_livelink_odometer.py`, `normalize_telemetry_odometer_units.py` and
`fix_session_odometer_units.py` each built their engine as
`create_engine(f"sqlite:///{args.db}")`. On a PostgreSQL instance that does not
fail loudly: SQLAlchemy happily creates an **empty SQLite file** at the given
path, and the tool then dies with `no such table: livelink_devices`. PostgreSQL
is a supported, CI-tested deployment, so every PostgreSQL instance hit by the
v2.26.2 odometer-units regression had no repair path at all.

The conversion these tools need already existed, written inline in
`init_db` (`app/database.py`), which is why it is extracted here rather than
written a second time.
"""

import pytest

from app.utils.db_url import to_sync_url


class TestToSyncUrl:
    """Async driver URLs convert to the sync driver the tools and migrations use."""

    def test_asyncpg_becomes_psycopg2(self):
        """PostgreSQL is the case the tools got wrong; it must survive intact."""
        assert (
            to_sync_url("postgresql+asyncpg://u:p@host:5432/mygarage")
            == "postgresql+psycopg2://u:p@host:5432/mygarage"
        )

    def test_aiosqlite_becomes_sqlite(self):
        assert to_sync_url("sqlite+aiosqlite:////data/mygarage.db") == "sqlite:////data/mygarage.db"

    def test_an_already_sync_url_is_unchanged(self):
        """Idempotent: running it twice must not corrupt the URL."""
        assert to_sync_url("postgresql+psycopg2://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"
        assert to_sync_url("sqlite:////data/mygarage.db") == "sqlite:////data/mygarage.db"

    def test_a_postgres_url_never_becomes_sqlite(self):
        """The exact defect: a PostgreSQL instance silently getting a SQLite file.

        Asserted as its own case rather than left implicit in the conversion
        test, because this is the property that mattered and the one a future
        refactor could quietly break.
        """
        for url in (
            "postgresql+asyncpg://u:p@host/mygarage",
            "postgresql://u:p@host/mygarage",
            "postgresql+psycopg2://u:p@host/mygarage",
        ):
            assert not to_sync_url(url).startswith("sqlite"), url

    @pytest.mark.parametrize("url", ["", "   "])
    def test_an_empty_url_is_rejected(self, url):
        """An empty URL would otherwise reach create_engine as a mystery failure."""
        with pytest.raises(ValueError, match="empty"):
            to_sync_url(url)
