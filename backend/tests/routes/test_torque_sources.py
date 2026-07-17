"""Route tests for Task 13: owner-scoped Torque source registration on
``app/routes/livelink_vehicle.py`` (prefix ``/api/vehicles/{vin}/livelink``).

Covers:
- POST   .../torque-sources             -> create, returns {device_id, label,
  upload_url, token} (token shown once); upload_url ends in
  `/api/v1/torque/<token>/upload`.
- GET    .../torque-sources             -> list of THIS vin's torque sources,
  no token in the response.
- DELETE .../torque-sources/{device_id} -> revoke; scoped to vin AND
  kind == 'torque' (R1-H5): an owner of VIN-A must not be able to delete
  VIN-B's device by supplying B's device_id.
- Owner-gated via get_vehicle_for_owner_or_403: a write-share (non-owner)
  gets 403 on create.

Fixtures: ``client`` / ``db_session`` from tests/conftest.py (base conftest).
Non-admin users are created locally (mirrors test_trips_read.py /
test_torque_ingest.py) so JWT auth actually enforces vehicle-access
permissions -- the base conftest's ``test_user`` is an admin, which bypasses
the checks these tests exist to prove.
"""

import itertools

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.services.auth import create_access_token

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


async def _make_owned_vehicle(db_session: AsyncSession) -> tuple[str, dict[str, str]]:
    """Create a non-admin owner user + vehicle, return (vin, owner_headers)."""
    n = next(_SEQ)
    owner = User(
        username=f"torque_src_owner_{n}",
        email=f"torque_src_owner_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(owner)
    await db_session.flush()

    vin = f"TORQSRCTEST{n:06d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=owner.id,
        nickname=f"Torque Source Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.commit()

    return vin, _headers(owner)


async def _make_vehicle_with_write_share(
    db_session: AsyncSession,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Create an owner + vehicle + a write-share user.

    Returns (vin, owner_headers, write_share_headers).
    """
    n = next(_SEQ)
    owner = User(
        username=f"torque_src_share_owner_{n}",
        email=f"torque_src_share_owner_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    writer = User(
        username=f"torque_src_writer_{n}",
        email=f"torque_src_writer_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add_all([owner, writer])
    await db_session.flush()

    vin = f"TORQSRCSHR{n:07d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=owner.id,
        nickname=f"Torque Source Share Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()

    db_session.add(
        VehicleShare(vehicle_vin=vin, user_id=writer.id, permission="write", shared_by=owner.id)
    )
    await db_session.commit()

    return vin, _headers(owner), _headers(writer)


@pytest.mark.asyncio
async def test_create_torque_source_returns_token_and_upload_url(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /torque-sources: 200, body has device_id/label/upload_url/token;
    upload_url ends with /api/v1/torque/<token>/upload."""
    vin, owner_headers = await _make_owned_vehicle(db_session)

    r = await client.post(
        f"/api/vehicles/{vin}/livelink/torque-sources",
        json={"label": "My Torque Phone"},
        headers=owner_headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert body["device_id"].startswith("tq_")
    assert body["label"] == "My Torque Phone"
    assert body["token"]
    assert body["upload_url"].endswith(f"/api/v1/torque/{body['token']}/upload")

    result = await db_session.execute(
        select(LiveLinkDevice).where(LiveLinkDevice.device_id == body["device_id"])
    )
    device = result.scalar_one()
    assert device.vin == vin
    assert device.kind == "torque"


@pytest.mark.asyncio
async def test_create_torque_source_without_label_uses_default(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /torque-sources: label is optional."""
    vin, owner_headers = await _make_owned_vehicle(db_session)

    r = await client.post(
        f"/api/vehicles/{vin}/livelink/torque-sources",
        json={},
        headers=owner_headers,
    )

    assert r.status_code == 200
    body = r.json()
    assert body["label"]  # falls back to a default ("Torque Pro")


@pytest.mark.asyncio
async def test_list_torque_sources_returns_only_this_vins_sources_no_token(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /torque-sources: only this vin's torque sources, and no token field."""
    vin_a, owner_headers_a = await _make_owned_vehicle(db_session)
    vin_b, owner_headers_b = await _make_owned_vehicle(db_session)
    _ = owner_headers_b

    create_r = await client.post(
        f"/api/vehicles/{vin_a}/livelink/torque-sources",
        json={"label": "Source A"},
        headers=owner_headers_a,
    )
    assert create_r.status_code == 200
    device_id_a = create_r.json()["device_id"]

    await client.post(
        f"/api/vehicles/{vin_b}/livelink/torque-sources",
        json={"label": "Source B"},
        headers=owner_headers_b,
    )

    r = await client.get(f"/api/vehicles/{vin_a}/livelink/torque-sources", headers=owner_headers_a)

    assert r.status_code == 200
    body = r.json()
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["device_id"] == device_id_a
    assert source["label"] == "Source A"
    assert "token" not in source


@pytest.mark.asyncio
async def test_delete_torque_source_removes_own_device(
    client: AsyncClient, db_session: AsyncSession
):
    """DELETE /torque-sources/{device_id}: 204, device row removed."""
    vin, owner_headers = await _make_owned_vehicle(db_session)
    create_r = await client.post(
        f"/api/vehicles/{vin}/livelink/torque-sources",
        json={},
        headers=owner_headers,
    )
    device_id = create_r.json()["device_id"]

    r = await client.delete(
        f"/api/vehicles/{vin}/livelink/torque-sources/{device_id}", headers=owner_headers
    )

    assert r.status_code == 204

    result = await db_session.execute(
        select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_torque_source_cross_vin_is_404_and_does_not_delete(
    client: AsyncClient, db_session: AsyncSession
):
    """R1-H5: owner of VIN-A calling DELETE .../{vinA}/.../torque-sources/{device_id-of-VIN-B}
    gets 404, and VIN-B's device still exists afterward."""
    vin_a, owner_headers_a = await _make_owned_vehicle(db_session)
    vin_b, owner_headers_b = await _make_owned_vehicle(db_session)

    create_r_b = await client.post(
        f"/api/vehicles/{vin_b}/livelink/torque-sources",
        json={"label": "Source B"},
        headers=owner_headers_b,
    )
    device_id_b = create_r_b.json()["device_id"]

    r = await client.delete(
        f"/api/vehicles/{vin_a}/livelink/torque-sources/{device_id_b}", headers=owner_headers_a
    )

    assert r.status_code == 404

    result = await db_session.execute(
        select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id_b)
    )
    still_there = result.scalar_one_or_none()
    assert still_there is not None
    assert still_there.vin == vin_b


@pytest.mark.asyncio
async def test_create_torque_source_forbidden_for_write_share_non_owner(
    client: AsyncClient, db_session: AsyncSession
):
    """POST /torque-sources: a write-share (non-owner) user gets 403 -- proves
    the OWNER gate (get_vehicle_for_owner_or_403), not the write-share gate,
    is enforced."""
    vin, _owner_headers, write_headers = await _make_vehicle_with_write_share(db_session)

    r = await client.post(
        f"/api/vehicles/{vin}/livelink/torque-sources",
        json={"label": "Should Not Work"},
        headers=write_headers,
    )

    assert r.status_code == 403
