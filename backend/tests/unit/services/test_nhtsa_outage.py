"""`get_vehicle_recalls`: an NHTSA outage is not "no recalls".

The scheduled recall check leaves `nhtsa_last_check` alone when NHTSA didn't
answer, and the manual check answers 502 (B5-1). A timeout, any other transport error, a body
httpx can't decode, a redirect loop, an HTTP error status or a 200 whose body
isn't JSON raises `NHTSAUnavailableError` from the vPIC decode and from the
recalls fetch alike. A VIN vPIC can't
resolve is still a `ValueError`: that vehicle can't be checked, which no
retry fixes.

The name is looked up on the module inside each test, so on code without it
each test fails on its own instead of the whole file failing to import.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import nhtsa as nhtsa_module
from app.services.nhtsa import NHTSAService
from tests._fake_nhtsa import decode_answer, failure, is_decode, serve

pytestmark = pytest.mark.unit

VIN = "1HGCM82673A123456"


def _serve(monkeypatch: pytest.MonkeyPatch, *, step: str | None, how: str = "") -> None:
    """Answer both requests normally except `step` ("decode" or "recalls"),
    which fails as `how`."""

    def answer(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        decode = is_decode(url)
        if step == ("decode" if decode else "recalls"):
            return failure(request, how)
        if decode:
            return decode_answer(request)
        return httpx.Response(200, request=request, json={"results": []})

    serve(monkeypatch, answer)


_ORIGINAL = {
    "timeout": httpx.TransportError,
    "read-error": httpx.TransportError,
    "decoding-error": httpx.DecodingError,
    "too-many-redirects": httpx.TooManyRedirects,
    "503": httpx.HTTPStatusError,
    "400": httpx.HTTPStatusError,
    "not-json": ValueError,
}


@pytest.mark.parametrize("step", ["decode", "recalls"])
@pytest.mark.parametrize("how", list(_ORIGINAL))
async def test_an_outage_raises_unavailable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, step: str, how: str
) -> None:
    """Every outage shape, at either step, is `NHTSAUnavailableError`, chained
    from the original error and carrying none of the response body.

    The decoding-error and too-many-redirects rows were also red on the branch
    before the fix wave, whose outage set was `httpx.TransportError`: those
    two are `httpx.RequestError`s outside it, so the decode step wrapped them
    as a `ValueError` and the recalls step let them escape unclassified.
    """
    unavailable = nhtsa_module.NHTSAUnavailableError
    _serve(monkeypatch, step=step, how=how)

    with pytest.raises(unavailable) as caught:
        await NHTSAService().get_vehicle_recalls(VIN, db_session)

    assert not isinstance(caught.value, ValueError)
    assert isinstance(caught.value.__cause__, _ORIGINAL[how])
    assert "maintenance" not in str(caught.value)


async def test_an_undecodable_vin_is_still_a_value_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vPIC answering without a model is a vehicle that can't be checked, not
    an outage."""

    serve(monkeypatch, lambda url: decode_answer(httpx.Request("GET", url), model=""))

    with pytest.raises(ValueError, match="make, model, and year"):
        await NHTSAService().get_vehicle_recalls(VIN, db_session)


#: What api.nhtsa.gov sends for a make, model and year with no recalls.
NO_RECALLS = {"Count": 0, "Message": "Results returned successfully", "results": []}


async def test_a_400_saying_no_recalls_is_no_recalls(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NHTSA answers a car with a clean record with a 400 and an empty
    `results`. That's an answer: red on 3.10.0-rc1, where the scheduled check
    read it as an outage and held `nhtsa_last_check` back every night."""

    def answer(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        if is_decode(url):
            return decode_answer(request)
        return httpx.Response(400, request=request, json=NO_RECALLS)

    serve(monkeypatch, answer)

    recalls = await NHTSAService().get_vehicle_recalls(VIN, db_session)

    assert recalls == []


@pytest.mark.parametrize(
    "body", [{"results": [{"NHTSACampaignNumber": "25V297000"}]}, {"message": "Bad Request"}]
)
async def test_any_other_400_is_still_an_outage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
) -> None:
    """Only the empty answer passes: a 400 with results in it, or without a
    `results` list at all, is still NHTSA not answering usably."""

    def answer(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        if is_decode(url):
            return decode_answer(request)
        return httpx.Response(400, request=request, json=body)

    serve(monkeypatch, answer)

    with pytest.raises(nhtsa_module.NHTSAUnavailableError):
        await NHTSAService().get_vehicle_recalls(VIN, db_session)
