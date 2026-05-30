"""Negative-authz tests for Phase 2 of the v2.28.0 hardening.

Covers Group A (vehicle core = OWNER), Group B (child writes = write-share),
and Group D device-ownership. Matrix fixtures live in ``conftest.py``.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# --- Group A: vehicle core = OWNER -------------------------------------------


class TestVehicleMetadataOwnerOnly:
    async def test_read_share_cannot_edit(self, client, owned_vehicle, reader_headers):
        resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}",
            json={"nickname": "Hacked"},
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_write_share_cannot_edit(self, client, owned_vehicle, writer_headers):
        # D-2: editing identity metadata is owner-only; a write-share must not.
        resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}",
            json={"nickname": "Hacked"},
            headers=writer_headers,
        )
        assert resp.status_code == 403

    async def test_owner_can_edit(self, client, owned_vehicle, owner_headers):
        resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}",
            json={"nickname": "Renamed"},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["nickname"] == "Renamed"


class TestArchiveOwnerOnly:
    def _payload(self) -> dict:
        return {"reason": "Sold", "visible": True}

    async def test_read_share_cannot_archive(self, client, owned_vehicle, reader_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/archive",
            json=self._payload(),
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_write_share_cannot_archive(self, client, owned_vehicle, writer_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/archive",
            json=self._payload(),
            headers=writer_headers,
        )
        assert resp.status_code == 403

    async def test_owner_can_archive(self, client, owned_vehicle, owner_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/archive",
            json=self._payload(),
            headers=owner_headers,
        )
        assert resp.status_code == 200

    async def test_no_token_local_mode_unauthorized(self, client, owned_vehicle):
        # optional_auth -> require_auth: a no-token request in local mode now 401s
        # instead of falling through the none-mode branch (fail-open closed).
        resp = await client.post(f"/api/vehicles/{owned_vehicle.vin}/archive", json=self._payload())
        assert resp.status_code == 401


class TestVisibilityOwnerOnly:
    async def test_read_share_cannot_toggle(self, client, owned_vehicle, reader_headers):
        resp = await client.patch(
            f"/api/vehicles/{owned_vehicle.vin}/archive/visibility?visible=false",
            headers=reader_headers,
        )
        assert resp.status_code == 403


class TestWindowStickerOwnerOnly:
    async def test_read_share_cannot_edit_data(self, client, owned_vehicle, reader_headers):
        resp = await client.patch(
            f"/api/vehicles/{owned_vehicle.vin}/window-sticker/data",
            json={"msrp_total": "12345.00"},
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_write_share_cannot_edit_data(self, client, owned_vehicle, writer_headers):
        # D-8: window-sticker mutates the vehicle row -> OWNER-only, write-share 403.
        resp = await client.patch(
            f"/api/vehicles/{owned_vehicle.vin}/window-sticker/data",
            json={"msrp_total": "12345.00"},
            headers=writer_headers,
        )
        assert resp.status_code == 403

    async def test_owner_can_edit_data(self, client, owned_vehicle, owner_headers):
        resp = await client.patch(
            f"/api/vehicles/{owned_vehicle.vin}/window-sticker/data",
            json={"msrp_total": "12345.00"},
            headers=owner_headers,
        )
        assert resp.status_code == 200

    async def test_write_share_cannot_delete(self, client, owned_vehicle, writer_headers):
        resp = await client.delete(
            f"/api/vehicles/{owned_vehicle.vin}/window-sticker", headers=writer_headers
        )
        assert resp.status_code == 403


# --- Group B: child writes = write-share -------------------------------------


class TestTrailerChildWrite:
    async def test_read_share_cannot_create(self, client, owned_vehicle, reader_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/trailer",
            json={"vin": owned_vehicle.vin},
            headers=reader_headers,
        )
        assert resp.status_code == 403

    async def test_write_share_can_create(self, client, owned_vehicle, writer_headers):
        resp = await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/trailer",
            json={"vin": owned_vehicle.vin},
            headers=writer_headers,
        )
        assert resp.status_code == 201

    async def test_write_share_can_update(self, client, owned_vehicle, writer_headers):
        # Ensure trailer exists, then update as the write-share.
        await client.post(
            f"/api/vehicles/{owned_vehicle.vin}/trailer",
            json={"vin": owned_vehicle.vin},
            headers=writer_headers,
        )
        resp = await client.put(
            f"/api/vehicles/{owned_vehicle.vin}/trailer",
            json={"hitch_type": "Ball"},
            headers=writer_headers,
        )
        assert resp.status_code == 200


# --- Group D: device-ownership -----------------------------------------------

DEVICE_ID = "authzdev01"


@pytest_asyncio.fixture
async def owned_device(db_session: AsyncSession, owned_vehicle: Vehicle) -> LiveLinkDevice:
    from sqlalchemy import select

    result = await db_session.execute(
        select(LiveLinkDevice).where(LiveLinkDevice.device_id == DEVICE_ID)
    )
    device = result.scalar_one_or_none()
    if device is None:
        device = LiveLinkDevice(device_id=DEVICE_ID, vin=owned_vehicle.vin)
        db_session.add(device)
    else:
        device.vin = owned_vehicle.vin
    await db_session.commit()
    await db_session.refresh(device)
    return device


@pytest_asyncio.fixture
async def unrelated_vehicle(db_session: AsyncSession, unrelated_user: User) -> Vehicle:
    from sqlalchemy import select

    vin = "WP0ZZZ99ZTS000002"
    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        vehicle = Vehicle(
            vin=vin,
            user_id=unrelated_user.id,
            nickname="Unrelated",
            vehicle_type="Car",
            year=2012,
            make="Porsche",
            model="911",
        )
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)
    return vehicle


class TestDeviceOwnership:
    async def test_non_owner_cannot_view_device(self, client, owned_device, unrelated_headers):
        resp = await client.get(
            f"/api/livelink/devices/{owned_device.device_id}", headers=unrelated_headers
        )
        assert resp.status_code == 403

    async def test_non_owner_cannot_command_device(self, client, owned_device, unrelated_headers):
        resp = await client.post(
            f"/api/livelink/devices/{owned_device.device_id}/command",
            json={"command": "get_vbatt"},
            headers=unrelated_headers,
        )
        assert resp.status_code == 403

    async def test_owner_can_view_device(self, client, owned_device, owner_headers):
        resp = await client.get(
            f"/api/livelink/devices/{owned_device.device_id}", headers=owner_headers
        )
        assert resp.status_code == 200

    async def test_relink_to_unowned_target_forbidden(
        self, client, owned_device, unrelated_vehicle, owner_headers
    ):
        # D-5 both-VIN check: owner of the current vehicle still cannot relink the
        # device onto a vehicle they do not own.
        resp = await client.put(
            f"/api/livelink/devices/{owned_device.device_id}",
            json={"vin": unrelated_vehicle.vin},
            headers=owner_headers,
        )
        assert resp.status_code == 403
