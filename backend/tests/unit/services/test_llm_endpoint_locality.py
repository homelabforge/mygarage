"""Whether the LLM endpoint is on the household's own network (#211, F-2).

A document only goes to a vision model outside the network with the
person's consent, so the classification fails closed: a name that does not
resolve, or resolves to any public address, is external. The resolver is
mocked; nothing here touches DNS.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

from app.services import llm_client


def _infos(*addresses: str) -> list[tuple[Any, ...]]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 0),
        )
        for address in addresses
    ]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    llm_client.clear_locality_cache()
    yield
    llm_client.clear_locality_cache()


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch):
    """Answer ``getaddrinfo`` from a table and count the lookups."""
    calls: list[str] = []

    def _install(table: dict[str, list[str] | None]) -> list[str]:
        def _fake(host: str, *_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
            calls.append(host)
            answer = table.get(host)
            if answer is None:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
            return _infos(*answer)

        monkeypatch.setattr(llm_client, "_resolve", _fake)
        return calls

    return _install


@pytest.mark.asyncio
class TestIsLocalEndpoint:
    @pytest.mark.parametrize(
        "base_url",
        [
            "http://127.0.0.1:11434/v1",
            "http://[::1]:11434/v1",
            "http://192.168.1.20:11434/v1",
            "http://10.0.0.5/v1",
            "http://172.17.0.1:11434/v1",
            "http://169.254.10.10/v1",
            "http://100.101.102.103:11434/v1",  # Tailscale (100.64.0.0/10)
            "http://[fd7a:115c:a1e0::1]:11434/v1",  # Tailscale IPv6 ULA
        ],
    )
    async def test_private_address_literals_are_local(self, resolver, base_url: str):
        calls = resolver({})
        assert await llm_client.is_local_endpoint(base_url) is True
        assert calls == []  # a literal is never looked up

    @pytest.mark.parametrize(
        "base_url", ["https://8.8.8.8/v1", "https://[2606:4700::1111]/v1", "http://100.128.0.1/v1"]
    )
    async def test_public_address_literals_are_external(self, resolver, base_url: str):
        resolver({})
        assert await llm_client.is_local_endpoint(base_url) is False

    @pytest.mark.parametrize(
        "base_url", ["http://ollama:11434/v1", "http://localhost:11434/v1", "http://nas.local/v1"]
    )
    async def test_single_label_and_dot_local_names_are_local(self, resolver, base_url: str):
        calls = resolver({})
        assert await llm_client.is_local_endpoint(base_url) is True
        assert calls == []

    async def test_names_resolving_to_private_addresses_are_local(self, resolver):
        resolver(
            {
                "host.docker.internal": ["172.17.0.1"],
                "llm.lan": ["192.168.2.40"],
                "gpu.tail1234.ts.net": ["100.88.1.2", "fd7a:115c:a1e0::2"],
            }
        )
        assert await llm_client.is_local_endpoint("http://host.docker.internal:11434/v1")
        assert await llm_client.is_local_endpoint("http://llm.lan/v1")
        assert await llm_client.is_local_endpoint("http://gpu.tail1234.ts.net:11434/v1")

    async def test_a_public_name_is_external(self, resolver):
        resolver({"openrouter.ai": ["104.18.2.115"], "api.openai.com": ["162.159.140.245"]})
        assert await llm_client.is_local_endpoint("https://openrouter.ai/api/v1") is False
        assert await llm_client.is_local_endpoint("https://api.openai.com/v1") is False

    async def test_any_public_address_makes_it_external(self, resolver):
        resolver({"split.example.com": ["192.168.1.5", "93.184.216.34"]})
        assert await llm_client.is_local_endpoint("https://split.example.com/v1") is False

    async def test_an_unresolvable_name_is_external(self, resolver):
        resolver({})
        assert await llm_client.is_local_endpoint("https://nowhere.example.com/v1") is False

    async def test_a_url_without_a_host_is_external(self, resolver):
        resolver({})
        assert await llm_client.is_local_endpoint("not a url") is False

    async def test_the_answer_is_cached_per_base_url(self, resolver):
        calls = resolver({"llm.lan": ["192.168.2.40"]})
        for _ in range(3):
            assert await llm_client.is_local_endpoint("http://llm.lan/v1")
        assert calls == ["llm.lan"]
