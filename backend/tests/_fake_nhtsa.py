"""A fake NHTSA behind httpx, shared by the outage and scheduled-check tests.

Nothing here touches the network or DNS: `serve` swaps `httpx.AsyncClient.get`
for a function of the URL and turns hostname resolution off, so the SSRF
check in `NHTSAService` passes without a lookup.
"""

from collections.abc import Callable

import httpx
import pytest

MAINTENANCE_PAGE = "<html><body>NHTSA is down for maintenance</body></html>"


def is_decode(url: str) -> bool:
    """Whether `url` is a vPIC decode rather than a recalls lookup."""
    return "/DecodeVinValues/" in httpx.URL(url).path


def decode_answer(
    request: httpx.Request, *, make: str = "HONDA", model: str = "Accord"
) -> httpx.Response:
    """vPIC decoding the VIN to a 2020 `make` `model`. A blank model is a VIN it can't resolve."""
    result = {"Make": make, "Model": model, "ModelYear": "2020", "ErrorCode": "0"}
    return httpx.Response(200, request=request, json={"Results": [result]})


def failure(request: httpx.Request, how: str) -> httpx.Response:
    """The response for `how`, or the transport error it stands for."""
    if how == "timeout":
        raise httpx.ReadTimeout("timed out", request=request)
    if how == "read-error":
        raise httpx.ReadError("connection reset", request=request)
    if how == "decoding-error":
        raise httpx.DecodingError("bad gzip stream", request=request)
    if how == "too-many-redirects":
        raise httpx.TooManyRedirects("redirect loop", request=request)
    if how == "503":
        return httpx.Response(503, request=request, text=MAINTENANCE_PAGE)
    if how == "400":
        return httpx.Response(400, request=request, text=MAINTENANCE_PAGE)
    if how == "not-json":
        return httpx.Response(200, request=request, text=MAINTENANCE_PAGE)
    raise AssertionError(how)


def serve(monkeypatch: pytest.MonkeyPatch, answer: Callable[[str], httpx.Response]) -> None:
    """Answer every httpx GET with `answer(url)`, with DNS lookups off."""

    async def fake_get(client: object, url: str, **kwargs: object) -> httpx.Response:
        return answer(url)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)
