"""The vision side of the shared LLM client (#211).

What the endpoint receives is the contract: a text part followed by one
``image_url`` part per image, the vision model (or the text model when none
is set), OpenRouter's identification headers only when the endpoint is
OpenRouter, and a 502 for every transport failure. ``chat_completion`` is
exercised too, because it now shares ``_post_chat`` and must send exactly
what it sent before the refactor.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services import llm_client

LLM_KEYS = ("llm_base_url", "llm_model", "llm_api_key", "llm_vision_model")


async def _set(db: AsyncSession, values: dict[str, str]) -> None:
    for key, value in values.items():
        row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if row is None:
            db.add(Setting(key=key, value=value, category="integrations"))
        else:
            row.value = value
    await db.commit()


@pytest_asyncio.fixture
async def llm_settings(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Snapshot the LLM rows and put them back: the test DB is shared."""
    before: dict[str, str | None] = {}
    for key in LLM_KEYS:
        row = (
            await db_session.execute(select(Setting).where(Setting.key == key))
        ).scalar_one_or_none()
        before[key] = row.value if row is not None else None
    try:
        yield db_session
    finally:
        for key, value in before.items():
            row = (
                await db_session.execute(select(Setting).where(Setting.key == key))
            ).scalar_one_or_none()
            if value is None:
                if row is not None:
                    await db_session.delete(row)
            elif row is None:
                db_session.add(Setting(key=key, value=value, category="integrations"))
            else:
                row.value = value
        await db_session.commit()


