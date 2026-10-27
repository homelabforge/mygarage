"""PG sessions keep UTC whatever zone the server runs in (RD-6).

The test sidecar runs Asia/Kolkata (+05:30) on purpose. A positive half-hour
offset means a sign flip or hour-only maths fails too, not just a missing pin.
"""

import os
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.database import AsyncSessionLocal
from app.database import engine as app_engine
from app.models.note import Note
from app.utils.datetime_utils import utc_now
from app.utils.db_url import to_sync_url
from app.utils.pg_session import create_utc_async_engine, create_utc_engine

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
IS_PG = bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL).get_backend_name() == "postgresql"
pytestmark = pytest.mark.skipif(not IS_PG, reason="PostgreSQL-only tests")

# Commit latency, not zone error: an unpinned session is 5.5 h out here.
SKEW = timedelta(seconds=30)


def test_server_zone_is_not_utc() -> None:
    """If the sidecar drifts back to UTC, every other zone test here passes for nothing."""
    # Unpinned on purpose: this is the zone any session gets from the server.
    engine = create_engine(to_sync_url(TEST_DATABASE_URL), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            zone, source = conn.execute(
                text("SELECT setting, source FROM pg_settings WHERE name = 'TimeZone'")
            ).one()
            offset = int(conn.execute(text("SELECT EXTRACT(TIMEZONE FROM now())")).scalar_one())
    finally:
        engine.dispose()

    # A client-side zone (PGTZ, options) would hide what the server itself runs.
    assert source != "client", f"TimeZone {zone} came from the client, not the server"
    assert offset > 0, f"server zone {zone} is UTC{offset:+d}s; want a positive offset"
    assert offset % 3600 != 0, f"server zone {zone} is a whole-hour offset ({offset}s)"


async def test_the_suites_own_sessions_run_in_utc(db_session: AsyncSession) -> None:
    """The shared test engine is pinned too, or every PG test reads skewed stamps."""
    assert (await db_session.execute(text("SHOW timezone"))).scalar_one() == "UTC"


async def _note_stamps_through_the_app(vin: str) -> tuple[datetime, datetime | None]:
    """Insert, edit and delete a note through the app's own session factory.

    `notes.created_at` is a server default and `notes.updated_at` an onupdate,
    and the app never sets either, so the session zone is all that decides them.
    """
    try:
        async with AsyncSessionLocal() as session:
            note = Note(vin=vin, date=date(2026, 1, 15), content="zone probe")
            session.add(note)
            await session.commit()
            try:
                await session.refresh(note)
                created = note.created_at
                note.content = "zone probe, edited"
                await session.commit()
                await session.refresh(note)
                updated = note.updated_at
            finally:
                await session.delete(note)
                await session.commit()
    finally:
        # The app engine pools; leave none of its connections behind for other
        # tests, even when the probe itself fails.
        await app_engine.dispose()
    return created, updated


async def test_app_session_server_default_lands_in_utc(test_vehicle: dict[str, object]) -> None:
    created, _ = await _note_stamps_through_the_app(str(test_vehicle["vin"]))
    now = utc_now()
    assert abs(now - created) < SKEW, f"created_at {created} vs UTC now {now}"


async def test_app_session_onupdate_lands_in_utc(test_vehicle: dict[str, object]) -> None:
    _, updated = await _note_stamps_through_the_app(str(test_vehicle["vin"]))
    now = utc_now()
    assert updated is not None
    assert abs(now - updated) < SKEW, f"updated_at {updated} vs UTC now {now}"


def test_psycopg2_pin_survives_a_rollback_and_beats_client_options() -> None:
    """The runner and tools' driver: the SET has to outlive the first transaction.

    One pooled connection, so the second checkout is the same session the first
    one rolled back. A zone in `options` loses to the pin; the search_path in
    there still applies.
    """
    engine = create_utc_engine(
        to_sync_url(TEST_DATABASE_URL),
        connect_args={"options": "-c timezone=America/Chicago -c search_path=public"},
        pool_size=1,
        max_overflow=0,
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.rollback()
        with engine.connect() as conn:
            zone = conn.execute(text("SHOW timezone")).scalar_one()
            search_path = conn.execute(text("SHOW search_path")).scalar_one()
            stamp = conn.execute(text("SELECT now()::timestamp")).scalar_one()
    finally:
        engine.dispose()

    assert zone == "UTC"
    assert search_path == "public"
    assert abs(utc_now() - stamp) < SKEW


async def test_asyncpg_pin_keeps_the_callers_server_settings() -> None:
    """A fixture's own search_path rides along with the pin, and its zone loses."""
    engine = create_utc_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": "public", "timezone": "America/Chicago"}},
    )
    try:
        async with engine.connect() as conn:
            zone = (await conn.execute(text("SHOW timezone"))).scalar_one()
            search_path = (await conn.execute(text("SHOW search_path"))).scalar_one()
    finally:
        await engine.dispose()

    assert zone == "UTC"
    assert search_path == "public"
