"""Ask My Garage — grounded Q&A over vehicle records and DTC enrichment."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.garage_assistant import (
    AssistantCitation,
    AssistantHistoryMessage,
    GarageAssistantChatResponse,
)
from app.services import llm_client
from app.services.garage_context_service import build_garage_context
from app.utils.render_context import UserRenderContextSource, render_context_for_request

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are Ask My Garage, a vehicle assistant for the user's own garage log.

Rules:
1. Answer ONLY using the JSON context provided. Never invent fluid specs, torque values, or repair procedures from year/make/model knowledge.
2. If a requested fact is missing from context, say so clearly and name what the user can add (e.g. oil_viscosity in Specs, or log DTCs via LiveLink).
3. For diagnostics: use only active_dtcs, recently_cleared_dtcs, and looked_up_codes (including common_causes, symptoms, fix_guidance). Do not invent diagnostic steps beyond that enrichment. Frame answers as guidance, not a professional diagnosis; suggest a qualified technician for safety-critical issues.
4. Prefer concise, practical answers. When you quote oil capacity or lug torque, copy the string from maintenance_specs.display VERBATIM: it is already in this reader's own units. Never convert a value, and never name a unit that is not in the context.
5. Reply with ONLY a JSON object:
{"answer":"...","citations":[{"source":"vehicle_spec|service_visit|note|supply|tire|reminder|dtc|dtc_definition|trailer","label":"...","detail":"..."}],"missing":["field_or_topic",...]}
Use an empty citations/missing array when none apply. citation source must be one of the listed values.
"""


def _coerce_citations(raw: Any) -> list[AssistantCitation]:
    if not isinstance(raw, list):
        return []
    allowed = {
        "vehicle_spec",
        "service_visit",
        "note",
        "supply",
        "tire",
        "reminder",
        "dtc",
        "dtc_definition",
        "trailer",
    }
    out: list[AssistantCitation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        label = item.get("label")
        if source not in allowed or not isinstance(label, str) or not label.strip():
            continue
        detail = item.get("detail")
        out.append(
            AssistantCitation(
                source=source,  # type: ignore[arg-type]
                label=label.strip()[:120],
                detail=(str(detail)[:300] if detail is not None else None),
            )
        )
    return out


def _coerce_missing(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:80])
    return out


async def ask_garage(
    db: AsyncSession,
    *,
    vin: str,
    message: str,
    history: list[AssistantHistoryMessage] | None = None,
    current_user: UserRenderContextSource | None = None,
) -> GarageAssistantChatResponse:
    """Grounded chat turn. Raises 403 when the assistant setting is disabled.

    :param current_user: Whose units the answer is rendered in. The CALLER's,
        not the vehicle owner's: ``get_vehicle_or_403`` admits admins and
        shared viewers, and a shared viewer should read their own units.
    """
    if not await llm_client.setting_enabled(db, "llm_garage_assistant_enabled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ask My Garage assistant is disabled",
        )

    ctx = await render_context_for_request(current_user, db)
    context = await build_garage_context(db, vin, user_message=message, ctx=ctx)
    if not context:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    history_block = ""
    if history:
        lines = []
        for turn in history[-6:]:
            lines.append(f"{turn.role}: {turn.content[:500]}")
        history_block = "Prior turns:\n" + "\n".join(lines) + "\n\n"

    user_payload = (
        f"{history_block}"
        f"Garage context (JSON):\n{json.dumps(context, default=str)}\n\n"
        f"User question: {message.strip()}"
    )

    content = await llm_client.chat_completion(
        db,
        system=_SYSTEM_PROMPT,
        user=user_payload,
        temperature=0,
        timeout=90.0,
    )
    raw = llm_client.extract_json_object(str(content))
    answer = raw.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM response missing answer",
        )

    return GarageAssistantChatResponse(
        answer=answer.strip(),
        citations=_coerce_citations(raw.get("citations")),
        missing=_coerce_missing(raw.get("missing")),
    )
