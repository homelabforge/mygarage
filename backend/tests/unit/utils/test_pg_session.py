"""The UTC session pin for PG engines (RD-6, R1), checked without a PG server.

What actually reaches the driver is captured by swapping `asyncpg.connect` for
a fake that records its kwargs and refuses, so these run on the SQLite job too.
The behaviour against a real non-UTC server is in
`tests/integration/test_pg_session_timezone.py`.
"""

import importlib.util
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine

import app.database
from app.config import settings
from app.utils import pg_session
from app.utils.pg_session import (
    asyncpg_connect_args,
    create_utc_async_engine,
    create_utc_engine,
    pin_psycopg2_engine,
)

pytestmark = pytest.mark.unit

# Port 1 on loopback: nothing listens, and nothing here gets that far anyway.
ASYNCPG_URL = "postgresql+asyncpg://probe:probe@127.0.0.1:1/probe"
PSYCOPG2_URL = "postgresql+psycopg2://probe:probe@127.0.0.1:1/probe"


class _RefusedError(Exception):
    """The fake connect's refusal, so a real connection error can't pass for it."""


async def _driver_kwargs(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The kwargs the engine hands `asyncpg.connect` on its first connect."""
    seen: dict[str, Any] = {}

    async def fake_connect(*args: Any, **kwargs: Any) -> None:
        seen.update(kwargs)
        raise _RefusedError

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    try:
        with pytest.raises(_RefusedError):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()
    return seen


def _pin_count(engine: Engine) -> int:
    return list(engine.pool.dispatch.connect).count(pg_session._set_session_utc)  # pyright: ignore[reportPrivateUsage]


def test_asyncpg_connect_args_merges_into_existing_server_settings() -> None:
    """A fixture's search_path survives the pin, and the input isn't touched."""
    given = {"timeout": 5, "server_settings": {"search_path": "probe", "timezone": "Asia/Kolkata"}}
    merged = asyncpg_connect_args(given)
    assert merged == {"timeout": 5, "server_settings": {"search_path": "probe", "timezone": "UTC"}}
    assert given["server_settings"] == {"search_path": "probe", "timezone": "Asia/Kolkata"}


def test_asyncpg_connect_args_with_nothing_given() -> None:
    assert asyncpg_connect_args() == {"server_settings": {"timezone": "UTC"}}


async def test_the_app_engine_asks_asyncpg_for_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """`app.database`'s PG branch, as a fresh copy built under a PG URL.

    asyncpg ignores PGTZ, so without this the app's sessions take the server's zone.
    """
    monkeypatch.setattr(settings, "database_url", ASYNCPG_URL)
    path = Path(app.database.__file__)
    spec = importlib.util.spec_from_file_location("_database_pin_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    kwargs = await _driver_kwargs(module.engine, monkeypatch)
    assert kwargs.get("server_settings", {}).get("timezone") == "UTC"


async def test_create_utc_async_engine_pins_and_keeps_other_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_utc_async_engine(
        ASYNCPG_URL, connect_args={"server_settings": {"search_path": "probe"}}
    )
    kwargs = await _driver_kwargs(engine, monkeypatch)
    assert kwargs["server_settings"] == {"search_path": "probe", "timezone": "UTC"}


def test_create_utc_async_engine_leaves_sqlite_alone() -> None:
    engine = create_utc_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert engine.dialect.name == "sqlite"
    finally:
        engine.sync_engine.dispose()


def test_create_utc_engine_pins_psycopg2_and_leaves_sqlite_alone() -> None:
    pg = create_utc_engine(PSYCOPG2_URL)
    lite = create_utc_engine("sqlite://")
    try:
        assert _pin_count(pg) == 1
        assert _pin_count(lite) == 0
    finally:
        pg.dispose()
        lite.dispose()


@pytest.mark.parametrize(
    ("factory", "url"),
    [
        (create_utc_engine, "postgresql+asyncpg://probe@127.0.0.1:1/probe"),
        (create_utc_async_engine, "postgresql+psycopg://probe@127.0.0.1:1/probe"),
    ],
)
def test_a_driver_the_pin_cant_handle_is_refused(factory: Any, url: str) -> None:
    """A pin that silently did nothing would look exactly like one that works."""
    with pytest.raises(ValueError, match="can't pin"):
        factory(url)


def test_pin_psycopg2_engine_refuses_sqlite() -> None:
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(ValueError, match="postgresql\\+psycopg2"):
            pin_psycopg2_engine(engine)
    finally:
        engine.dispose()
