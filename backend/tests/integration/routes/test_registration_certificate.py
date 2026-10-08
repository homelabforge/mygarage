"""The registration certificate routes (#211).

The document reader is patched at `registration_certificate_service.
document_reader_service.read_document`: what matters here is what the
routes do with a read (text or model), not how the file is read.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import fitz  # PyMuPDF
import pytest
import pytest_asyncio
from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import delete, select

from app.models.document import Document
from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle
from app.services.document_reader_service import AI_READING_NOT_CONFIGURED, DocumentReadResult

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

READ_DOCUMENT = (
    "app.services.registration_certificate_service.document_reader_service.read_document"
)
PREFIX = "MRCT"


@pytest_asyncio.fixture(autouse=True)
async def _drop_vehicles(db_session):
    yield
    await db_session.rollback()
    vins = [
        row[0]
        for row in (
            await db_session.execute(select(Vehicle.vin).where(Vehicle.vin.like(f"{PREFIX}%")))
        ).all()
    ]
    if vins:
        visit_ids = [
            row[0]
            for row in (
                await db_session.execute(select(ServiceVisit.id).where(ServiceVisit.vin.in_(vins)))
            ).all()
        ]
        if visit_ids:
            await db_session.execute(
                delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids))
            )
            await db_session.execute(delete(ServiceVisit).where(ServiceVisit.id.in_(visit_ids)))
        await db_session.execute(delete(Reminder).where(Reminder.vin.in_(vins)))
        await db_session.execute(delete(MaintenanceRule).where(MaintenanceRule.vin.in_(vins)))
        await db_session.execute(delete(Document).where(Document.vin.in_(vins)))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_(vins)))
    await db_session.commit()


def _vin() -> str:
    return (
        PREFIX + uuid.uuid4().hex.upper().replace("O", "P").replace("I", "J").replace("Q", "R")
    )[:17]


def _text_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 60), text, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 240, 240)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _certificate_text(vin: str, *, first_registration: str, last_inspection: str | None) -> str:
    lines = [
        "RÉPUBLIQUE FRANÇAISE",
        "CERTIFICAT D'IMMATRICULATION",
        f"A AB-123-CD   B {first_registration}",
        "C.1 DUPONT JEAN",
        "D.1 RENAULT",
        "D.3 CLIO",
        f"E {vin}",
        "J M1   J.1 VP",
        "P.1 1498   P.2 74   P.3 ES   P.6 5",
        "V.7 118   V.9 Euro 6d-TEMP",
    ]
    if last_inspection:
        lines.append(f"X.1 {last_inspection}")
    lines.append("Y.1 162,50   Y.3 0   Y.6 176,26")
    return "\n".join(lines)


def _text_read(text: str) -> DocumentReadResult:
    return DocumentReadResult(kind="registration_certificate", source="text", raw_text=text)


def _llm_read(fields: dict[str, Any]) -> DocumentReadResult:
    return DocumentReadResult(
        kind="registration_certificate", source="llm", fields=fields, model="llava", pages=1
    )


async def _create_vehicle(client: AsyncClient, headers: dict, **fields: Any) -> str:
    vin = _vin()
    payload = {"vin": vin, "nickname": f"rct-{vin[-4:]}", "vehicle_type": "Car", **fields}
    r = await client.post("/api/vehicles", headers=headers, json=payload)
    assert r.status_code == 201, r.text
    return vin


def _upload(content: bytes, name: str = "cg.pdf", mime: str = "application/pdf"):
    return {"file": (name, content, mime)}


class TestParse:
    async def test_requires_auth(self, client: AsyncClient):
        r = await client.post("/api/registration-certificate/parse", files=_upload(_text_pdf("x")))
        assert r.status_code == 401

    async def test_text_pdf_is_parsed_without_a_model(self, client: AsyncClient, auth_headers):
        vin = _vin()
        text = _certificate_text(vin, first_registration="12/03/2023", last_inspection="10/02/2026")
        with patch(READ_DOCUMENT, new=AsyncMock(return_value=_text_read(text))) as read:
            r = await client.post(
                "/api/registration-certificate/parse",
                headers=auth_headers,
                files=_upload(_text_pdf(text)),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "text"
        assert body["country"] == "FR"
        assert body["confidence"] == 100.0
        assert body["fields"]["vin"] == vin
        assert "raw_text" not in body["fields"]
        assert body["vehicle_patch"]["vin"] == vin
        assert body["vehicle_patch"]["first_registration_date"] == "2023-03-12"
        assert body["vehicle_patch"]["fuel_type"] == "gasoline"
        assert body["vehicle_patch"]["vehicle_type"] == "Car"
        assert body["last_inspection_date"] == "2026-02-10"
        assert body["suggested_tax_records"] == [
            {
                "code": "Y.1",
                "tax_type": "registration_tax",
                "amount": "162.50",
                "date": "2023-03-12",
            }
        ]
        assert body["warnings"] == []
        assert body["model"] is None
        read.assert_awaited_once()
        assert read.await_args.kwargs["kind"] == "registration_certificate"

    async def test_photo_read_by_the_model(self, client: AsyncClient, auth_headers):
        fields = {
            "country": "FR",
            "A": "AB-123-CD",
            "B": "2023-03-12",
            "D1": "Renault",
            "D3": "Clio",
            "E": "VF1RFB00X5612345O",
            "P3": "ES",
        }
        with patch(READ_DOCUMENT, new=AsyncMock(return_value=_llm_read(fields))):
            r = await client.post(
                "/api/registration-certificate/parse?country=fr",
                headers=auth_headers,
                files=_upload(_jpeg(), "cg.jpg", "image/jpeg"),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "llm"
        assert body["model"] == "llava"
        assert body["pages"] == 1
        assert body["vehicle_patch"]["make"] == "Renault"
        assert "vin" not in body["vehicle_patch"]
        assert any(w.startswith("E:") for w in body["warnings"])
        assert "VIN (E) not found" in body["warnings"]

    async def test_reader_409_is_relayed(self, client: AsyncClient, auth_headers):
        with patch(
            READ_DOCUMENT,
            new=AsyncMock(
                side_effect=HTTPException(status_code=409, detail=AI_READING_NOT_CONFIGURED)
            ),
        ):
            r = await client.post(
                "/api/registration-certificate/parse",
                headers=auth_headers,
                files=_upload(_jpeg(), "cg.jpg", "image/jpeg"),
            )
        assert r.status_code == 409
        assert r.json()["detail"] == AI_READING_NOT_CONFIGURED

    @pytest.mark.parametrize(
        ("name", "mime", "content"),
        [
            ("cg.txt", "text/plain", b"hello"),
            ("cg.pdf", "image/gif", b"GIF89a"),
            ("cg.pdf", "application/pdf", b"not a pdf at all"),
            ("cg.jpg", "image/jpeg", b""),
        ],
    )
    async def test_bad_uploads_are_400(
        self, client: AsyncClient, auth_headers, name, mime, content
    ):
        r = await client.post(
            "/api/registration-certificate/parse",
            headers=auth_headers,
            files=_upload(content, name, mime),
        )
        assert r.status_code == 400, r.text

    async def test_heic_is_accepted_by_its_header(self, client: AsyncClient, auth_headers):
        heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64
        with patch(READ_DOCUMENT, new=AsyncMock(return_value=_llm_read({"D1": "Renault"}))):
            r = await client.post(
                "/api/registration-certificate/parse",
                headers=auth_headers,
                files=_upload(heic, "IMG_0001.HEIC", "image/heic"),
            )
        assert r.status_code == 200, r.text


class TestImport:
    async def test_owner_only(self, client: AsyncClient, auth_headers, non_admin_headers):
        vin = await _create_vehicle(client, auth_headers)
        r = await client.post(
            f"/api/vehicles/{vin}/registration-certificate",
            headers=non_admin_headers,
            files=_upload(_text_pdf("x")),
        )
        assert r.status_code in (403, 404)

    async def test_fills_empty_fields_stores_the_document_and_records_the_inspection(
        self, client: AsyncClient, auth_headers, db_session
    ):
        vin = await _create_vehicle(client, auth_headers, make="Renault")
        today = date.today()
        # Five years old: past the first four-year cycle, so France's rule is
        # a test every two years, counted from the last one.
        first = today - relativedelta(years=5, days=10)
        inspection = today - timedelta(days=30)
        text = _certificate_text(
            vin,
            first_registration=first.strftime("%d/%m/%Y"),
            last_inspection=inspection.strftime("%d/%m/%Y"),
        )
        with patch(READ_DOCUMENT, new=AsyncMock(return_value=_text_read(text))):
            r = await client.post(
                f"/api/vehicles/{vin}/registration-certificate",
                headers=auth_headers,
                files=_upload(_text_pdf(text)),
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["document"]["document_type"] == "registration"
        assert body["document"]["title"] == "Registration certificate (AB-123-CD)"
        assert body["document"]["vin"] == vin
        assert "make" in body["skipped"]  # already "Renault"
        assert "vehicle_type" in body["skipped"]  # never changed without overwrite
        assert "vin" not in body["applied"]
        for name in (
            "license_plate",
            "first_registration_date",
            "model",
            "fuel_type",
            "fiscal_power",
        ):
            assert name in body["applied"], name
        assert body["inspection_recorded"] is True
        assert body["parse"]["source"] == "text"

        vehicle = await client.get(f"/api/vehicles/{vin}", headers=auth_headers)
        data = vehicle.json()
        assert data["make"] == "Renault"
        assert data["model"] == "CLIO"
        assert data["license_plate"] == "AB-123-CD"
        assert data["first_registration_date"] == first.isoformat()
        assert data["registration_country"] == "FR"
        assert data["fuel_type"] == "gasoline"
        assert data["fiscal_power"] == 5
        assert data["co2_g_km"] == 118
        assert data["euro_emission_class"] == "Euro 6d-TEMP"
        assert data["power_kw"] == 74
        assert data["displacement_l"] == "1.5"

        documents = await client.get(f"/api/vehicles/{vin}/documents", headers=auth_headers)
        assert [d["document_type"] for d in documents.json()["documents"]] == ["registration"]

        # X.1 became a passed inspection visit, and the periodic inspection
        # reminder counts from it (France: two years after the test).
        visits = (
            (await db_session.execute(select(ServiceVisit).where(ServiceVisit.vin == vin)))
            .scalars()
            .all()
        )
        assert [v.date for v in visits] == [inspection]
        items = (
            (
                await db_session.execute(
                    select(ServiceLineItem).where(ServiceLineItem.visit_id == visits[0].id)
                )
            )
            .scalars()
            .all()
        )
        assert items[0].maintenance_type == "state_inspection"
        assert items[0].inspection_result == "passed"
        assert items[0].description == "Contrôle technique"
        reminders = await client.get(f"/api/vehicles/{vin}/reminders", headers=auth_headers)
        assert reminders.status_code == 200, reminders.text
        pending = [
            rem
            for rem in reminders.json()
            if rem["status"] == "pending" and rem.get("source") == "inspection"
        ]
        assert len(pending) == 1
        assert pending[0]["due_date"] == (inspection + relativedelta(years=2)).isoformat()

        # A second import of the same certificate changes nothing more.
        with patch(READ_DOCUMENT, new=AsyncMock(return_value=_text_read(text))):
            again = await client.post(
                f"/api/vehicles/{vin}/registration-certificate",
                headers=auth_headers,
                files=_upload(_text_pdf(text)),
            )
        assert again.status_code == 201
        assert again.json()["applied"] == []
        assert again.json()["inspection_recorded"] is False
        visits_after = (
            (await db_session.execute(select(ServiceVisit).where(ServiceVisit.vin == vin)))
            .scalars()
            .all()
        )
        assert len(visits_after) == 1

    async def test_overwrite_replaces_values_but_never_the_vin(
        self, client: AsyncClient, auth_headers
    ):
        vin = await _create_vehicle(client, auth_headers, make="Peugeot", model="208")
        other_vin = _vin()
        text = _certificate_text(other_vin, first_registration="12/03/2023", last_inspection=None)
        with patch(READ_DOCUMENT, new=AsyncMock(return_value=_text_read(text))):
            r = await client.post(
                f"/api/vehicles/{vin}/registration-certificate?overwrite=true",
                headers=auth_headers,
                files=_upload(_text_pdf(text)),
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "make" in body["applied"] and "model" in body["applied"]
        assert "vin" in body["skipped"]
        assert any("is not this vehicle's" in w for w in body["parse"]["warnings"])
        assert body["inspection_recorded"] is False
        vehicle = (await client.get(f"/api/vehicles/{vin}", headers=auth_headers)).json()
        assert vehicle["vin"] == vin
        assert vehicle["make"] == "RENAULT"
        assert vehicle["model"] == "CLIO"

    async def test_reader_409_files_nothing(self, client: AsyncClient, auth_headers, db_session):
        vin = await _create_vehicle(client, auth_headers)
        with patch(
            READ_DOCUMENT,
            new=AsyncMock(
                side_effect=HTTPException(status_code=409, detail=AI_READING_NOT_CONFIGURED)
            ),
        ):
            r = await client.post(
                f"/api/vehicles/{vin}/registration-certificate",
                headers=auth_headers,
                files=_upload(_jpeg(), "cg.jpg", "image/jpeg"),
            )
        assert r.status_code == 409
        documents = await client.get(f"/api/vehicles/{vin}/documents", headers=auth_headers)
        assert documents.json()["documents"] == []
