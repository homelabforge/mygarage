"""`document_reader_service`: text first, vision when allowed, 409 otherwise (#211).

The model is mocked at ``llm_client.vision_completion``; what matters here is
which path a document takes and what the caller gets back, not what the
endpoint answers.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import Any

import pymupdf
import pytest
import pytest_asyncio
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services import document_reader_service as reader
from app.services import llm_client
from app.services.document_prompts import PROMPTS, prompt_for
from app.services.document_prompts.registration_certificate import KEYS as REGISTRATION_KEYS


def _pdf(text: str | None) -> bytes:
    """One page carrying ``text`` as six lines (a single long line would run
    off the page and be dropped from the text layer), or a blank page."""
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), "\n".join(f"{text} {n}" for n in range(6)), fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 400), (230, 230, 230)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def _set_flag(db: AsyncSession, value: str | None) -> None:
    row = (
        await db.execute(select(Setting).where(Setting.key == reader.DOCUMENT_READING_SETTING))
    ).scalar_one_or_none()
    if value is None:
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(Setting(key=reader.DOCUMENT_READING_SETTING, value=value, category="integrations"))
    else:
        row.value = value
    await db.commit()


@pytest_asyncio.fixture
async def reading_flag(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    row = (
        await db_session.execute(
            select(Setting).where(Setting.key == reader.DOCUMENT_READING_SETTING)
        )
    ).scalar_one_or_none()
    before = row.value if row is not None else None
    try:
        yield db_session
    finally:
        await _set_flag(db_session, before)


@pytest.fixture
def no_vision(monkeypatch: pytest.MonkeyPatch):
    async def _never(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("vision_completion must not be called on this path")

    monkeypatch.setattr(llm_client, "vision_completion", _never)


@pytest.fixture
def vision_answer(monkeypatch: pytest.MonkeyPatch):
    """Patch the model with a canned answer and record what it was asked."""
    calls: list[dict[str, Any]] = []

    def _install(answer: str) -> list[dict[str, Any]]:
        async def _fake(_db: Any, *, system: str, user_text: str, images: list, **kw: Any) -> str:
            calls.append({"system": system, "user_text": user_text, "images": images, **kw})
            return answer

        monkeypatch.setattr(llm_client, "vision_completion", _fake)
        return calls

    return _install


@pytest_asyncio.fixture
async def external_endpoint(
    reading_flag: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncSession]:
    """Point the LLM at OpenRouter, resolved to a public address (B2)."""
    db = reading_flag
    row = (
        await db.execute(select(Setting).where(Setting.key == llm_client.LLM_BASE_URL_SETTING))
    ).scalar_one_or_none()
    before = row.value if row is not None else None
    if row is None:
        db.add(
            Setting(
                key=llm_client.LLM_BASE_URL_SETTING,
                value="https://openrouter.ai/api/v1",
                category="integrations",
            )
        )
    else:
        row.value = "https://openrouter.ai/api/v1"
    await db.commit()
    monkeypatch.setattr(
        llm_client.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("104.18.2.115", 0))],
    )
    llm_client.clear_locality_cache()
    try:
        yield db
    finally:
        llm_client.clear_locality_cache()
        row = (
            await db.execute(select(Setting).where(Setting.key == llm_client.LLM_BASE_URL_SETTING))
        ).scalar_one_or_none()
        if before is None:
            if row is not None:
                await db.delete(row)
        elif row is not None:
            row.value = before
        await db.commit()


LONG_TEXT = "CERTIFICAT D'IMMATRICULATION  A AB-123-CD  B 12/03/2023  " * 3


@pytest.mark.asyncio
class TestReadDocument:
    async def test_text_pdf_is_read_without_the_model(self, reading_flag, no_vision):
        await _set_flag(reading_flag, "false")
        result = await reader.read_document(
            reading_flag,
            kind="registration_certificate",
            file_bytes=_pdf(LONG_TEXT),
            filename="cg.pdf",
            content_type="application/pdf",
        )
        assert result.source == "text"
        assert result.raw_text is not None
        assert "AB-123-CD" in result.raw_text
        assert result.fields == {}
        assert result.pages == 0
        assert result.model is None

    async def test_photo_with_reading_off_is_409_with_the_code(self, reading_flag, no_vision):
        await _set_flag(reading_flag, "false")
        with pytest.raises(HTTPException) as exc:
            await reader.read_document(
                reading_flag,
                kind="registration_certificate",
                file_bytes=_jpeg(),
                filename="cg.jpg",
                content_type="image/jpeg",
            )
        assert exc.value.status_code == 409
        assert exc.value.detail == reader.AI_READING_NOT_CONFIGURED

    async def test_missing_flag_row_means_off(self, reading_flag, no_vision):
        await _set_flag(reading_flag, None)
        assert await reader.reading_enabled(reading_flag) is False

    async def test_photo_with_reading_on_goes_to_the_model(self, reading_flag, vision_answer):
        await _set_flag(reading_flag, "true")
        calls = vision_answer(
            'Here you go:\n{"country": "FR", "A": " AB-123-CD ", "B": "2023-03-12", '
            '"E": "VF1RFB00X56123456", "P2": 66, "Y1": null, "V9": {"oops": 1}, '
            '"extra": "ignored", "D1": ""}'
        )
        result = await reader.read_document(
            reading_flag,
            kind="registration_certificate",
            file_bytes=_jpeg(),
            filename="cg.jpg",
            content_type="image/jpeg",
        )
        assert result.source == "llm"
        assert result.raw_text is None
        assert result.pages == 1
        assert result.model  # the configured model name, whatever it is
        assert set(result.fields) == set(REGISTRATION_KEYS)
        assert result.fields["country"] == "FR"
        assert result.fields["A"] == "AB-123-CD"
        assert result.fields["E"] == "VF1RFB00X56123456"
        assert result.fields["P2"] == 66
        assert result.fields["Y1"] is None
        assert result.fields["D1"] is None
        assert result.fields["V9"] is None
        assert result.warnings == ["V9: unusable value dropped"]
        assert "extra" not in result.fields

        assert len(calls) == 1
        prompt = prompt_for("registration_certificate")
        assert calls[0]["system"] == prompt.system
        assert calls[0]["user_text"] == prompt.user_text
        assert [mime for _data, mime in calls[0]["images"]] == ["image/jpeg"]

    async def test_scanned_pdf_with_reading_on_is_rasterised(self, reading_flag, vision_answer):
        await _set_flag(reading_flag, "true")
        calls = vision_answer('{"insurer": "MAIF"}')
        result = await reader.read_document(
            reading_flag,
            kind="insurance_policy",
            file_bytes=_pdf(None),
            filename="scan.pdf",
            content_type="application/pdf",
        )
        assert result.source == "llm"
        assert result.fields["insurer"] == "MAIF"
        assert result.fields["coverages"] is None
        assert len(calls[0]["images"]) == 1

    async def test_unreadable_upload_is_400(self, reading_flag, no_vision):
        await _set_flag(reading_flag, "true")
        with pytest.raises(HTTPException) as exc:
            await reader.read_document(
                reading_flag,
                kind="insurance_policy",
                file_bytes=b"garbage",
                filename="x.jpg",
                content_type="image/jpeg",
            )
        assert exc.value.status_code == 400

    async def test_answer_without_json_is_502(self, reading_flag, vision_answer):
        await _set_flag(reading_flag, "true")
        vision_answer("I cannot read this document.")
        with pytest.raises(HTTPException) as exc:
            await reader.read_document(
                reading_flag,
                kind="insurance_policy",
                file_bytes=_jpeg(),
                filename="x.jpg",
                content_type="image/jpeg",
            )
        assert exc.value.status_code == 502


@pytest.mark.asyncio
class TestExternalVisionConsent:
    """B2: a document reaches a vision model outside the network only with
    the person's consent, and the 409 that asks for it calls no model."""

    async def test_photo_to_an_external_endpoint_needs_consent(
        self, external_endpoint, vision_answer
    ):
        await _set_flag(external_endpoint, "true")
        calls = vision_answer('{"A": "AB-123-CD"}')
        with pytest.raises(HTTPException) as exc:
            await reader.read_document(
                external_endpoint,
                kind="registration_certificate",
                file_bytes=_jpeg(),
                filename="cg.jpg",
                content_type="image/jpeg",
            )
        assert exc.value.status_code == 409
        assert exc.value.detail == {"code": "vision_consent_required", "host": "openrouter.ai"}
        assert calls == []

    async def test_scanned_pdf_to_an_external_endpoint_needs_consent(
        self, external_endpoint, vision_answer
    ):
        await _set_flag(external_endpoint, "true")
        calls = vision_answer('{"insurer": "MAIF"}')
        with pytest.raises(HTTPException) as exc:
            await reader.read_document(
                external_endpoint,
                kind="insurance_policy",
                file_bytes=_pdf(None),
                filename="scan.pdf",
                content_type="application/pdf",
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "vision_consent_required"
        assert calls == []

    async def test_consent_lets_the_document_through(self, external_endpoint, vision_answer):
        await _set_flag(external_endpoint, "true")
        calls = vision_answer('{"A": "AB-123-CD"}')
        result = await reader.read_document(
            external_endpoint,
            kind="registration_certificate",
            file_bytes=_jpeg(),
            filename="cg.jpg",
            content_type="image/jpeg",
            allow_external_vision=True,
        )
        assert result.source == "llm"
        assert len(calls) == 1

    async def test_a_text_pdf_never_asks(self, external_endpoint, no_vision):
        await _set_flag(external_endpoint, "true")
        result = await reader.read_document(
            external_endpoint,
            kind="registration_certificate",
            file_bytes=_pdf(LONG_TEXT),
            filename="cg.pdf",
            content_type="application/pdf",
        )
        assert result.source == "text"

    async def test_reading_off_still_says_not_configured(self, external_endpoint, no_vision):
        await _set_flag(external_endpoint, "false")
        with pytest.raises(HTTPException) as exc:
            await reader.read_document(
                external_endpoint,
                kind="registration_certificate",
                file_bytes=_jpeg(),
                filename="cg.jpg",
                content_type="image/jpeg",
            )
        assert exc.value.detail == reader.AI_READING_NOT_CONFIGURED

    async def test_a_local_endpoint_never_asks(self, reading_flag, vision_answer, monkeypatch):
        # The default endpoint is 127.0.0.1: no lookup, no question.
        monkeypatch.setattr(llm_client, "is_local_endpoint", _always_local)
        await _set_flag(reading_flag, "true")
        calls = vision_answer('{"A": "AB-123-CD"}')
        result = await reader.read_document(
            reading_flag,
            kind="registration_certificate",
            file_bytes=_jpeg(),
            filename="cg.jpg",
            content_type="image/jpeg",
        )
        assert result.source == "llm"
        assert len(calls) == 1


async def _always_local(_base_url: str) -> bool:
    return True

    async def test_the_request_goes_where_consent_looked(
        self, external_endpoint, vision_answer, monkeypatch: pytest.MonkeyPatch
    ):
        """FB-2: consent checks one base URL; the request must go to that same
        URL, not one re-read after an admin changed it in between."""
        local = "http://127.0.0.1:11434/v1"
        await _set_flag(external_endpoint, "true")
        row = (
            await external_endpoint.execute(
                select(Setting).where(Setting.key == llm_client.LLM_BASE_URL_SETTING)
            )
        ).scalar_one()
        row.value = local
        await external_endpoint.commit()
        checked = llm_client.is_local_endpoint

        async def _check_then_change(base_url: str) -> bool:
            answer = await checked(base_url)
            row.value = "https://openrouter.ai/api/v1"
            await external_endpoint.commit()
            return answer

        monkeypatch.setattr(llm_client, "is_local_endpoint", _check_then_change)
        calls = vision_answer('{"A": "AB-123-CD"}')
        await reader.read_document(
            external_endpoint,
            kind="registration_certificate",
            file_bytes=_jpeg(),
            filename="cg.jpg",
            content_type="image/jpeg",
        )
        assert len(calls) == 1
        assert calls[0].get("base_url") == local


class TestCoerceFields:
    def test_keeps_scalars_lists_and_flat_objects(self):
        fields, warnings = reader.coerce_fields(
            {
                "insurer": "  AXA ",
                "premium": 612.4,
                "deductible": 300,
                "coverages": [{"name": "Bris de glace", "limit": None}, "Vol"],
                "plates": [" AB-123-CD "],
                "vins": [],
                "policy_type": True,
            },
            ("insurer", "premium", "deductible", "coverages", "plates", "vins", "policy_type"),
        )
        assert warnings == []
        assert fields == {
            "insurer": "AXA",
            "premium": 612.4,
            "deductible": 300,
            "coverages": [{"name": "Bris de glace", "limit": None}, "Vol"],
            "plates": ["AB-123-CD"],
            "vins": [],
            "policy_type": True,
        }

    def test_nested_objects_and_nested_lists_are_dropped_with_a_warning(self):
        fields, warnings = reader.coerce_fields(
            {"a": {"x": 1}, "b": [[1, 2]], "c": None}, ("a", "b", "c", "d")
        )
        assert fields == {"a": None, "b": None, "c": None, "d": None}
        assert warnings == ["a: unusable value dropped", "b: unusable value dropped"]


class TestPrompts:
    def test_registry_names_both_kinds(self):
        assert set(PROMPTS) == {"registration_certificate", "insurance_policy"}
        for prompt in PROMPTS.values():
            assert prompt.keys
            assert "JSON" in prompt.system
            for key in prompt.keys:
                assert key in prompt.system

    def test_unknown_kind_is_a_value_error(self):
        with pytest.raises(ValueError):
            prompt_for("window_sticker")
