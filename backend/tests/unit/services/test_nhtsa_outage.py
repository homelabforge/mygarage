"""`get_vehicle_recalls(raise_on_error=True)`: an NHTSA outage is not "no recalls".

The scheduled recall check asks for this so it can leave `nhtsa_last_check`
alone when NHTSA didn't answer. A timeout, any other transport error, an HTTP
error status or a 200 whose body isn't JSON raises `NHTSAUnavailableError`
from the vPIC decode and from the recalls fetch alike. A VIN vPIC can't
resolve is still a `ValueError`: that vehicle can't be checked, which no
retry fixes. Without the flag (the manual check) nothing changes.

The name is looked up on the module inside each test, so on code without it
each test fails on its own instead of the whole file failing to import.
"""

from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import nhtsa as nhtsa_module
from app.services.nhtsa import NHTSAService

pytestmark = pytest.mark.unit

VIN = "1HGCM82673A123456"
MAINTENANCE_PAGE = "<html><body>NHTSA is down for maintenance</body></html>"


def _decode_answer(request: httpx.Request, *, model: str = "Accord") -> httpx.Response:
    """vPIC decoding the VIN to a 2020 Honda `model`."""
    result = {"Make": "HONDA", "Model": model, "ModelYear": "2020", "ErrorCode": "0"}
    return httpx.Response(200, request=request, json={"Results": [result]})


def _failure(request: httpx.Request, how: str) -> httpx.Response:
    """The response for `how`, or the transport error it stands for."""
    if how == "timeout":
        raise httpx.ReadTimeout("timed out", request=request)
    if how == "read-error":
        raise httpx.ReadError("connection reset", request=request)
    if how == "503":
        return httpx.Response(503, request=request, text=MAINTENANCE_PAGE)
    if how == "not-json":
        return httpx.Response(200, request=request, text=MAINTENANCE_PAGE)
    raise AssertionError(how)


def _serve(monkeypatch: pytest.MonkeyPatch, *, step: str | None, how: str = "") -> None:
    """Answer both requests normally except `step` ("decode" or "recalls"),
    which fails as `how`. No network, no DNS."""

    async def fake_get(client: object, url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("GET", url)
        is_decode = "/DecodeVinValues/" in urlsplit(url).path
        if step == ("decode" if is_decode else "recalls"):
            return _failure(request, how)
        if is_decode:
            return _decode_answer(request)
        return httpx.Response(200, request=request, json={"results": []})

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)


_ORIGINAL = {
    "timeout": httpx.TransportError,
    "read-error": httpx.TransportError,
    "503": httpx.HTTPStatusError,
    "not-json": ValueError,
}


@pytest.mark.parametrize("step", ["decode", "recalls"])
@pytest.mark.parametrize("how", ["timeout", "read-error", "503", "not-json"])
async def test_an_outage_raises_unavailable_when_asked(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, step: str, how: str
) -> None:
    """Every outage shape, at either step, is `NHTSAUnavailableError`, chained
    from the original error and carrying none of the response body.

    Red on main: there was no such error and no `raise_on_error`.
    """
    unavailable = nhtsa_module.NHTSAUnavailableError
    _serve(monkeypatch, step=step, how=how)

    with pytest.raises(unavailable) as caught:
        await NHTSAService().get_vehicle_recalls(VIN, db_session, raise_on_error=True)

    assert not isinstance(caught.value, ValueError)
    assert isinstance(caught.value.__cause__, _ORIGINAL[how])
    assert "maintenance" not in str(caught.value)


async def test_an_undecodable_vin_is_still_a_value_error_when_asked(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vPIC answering without a model is a vehicle that can't be checked, not
    an outage. Red on main only because `raise_on_error` didn't exist."""

    async def fake_get(client: object, url: str, **kwargs: object) -> httpx.Response:
        return _decode_answer(httpx.Request("GET", url), model="")

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)

    with pytest.raises(ValueError, match="make, model, and year"):
        await NHTSAService().get_vehicle_recalls(VIN, db_session, raise_on_error=True)


async def test_by_default_a_recalls_timeout_is_still_no_recalls(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: the manual check keeps its fallback (B5-1)."""
    _serve(monkeypatch, step="recalls", how="timeout")

    assert await NHTSAService().get_vehicle_recalls(VIN, db_session) == []


async def test_by_default_a_decode_timeout_is_still_a_value_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: the manual check still maps it to its 422."""
    _serve(monkeypatch, step="decode", how="timeout")

    with pytest.raises(ValueError, match="Could not decode VIN"):
        await NHTSAService().get_vehicle_recalls(VIN, db_session)
