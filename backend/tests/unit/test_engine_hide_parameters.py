"""Every engine the app builds hides bound parameters from its error messages (plan test 10, L3).

A failed statement's message carries its bound parameters by default, and the
database error handler logs that message. A failed settings write would log the
secret it was writing. With `hide_parameters=True` the message says the
parameters are hidden instead.

`app.database` builds one engine, for whichever dialect `settings.database_url`
names, at import. The test loads a fresh copy of the module under each dialect
so both branches are checked on the engine object they really build; the copy
is a separate module, so the app's own engine is untouched. The migration
runner's engine is built the way its own tests build it.
"""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database
from app.config import settings
from app.migrations.runner import MigrationRunner

pytestmark = pytest.mark.unit

SECRET = "hunter2-bound-parameter"

DATABASE_URLS = {
    "sqlite": "sqlite+aiosqlite:///:memory:",
    "postgresql": "postgresql+asyncpg://probe:probe@127.0.0.1:1/probe",
}


def _fresh_database_module(dialect: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A fresh copy of `app.database`, imported with `settings.database_url` set to `dialect`'s URL."""
    monkeypatch.setattr(settings, "database_url", DATABASE_URLS[dialect])
    path = Path(app.database.__file__)
    spec = importlib.util.spec_from_file_location(f"_database_probe_{dialect}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=sorted(DATABASE_URLS))
def database_module(request: pytest.FixtureRequest, monkeypatch) -> Iterator[ModuleType]:
    """A fresh copy of `app.database` per dialect; its engine is disposed afterwards."""
    module = _fresh_database_module(request.param, monkeypatch)
    yield module
    module.engine.sync_engine.dispose()


def test_the_app_engine_hides_parameters() -> None:
    """The engine the running app uses, as imported."""
    assert app.database.engine.sync_engine.hide_parameters is True


def test_each_dialects_engine_hides_parameters(database_module: ModuleType) -> None:
    """Both branches of `app.database`: SQLite and PostgreSQL build different engines."""
    assert database_module.engine.sync_engine.hide_parameters is True


async def test_a_failed_statement_on_the_sqlite_engine_names_no_parameter(monkeypatch) -> None:
    """The behaviour the flag buys: the error message hides the bound value."""
    module = _fresh_database_module("sqlite", monkeypatch)
    try:
        async with module.engine.connect() as conn:
            with pytest.raises(DBAPIError) as raised:
                await conn.execute(
                    text("INSERT INTO no_such_table (value) VALUES (:v)"), {"v": SECRET}
                )
    finally:
        await module.engine.dispose()
    assert SECRET not in str(raised.value)
    assert "hide_parameters=True" in str(raised.value)


def test_the_migration_runner_engine_hides_parameters(tmp_path: Path) -> None:
    runner = MigrationRunner("sqlite://", tmp_path)
    try:
        assert runner.engine.hide_parameters is True
        with runner.engine.connect() as conn, pytest.raises(DBAPIError) as raised:
            conn.execute(text("INSERT INTO no_such_table (value) VALUES (:v)"), {"v": SECRET})
        assert SECRET not in str(raised.value)
    finally:
        runner.engine.dispose()
