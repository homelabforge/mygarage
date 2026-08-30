"""Opt-in LLM-assisted fuel receipt parsing (draft only — never writes FuelRecord)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import llm_client

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


async def parse_receipt_draft(
    db: AsyncSession,
    *,
    text: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Return ``{"draft": {...}, "source": "llm"}``. Raises 403 when disabled."""
    if not await llm_client.setting_enabled(db, "llm_receipt_parse_enabled"):
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

    system = (
        "You extract vehicle fuel/charge receipt fields. "
        "Reply with ONLY a JSON object using keys: "
        + ", ".join(_DRAFT_KEYS)
        + ". Use null for unknown values. Prefer metric: liters, odometer_km, price per liter."
    )
    content = await llm_client.chat_completion(
        db,
        system=system,
        user=f"Receipt text:\n{receipt_text[:8000]}",
        temperature=0,
    )
    raw = llm_client.extract_json_object(str(content))
    draft = {k: raw.get(k) for k in _DRAFT_KEYS}
    return {"draft": draft, "source": "llm"}
