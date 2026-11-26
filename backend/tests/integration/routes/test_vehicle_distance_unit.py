"""Per-vehicle distance unit (#172), end to end through the API.

The suite shares one database: every row here is created with a unique VIN and
deleted in `finally`.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminder import Reminder
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Pre-computed argon2id hash for "testpassword123", copied from
# tests/conftest.py: hashing here would need threads these containers do not
# always have.
_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"


def _vin(prefix: str = "DU") -> str:
    return (prefix + uuid.uuid4().hex.upper())[:17]


async def _create(client: AsyncClient, headers: dict[str, str], vin: str, **extra: object) -> dict:
    body = {"vin": vin, "nickname": f"DU {vin[-4:]}", "vehicle_type": "Car"} | extra
    response = await client.post("/api/vehicles", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _drop(db: AsyncSession, vin: str) -> None:
    await db.rollback()
    await db.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db.commit()


class TestVehicleField:
    async def test_new_vehicles_start_on_account_default(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        vin = _vin()
        try:
            assert (await _create(client, auth_headers, vin))["distance_unit"] is None
        finally:
            await _drop(db_session, vin)

    async def test_set_then_clear_with_null(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        vin = _vin()
        try:
            await _create(client, auth_headers, vin)
            put = await client.put(
                f"/api/vehicles/{vin}", headers=auth_headers, json={"distance_unit": "mi"}
            )
            assert put.status_code == 200, put.text
            assert put.json()["distance_unit"] == "mi"
            # A partial update that omits the field leaves it alone.
            other = await client.put(
                f"/api/vehicles/{vin}", headers=auth_headers, json={"nickname": "Renamed"}
            )
            assert other.json()["distance_unit"] == "mi"
            cleared = await client.put(
                f"/api/vehicles/{vin}", headers=auth_headers, json={"distance_unit": None}
            )
            assert cleared.json()["distance_unit"] is None
        finally:
            await _drop(db_session, vin)

    @pytest.mark.parametrize("bad", ["MI", "miles", ""])
    async def test_a_bad_write_token_is_a_422(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        bad: str,
    ) -> None:
        vin = _vin()
        try:
            await _create(client, auth_headers, vin)
            put = await client.put(
                f"/api/vehicles/{vin}", headers=auth_headers, json={"distance_unit": bad}
            )
            assert put.status_code == 422, put.text
        finally:
            await _drop(db_session, vin)

    async def test_a_hand_stored_bad_value_is_served_as_null(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        vin = _vin()
        try:
            await _create(client, auth_headers, vin)
            # Fits VARCHAR(2): PostgreSQL refuses a longer bad token before the
            # response path is ever exercised.
            await db_session.execute(
                update(Vehicle).where(Vehicle.vin == vin).values(distance_unit="MI")
            )
            await db_session.commit()
            db_session.expunge_all()
            got = await client.get(f"/api/vehicles/{vin}", headers=auth_headers)
            assert got.status_code == 200, got.text
            assert got.json()["distance_unit"] is None
        finally:
            await _drop(db_session, vin)


async def _metric_user(db: AsyncSession) -> tuple[User, dict[str, str]]:
    """A dedicated metric admin and its bearer headers.

    Never the shared `testuser`: `PUT /api/auth/me/units` clears or
    materialises all eleven override columns, so "restore imperial" is not a
    restore, and a leaked unit change makes later modules order-dependent.
    Pattern: `test_reports_csv_v6_units.py:_make_preset_user`.
    """
    name = f"du_{uuid.uuid4().hex[:12]}"
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=True,
        unit_preference="metric",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return user, {"Authorization": f"Bearer {token}"}


async def _drop_user(db: AsyncSession, user_id: int) -> None:
    await db.rollback()
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()


class TestSurfaces:
    async def test_odometer_export_follows_the_vehicle_and_an_explicit_preset_wins(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        vin = _vin()
        user, headers = await _metric_user(db_session)
        user_id = user.id
        try:
            await _create(client, headers, vin, distance_unit="mi")
            made = await client.post(
                f"/api/vehicles/{vin}/odometer",
                headers=headers,
                json={"vin": vin, "date": "2026-03-01", "odometer_km": 16093.44},
            )
            assert made.status_code == 201, made.text
            default = await client.get(f"/api/export/vehicles/{vin}/odometer/csv", headers=headers)
            assert default.status_code == 200, default.text
            header, first = default.text.splitlines()[:2]
            assert "(mi)" in header and "(km)" not in header
            # Rows lead with units_version, unit_system (export.py:130-146), and a
            # metric set with distance=mi is the "custom" marker.
            assert first.split(",")[1] == "custom"
            assert first.split(",")[3] == "10000.000"
            explicit = await client.get(
                f"/api/export/vehicles/{vin}/odometer/csv?units=metric", headers=headers
            )
            assert "(km)" in explicit.text.splitlines()[0]
        finally:
            await _drop(db_session, vin)
            await _drop_user(db_session, user_id)

    async def test_service_history_csv_follows_the_vehicle(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        vin = _vin()
        user, headers = await _metric_user(db_session)
        user_id = user.id
        try:
            await _create(client, headers, vin, distance_unit="mi")
            report = await client.get(
                f"/api/vehicles/{vin}/reports/service-history-csv", headers=headers
            )
            assert report.status_code == 200, report.text
            assert "Odometer (mi)" in report.text.splitlines()[0]
        finally:
            await _drop(db_session, vin)
            await _drop_user(db_session, user_id)


class TestMixedPages:
    async def test_every_carrier_serves_the_unit(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        from datetime import date, timedelta

        vin = _vin()
        try:
            await _create(client, auth_headers, vin, distance_unit="mi")
            dash = (await client.get("/api/dashboard", headers=auth_headers)).json()
            card = next(v for v in dash["vehicles"] if v["vin"] == vin)
            assert card["distance_unit"] == "mi"

            qe = (await client.get("/api/quick-entry/vehicles", headers=auth_headers)).json()
            assert next(v for v in qe["vehicles"] if v["vin"] == vin)["distance_unit"] == "mi"

            due = (date.today() + timedelta(days=10)).isoformat()
            made = await client.post(
                f"/api/vehicles/{vin}/reminders",
                headers=auth_headers,
                json={
                    "title": "DU rotation",
                    "reminder_type": "both",
                    "due_date": due,
                    "due_mileage_km": "20000",
                },
            )
            assert made.status_code == 201, made.text
            calendar = (await client.get("/api/calendar", headers=auth_headers)).json()
            event = next(
                e for e in calendar["events"] if e["id"] == f"reminder-{made.json()['id']}"
            )
            assert event["vehicle_distance_unit"] == "mi"
        finally:
            await db_session.rollback()
            await db_session.execute(delete(Reminder).where(Reminder.vin == vin))
            await db_session.commit()
            await _drop(db_session, vin)

    async def test_one_bad_row_does_not_take_down_the_pages(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        vin = _vin()
        try:
            await _create(client, auth_headers, vin)
            # "MI" fits VARCHAR(2): PostgreSQL refuses "miles" before the
            # response path is exercised.
            await db_session.execute(
                update(Vehicle).where(Vehicle.vin == vin).values(distance_unit="MI")
            )
            await db_session.commit()
            db_session.expunge_all()
            for path in (
                "/api/dashboard",
                "/api/quick-entry/vehicles",
                "/api/calendar",
                f"/api/vehicles/{vin}",
                "/api/vehicles",
                f"/api/analytics/vehicles/{vin}",
            ):
                response = await client.get(path, headers=auth_headers)
                assert response.status_code == 200, (path, response.text)
            dash = (await client.get("/api/dashboard", headers=auth_headers)).json()
            assert next(v for v in dash["vehicles"] if v["vin"] == vin)["distance_unit"] is None
            analytics = (
                await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
            ).json()
            assert analytics["distance_unit"] is None
        finally:
            await _drop(db_session, vin)
