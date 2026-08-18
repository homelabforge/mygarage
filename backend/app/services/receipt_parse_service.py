"""Opt-in LLM-assisted fuel receipt parsing (draft only — never writes FuelRecord)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

OCR_FAILED_DETAIL = "Could not read any text from the image. Paste the receipt text instead."

_DRAFT_KEYS = (
    "date",
    "odometer_km",
    "liters",
    "kwh",
    "cost",
    "price_per_unit",
    "fuel_type_used",
    "notes",
    "station_name",
)


async def _setting(db: AsyncSession, key: str, default: str = "") -> str:
    row = await SettingsService.get(db, key)
    return (row.value if row and row.value is not None else default) or default


async def _enabled(db: AsyncSession) -> bool:
    return (await _setting(db, "llm_receipt_parse_enabled", "false")).lower() in (
        "true",
        "1",
        "yes",
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM response did not contain a JSON object",
        )
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM response JSON was invalid",
        ) from err
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM response JSON must be an object",
        )
    return data


async def parse_receipt_draft(
    db: AsyncSession,
    *,
    text: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Return ``{"draft": {...}, "source": "llm"}``. Raises 403 when disabled."""
    if not await _enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LLM receipt parsing is disabled",
        )

    receipt_text = (text or "").strip()
    if not receipt_text and file_bytes:
        from app.services.document_ocr import DocumentOCRService

        ocr = DocumentOCRService()
        name = (filename or "").lower()
        is_pdf = name.endswith(".pdf") or (content_type or "").endswith("pdf")
        try:
            receipt_text = (
                await ocr.extract_text_from_bytes(file_bytes, is_pdf=is_pdf) or ""
            ).strip()
        except Exception as exc:  # noqa: BLE001 - OCR backends raise broadly
            # Deliberately NOT falling through with a placeholder. That spent a
            # 60s LLM call on text we never had, then returned an all-null draft
            # indistinguishable from a genuinely blank receipt.
            logger.info("Receipt OCR failed (%s)", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=OCR_FAILED_DETAIL,
            ) from exc

    if not receipt_text:
        # document_ocr swallows a missing OCR dependency and returns "", so a
        # user who did upload an image would otherwise be told to provide one.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OCR_FAILED_DETAIL if file_bytes else "Provide text or an image file",
        )

    base_url = (await _setting(db, "llm_base_url", "http://127.0.0.1:11434/v1")).rstrip("/")
    model = await _setting(db, "llm_model", "llama3.2")
    api_key = await _setting(db, "llm_api_key", "")

    system = (
        "You extract vehicle fuel/charge receipt fields. "
        "Reply with ONLY a JSON object using keys: "
        + ", ".join(_DRAFT_KEYS)
        + ". Use null for unknown values. Prefer metric: liters, odometer_km, price per liter."
    )
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Receipt text:\n{receipt_text[:8000]}"},
        ],
        "temperature": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as err:
        logger.error("LLM receipt parse HTTP error: %s", err)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM endpoint request failed",
        ) from err

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected LLM response shape",
        ) from err

    raw = _extract_json_object(str(content))
    draft = {k: raw.get(k) for k in _DRAFT_KEYS}
    return {"draft": draft, "source": "llm"}
