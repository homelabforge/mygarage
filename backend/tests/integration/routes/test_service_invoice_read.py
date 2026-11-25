"""POST /api/vehicles/{vin}/service-visits/read-invoice: which path a file
takes, what the gate answers, and that nothing is written.

The models are mocked at ``llm_client``; the draft's arithmetic is covered in
tests/unit/services/test_service_invoice_service.py.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from typing import Any

import pymupdf
import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.vendor import Vendor
from app.services import llm_client
from app.services import service_invoice_service as svc

REPLY = {
    "invoice_number": "1597",
    "date": "05-10-2026",
    "vendor_name": "FOXIMOTO (PTY) LTD",
    "odometer": None,
    "odometer_unit": None,
    "currency": "ZAR",
    "subtotal": 621.5,
    "tax_amount": None,
    "total": 621.5,
    "line_items": [
        {
            "description": "air filter incl. oil",
            "quantity": 1,
            "unit_price": 440,
            "amount": 440,
            "kind": "part",
        },
        {
            "description": "brake fluid",
            "quantity": 0.33,
            "unit_price": 550,
            "amount": 181.5,
            "kind": "part",
        },
    ],
}


_TOUCHED = ("llm_document_reading_enabled", "llm_base_url")


async def _settings(db: AsyncSession, values: dict[str, str | None]) -> None:
    for key, value in values.items():
        row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _restore_settings(db_session: AsyncSession) -> AsyncIterator[None]:
    """The settings table outlives a test: put back what these tests change,
    or the document reader's own tests meet an external endpoint."""
    before: dict[str, str | None] = {}
    for key in _TOUCHED:
        row = (
            await db_session.execute(select(Setting).where(Setting.key == key))
        ).scalar_one_or_none()
        before[key] = row.value if row is not None else None
    yield
    await _settings(db_session, before)


def _text_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    lines = ["Invoice #: 1597", "Date: 05-10-2026", "From: FOXIMOTO (PTY) LTD"] + [
        f"{n}  air filter incl. oil  R440.00  R440.00" for n in range(6)
    ]
    page.insert_text((60, 72), "\n".join(lines), fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (255, 255, 255)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def chat(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _fake(_db: Any, *, system: str, user: str, **kw: Any) -> str:
        calls.append({"system": system, "user": user, **kw})
        return json.dumps(REPLY)

    monkeypatch.setattr(llm_client, "chat_completion", _fake)
    return calls


async def _post(
    client: AsyncClient, headers: dict[str, str], vin: str, name: str, data: bytes, mime: str
):
    return await client.post(
        f"/api/vehicles/{vin}/service-visits/read-invoice",
        files={"file": (name, data, mime)},
        headers=headers,
    )


@pytest.mark.integration
@pytest.mark.asyncio
class TestReadInvoice:
    async def test_off_is_409_ai_reading_not_configured(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession, chat
    ):
        await _settings(db_session, {"llm_document_reading_enabled": "false"})
        response = await _post(
            client, auth_headers, test_vehicle["vin"], "i.pdf", _text_pdf(), "application/pdf"
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "ai_reading_not_configured"
        assert chat == []

    async def test_text_pdf_goes_to_the_text_model_and_writes_nothing(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession, chat
    ):
        await _settings(
            db_session,
            {"llm_document_reading_enabled": "true", "llm_base_url": "http://127.0.0.1:11434/v1"},
        )
        vendor = Vendor(name="Foximoto (Pty) Ltd")
        db_session.add(vendor)
        await db_session.commit()
        before = (
            await db_session.execute(select(func.count()).select_from(ServiceVisit))
        ).scalar_one()

        response = await _post(
            client, auth_headers, test_vehicle["vin"], "i.pdf", _text_pdf(), "application/pdf"
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "text"
        assert len(chat) == 1
        assert "Document text:\nInvoice #: 1597" in chat[0]["user"]
        draft = body["draft"]
        assert draft["invoice_number"] == "1597"
        assert draft["vendor_id"] is not None
        assert [line["description"] for line in draft["line_items"]] == [
            "air filter incl. oil",
            "brake fluid",
        ]
        assert [float(line["cost"]) for line in draft["line_items"]] == [440.0, 181.5]
        assert float(draft["total"]) == 621.5
        after = (
            await db_session.execute(select(func.count()).select_from(ServiceVisit))
        ).scalar_one()
        assert after == before
        await db_session.delete(vendor)
        await db_session.commit()

    async def test_a_photo_is_ocrd_for_the_text_model(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        db_session: AsyncSession,
        chat,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await _settings(
            db_session,
            {"llm_document_reading_enabled": "true", "llm_base_url": "http://127.0.0.1:11434/v1"},
        )

        async def _ocr(*_a: Any, **_k: Any) -> str:
            return "FOXIMOTO (PTY) LTD Invoice 1597\n" + "1 air filter incl. oil R440.00\n" * 10

        monkeypatch.setattr(svc, "_ocr", _ocr)
        response = await _post(
            client, auth_headers, test_vehicle["vin"], "i.jpg", _jpeg(), "image/jpeg"
        )
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "ocr"
        assert "air filter" in chat[0]["user"]

    async def test_no_ocr_text_falls_back_to_the_vision_model(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        db_session: AsyncSession,
        chat,
        monkeypatch: pytest.MonkeyPatch,
    ):
        await _settings(
            db_session,
            {"llm_document_reading_enabled": "true", "llm_base_url": "http://127.0.0.1:11434/v1"},
        )

        async def _ocr(*_a: Any, **_k: Any) -> str:
            return ""

        seen: dict[str, Any] = {}

        async def _vision(_db: Any, *, system: str, user_text: str, images: list, **kw: Any) -> str:
            seen.update(kw, images=len(images))
            return json.dumps(REPLY)

        monkeypatch.setattr(svc, "_ocr", _ocr)
        monkeypatch.setattr(llm_client, "vision_completion", _vision)
        response = await _post(
            client, auth_headers, test_vehicle["vin"], "i.jpg", _jpeg(), "image/jpeg"
        )
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "llm"
        assert chat == []
        assert seen["images"] == 1
        assert seen["max_tokens"] == 6000

    async def test_an_external_endpoint_asks_first(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession, chat
    ):
        await _settings(
            db_session,
            {
                "llm_document_reading_enabled": "true",
                "llm_base_url": "https://openrouter.ai/api/v1",
            },
        )
        response = await _post(
            client, auth_headers, test_vehicle["vin"], "i.pdf", _text_pdf(), "application/pdf"
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "vision_consent_required"
        assert chat == []
