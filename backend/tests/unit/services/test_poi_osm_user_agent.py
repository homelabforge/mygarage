"""The Overpass search identifies itself.

overpass-api.de refuses httpx's default User-Agent with 406 Not Acceptable.
Every OSM search then came back empty, which, with no keyed provider
configured, is every POI search. Nominatim (routes/poi.py) already
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
    """A quiet instance gets hedge_seconds, not the full 30 s timeout."""
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
    provider.overpass_urls = [
        f"https://{slow}/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://answers.example/api/interpreter",
    ]

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        {"elements": [], "remark": 'runtime error: Query timed out in "query" at line 3'},
        {
            "elements": [STATION | {"id": 2, "tags": {"amenity": "fuel", "name": "Half A Query"}}],
            "remark": "runtime error: Query run out of memory",
        },
        [STATION],
    ],
    ids=["timeout-remark", "partial-out-of-memory", "not-an-object"],
)
async def test_an_overpass_failure_dressed_as_200_does_not_win(monkeypatch, failure):
    """Overpass says "timed out" or "out of memory" with a 200 and a remark."""
    real_client = httpx.AsyncClient

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fails.example":
            return httpx.Response(200, json=failure, request=request)
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"elements": [STATION]}, request=request)

    monkeypatch.setattr(
        osm.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    provider = OSMProvider()
    provider.overpass_urls = [
        "https://fails.example/api/interpreter",
        "https://answers.example/api/interpreter",
    ]

    results = await provider.search(-34.0336, 18.4468, 2000, [POICategory.GAS_STATION])

    assert [r["business_name"] for r in results] == ["Engen Meadowridge"]


def _counting(hosts: list[str], first_fails: bool):
    async def handle(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if first_fails and request.url.host == "first.example":
            return httpx.Response(406, request=request)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"elements": [STATION]}, request=request)

    return handle


def _two_instance_provider(monkeypatch, handle) -> OSMProvider:
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        osm.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    provider = OSMProvider()
    provider.overpass_urls = [
        "https://first.example/api/interpreter",
        "https://second.example/api/interpreter",
    ]
    return provider


@pytest.mark.asyncio
async def test_a_healthy_first_instance_is_the_only_one_asked(monkeypatch):
    """The volunteer servers see one request per search, not one each."""
    hosts: list[str] = []
    provider = _two_instance_provider(monkeypatch, _counting(hosts, first_fails=False))

    results = await provider.search(-34.0336, 18.4468, 2000, [POICategory.GAS_STATION])

    assert [r["business_name"] for r in results] == ["Engen Meadowridge"]
    assert hosts == ["first.example"]


@pytest.mark.asyncio
async def test_a_fast_failure_asks_the_next_instance_straight_away(monkeypatch):
    hosts: list[str] = []
    provider = _two_instance_provider(monkeypatch, _counting(hosts, first_fails=True))

    started = asyncio.get_running_loop().time()
    results = await provider.search(-34.0336, 18.4468, 2000, [POICategory.GAS_STATION])

    assert [r["business_name"] for r in results] == ["Engen Meadowridge"]
    assert hosts == ["first.example", "second.example"]
    assert asyncio.get_running_loop().time() - started < provider.hedge_seconds
