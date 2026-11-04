"""Tires follow the vehicle's wheel layout (#272).

New placements (mount, create-and-mount, rotate, past periods, set fit) are
refused off the layout. What's already stored stays listed and editable, so a
type change never strands a tire (Review Focus 2). The suite shares one
database: every vehicle here gets a unique VIN and is deleted in `finally`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

Headers = dict[str, str]


def _vin() -> str:
    return ("TWL" + uuid.uuid4().hex.upper())[:17]


def _off_layout(position: str, layout: str) -> str:
    return f"{position} isn't a tire position on this vehicle's wheel layout ({layout})."


async def _vehicle(client: AsyncClient, headers: Headers, vehicle_type: str, **extra: Any) -> str:
    vin = _vin()
    body = {"vin": vin, "nickname": f"TWL {vin[-4:]}", "vehicle_type": vehicle_type} | extra
    response = await client.post("/api/vehicles", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return vin


async def _drop(db: AsyncSession, vin: str) -> None:
    await db.rollback()
    await db.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db.commit()


async def _stored(client: AsyncClient, headers: Headers, vin: str, **extra: Any) -> dict:
    response = await client.post(
        f"/api/vehicles/{vin}/tires", headers=headers, json={"vin": vin, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _mounted(client: AsyncClient, headers: Headers, vin: str, position: str) -> dict:
    response = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount",
        headers=headers,
        json={"vin": vin, "position": position, "tread_depth_mm": "8.0"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _mount(client: AsyncClient, headers: Headers, vin: str, tire_id: int, position: str):
    return await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/mount", headers=headers, json={"position": position}
    )


async def _list(client: AsyncClient, headers: Headers, vin: str) -> dict:
    response = await client.get(f"/api/vehicles/{vin}/tires", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _positions_by_id(client: AsyncClient, headers: Headers, vin: str) -> dict[int, Any]:
    return {tire["id"]: tire["position"] for tire in (await _list(client, headers, vin))["tires"]}


async def test_list_carries_layout(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    bike = await _vehicle(client, auth_headers, "Motorcycle")
    car = await _vehicle(client, auth_headers, "Car")
    try:
        listed = await _list(client, auth_headers, bike)
        assert listed["wheel_layout"] == "two"
        assert listed["positions"] == ["F", "R"]
        assert listed["rotates"] is False

        listed = await _list(client, auth_headers, car)
        assert listed["wheel_layout"] == "four"
        assert listed["positions"] == ["FL", "FR", "RL", "RR", "SPARE"]
        assert listed["rotates"] is True
    finally:
        await _drop(db_session, bike)
        await _drop(db_session, car)


async def test_mount_at_f_ok_fl_refused(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        front = await _stored(client, auth_headers, vin)
        ok = await _mount(client, auth_headers, vin, front["id"], "F")
        assert ok.status_code == 200, ok.text
        assert ok.json()["position"] == "F"

        spare = await _stored(client, auth_headers, vin)
        for position in ("FL", "SPARE"):
            refused = await _mount(client, auth_headers, vin, spare["id"], position)
            assert refused.status_code == 422, refused.text
            assert refused.json()["detail"] == _off_layout(position, "two")

        # Create-and-mount refuses too, and leaves no orphan tire behind.
        before = await _list(client, auth_headers, vin)
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={"vin": vin, "position": "RL", "tread_depth_mm": "8.0"},
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("RL", "two")
        assert (await _list(client, auth_headers, vin))["total"] == before["total"]
    finally:
        await _drop(db_session, vin)


async def test_rotate_destination_off_layout_refused(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        front = await _mounted(client, auth_headers, vin, "F")
        rear = await _mounted(client, auth_headers, vin, "R")
        refused = await client.post(
            f"/api/vehicles/{vin}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": front["id"], "position": "R"},
                    {"tire_id": rear["id"], "position": "FL"},
                ]
            },
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("FL", "two")
        assert await _positions_by_id(client, auth_headers, vin) == {
            front["id"]: "F",
            rear["id"]: "R",
        }

        # The same swap inside the layout goes through (D5).
        swapped = await client.post(
            f"/api/vehicles/{vin}/tires/rotate",
            headers=auth_headers,
            json={
                "moves": [
                    {"tire_id": front["id"], "position": "R"},
                    {"tire_id": rear["id"], "position": "F"},
                ]
            },
        )
        assert swapped.status_code == 200, swapped.text
        assert swapped.json()["wheel_layout"] == "two"
    finally:
        await _drop(db_session, vin)


async def test_past_period_off_layout_refused(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        tire = await _stored(client, auth_headers, vin)
        url = f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods"
        period = {"mounted_on": "2026-01-01", "dismounted_on": "2026-02-01"}
        refused = await client.post(url, headers=auth_headers, json={"position": "FL", **period})
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("FL", "two")

        ok = await client.post(url, headers=auth_headers, json={"position": "F", **period})
        assert ok.status_code == 201, ok.text
        assert [p["position"] for p in ok.json()["mount_periods"]] == ["F"]
    finally:
        await _drop(db_session, vin)


async def test_a_missing_or_retired_tire_beats_the_layout_refusal(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    # The tire is looked up first: an off-layout corner on a tire that isn't
    # there is a 404, and on a retired one the usual 409.
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        missing = await _mount(client, auth_headers, vin, 999_999_999, "FL")
        assert missing.status_code == 404, missing.text

        period = {"position": "FL", "mounted_on": "2026-01-01", "dismounted_on": "2026-02-01"}
        missing = await client.post(
            f"/api/vehicles/{vin}/tires/999999999/mount-periods", headers=auth_headers, json=period
        )
        assert missing.status_code == 404, missing.text

        tire = await _stored(client, auth_headers, vin)
        retired = await client.post(
            f"/api/vehicles/{vin}/tires/{tire['id']}/retire", headers=auth_headers, json={}
        )
        assert retired.status_code == 200, retired.text
        refused = await _mount(client, auth_headers, vin, tire["id"], "FL")
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == "This tire is retired."
    finally:
        await _drop(db_session, vin)


async def test_set_mount_with_off_layout_memory_refused(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    # Remembered at FL on the car, and the car becomes a bike (Review Focus 3).
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        made = await client.post(
            f"/api/vehicles/{vin}/tire-sets", headers=auth_headers, json={"name": "Summer"}
        )
        assert made.status_code == 201, made.text
        set_id = made.json()["id"]
        front = await _stored(client, auth_headers, vin, brand="Pirelli")
        rear = await _stored(client, auth_headers, vin, brand="Dunlop")
        for tire in (front, rear):
            joined = await client.put(
                f"/api/vehicles/{vin}/tires/{tire['id']}",
                headers=auth_headers,
                json={"set_id": set_id},
            )
            assert joined.status_code == 200, joined.text
        mounted = await _mount(client, auth_headers, vin, front["id"], "FL")
        assert mounted.status_code == 200, mounted.text
        off = await client.post(
            f"/api/vehicles/{vin}/tires/{front['id']}/dismount", headers=auth_headers, json={}
        )
        assert off.status_code == 200, off.text
        changed = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"vehicle_type": "Motorcycle"}
        )
        assert changed.status_code == 200, changed.text
        # The rear tire's memory is on the layout, so it would fit if anything did.
        past = await client.post(
            f"/api/vehicles/{vin}/tires/{rear['id']}/mount-periods",
            headers=auth_headers,
            json={"position": "R", "mounted_on": "2025-01-01", "dismounted_on": "2025-02-01"},
        )
        assert past.status_code == 201, past.text

        refused = await client.post(
            f"/api/vehicles/{vin}/tire-sets/{set_id}/mount", headers=auth_headers, json={}
        )
        assert refused.status_code == 422, refused.text
        detail = refused.json()["detail"]
        assert "Pirelli" in detail
        assert "FL" in detail
        # All or nothing: the rear tire didn't go on either.
        assert await _positions_by_id(client, auth_headers, vin) == {
            front["id"]: None,
            rear["id"]: None,
        }
    finally:
        await _drop(db_session, vin)


async def test_type_change_keeps_tires_visible(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        tires = {p: await _mounted(client, auth_headers, vin, p) for p in ("FL", "FR", "RL", "RR")}
        changed = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"vehicle_type": "Motorcycle"}
        )
        assert changed.status_code == 200, changed.text

        listed = await _list(client, auth_headers, vin)
        assert listed["wheel_layout"] == "two"
        assert sorted(t["position"] for t in listed["tires"]) == ["FL", "FR", "RL", "RR"]

        fl = tires["FL"]["id"]
        off = await client.post(
            f"/api/vehicles/{vin}/tires/{fl}/dismount", headers=auth_headers, json={}
        )
        assert off.status_code == 200, off.text
        back = await _mount(client, auth_headers, vin, fl, "F")
        assert back.status_code == 200, back.text
        assert back.json()["position"] == "F"
    finally:
        await _drop(db_session, vin)


async def test_off_layout_period_dates_still_editable(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        rr = await client.post(
            f"/api/vehicles/{vin}/tires/create-and-mount",
            headers=auth_headers,
            json={
                "vin": vin,
                "position": "RR",
                "tread_depth_mm": "8.0",
                "mounted_on": "2026-03-01",
            },
        )
        assert rr.status_code == 201, rr.text
        tire = rr.json()
        changed = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"vehicle_type": "Motorcycle"}
        )
        assert changed.status_code == 200, changed.text

        [period] = tire["mount_periods"]
        edited = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}/mount-periods/{period['id']}",
            headers=auth_headers,
            json={"mounted_on": "2026-02-01"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["position"] == "RR"
        assert edited.json()["mount_periods"][0]["mounted_on"] == "2026-02-01"
    finally:
        await _drop(db_session, vin)


async def test_dually_mounts_inner_outer(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Truck", wheel_layout="dually")
    try:
        inner = await _stored(client, auth_headers, vin)
        ok = await _mount(client, auth_headers, vin, inner["id"], "RLI")
        assert ok.status_code == 200, ok.text

        other = await _stored(client, auth_headers, vin)
        refused = await _mount(client, auth_headers, vin, other["id"], "RL")
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("RL", "dually")
    finally:
        await _drop(db_session, vin)


async def test_set_mount_leaves_a_member_already_on_its_corner(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    # A member sitting at FL after the type change isn't being placed, so the
    # fit doesn't refuse over it (Review Focus 2).
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        made = await client.post(
            f"/api/vehicles/{vin}/tire-sets", headers=auth_headers, json={"name": "Summer"}
        )
        assert made.status_code == 201, made.text
        set_id = made.json()["id"]
        tire = await _mounted(client, auth_headers, vin, "FL")
        joined = await client.put(
            f"/api/vehicles/{vin}/tires/{tire['id']}", headers=auth_headers, json={"set_id": set_id}
        )
        assert joined.status_code == 200, joined.text
        changed = await client.put(
            f"/api/vehicles/{vin}", headers=auth_headers, json={"vehicle_type": "Motorcycle"}
        )
        assert changed.status_code == 200, changed.text

        fit = await client.post(
            f"/api/vehicles/{vin}/tire-sets/{set_id}/mount", headers=auth_headers, json={}
        )
        assert fit.status_code == 200, fit.text
        assert await _positions_by_id(client, auth_headers, vin) == {tire["id"]: "FL"}
    finally:
        await _drop(db_session, vin)