def _mock_client(content: Any = "OK") -> tuple[Any, AsyncMock]:
    """A patched ``httpx.AsyncClient`` whose ``post`` returns ``content``."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"choices": [{"message": {"content": content}}]})
    instance = AsyncMock()
    instance.post = AsyncMock(return_value=response)
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    patcher = patch("httpx.AsyncClient", return_value=instance)
    return patcher, instance.post


PNG = b"\x89PNG\r\n\x1a\nfake"
JPG = b"\xff\xd8\xff\xe0fake"


@pytest.mark.asyncio
class TestVisionCompletion:
    async def test_user_message_carries_text_then_one_part_per_image(self, llm_settings):
        await _set(llm_settings, {"llm_model": "llava", "llm_vision_model": ""})
        patcher, post = _mock_client('{"A": "AB-123-CD"}')
        with patcher:
            answer = await llm_client.vision_completion(
                llm_settings,
                system="SYS",
                user_text="Read it",
                images=[(PNG, "image/png"), (JPG, "image/jpeg")],
            )
        assert answer == '{"A": "AB-123-CD"}'
        payload = post.call_args.kwargs["json"]
        assert payload["model"] == "llava"
        assert payload["temperature"] == 0
        assert payload["max_tokens"] == 2000
        system, user = payload["messages"]
        assert system == {"role": "system", "content": "SYS"}
        assert user["role"] == "user"
        parts = user["content"]
        assert parts[0] == {"type": "text", "text": "Read it"}
        assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
        assert parts[1]["image_url"]["url"] == (
            "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
        )
        assert parts[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    async def test_vision_model_setting_wins_over_text_model(self, llm_settings):
        await _set(llm_settings, {"llm_model": "llama3.2", "llm_vision_model": "qwen2.5vl"})
        patcher, post = _mock_client()
        with patcher:
            await llm_client.vision_completion(
                llm_settings, system="s", user_text="u", images=[(PNG, "image/png")]
            )
        assert post.call_args.kwargs["json"]["model"] == "qwen2.5vl"
        assert await llm_client.vision_model(llm_settings) == "qwen2.5vl"

    async def test_blank_vision_model_falls_back_to_text_model(self, llm_settings):
        await _set(llm_settings, {"llm_model": "llama3.2", "llm_vision_model": "   "})
        assert await llm_client.vision_model(llm_settings) == "llama3.2"

    async def test_no_images_is_a_programming_error(self, llm_settings):
        with pytest.raises(ValueError):
            await llm_client.vision_completion(llm_settings, system="s", user_text="u", images=[])

    async def test_openrouter_gets_its_identification_headers(self, llm_settings):
        await _set(
            llm_settings,
            {"llm_base_url": "https://openrouter.ai/api/v1/", "llm_api_key": "sk-or-test"},
        )
        patcher, post = _mock_client()
        with patcher:
            await llm_client.vision_completion(
                llm_settings, system="s", user_text="u", images=[(PNG, "image/png")]
            )
        assert post.call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"
        headers = post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-or-test"
        assert headers["HTTP-Referer"] == llm_client.OPENROUTER_HEADERS["HTTP-Referer"]
        assert headers["X-Title"] == "MyGarage"

    async def test_other_endpoints_get_no_openrouter_headers(self, llm_settings):
        await _set(llm_settings, {"llm_base_url": "http://127.0.0.1:11434/v1", "llm_api_key": ""})
        patcher, post = _mock_client()
        with patcher:
            await llm_client.chat_completion(llm_settings, system="s", user="u")
        headers = post.call_args.kwargs["headers"]
        assert "HTTP-Referer" not in headers
        assert "X-Title" not in headers
        assert "Authorization" not in headers

    async def test_transport_failure_is_a_502(self, llm_settings):
        instance = AsyncMock()
        instance.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with patch("httpx.AsyncClient", return_value=instance):
            with pytest.raises(HTTPException) as exc:
                await llm_client.vision_completion(
                    llm_settings, system="s", user_text="u", images=[(PNG, "image/png")]
                )
        assert exc.value.status_code == 502

    async def test_unexpected_shape_is_a_502(self, llm_settings):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json = MagicMock(return_value={"error": "nope"})
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with patch("httpx.AsyncClient", return_value=instance):
            with pytest.raises(HTTPException) as exc:
                await llm_client.chat_completion(llm_settings, system="s", user="u")
        assert exc.value.status_code == 502


@pytest.mark.asyncio
class TestChatCompletionUnchanged:
    async def test_text_payload_is_the_pre_refactor_shape(self, llm_settings):
        await _set(llm_settings, {"llm_model": "llama3.2", "llm_vision_model": "qwen2.5vl"})
        patcher, post = _mock_client("hello")
        with patcher:
            answer = await llm_client.chat_completion(
                llm_settings, system="SYS", user="USER", temperature=0.2
            )
        assert answer == "hello"
        payload = post.call_args.kwargs["json"]
        # The text path ignores the vision model and sends no max_tokens.
        assert payload == {
            "model": "llama3.2",
            "messages": [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "USER"},
            ],
            "temperature": 0.2,
        }


class TestIsHttpUrl:
    @pytest.mark.parametrize(
        "value",
        [
            "http://127.0.0.1:11434/v1",
            "https://openrouter.ai/api/v1",
            "https://api.openai.com/v1/",
            "  http://ollama.lan:11434/v1  ",
        ],
    )
    def test_accepts_absolute_http_urls(self, value: str):
        assert llm_client.is_http_url(value)

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "localhost:11434",
            "127.0.0.1:11434/v1",
            "ftp://x/v1",
            "http://",
            "/v1",
            "https:///v1",
        ],
    )
    def test_rejects_anything_else(self, value: str):
        assert not llm_client.is_http_url(value)


@pytest.mark.asyncio
class TestProbe:
    async def test_text_only_when_vision_not_requested(self, llm_settings):
        await _set(llm_settings, {"llm_model": "llama3.2", "llm_vision_model": ""})
        patcher, post = _mock_client("OK")
        with patcher:
            result = await llm_client.probe(llm_settings, check_vision=False)
        assert result.valid is True
        assert result.text_ok is True
        assert result.vision_ok is None
        assert result.model == "llama3.2"
        assert result.vision_model == "llama3.2"
        assert post.await_count == 1

    async def test_text_and_vision_both_pass(self, llm_settings):
        await _set(llm_settings, {"llm_model": "llama3.2", "llm_vision_model": "llava"})
        patcher, post = _mock_client("red")
        with patcher:
            result = await llm_client.probe(llm_settings, check_vision=True)
        assert result.valid is True
        assert (result.text_ok, result.vision_ok) == (True, True)
        assert result.vision_model == "llava"
        assert post.await_count == 2
        vision_payload = post.call_args_list[1].kwargs["json"]
        assert vision_payload["model"] == "llava"
        parts = vision_payload["messages"][1]["content"]
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    async def test_text_failure_stops_before_vision(self, llm_settings):
        instance = AsyncMock()
        instance.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with patch("httpx.AsyncClient", return_value=instance):
            result = await llm_client.probe(llm_settings, check_vision=True)
        assert result.valid is False
        assert result.text_ok is False
        assert result.vision_ok is None
        assert "failed" in result.message
        assert instance.post.await_count == 1

    async def test_vision_failure_is_reported_not_raised(self, llm_settings):
        ok = MagicMock()
        ok.raise_for_status = MagicMock()
        ok.json = MagicMock(return_value={"choices": [{"message": {"content": "OK"}}]})
        instance = AsyncMock()
        instance.post = AsyncMock(side_effect=[ok, httpx.ReadTimeout("slow")])
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        with patch("httpx.AsyncClient", return_value=instance):
            result = await llm_client.probe(llm_settings, check_vision=True)
        assert result.valid is False
        assert (result.text_ok, result.vision_ok) == (True, False)
        assert result.message.startswith("Text model OK; vision model failed")

    async def test_empty_answer_is_not_ok(self, llm_settings):
        patcher, _post = _mock_client("   ")
        with patcher:
            result = await llm_client.probe(llm_settings, check_vision=False)
        assert result.valid is False
        assert "empty" in result.message
