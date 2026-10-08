"""Shared OpenAI-compatible chat client for opt-in LLM features.

Reads ``llm_base_url``, ``llm_model``, and ``llm_api_key`` from settings.
Used by fuel receipt parse, Ask My Garage and, with ``vision_completion``,
the document reader (#211): the same ``/chat/completions`` endpoint, with
the images of a document sent as ``image_url`` parts, to the model named by
``llm_vision_model`` (or ``llm_model`` when blank). Nothing here decides
whether a feature is on; the services check their own flag first.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.settings_service import SecretUnreadableError, SettingsService, reenter_message

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "llama3.2"

#: The settings keys the client reads (and the settings route validates).
LLM_BASE_URL_SETTING = "llm_base_url"
LLM_MODEL_SETTING = "llm_model"
LLM_API_KEY_SETTING = "llm_api_key"
LLM_VISION_MODEL_SETTING = "llm_vision_model"
LLM_PRESET_SETTING = "llm_provider_preset"
#: What the settings card may store in ``llm_provider_preset``: a hint for
#: the UI, never read by the client itself.
LLM_PROVIDER_PRESETS: tuple[str, ...] = ("custom", "openrouter", "ollama", "openai")

#: Sent when the endpoint is OpenRouter, which asks apps to identify
#: themselves this way (both headers are optional and ignored elsewhere).
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/homelabforge/mygarage",
    "X-Title": "MyGarage",
}


def is_http_url(value: str) -> bool:
    """Whether ``value`` is an absolute http(s) URL with a host."""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


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
    except ValueError:
        # JSONDecodeError is a ValueError, and so is an int past 4300 digits.
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM response did not contain a JSON object",
        )
    try:
        data = json.loads(match.group(0))
    except ValueError as err:
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


def is_openrouter(base_url: str) -> bool:
    """Whether the configured endpoint is OpenRouter."""
    return "openrouter.ai" in base_url.lower()


async def _endpoint(db: AsyncSession) -> tuple[str, dict[str, str]]:
    """The base URL (trailing slash trimmed) and the request headers."""
    base_url = (await setting(db, LLM_BASE_URL_SETTING, DEFAULT_BASE_URL)).rstrip("/")
    try:
        # Optional: a blank key calls without auth, so an unreadable one must stop
        # here rather than read as blank (R1-M1).
        api_key = await SettingsService.get_secret(db, LLM_API_KEY_SETTING) or ""
    except SecretUnreadableError as err:
        logger.error("LLM call refused: the stored %s can't be decrypted", err.key)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=reenter_message("LLM API key"),
        ) from err
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if is_openrouter(base_url):
        headers.update(OPENROUTER_HEADERS)
    return base_url, headers


async def _post_chat(db: AsyncSession, payload: dict[str, Any], *, timeout: float) -> str:
    """POST ``/chat/completions`` and return the assistant message content.

    Every failure is a 502 with a sentence the caller can show: the endpoint
    is the operator's, and a 4xx from it (a wrong key, a model the endpoint
    does not have) is still not the user's fault.
    """
    base_url, headers = await _endpoint(db)
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


async def chat_completion(
    db: AsyncSession,
    *,
    system: str,
    user: str,
    temperature: float = 0,
    timeout: float = 60.0,
) -> str:
    """A text-only completion with ``llm_model``."""
    model = await setting(db, LLM_MODEL_SETTING, DEFAULT_MODEL)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    return await _post_chat(db, payload, timeout=timeout)


async def vision_model(db: AsyncSession) -> str:
    """The model the document reader uses: ``llm_vision_model``, else ``llm_model``."""
    return (await setting(db, LLM_VISION_MODEL_SETTING, "")).strip() or await setting(
        db, LLM_MODEL_SETTING, DEFAULT_MODEL
    )


def image_part(image: bytes, mime: str) -> dict[str, Any]:
    """One ``image_url`` content part carrying the image inline (base64)."""
    encoded = base64.b64encode(image).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


async def vision_completion(
    db: AsyncSession,
    *,
    system: str,
    user_text: str,
    images: list[tuple[bytes, str]],
    temperature: float = 0,
    timeout: float = 90.0,
    max_tokens: int = 2000,
) -> str:
    """A completion whose user message carries images (``(bytes, mime)`` pairs).

    The OpenAI chat format: a text part followed by one ``image_url`` part per
    image, each a ``data:`` URL, which every OpenAI-compatible endpoint with a
    vision model accepts (OpenRouter, Ollama, OpenAI). ``max_tokens`` bounds
    the answer, which is a JSON object of a few dozen fields at most.
    """
    if not images:
        raise ValueError("vision_completion needs at least one image")
    model = await vision_model(db)
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    content.extend(image_part(image, mime) for image, mime in images)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return await _post_chat(db, payload, timeout=timeout)


# --- Connection test ---------------------------------------------------------


@dataclass
class ProbeResult:
    """What ``POST /api/settings/test/llm`` reports."""

    text_ok: bool
    #: None when the vision check was not run (document reading is off).
    vision_ok: bool | None
    message: str
    model: str
    vision_model: str

    @property
    def valid(self) -> bool:
        return self.text_ok and self.vision_ok is not False


def _probe_image() -> bytes:
    """A 64×64 solid red PNG, built in memory: the smallest image a vision
    model can be asked a question about."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (220, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


async def probe(db: AsyncSession, *, check_vision: bool, timeout: float = 30.0) -> ProbeResult:
    """Exercise the configured endpoint once as text and, when asked, once as vision.

    Never raises for an endpoint failure: the 502 detail becomes the message,
    which is what the settings card shows. The checks are cheap on purpose
    (a one-word answer, a 64×64 image) so an operator can press the button
    freely while tuning the settings.
    """
    model = await setting(db, LLM_MODEL_SETTING, DEFAULT_MODEL)
    vision = await vision_model(db)
    try:
        answer = await chat_completion(
            db,
            system="You are a connectivity check. Reply with the single word OK.",
            user="Reply with OK.",
            timeout=timeout,
        )
    except HTTPException as exc:
        return ProbeResult(
            text_ok=False,
            vision_ok=None,
            message=str(exc.detail),
            model=model,
            vision_model=vision,
        )
    if not answer.strip():
        return ProbeResult(
            text_ok=False,
            vision_ok=None,
            message="The endpoint answered with an empty message",
            model=model,
            vision_model=vision,
        )
    if not check_vision:
        return ProbeResult(
            text_ok=True, vision_ok=None, message="Text model OK", model=model, vision_model=vision
        )
    try:
        colour = await vision_completion(
            db,
            system="You describe images in one word.",
            user_text="What colour is this square? Answer with one word.",
            images=[(_probe_image(), "image/png")],
            timeout=timeout,
            max_tokens=20,
        )
    except HTTPException as exc:
        return ProbeResult(
            text_ok=True,
            vision_ok=False,
            message=f"Text model OK; vision model failed: {exc.detail}",
            model=model,
            vision_model=vision,
        )
    if not colour.strip():
        return ProbeResult(
            text_ok=True,
            vision_ok=False,
            message="Text model OK; the vision model answered with an empty message",
            model=model,
            vision_model=vision,
        )
    return ProbeResult(
        text_ok=True,
        vision_ok=True,
        message="Text model OK; vision model OK",
        model=model,
        vision_model=vision,
    )
