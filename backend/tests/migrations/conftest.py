"""Fixtures for migration behavior and crash recovery tests."""

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text


@pytest.fixture
def migrations_dir() -> Path:
    """Path to the real migrations directory."""
    return Path(__file__).parent.parent.parent / "app" / "migrations"


@pytest.fixture
def migration_db(tmp_path, monkeypatch):
    """
    Bare isolated SQLite DB with both env vars pointing to the same file.

    Filename must be 'mygarage.db' so both migration styles resolve correctly:
      - sqlite3 migrations read DATABASE_PATH (= tmp_path/mygarage.db)
      - SQLAlchemy migrations read DATA_DIR and append 'mygarage.db' (= tmp_path/mygarage.db)
    """
    db_file = tmp_path / "mygarage.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return db_file, f"sqlite:///{db_file}"


def _pg_sync_url() -> str | None:
    """Resolve TEST_DATABASE_URL → psycopg2 sync URL, or return None if unset.

    The migration runner uses synchronous SQLAlchemy, so we always coerce
    asyncpg → psycopg2 when handing engines to migrations.
    """
    raw = os.getenv("TEST_DATABASE_URL", "").strip()
    if not raw:
        return None
    if "asyncpg" in raw:
        return raw.replace("postgresql+asyncpg", "postgresql+psycopg2")
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw


def _reset_pg_schema(engine: Engine) -> None:
    """Drop and recreate the public schema on PG (clean slate per test)."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(params=["sqlite", "pg"])
def engine_for_migration(request, tmp_path, monkeypatch) -> Generator[tuple[str, Engine, str]]:
    """Engine fixture parameterized over SQLite and PostgreSQL.

    Yields ``(dialect, engine, url)`` where ``dialect`` is ``"sqlite"`` or
    ``"pg"``. Tests that want to verify behavior on both engines depend on
    this fixture and pytest will run them twice. PG runs are skipped (not
    failed) when ``TEST_DATABASE_URL`` is unset, which is the default in
    the SQLite-only ``bin/ci-check`` flow. They run inside the
    ``docker-compose.test.yml`` stack which exports the URL automatically.

    Each PG run drops and recreates the ``public`` schema before yielding,
    so tests are isolated from each other and from prior runs.
    """
    if request.param == "sqlite":
        db_file = tmp_path / "mygarage.db"
        monkeypatch.setenv("DATABASE_PATH", str(db_file))
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        url = f"sqlite:///{db_file}"
        engine = create_engine(url)
        try:
            yield "sqlite", engine, url
        finally:
            engine.dispose()
        return

    pg_url = _pg_sync_url()
    if pg_url is None:
        pytest.skip(
            "TEST_DATABASE_URL not set — PG migration tests require the docker-compose.test.yml stack"
        )
    engine = create_engine(pg_url)
    _reset_pg_schema(engine)
    try:
        yield "pg", engine, pg_url
    finally:
        engine.dispose()


@pytest.fixture
def pg_engine() -> Generator[Engine]:
    """PG-only engine fixture for tests that load a baseline dump.

    Skipped (not failed) when ``TEST_DATABASE_URL`` is unset. The
    ``public`` schema is reset to empty before yield, so the test can
    immediately call ``load_baseline`` (or run ``create_all``) without
    worrying about leftover state from prior tests.

    Use this fixture when the test is inherently PG-only — for example,
    pre-migration baseline tests that load a ``pg_dump`` containing
    PostgreSQL-specific syntax (``SERIAL``, sequence DDL, etc.). For
    cross-engine tests, prefer ``engine_for_migration``.
    """
    pg_url = _pg_sync_url()
    if pg_url is None:
        pytest.skip(
            "TEST_DATABASE_URL not set — PG-only tests require the docker-compose.test.yml stack"
        )
    engine = create_engine(pg_url)
    _reset_pg_schema(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _write_fake_migration(path: Path, table_name: str) -> None:
    """Write a minimal synthetic migration that creates a table."""
    path.write_text(
        "from sqlalchemy import create_engine, text\n"
        "def upgrade(engine=None):\n"
        "    if engine is None:\n"
        "        import os\n"
        "        engine = create_engine(f\"sqlite:///{os.environ['DATABASE_PATH']}\")\n"
        "    with engine.begin() as conn:\n"
        f'        conn.execute(text("CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY)"))\n'
    )


@pytest.fixture
def fake_migrations_success_dir(tmp_path, monkeypatch):
    """Synthetic dir with 2 successful migrations. Used for noop and tracking tests."""
    fake_dir = tmp_path / "fake_migrations_success"
    fake_dir.mkdir()
    (fake_dir / "__init__.py").write_text("")
    db_file = tmp_path / "fake_success.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    _write_fake_migration(fake_dir / "001_create_foo.py", "foo")
    _write_fake_migration(fake_dir / "002_create_bar.py", "bar")
    return fake_dir, db_file, f"sqlite:///{db_file}"


@pytest.fixture
def fake_migrations_failing_dir(tmp_path, monkeypatch):
    """Synthetic dir with 2 good migrations then 1 that raises. Used for stop-on-failure test."""
    fake_dir = tmp_path / "fake_migrations_failing"
    fake_dir.mkdir()
    (fake_dir / "__init__.py").write_text("")
    db_file = tmp_path / "fake_failing.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    _write_fake_migration(fake_dir / "001_create_foo.py", "foo")
    _write_fake_migration(fake_dir / "002_create_bar.py", "bar")
    (fake_dir / "003_fail.py").write_text(
        'def upgrade(engine=None):\n    raise RuntimeError("forced failure for testing")\n'
    )
    return fake_dir, db_file, f"sqlite:///{db_file}"
