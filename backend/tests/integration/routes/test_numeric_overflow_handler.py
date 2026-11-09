"""A numeric overflow that validation missed is a 422, not a 500.

Validation is the fence: every money input is bounded and every computed total
is checked before it is written. This is the backstop for a path that slipped
through. PostgreSQL refuses an over-column number with SQLSTATE 22003 ("numeric
field overflow", or "integer out of range" for an integer column), and that
reaches the client as a 422 saying the number is too large for storage, in debug
mode too. Every other database error keeps the treatment it had.

Driven through real request paths: the app's own route, with its service forced
to raise, and on PostgreSQL a real overflowing UPDATE through the request's
session, so the driver's own exception shape is what the handler sees.
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.services.spot_rental_service import SpotRentalService
from tests._logged import problems

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TOO_LARGE = "Number too large for storage"
DATABASE_ERROR = "A database error occurred. Please try again later."
STATEMENT = "UPDATE vehicles SET msrp_total=%(msrp_total)s WHERE vehicles.vin = %(vin)s"


class _AsyncpgShapedError(Exception):
    """What SQLAlchemy's asyncpg adapter raises: `sqlstate` and `pgcode` both set.

    asyncpg's own DataError is translated to the adapter's generic Error, so
    SQLAlchemy wraps it as a plain DBAPIError, not a DataError.
    """

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"numeric field overflow ({sqlstate})")
        self.sqlstate = self.pgcode = sqlstate


class _Psycopg2ShapedError(Exception):
    """What psycopg2 raises: the code on `pgcode` only."""

    def __init__(self, pgcode: str) -> None:
        super().__init__(f"database error ({pgcode})")
        self.pgcode = pgcode


@pytest_asyncio.fixture
async def own_vin(db_session: AsyncSession, test_user: dict[str, object]) -> AsyncGenerator[str]:
    vin = "OVF" + uuid.uuid4().hex[:14].upper()
    db_session.add(
        Vehicle(vin=vin, user_id=test_user["id"], nickname="Overflow", vehicle_type="RV")
    )
    await db_session.commit()
    yield vin
    await db_session.rollback()
    stored = await db_session.get(Vehicle, vin)
    if stored is not None:
        await db_session.delete(stored)
        await db_session.commit()


def _raising(exc: Exception) -> Any:
    async def list_rentals(self: SpotRentalService, vin: str, current_user: Any) -> Any:
        raise exc

    return list_rentals


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(DBAPIError(STATEMENT, {}, _AsyncpgShapedError("22003")), id="asyncpg"),
        pytest.param(DataError(STATEMENT, {}, _Psycopg2ShapedError("22003")), id="psycopg2"),
    ],
)
async def test_a_numeric_overflow_is_a_422(client, auth_headers, own_vin, monkeypatch, exc):
    monkeypatch.setattr(SpotRentalService, "list_rentals", _raising(exc))

    response = await client.get(f"/api/vehicles/{own_vin}/spot-rentals", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == TOO_LARGE


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(DataError(STATEMENT, {}, _Psycopg2ShapedError("22001")), id="string-too-long"),
        pytest.param(DBAPIError(STATEMENT, {}, _AsyncpgShapedError("22P02")), id="bad-text"),
        pytest.param(IntegrityError(STATEMENT, {}, _Psycopg2ShapedError("23505")), id="unique"),
        pytest.param(DBAPIError(STATEMENT, {}, Exception("no code at all")), id="no-sqlstate"),
    ],
)
async def test_any_other_database_error_keeps_its_500(
    client, auth_headers, own_vin, monkeypatch, exc, caplog, caplog_only
):
    monkeypatch.setattr(SpotRentalService, "list_rentals", _raising(exc))

    with caplog_only("app.utils.error_handlers"):
        response = await client.get(f"/api/vehicles/{own_vin}/spot-rentals", headers=auth_headers)

    assert response.status_code == 500, response.text
    assert response.json()["message"] == DATABASE_ERROR
    (logged,) = problems(caplog, "app.utils.error_handlers")
    assert logged.getMessage().startswith("Database error")
    assert logged.exc_info is not None
    assert logged.exc_info[1] is exc


async def test_a_real_postgresql_overflow_is_a_422(
    client, auth_headers, own_vin, monkeypatch, db_session
):
    """The driver's own exception, not a stand-in: a money column past its width."""
    if db_session.get_bind().dialect.name == "sqlite":
        pytest.skip("SQLite ignores a column's declared precision; 22003 is PostgreSQL's")

    async def list_rentals(self: SpotRentalService, vin: str, current_user: Any) -> Any:
        await self.db.execute(
            text("UPDATE vehicles SET msrp_total = :amount WHERE vin = :vin"),
            {"amount": Decimal("1e12"), "vin": vin},
        )

    monkeypatch.setattr(SpotRentalService, "list_rentals", list_rentals)

    response = await client.get(f"/api/vehicles/{own_vin}/spot-rentals", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == TOO_LARGE


def _app(*, debug: bool) -> FastAPI:
    """An app registered the way main.py registers its own, with two routes."""
    from app.utils.error_handlers import register_error_handlers

    app = FastAPI(debug=debug)
    register_error_handlers(app, debug=debug)

    @app.get("/overflow")
    async def overflow() -> None:
        raise DBAPIError(STATEMENT, {}, _AsyncpgShapedError("22003"))

    @app.get("/other")
    async def other() -> None:
        raise DataError(STATEMENT, {}, _Psycopg2ShapedError("22001"))

    return app


async def test_debug_mode_maps_the_overflow_too():
    """Debug shows tracebacks for real failures, but an overflow is the client's
    number, so it gets the same 422 there as in production."""
    transport = ASGITransport(app=_app(debug=True))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/overflow")
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == TOO_LARGE

        # Anything else still propagates, as it did with no handler at all.
        with pytest.raises(DataError):
            await client.get("/other")


async def test_production_mode_keeps_the_database_error_500(caplog, caplog_only):
    transport = ASGITransport(app=_app(debug=False))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with caplog_only("app.utils.error_handlers"):
            assert (await client.get("/overflow")).status_code == 422

            response = await client.get("/other")
        assert response.status_code == 500, response.text
        assert response.json()["message"] == DATABASE_ERROR

    overflow, other = problems(caplog, "app.utils.error_handlers")
    assert (overflow.levelno, overflow.exc_info) == (logging.WARNING, None)
    assert other.getMessage().startswith("Database error")
    assert other.exc_info is not None
    assert isinstance(other.exc_info[1], DataError)
