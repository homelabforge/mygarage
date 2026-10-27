"""PG sessions keep UTC whatever zone the server runs in (RD-6).

The test sidecar runs Asia/Kolkata (+05:30) on purpose. A positive half-hour
offset means a sign flip or hour-only maths fails too, not just a missing pin.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.utils.db_url import to_sync_url

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
IS_PG = bool(TEST_DATABASE_URL) and make_url(TEST_DATABASE_URL).get_backend_name() == "postgresql"
pytestmark = pytest.mark.skipif(not IS_PG, reason="PostgreSQL-only tests")


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
