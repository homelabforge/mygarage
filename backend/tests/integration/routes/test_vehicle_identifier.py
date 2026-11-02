"""Vehicles without a VIN (#226), end to end through the API.

A tractor or a mower is created with a serial / HIN / chassis number / asset
tag (or nothing), the server keys it with a generated "Q" key, and the key is
never a VIN. The suite shares one database: every row here is deleted in
`finally`.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.utils.vehicle_key import is_synthetic_key
from app.utils.vin import validate_vin

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _vin() -> str:
    return ("WD" + uuid.uuid4().hex.upper())[:17]


async def _drop(db: AsyncSession, *keys: str) -> None:
    await db.rollback()
    await db.execute(delete(Vehicle).where(Vehicle.vin.in_(keys)))
    await db.commit()


async def _post(client: AsyncClient, headers: dict[str, str], **body: object):
    return await client.post(
        "/api/vehicles",
        headers=headers,
        json={"nickname": "Kubota", "vehicle_type": "Tractor"} | body,
    )


class TestCreate:
    async def test_a_serial_numbered_tractor_gets_a_q_key(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        response = await _post(
            client, auth_headers, identifier_type="serial", identifier="  BX23S-10234 "
        )
        assert response.status_code == 201, response.text
        body = response.json()
        try:
            assert is_synthetic_key(body["vin"])
            assert validate_vin(body["vin"])[0] is False
            assert body["identifier_type"] == "serial"
            assert body["identifier"] == "BX23S-10234"
            assert body["has_vin"] is False
            fetched = await client.get(f"/api/vehicles/{body['vin']}", headers=auth_headers)
            assert fetched.status_code == 200
            assert fetched.json()["identifier"] == "BX23S-10234"
        finally:
            await _drop(db_session, body["vin"])

    async def test_an_attachment_with_no_identifier_at_all(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        response = await _post(
            client,
            auth_headers,
            nickname="Kombi head",
            vehicle_type="Attachment",
            identifier_type="none",
        )
        assert response.status_code == 201, response.text
        body = response.json()
        try:
            assert body["identifier"] is None
            assert body["has_vin"] is False
        finally:
            await _drop(db_session, body["vin"])

    async def test_a_vin_vehicle_still_reads_as_one(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        vin = _vin()
        response = await _post(client, auth_headers, vin=vin, vehicle_type="Car")
        try:
            assert response.status_code == 201, response.text
            assert response.json()["identifier_type"] == "vin"
            assert response.json()["has_vin"] is True
        finally:
            await _drop(db_session, vin)

    @pytest.mark.parametrize(
        "body",
        [
            {"identifier_type": "serial", "identifier": "X1", "vin": "1HGCM82633A004352"},
            {"identifier_type": "serial"},
            {"identifier_type": "serial", "identifier": "   "},
            {"identifier_type": "none", "identifier": "X1"},
            {"identifier_type": "vin"},
            {"identifier_type": "vin", "vin": "1HGCM82633A004352", "identifier": "X1"},
            {"identifier_type": "serial", "identifier": "X" * 65},
            {"identifier_type": "barcode", "identifier": "X1"},
            {"vin": "QABCDEFGH12345678"},
        ],
    )
    async def test_identity_that_does_not_match_its_type_is_refused(
        self, client: AsyncClient, auth_headers: dict[str, str], body: dict[str, object]
    ) -> None:
        response = await _post(client, auth_headers, **body)
        assert response.status_code == 422, response.text


class TestUpdate:
    async def test_a_generated_vin_can_become_the_real_serial(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        # seanauff's workaround: the tractor went in with a generated VIN.
        vin = _vin()
        assert (await _post(client, auth_headers, vin=vin)).status_code == 201
        try:
            response = await client.put(
                f"/api/vehicles/{vin}",
                headers=auth_headers,
                json={"identifier_type": "serial", "identifier": "BX23S-10234"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["vin"] == vin
            assert response.json()["has_vin"] is False
            # ...and back, because its key really is VIN-shaped.
            back = await client.put(
                f"/api/vehicles/{vin}", headers=auth_headers, json={"identifier_type": "vin"}
            )
            assert back.status_code == 200, back.text
            assert back.json()["has_vin"] is True
            assert back.json()["identifier"] is None
        finally:
            await _drop(db_session, vin)

    async def test_a_q_keyed_vehicle_cannot_claim_a_vin(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        created = (
            await _post(client, auth_headers, identifier_type="serial", identifier="S1")
        ).json()
        key = created["vin"]
        try:
            response = await client.put(
                f"/api/vehicles/{key}", headers=auth_headers, json={"identifier_type": "vin"}
            )
            assert response.status_code == 422, response.text
            stored = (await client.get(f"/api/vehicles/{key}", headers=auth_headers)).json()
            assert stored["identifier_type"] == "serial"
        finally:
            await _drop(db_session, key)

    async def test_switching_to_a_typed_identifier_needs_a_value(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        created = (await _post(client, auth_headers, identifier_type="none")).json()
        key = created["vin"]
        try:
            refused = await client.put(
                f"/api/vehicles/{key}", headers=auth_headers, json={"identifier_type": "hin"}
            )
            assert refused.status_code == 422, refused.text
            ok = await client.put(
                f"/api/vehicles/{key}",
                headers=auth_headers,
                json={"identifier_type": "hin", "identifier": "ABC12345D404"},
            )
            assert ok.status_code == 200, ok.text
            cleared = await client.put(
                f"/api/vehicles/{key}", headers=auth_headers, json={"identifier": None}
            )
            assert cleared.status_code == 422, cleared.text
            to_none = await client.put(
                f"/api/vehicles/{key}", headers=auth_headers, json={"identifier_type": "none"}
            )
            assert to_none.status_code == 200, to_none.text
            assert to_none.json()["identifier"] is None
        finally:
            await _drop(db_session, key)


class TestPhotoRoutesTakeAQKey:
    async def test_photo_routes_do_not_400_a_q_key(
        self, client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
    ) -> None:
        created = (
            await _post(client, auth_headers, identifier_type="serial", identifier="S2")
        ).json()
        key = created["vin"]
        try:
            for path in (
                f"/api/vehicles/{key}/photos/nope.jpg",
                f"/api/vehicles/{key}/photos/nope.jpg/thumbnail",
            ):
                response = await client.get(path, headers=auth_headers)
                assert response.status_code != 400, (path, response.text)
        finally:
            await _drop(db_session, key)

    async def test_photo_routes_still_refuse_a_traversal_key(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/api/vehicles/..%2F..%2Fetc/photos/x.jpg", headers=auth_headers
        )
        assert response.status_code in (400, 404)


class TestFilesForAVehicleWithoutAVin:
    """A tractor's downloads and uploads never lean on its generated key."""

    async def test_a_window_sticker_upload_is_409(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        keep_rows,
    ) -> None:
        """FB-6: a window sticker belongs to a VIN."""
        from app.services.settings_service import SettingsService

        await keep_rows("window_sticker_enabled")
        await SettingsService.set(db_session, "window_sticker_enabled", "true")
        await db_session.commit()
        key = (await _post(client, auth_headers, identifier_type="serial", identifier="S3")).json()[
            "vin"
        ]
        try:
            response = await client.post(
                f"/api/vehicles/{key}/window-sticker/upload",
                headers=auth_headers,
                files={"file": ("sticker.pdf", b"%PDF-1.4 sticker", "application/pdf")},
            )
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == "Window stickers need a vehicle with a VIN"
            row = await db_session.get(Vehicle, key)
            await db_session.refresh(row)
            assert row is not None and row.window_sticker_file_path is None
        finally:
            await _drop(db_session, key)

    @pytest.mark.parametrize(
        "path",
        [
            "toll-transactions/export/csv",
            "livelink/export/telemetry?start=2026-01-01T00:00:00&end=2026-01-02T00:00:00",
            "livelink/export/telemetry?start=2026-01-01T00:00:00&end=2026-01-02T00:00:00&format=json",
            "livelink/export/sessions",
            "livelink/export/sessions?format=json",
        ],
    )
    async def test_an_export_is_named_by_the_identifier(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        path: str,
    ) -> None:
        """FB-4: the filename carries the serial, never the Q key."""
        key = (
            await _post(client, auth_headers, identifier_type="serial", identifier="BX23S-77")
        ).json()["vin"]
        try:
            response = await client.get(f"/api/vehicles/{key}/{path}", headers=auth_headers)
            assert response.status_code == 200, response.text
            disposition = response.headers["content-disposition"]
            assert "BX23S-77" in disposition
            assert key not in disposition
        finally:
            await _drop(db_session, key)
