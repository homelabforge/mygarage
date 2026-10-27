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
        from sqlalchemy.engine import make_url

        url = resolve_sync_url("/data/mygarage.db")
        assert url.startswith("sqlite:///")
        assert make_url(url).database == "/data/mygarage.db"

    def test_a_relative_path_is_still_sqlite(self):
        from sqlalchemy.engine import make_url

        url = resolve_sync_url("mygarage.db")
        assert url.startswith("sqlite:///")
        assert make_url(url).database == "mygarage.db"

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
        from sqlalchemy.engine import make_url

        url = resolve_sync_url("C:/data/mygarage.db")
        assert url.startswith("sqlite:///")
        assert make_url(url).database == "C:/data/mygarage.db"

    def test_an_unreachable_dialect_is_refused_by_name(self):
        """A URL naming a driver the tools cannot use fails here, not mid-migration."""
        with pytest.raises(ValueError, match="mysql"):
            resolve_sync_url("mysql://u:p@host/mygarage")

    def test_a_driverless_postgres_url_builds_an_engine(self):
        """create_engine imports the driver up front, which is where a bare URL died on 2.1."""
        from sqlalchemy import create_engine

        engine = create_engine(resolve_sync_url("postgresql://u:p@host/mygarage"))
        assert engine.dialect.driver == "psycopg2"
        engine.dispose()

    @pytest.mark.parametrize(
        "path",
        [
            "/data/mygarage.db",
            "mygarage.db",
            "C:/data/mygarage.db",
            "/data/my%41garage.db",
            "/data/a#b.db",
        ],
    )
    def test_a_bare_path_is_taken_literally(self, path):
        """2.1 percent-decodes the database part of a URL, so the path can't be pasted into one raw.

        Only the %41 case failed before the fix; the rest are guards. Quoting the path before
        URL.create kills C: and #, resolving it kills mygarage.db, and stripping its leading
        slash kills /data/mygarage.db.
        """
        from sqlalchemy.engine import make_url

        url = resolve_sync_url(path)
        assert url.startswith("sqlite:///")
        assert make_url(url).database == path

    def test_an_explicit_url_is_not_escaped_again(self):
        """A URL the operator wrote is already a URL: %41 in it means A, as SQLAlchemy says.

        A guard: it passes before the fix too. Running a sqlite URL's path back through
        URL.create kills it by escaping the %41 a second time.
        """
        from sqlalchemy.engine import make_url

        assert (
            make_url(resolve_sync_url("sqlite:////data/my%41garage.db")).database
            == "/data/myAgarage.db"
        )


class TestCreateToolEngine:
    """Tools open their sync engine through one factory, on the runner's pin rule (R2)."""

    def test_sqlite_gets_a_plain_engine_and_no_connection(self, tmp_path):
        """SQLite has no session zone, and the factory shouldn't create the file by peeking."""
        from sqlalchemy import event

        from app.utils.pg_session import _set_session_utc
        from tools._tool_db import create_tool_engine

        db_file = tmp_path / "mygarage.db"
        engine = create_tool_engine(str(db_file))
        try:
            assert engine.dialect.name == "sqlite"
            assert engine.hide_parameters is True
            assert not event.contains(engine, "connect", _set_session_utc)
            assert not db_file.exists()
        finally:
            engine.dispose()

    def test_no_tool_builds_its_own_sync_engine(self):
        """A tool that called create_engine itself would skip the pin rule, pinned or not.

        Its PG side runs in tests/migrations/test_runner_utc_pin.py, which can reset the schema.
        """
        import ast
        from pathlib import Path

        tools_dir = Path(__file__).resolve().parents[3] / "tools"
        builders = {"create_engine", "create_utc_engine"}
        offenders = []
        for module in sorted(tools_dir.glob("*.py")):
            if module.name == "_tool_db.py":
                continue
            for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name in builders:
                    offenders.append(f"{module.name}:{node.lineno}")
        assert offenders == []
