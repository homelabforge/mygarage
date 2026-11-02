"""The Overpass search identifies itself.

The public Overpass instances refuse httpx's default User-Agent:
overpass-api.de with 406 Not Acceptable, overpass.openstreetmap.fr with
403 Forbidden. Every OSM search then came back empty, which, with no keyed
provider configured, is every POI search. Nominatim (routes/poi.py) already
sent an identifying User-Agent; the Overpass provider sent none.
"""

import asyncio

import httpx
import pytest

from app.services.poi import osm
from app.services.poi.base import POICategory
from app.services.poi.osm import OSMProvider

STATION = {
    "type": "node",
    "id": 1,
    "lat": -34.0336,
    "lon": 18.4468,
    "tags": {"amenity": "fuel", "name": "Engen Meadowridge", "brand": "Engen"},
}


def _like_overpass(seen: list[str]):
    """A transport that answers like the public instances: default UA refused."""

    def handle(request: httpx.Request) -> httpx.Response:
        agent = request.headers.get("user-agent", "")
        seen.append(agent)
        if agent.startswith("python-httpx"):
            return httpx.Response(406, request=request)
        return httpx.Response(200, json={"elements": [STATION]}, request=request)

    return handle


@pytest.mark.asyncio
async def test_search_sends_an_identifying_user_agent(monkeypatch):
    seen: list[str] = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        osm.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(_like_overpass(seen)), **kw),
    )

    results = await OSMProvider().search(-34.0336, 18.4468, 2000, [POICategory.GAS_STATION])

    assert [r["business_name"] for r in results] == ["Engen Meadowridge"]
    assert seen[0].startswith("MyGarage/")
    assert "github.com/homelabforge/mygarage" in seen[0]


@pytest.mark.asyncio
async def test_a_hanging_instance_does_not_hold_up_one_that_answers(monkeypatch):
    """All instances are asked at once; the first good answer wins."""
    real_client = httpx.AsyncClient
    slow = "overpass.kumi.systems"

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == slow:
            await asyncio.sleep(60)
        if request.url.host == "overpass-api.de":
            return httpx.Response(502, request=request)
        return httpx.Response(200, json={"elements": [STATION]}, request=request)

    monkeypatch.setattr(
        osm.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    provider = OSMProvider()
    assert provider.overpass_urls[0].startswith(f"https://{slow}/")

    started = asyncio.get_running_loop().time()
    results = await provider.search(-34.0336, 18.4468, 2000, [POICategory.GAS_STATION])

    assert [r["business_name"] for r in results] == ["Engen Meadowridge"]
    assert asyncio.get_running_loop().time() - started < 5


@pytest.mark.asyncio
async def test_every_instance_failing_still_raises(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        osm.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(503, request=r)), **kw
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await OSMProvider().search(-34.0336, 18.4468, 2000, [POICategory.GAS_STATION])
