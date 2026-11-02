"""The toll CSV carries bare amounts and names its currency in the header.

A CSV is for machines, so a "$12.34" cell was wrong twice: the "$" breaks a
numeric column, and it was a "$" for every user whatever their currency. The
amount is now a bare number and the header says which currency it is in.

Tests share one database, so the user, vehicle and settings this module
touches are its own and are put back in `finally`.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.models.toll import TollTransaction
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Copied from tests/conftest.py: hashing here would need threads these
# containers don't always have.
_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

_COLUMNS_AFTER_AMOUNT = [
    "Location",
    "Toll System",
    "Tag Number",
    "Notes",
    "Vehicle",
    "VIN",
    "Identifier",
]


async def _set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    """Upsert (or delete, for `value=None`) one settings row."""
    existing = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if value is None:
        if existing is not None:
            await db.delete(existing)
    elif existing is None:
        db.add(Setting(key=key, value=value))
    else:
        existing.value = value
    await db.commit()


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    """The stored value of one settings row, or None when it isn't set."""
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return row.value if row is not None else None


async def _seed(db: AsyncSession, currency_code: str) -> tuple[int, str, str]:
    """A user in `currency_code`, one vehicle and one forint-sized toll.

    Returns plain values (user id, username, VIN): an ORM row expires on every
    commit, and reading it back later would need IO the test can't do there.
    """
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"tollcsv_{suffix}",
        email=f"tollcsv_{suffix}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=False,
        currency_code=currency_code,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    user_id, username = user.id, user.username

    vin = "TOLLCSV" + uuid.uuid4().hex[:10].upper()
    db.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname="Toll CSV",
            vehicle_type="Car",
            year=2019,
            make="Skoda",
            model="Octavia",
        )
    )
    await db.commit()
    db.add(
        TollTransaction(
            vin=vin,
            date=date(2026, 3, 4),
            amount=Decimal("12500.50"),
            location="M1 Motorway",
        )
    )
    await db.commit()
    return user_id, username, vin


async def _cleanup(db: AsyncSession, user_id: int | None, vin: str | None) -> None:
    """Remove what `_seed` made, child rows first."""
    await db.rollback()
    if vin is not None:
        await db.execute(delete(TollTransaction).where(TollTransaction.vin == vin))
        await db.execute(delete(Vehicle).where(Vehicle.vin == vin))
    if user_id is not None:
        await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


async def test_the_amount_is_bare_and_the_header_names_the_users_currency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user_id: int | None = None
    vin: str | None = None
    try:
        user_id, username, vin = await _seed(db_session, "HUF")
        token = create_access_token(data={"sub": str(user_id), "username": username})

        response = await client.get(
            f"/api/vehicles/{vin}/toll-transactions/export/csv",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.text
        header, *data = _rows(response.text)
        assert header == ["Date", "Amount (HUF)", *_COLUMNS_AFTER_AMOUNT]
        assert len(data) == 1
        assert data[0][:3] == ["2026-03-04", "12500.50", "M1 Motorway"]
        # The currency moved into the header, it didn't grow its own column;
        # the ninth is the identifier of a vehicle without a VIN (#226).
        assert len(data[0]) == len(header) == 9
        assert "$" not in response.text
    finally:
        await _cleanup(db_session, user_id, vin)


async def test_with_auth_off_the_header_uses_the_pdf_reports_default_currency(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """No caller means no currency to read, so it falls back the same way the
    PDF report routes do."""
    user_id: int | None = None
    vin: str | None = None
    previous_mode = await _get_setting(db_session, "auth_mode")
    try:
        user_id, _username, vin = await _seed(db_session, "HUF")
        await _set_setting(db_session, "auth_mode", "none")

        # No Authorization header at all: `require_auth` returns None.
        response = await client.get(f"/api/vehicles/{vin}/toll-transactions/export/csv")

        assert response.status_code == 200, response.text
        header, *data = _rows(response.text)
        assert header == ["Date", "Amount (USD)", *_COLUMNS_AFTER_AMOUNT]
        assert data[0][1] == "12500.50"
        assert "$" not in response.text
    finally:
        await _cleanup(db_session, user_id, vin)
        await _set_setting(db_session, "auth_mode", previous_mode)
