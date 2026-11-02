"""Consent before a document reaches a vision model outside the network (B2).

End to end through the routes with the REAL document reader: only the
resolver (a public address for the endpoint) and the model are mocked, so
these tests see what an upload actually does. The 409 asks first and calls
no model; ``allow_external_vision=true`` is the answer; a PDF the server
can read itself never asks.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pymupdf
import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.settings import Setting
from app.models.vehicle import Vehicle
from app.services import llm_client
from app.services.document_reader_service import DOCUMENT_READING_SETTING

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PREFIX = "MVCN"
EXTERNAL_URL = "https://openrouter.ai/api/v1"
CONSENT_DETAIL = {"code": "vision_consent_required", "host": "openrouter.ai"}


async def _put(db: AsyncSession, key: str, value: str | None) -> None:
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if value is None:
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(Setting(key=key, value=value, category="integrations"))
    else:
        row.value = value
    await db.commit()


@pytest_asyncio.fixture
async def external_vision(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[list[dict[str, Any]]]:
    """Reading on, the endpoint on OpenRouter (resolved to a public address),
    the model answering a canned certificate; yields the model's call log."""
    keys = (DOCUMENT_READING_SETTING, llm_client.LLM_BASE_URL_SETTING)
    before: dict[str, str | None] = {}
    for key in keys:
        row = (
            await db_session.execute(select(Setting).where(Setting.key == key))
        ).scalar_one_or_none()
        before[key] = row.value if row is not None else None
    await _put(db_session, DOCUMENT_READING_SETTING, "true")
    await _put(db_session, llm_client.LLM_BASE_URL_SETTING, EXTERNAL_URL)
    # The endpoint's own lookup only: patching socket.getaddrinfo would send
    # the PostgreSQL driver's next connect to this address too.
    monkeypatch.setattr(
        llm_client, "_resolve", lambda *_a, **_k: [(2, 1, 6, "", ("104.18.2.115", 0))]
    )
    llm_client.clear_locality_cache()

    calls: list[dict[str, Any]] = []

    async def _vision(_db: Any, **kwargs: Any) -> str:
        calls.append(kwargs)
        return '{"country": "FR", "A": "AB-123-CD", "D1": "Renault", "insurer": "MAIF"}'

    monkeypatch.setattr(llm_client, "vision_completion", _vision)
    try:
        yield calls
    finally:
        llm_client.clear_locality_cache()
        await db_session.rollback()
        for key, value in before.items():
            await _put(db_session, key, value)
        vins = [
            row[0]
            for row in (
                await db_session.execute(select(Vehicle.vin).where(Vehicle.vin.like(f"{PREFIX}%")))
            ).all()
        ]
        if vins:
            await db_session.execute(delete(Document).where(Document.vin.in_(vins)))
            await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_(vins)))
            await db_session.commit()


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 240, 240)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _pdf(text: str | None) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        for n, line in enumerate(text.splitlines()):
            page.insert_text((40, 60 + 14 * n), line, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


async def _vehicle(client: AsyncClient, headers: dict) -> str:
    vin = (PREFIX + uuid.uuid4().hex.upper().replace("O", "P").replace("I", "J"))[:17]
    vin = vin.replace("Q", "R")
    r = await client.post(
        "/api/vehicles",
        headers=headers,
        json={"vin": vin, "nickname": f"vc-{vin[-4:]}", "vehicle_type": "Car"},
    )
    assert r.status_code == 201, r.text
    return vin


class TestCertificate:
    async def test_parse_asks_first_and_calls_no_model(
        self, client: AsyncClient, auth_headers, external_vision
    ):
        r = await client.post(
            "/api/registration-certificate/parse",
            headers=auth_headers,
            files={"file": ("cg.jpg", _jpeg(), "image/jpeg")},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == CONSENT_DETAIL
        assert external_vision == []

        r = await client.post(
            "/api/registration-certificate/parse?allow_external_vision=true",
            headers=auth_headers,
            files={"file": ("cg.jpg", _jpeg(), "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "llm"
        assert len(external_vision) == 1

    async def test_import_files_nothing_until_consent(
        self, client: AsyncClient, auth_headers, external_vision, db_session: AsyncSession
    ):
        vin = await _vehicle(client, auth_headers)
        url = f"/api/vehicles/{vin}/registration-certificate"
        r = await client.post(
            url, headers=auth_headers, files={"file": ("cg.jpg", _jpeg(), "image/jpeg")}
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == CONSENT_DETAIL
        assert external_vision == []
        filed = (await db_session.execute(select(Document).where(Document.vin == vin))).all()
        assert filed == []

        r = await client.post(
            f"{url}?allow_external_vision=true",
            headers=auth_headers,
            files={"file": ("cg.jpg", _jpeg(), "image/jpeg")},
        )
        assert r.status_code == 201, r.text
        assert len(external_vision) == 1

    async def test_a_text_pdf_never_asks(self, client: AsyncClient, auth_headers, external_vision):
        text = (
            "RÉPUBLIQUE FRANÇAISE\nCERTIFICAT D'IMMATRICULATION\nA AB-123-CD   B 12/03/2023\n"
            "D.1 RENAULT\nD.3 CLIO\nJ M1   J.1 VP\nP.1 1498   P.2 74   P.3 ES   P.6 5"
        )
        r = await client.post(
            "/api/registration-certificate/parse",
            headers=auth_headers,
            files={"file": ("cg.pdf", _pdf(text), "application/pdf")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "text"
        assert external_vision == []


class TestInsurance:
    async def test_a_photo_asks_first_and_calls_no_model(
        self, client: AsyncClient, auth_headers, external_vision
    ):
        r = await client.post(
            "/api/insurance/parse-pdf",
            headers=auth_headers,
            files={"file": ("avis.jpg", _jpeg(), "image/jpeg")},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == CONSENT_DETAIL
        assert external_vision == []

        r = await client.post(
            "/api/insurance/parse-pdf?allow_external_vision=true",
            headers=auth_headers,
            files={"file": ("avis.jpg", _jpeg(), "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "llm"
        assert len(external_vision) == 1

    async def test_a_pdf_with_text_never_asks(
        self, client: AsyncClient, auth_headers, external_vision
    ):
        text = (
            "AVIS D'ECHEANCE\nMAIF assurance automobile\nContrat n 123456\n"
            "Periode du 01/01/2026 au 31/12/2026\nCotisation annuelle TTC : 612,40 EUR"
        )
        r = await client.post(
            "/api/insurance/parse-pdf",
            headers=auth_headers,
            files={"file": ("avis.pdf", _pdf(text), "application/pdf")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "text"
        assert external_vision == []
