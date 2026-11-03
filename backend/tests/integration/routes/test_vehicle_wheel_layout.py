"""Per-vehicle wheel layout (#272), end to end through the vehicle API.

NULL means "whatever the type usually has", so the response carries the stored
override and the layout it resolves to. The suite shares one database: every
row here is created with a unique VIN and deleted in `finally`.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _vin(prefix: str = "WL") -> str:
    return (prefix + uuid.uuid4().hex.upper())[:17]


async def _create(
    client: AsyncClient, headers: dict[str, str], vin: str, vehicle_type: str, **extra: object
) -> dict:
    body = {"vin": vin, "nickname": f"WL {vin[-4:]}", "vehicle_type": vehicle_type} | extra
    response = await client.post("/api/vehicles", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _put(client: AsyncClient, headers: dict[str, str], vin: str, body: dict) -> dict:
    response = await client.put(f"/api/vehicles/{vin}", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def _drop(db: AsyncSession, vin: str) -> None:
    await db.rollback()
    await db.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db.commit()


async def test_motorcycle_defaults_to_two(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin = _vin()
    try:
        body = await _create(client, auth_headers, vin, "Motorcycle")
        assert body["wheel_layout"] is None
        assert body["effective_wheel_layout"] == "two"
        assert body["default_wheel_layout"] == "two"
        # The read path says the same as the create response.
        read = await client.get(f"/api/vehicles/{vin}", headers=auth_headers)
        assert read.status_code == 200, read.text
        assert read.json()["effective_wheel_layout"] == "two"
    finally:
        await _drop(db_session, vin)


async def test_create_takes_an_override(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin = _vin()
    try:
        body = await _create(client, auth_headers, vin, "Truck", wheel_layout="dually")
        assert body["wheel_layout"] == "dually"
        assert body["effective_wheel_layout"] == "dually"
        assert body["default_wheel_layout"] == "four"
    finally:
        await _drop(db_session, vin)


async def test_override_and_reset(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin = _vin()
    try:
        await _create(client, auth_headers, vin, "Motorcycle")
        put = await _put(client, auth_headers, vin, {"wheel_layout": "trike_2f1r"})
        assert put["wheel_layout"] == "trike_2f1r"
        assert put["effective_wheel_layout"] == "trike_2f1r"
        assert put["default_wheel_layout"] == "two"
        # A partial update that omits the field leaves the override alone.
        other = await _put(client, auth_headers, vin, {"nickname": "x"})
        assert other["wheel_layout"] == "trike_2f1r"
        assert other["effective_wheel_layout"] == "trike_2f1r"
        # Explicit null goes back to automatic.
        reset = await _put(client, auth_headers, vin, {"wheel_layout": None})
        assert reset["wheel_layout"] is None
        assert reset["effective_wheel_layout"] == "two"
        stored = await db_session.scalar(select(Vehicle.wheel_layout).where(Vehicle.vin == vin))
        assert stored is None
    finally:
        await _drop(db_session, vin)


async def test_type_change_follows_when_automatic(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin = _vin()
    try:
        created = await _create(client, auth_headers, vin, "Car")
        assert created["effective_wheel_layout"] == "four"
        moved = await _put(client, auth_headers, vin, {"vehicle_type": "Motorcycle"})
        assert moved["wheel_layout"] is None
        assert moved["effective_wheel_layout"] == "two"
        assert moved["default_wheel_layout"] == "two"
    finally:
        await _drop(db_session, vin)


async def test_type_change_keeps_an_override(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin = _vin()
    try:
        await _create(client, auth_headers, vin, "Car", wheel_layout="four")
        moved = await _put(client, auth_headers, vin, {"vehicle_type": "Boat"})
        assert moved["wheel_layout"] == "four"
        assert moved["effective_wheel_layout"] == "four"
        assert moved["default_wheel_layout"] == "none"
    finally:
        await _drop(db_session, vin)


@pytest.mark.parametrize("bad", ["hovercraft", "FOUR", ""])
async def test_bad_layout_422(
    bad: str, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin, refused_vin = _vin(), _vin()
    try:
        await _create(client, auth_headers, vin, "Car")
        put = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"wheel_layout": bad}
        )
        assert put.status_code == 422, put.text
        post = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": refused_vin,
                "nickname": "Bad",
                "vehicle_type": "Car",
                "wheel_layout": bad,
            },
        )
        assert post.status_code == 422, post.text
    finally:
        await _drop(db_session, vin)
        await _drop(db_session, refused_vin)


async def test_an_unknown_stored_layout_reads_as_the_default(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    # A restore or a downgrade can leave one we don't know: it reads, it doesn't 500.
    vin = _vin()
    try:
        await _create(client, auth_headers, vin, "Motorcycle")
        vehicle = await db_session.get(Vehicle, vin)
        assert vehicle is not None
        vehicle.wheel_layout = "hovercraft"
        await db_session.commit()
        read = await client.get(f"/api/vehicles/{vin}", headers=auth_headers)
        assert read.status_code == 200, read.text
        assert read.json()["wheel_layout"] is None
        assert read.json()["effective_wheel_layout"] == "two"
    finally:
        await _drop(db_session, vin)


async def test_write_share_cannot_change_layout(
    client: AsyncClient,
    owned_vehicle: Vehicle,
    writer_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # Layout is vehicle core metadata, so it's owner-only like the rest of the PUT.
    before = owned_vehicle.wheel_layout
    resp = await client.put(
        f"/api/vehicles/{owned_vehicle.vin}",
        json={"wheel_layout": "trike_1f2r"},
        headers=writer_headers,
    )
    assert resp.status_code == 403, resp.text
    await db_session.refresh(owned_vehicle)
    assert owned_vehicle.wheel_layout == before


async def test_json_export_carries_wheel_layout(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    vin = _vin()
    try:
        await _create(client, auth_headers, vin, "Motorcycle", wheel_layout="trike_1f2r")
        response = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["vehicle"]["wheel_layout"] == "trike_1f2r"
    finally:
        await _drop(db_session, vin)
