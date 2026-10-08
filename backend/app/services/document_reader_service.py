"""Read an uploaded document into fields, by text when there is text and by a
vision model when there is not (#211).

The strategy, in order:

1. A PDF with a text layer is read with PyMuPDF (no OCR, no model, no
   network): the result carries ``raw_text`` and the kind's own regex parser
   does the rest. ``source`` is ``"text"``.
2. Otherwise, when ``llm_document_reading_enabled`` is on, the document is
   turned into at most two JPEG images (`document_images`) and sent to the
   configured vision model with the kind's prompt (`document_prompts`). The
   JSON answer is reduced to the prompt's keys and scalar values; every
   value is still for the kind's parser to validate before it is applied,
   because a model guesses. ``source`` is ``"llm"``.
3. Otherwise the request fails with 409 and the code
   ``ai_reading_not_configured``, which the UI turns into "configure AI
   document reading in Settings, or type the values by hand".

Never a required path: a document a person cannot have read is still a
document they can type from.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import llm_client
from app.services.document_images import has_text_layer, is_pdf, to_images
from app.services.document_prompts import DocumentKind, prompt_for
from app.services.settings_service import SettingsService
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: The setting that turns the vision path on.
DOCUMENT_READING_SETTING = "llm_document_reading_enabled"
#: The 409 detail the frontend matches on.
AI_READING_NOT_CONFIGURED = "ai_reading_not_configured"

Source = Literal["text", "llm"]


@dataclass
class DocumentReadResult:
    kind: str
    source: Source
    #: The PDF's text, on the text path; None on the model path.
    raw_text: str | None = None
    #: The model's answer reduced to the prompt's keys, on the model path.
    fields: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: The model that answered, on the model path.
    model: str | None = None
    #: How many images were sent, on the model path.
    pages: int = 0


def coerce_fields(raw: dict[str, Any], keys: tuple[str, ...]) -> tuple[dict[str, Any], list[str]]:
    """Keep the prompt's keys and the values a parser can read.

    A string is trimmed (empty → None); numbers and booleans pass; a list of
    scalars or of flat objects passes (coverages, plates, VINs); anything
    else is dropped with a warning naming the key. Unknown keys are dropped
    silently: a chatty model adds them.
    """
    fields: dict[str, Any] = {}
    warnings: list[str] = []
    for key in keys:
        value = raw.get(key)
        if value is None:
            fields[key] = None
        elif isinstance(value, str):
            fields[key] = value.strip() or None
        elif isinstance(value, bool | int | float):
            fields[key] = value
        elif isinstance(value, list) and all(
            isinstance(item, str | int | float | bool | dict) for item in value
        ):
            fields[key] = [item.strip() if isinstance(item, str) else item for item in value]
        else:
            warnings.append(f"{key}: unusable value dropped")
            fields[key] = None
    return fields, warnings


async def reading_enabled(db: AsyncSession) -> bool:
    return await SettingsService.get_bool(db, DOCUMENT_READING_SETTING, default=False)


async def read_document(
    db: AsyncSession,
    *,
    kind: DocumentKind,
    file_bytes: bytes,
    filename: str | None,
    content_type: str | None,
) -> DocumentReadResult:
    """See the module docstring. Raises 409 when neither path can read the file."""
    prompt = prompt_for(kind)

    if is_pdf(filename, content_type) and await asyncio.to_thread(has_text_layer, file_bytes):
        from app.services.document_ocr import DocumentOCRService

        text = await DocumentOCRService().extract_text_from_bytes(file_bytes, is_pdf=True)
        return DocumentReadResult(kind=kind, source="text", raw_text=text)

    if not await reading_enabled(db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AI_READING_NOT_CONFIGURED)

    try:
        images = await asyncio.to_thread(to_images, file_bytes, filename, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    content = await llm_client.vision_completion(
        db, system=prompt.system, user_text=prompt.user_text, images=images
    )
    raw = llm_client.extract_json_object(str(content))
    fields, warnings = coerce_fields(raw, prompt.keys)
    model = await llm_client.vision_model(db)
    logger.info(
        "Document %s read by %s (%d image(s), %d warning(s))",
        sanitize_for_log(kind),
        sanitize_for_log(model),
        len(images),
        len(warnings),
    )
    return DocumentReadResult(
        kind=kind,
        source="llm",
        fields=fields,
        warnings=warnings,
        model=model,
        pages=len(images),
    )
