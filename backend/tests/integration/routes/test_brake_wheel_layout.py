"""Brakes follow the vehicle's wheel layout (#272).

The overview lists the layout's corners, then any off-layout corner that still
has history. New measurements and jobs are refused off the layout; what's
stored stays editable and keeps driving the axle reminder (Review Focus 2).
The suite shares one database: every vehicle here gets a unique VIN and is
deleted in `finally`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brake import BrakeMeasurement
from app.models.reminder import Reminder
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

Headers = dict[str, str]


def _vin() -> str:
    return ("BWL" + uuid.uuid4().hex.upper())[:17]


def _off_layout(position: str, layout: str) -> str:
    return f"{position} isn't a brake position on this vehicle's wheel layout ({layout})."


async def _vehicle(client: AsyncClient, headers: Headers, vehicle_type: str) -> str:
    vin = _vin()
    body = {"vin": vin, "nickname": f"BWL {vin[-4:]}", "vehicle_type": vehicle_type}
    response = await client.post("/api/vehicles", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return vin


async def _drop(db: AsyncSession, vin: str) -> None:
    await db.rollback()
    await db.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db.commit()


async def _retype(client: AsyncClient, headers: Headers, vin: str, vehicle_type: str) -> None:
    changed = await client.put(
        f"/api/vehicles/{vin}", headers=headers, json={"vehicle_type": vehicle_type}
    )
    assert changed.status_code == 200, changed.text


async def _overview(client: AsyncClient, headers: Headers, vin: str) -> dict[str, Any]:
    response = await client.get(f"/api/vehicles/{vin}/brakes", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _log(
    client: AsyncClient, headers: Headers, vin: str, position: str, inner_pad_mm: str
) -> Response:
    return await client.post(
        f"/api/vehicles/{vin}/brakes/measurements",
        headers=headers,
        json={
            "recorded_at": "2026-09-01",
            "corners": [{"position": position, "inner_pad_mm": inner_pad_mm}],
        },
    )


async def _job(client: AsyncClient, headers: Headers, vin: str, position: str) -> Response:
    return await client.post(
        f"/api/vehicles/{vin}/brakes/jobs",
        headers=headers,
        json={
            "performed_on": "2026-09-10",
            "friction_replaced": True,
            "corners": [{"position": position, "new_thickness_mm": "10"}],
        },
    )


def _corner(body: dict[str, Any], position: str) -> dict[str, Any]:
    return next(c for c in body["corners"] if c["position"] == position)


async def _pending_front(db: AsyncSession, vin: str) -> list[Reminder]:
    db.expire_all()
    rows = await db.execute(
        select(Reminder).where(
            Reminder.vin == vin,
            Reminder.source == "low_brakes_front",
            Reminder.status == "pending",
        )
    )
    return list(rows.scalars().all())


async def test_two_wheel_overview(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        body = await _overview(client, auth_headers, vin)
        assert body["wheel_layout"] == "two"
        assert [c["position"] for c in body["corners"]] == ["F", "R"]
        assert [c["on_layout"] for c in body["corners"]] == [True, True]
        assert [c["axle"] for c in body["corners"]] == ["front", "rear"]
    finally:
        await _drop(db_session, vin)


async def test_four_wheel_overview_unchanged(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        body = await _overview(client, auth_headers, vin)
        assert body["wheel_layout"] == "four"
        assert [c["position"] for c in body["corners"]] == ["FL", "FR", "RL", "RR"]
        assert all(c["on_layout"] for c in body["corners"])
    finally:
        await _drop(db_session, vin)


async def test_log_at_fl_refused_on_bike(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        refused = await _log(client, auth_headers, vin, "FL", "6")
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("FL", "two")
        # Nothing written: FL doesn't turn up as an off-layout corner with data.
        assert [c["position"] for c in (await _overview(client, auth_headers, vin))["corners"]] == [
            "F",
            "R",
        ]

        ok = await _log(client, auth_headers, vin, "F", "6")
        assert ok.status_code == 201, ok.text
        front = _corner(ok.json(), "F")
        assert Decimal(front["inner_pad_mm"]) == Decimal("6.00")
        assert len(front["measurements"]) == 1
    finally:
        await _drop(db_session, vin)


async def test_job_at_f(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Motorcycle")
    try:
        refused = await _job(client, auth_headers, vin, "FR")
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("FR", "two")

        made = await _job(client, auth_headers, vin, "F")
        assert made.status_code == 201, made.text
        body = await _overview(client, auth_headers, vin)
        assert [c["position"] for c in body["corners"]] == ["F", "R"]
        front, rear = _corner(body, "F"), _corner(body, "R")
        assert len(front["jobs"]) == 1
        assert front["last_job"]["position"] == "F"
        assert Decimal(front["thinnest_mm"]) == Decimal("10.00")
        assert rear["jobs"] == []
    finally:
        await _drop(db_session, vin)


async def test_off_layout_corner_with_data_listed(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        logged = await _log(client, auth_headers, vin, "FL", "6")
        assert logged.status_code == 201, logged.text
        measurement_id = _corner(logged.json(), "FL")["measurements"][0]["id"]
        await _retype(client, auth_headers, vin, "Motorcycle")

        body = await _overview(client, auth_headers, vin)
        assert body["wheel_layout"] == "two"
        assert [c["position"] for c in body["corners"]] == ["F", "R", "FL"]
        assert [c["on_layout"] for c in body["corners"]] == [True, True, False]
        assert _corner(body, "FL")["axle"] == "front"

        # Old rows stay editable; only new placements are held to the layout.
        edited = await client.put(
            f"/api/vehicles/{vin}/brakes/measurements/{measurement_id}",
            headers=auth_headers,
            json={"inner_pad_mm": "5.5"},
        )
        assert edited.status_code == 200, edited.text
        assert Decimal(_corner(edited.json(), "FL")["inner_pad_mm"]) == Decimal("5.50")

        deleted = await client.delete(
            f"/api/vehicles/{vin}/brakes/measurements/{measurement_id}", headers=auth_headers
        )
        assert deleted.status_code == 204, deleted.text
        # No data left, so the off-layout corner goes away.
        body = await _overview(client, auth_headers, vin)
        assert [c["position"] for c in body["corners"]] == ["F", "R"]
    finally:
        await _drop(db_session, vin)


async def test_off_layout_corners_follow_vocabulary_order(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        # Logged rear first, so the order can't just be insertion order.
        for position in ("RR", "FR"):
            logged = await _log(client, auth_headers, vin, position, "7")
            assert logged.status_code == 201, logged.text
        await _retype(client, auth_headers, vin, "Motorcycle")
        body = await _overview(client, auth_headers, vin)
        assert [c["position"] for c in body["corners"]] == ["F", "R", "FR", "RR"]
        assert [c["axle"] for c in body["corners"]] == ["front", "rear", "front", "rear"]
    finally:
        await _drop(db_session, vin)


async def test_off_layout_low_corner_still_reminds(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Car")
    try:
        # History from before the type change, written straight in (an import
        # would do the same), so no reminder exists yet.
        db_session.add(
            BrakeMeasurement(
                vin=vin,
                position="FL",
                recorded_at=dt.date(2026, 9, 1),
                inner_pad_mm=Decimal("2.80"),
            )
        )
        await db_session.commit()
        await _retype(client, auth_headers, vin, "Motorcycle")
        assert await _pending_front(db_session, vin) == []

        # A healthy F check is front-axle news; the low FL still holds the axle LOW.
        logged = await _log(client, auth_headers, vin, "F", "9.5")
        assert logged.status_code == 201, logged.text
        assert _corner(logged.json(), "FL")["condition"] == "replace_now"
        pending = await _pending_front(db_session, vin)
        assert [r.title for r in pending] == ["Front brake pads low"]

        # And another healthy F doesn't complete it while FL is still low.
        again = await _log(client, auth_headers, vin, "F", "9.4")
        assert again.status_code == 201, again.text
        assert [r.id for r in await _pending_front(db_session, vin)] == [pending[0].id]
    finally:
        await _drop(db_session, vin)


async def test_none_layout_overview_empty(
    client: AsyncClient, auth_headers: Headers, db_session: AsyncSession
) -> None:
    vin = await _vehicle(client, auth_headers, "Boat")
    try:
        body = await _overview(client, auth_headers, vin)
        assert body["wheel_layout"] == "none"
        assert body["corners"] == []

        refused = await _log(client, auth_headers, vin, "F", "6")
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == _off_layout("F", "none")
    finally:
        await _drop(db_session, vin)
