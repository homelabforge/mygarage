"""`--db` must accept whatever database the instance actually runs.

The three raw-SQL maintenance tools took `--db` as a filesystem path and built
`sqlite:///{path}` from it unconditionally. That is wrong two ways on a
PostgreSQL instance: there is no path to give, and any path given produces an
empty SQLite file rather than an error.

`resolve_sync_url` keeps the old path form working, because the published
upgrade note tells people to pass `/data/mygarage.db`, and adds the two forms
that instance needs: a full URL, or nothing at all (fall back to the app's own
configured database).
"""

import pytest

from tools._tool_db import resolve_sync_url


class TestResolveSyncUrl:
    """`--db` accepts a path, a URL, or nothing."""

    def test_a_bare_path_is_still_sqlite(self):
        """The published upgrade note passes `/data/mygarage.db`; it must keep working."""
        assert resolve_sync_url("/data/mygarage.db") == "sqlite:////data/mygarage.db"

    def test_a_relative_path_is_still_sqlite(self):
        assert resolve_sync_url("mygarage.db") == "sqlite:///mygarage.db"

    def test_a_postgres_url_stays_postgres(self):
        """The defect. A path-only reading of this produced a SQLite file."""
        assert (
            resolve_sync_url("postgresql+asyncpg://u:p@host/mygarage")
            == "postgresql+psycopg2://u:p@host/mygarage"
        )

    def test_a_sqlite_url_is_accepted_as_a_url(self):
        assert resolve_sync_url("sqlite:////data/mygarage.db") == "sqlite:////data/mygarage.db"

    def test_no_argument_falls_back_to_the_configured_database(self, monkeypatch):
        """A tool run inside the container should not need to be told where the DB is."""
        import app.config

        monkeypatch.setattr(
            app.config.settings, "database_url", "postgresql+asyncpg://u:p@host/mygarage"
        )
        assert resolve_sync_url(None) == "postgresql+psycopg2://u:p@host/mygarage"

    def test_a_windows_style_path_is_not_mistaken_for_a_url(self):
        """`C:\\db` contains a colon but is not a scheme. Guarded deliberately."""
        assert resolve_sync_url("C:/data/mygarage.db") == "sqlite:///C:/data/mygarage.db"

    def test_an_unreachable_dialect_is_refused_by_name(self):
        """A URL naming a driver the tools cannot use fails here, not mid-migration."""
        with pytest.raises(ValueError, match="mysql"):
            resolve_sync_url("mysql://u:p@host/mygarage")
