"""Shared OpenAI-compatible chat client for opt-in LLM features.

Reads ``llm_base_url``, ``llm_model``, and ``llm_api_key`` from settings.
Used by fuel receipt parse and Ask My Garage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import SecretUnreadableError, SettingsService, reenter_message

logger = logging.getLogger(__name__)


async def setting(db: AsyncSession, key: str, default: str = "") -> str:
    row = await SettingsService.get(db, key)
    return (row.value if row and row.value is not None else default) or default


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM response, tolerating surrounding prose."""
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


async def chat_completion(
    db: AsyncSession,
    *,
    system: str,
    user: str,
    temperature: float = 0,
    timeout: float = 60.0,
) -> str:
    """POST ``/chat/completions`` and return the assistant message content."""
    base_url = (await setting(db, "llm_base_url", "http://127.0.0.1:11434/v1")).rstrip("/")
    model = await setting(db, "llm_model", "llama3.2")
    try:
        # Optional: a blank key calls without auth, so an unreadable one must stop
        # here rather than read as blank (R1-M1).
        api_key = await SettingsService.get_secret(db, "llm_api_key") or ""
    except SecretUnreadableError as err:
        logger.error("LLM call refused: the stored %s can't be decrypted", err.key)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=reenter_message("LLM API key"),
        ) from err

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as err:
        logger.error("LLM chat completion HTTP error: %s", err)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM endpoint request failed",
        ) from err

    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected LLM response shape",
        ) from err
