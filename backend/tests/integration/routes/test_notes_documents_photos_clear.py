"""Documents, notes and photo captions follow the update contract.

Their updates were `if x is not None`. The UI got away with it by sending ''
for an emptied field, so any client that sends null had its clear ignored.
A document title could also be saved blank, both on edit and on upload.
"""

from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.document import Document
from app.models.photo import VehiclePhoto

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nTest PDF content"


async def _document(client: AsyncClient, headers: dict, vin: str) -> dict:
    r = await client.post(
        f"/api/vehicles/{vin}/documents",
        files={"file": ("doc.pdf", BytesIO(_PDF), "application/pdf")},
        data={"title": "Registration", "document_type": "Registration", "description": "2026"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestDocuments:
    @pytest.mark.parametrize("field", ["document_type", "description"])
    async def test_null_clears(self, client, auth_headers, own_vehicle, field):
        doc = await _document(client, auth_headers, own_vehicle.vin)
        url = f"/api/vehicles/{own_vehicle.vin}/documents/{doc['id']}"
        r = await client.put(url, json={field: None}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()[field] is None
        assert r.json()["title"] == "Registration"

    @pytest.mark.parametrize("title", [None, "", "   "])
    async def test_a_blank_title_is_a_422(self, client, auth_headers, own_vehicle, title):
        doc = await _document(client, auth_headers, own_vehicle.vin)
        url = f"/api/vehicles/{own_vehicle.vin}/documents/{doc['id']}"
        r = await client.put(url, json={"title": title}, headers=auth_headers)
        assert r.status_code == 422, r.text

    async def test_a_title_is_stored_stripped(self, client, auth_headers, own_vehicle):
        doc = await _document(client, auth_headers, own_vehicle.vin)
        url = f"/api/vehicles/{own_vehicle.vin}/documents/{doc['id']}"
        r = await client.put(url, json={"title": "  Title deed  "}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Title deed"

    @pytest.mark.parametrize("title", ["", "   "])
    async def test_upload_refuses_a_blank_title_before_writing_anything(
        self, client, auth_headers, db_session, own_vehicle, title
    ):
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/documents",
            files={"file": ("doc.pdf", BytesIO(_PDF), "application/pdf")},
            data={"title": title},
            headers=auth_headers,
        )
        assert r.status_code == 422, r.text
        rows = await db_session.scalar(
            select(func.count()).select_from(Document).where(Document.vin == vin)
        )
        assert rows == 0
        vin_dir = settings.documents_dir / vin
        assert not vin_dir.exists() or not any(vin_dir.iterdir())

    async def test_upload_strips_the_title(self, client, auth_headers, own_vehicle):
        r = await client.post(
            f"/api/vehicles/{own_vehicle.vin}/documents",
            files={"file": ("doc.pdf", BytesIO(_PDF), "application/pdf")},
            data={"title": "  Manual  "},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["title"] == "Manual"


class TestNotes:
    async def _note(self, client, headers, vin) -> dict:
        r = await client.post(
            f"/api/vehicles/{vin}/notes",
            json={"vin": vin, "date": "2026-01-02", "title": "Tyres", "content": "Rotate at 10k"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def test_null_title_clears(self, client, auth_headers, own_vehicle):
        note = await self._note(client, auth_headers, own_vehicle.vin)
        url = f"/api/vehicles/{own_vehicle.vin}/notes/{note['id']}"
        r = await client.put(url, json={"title": None}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["title"] is None
        assert r.json()["content"] == "Rotate at 10k"

    @pytest.mark.parametrize("field", ["date", "content"])
    async def test_null_on_a_required_field_is_a_422(
        self, client, auth_headers, own_vehicle, field
    ):
        note = await self._note(client, auth_headers, own_vehicle.vin)
        url = f"/api/vehicles/{own_vehicle.vin}/notes/{note['id']}"
        r = await client.put(url, json={field: None}, headers=auth_headers)
        assert r.status_code == 422, r.text


class TestPhotoCaption:
    async def _photo(self, db_session: AsyncSession, vin: str) -> int:
        photo = VehiclePhoto(vin=vin, file_path=f"{vin}/p.jpg", caption="Before paint")
        db_session.add(photo)
        await db_session.commit()
        return photo.id

    async def test_null_caption_clears(self, client, auth_headers, db_session, own_vehicle):
        photo_id = await self._photo(db_session, own_vehicle.vin)
        r = await client.patch(
            f"/api/vehicles/{own_vehicle.vin}/photos/{photo_id}",
            json={"caption": None},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        db_session.expire_all()
        stored = await db_session.get(VehiclePhoto, photo_id)
        assert stored is not None and stored.caption is None

    async def test_omitted_caption_is_kept(self, client, auth_headers, db_session, own_vehicle):
        photo_id = await self._photo(db_session, own_vehicle.vin)
        r = await client.patch(
            f"/api/vehicles/{own_vehicle.vin}/photos/{photo_id}",
            json={"is_main": True},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        db_session.expire_all()
        stored = await db_session.get(VehiclePhoto, photo_id)
        assert stored is not None and stored.caption == "Before paint"

    async def test_null_is_main_is_a_422(self, client, auth_headers, db_session, own_vehicle):
        photo_id = await self._photo(db_session, own_vehicle.vin)
        r = await client.patch(
            f"/api/vehicles/{own_vehicle.vin}/photos/{photo_id}",
            json={"is_main": None},
            headers=auth_headers,
        )
        assert r.status_code == 422, r.text
