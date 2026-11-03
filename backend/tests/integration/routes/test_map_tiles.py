"""Map tiles come from MyGarage's server, not from the browser.

Browsers loading tile.openstreetmap.org directly got 503 for every tile, so
the maps showed markers on a blank square. The server fetches each tile with
an identifying User-Agent and caches it under the data directory.
"""

import os
import time

import httpx
import pytest
from httpx import AsyncClient

from app.routes import map_tiles

PNG = b"\x89PNG\r\n\x1a\n tile"


@pytest.fixture
def osm(monkeypatch, tmp_path):
    """Stand in for tile.openstreetmap.org; records each request it gets."""
    seen: list[httpx.Request] = []
    state = {"status": 200}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if state["status"] != 200:
            return httpx.Response(state["status"], request=request)
        return httpx.Response(
            200, content=PNG, headers={"content-type": "image/png"}, request=request
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        map_tiles.httpx,
        "AsyncClient",
        lambda *a, **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    monkeypatch.setattr(map_tiles, "TILE_CACHE_DIR", tmp_path)
    return seen, state, tmp_path


@pytest.mark.integration
@pytest.mark.asyncio
class TestMapTiles:
    async def test_requires_auth(self, client: AsyncClient, osm):
        response = await client.get("/api/map/tiles/15/18063/19683.png")
        assert response.status_code == 401
        assert osm[0] == []

    async def test_fetches_with_user_agent_and_caches(self, client: AsyncClient, auth_headers, osm):
        seen, _, cache = osm
        first = await client.get("/api/map/tiles/15/18063/19683.png", headers=auth_headers)
        second = await client.get("/api/map/tiles/15/18063/19683.png", headers=auth_headers)

        assert first.status_code == second.status_code == 200
        assert first.content == second.content == PNG
        assert first.headers["content-type"] == "image/png"
        assert "max-age=604800" in first.headers["cache-control"]
        assert len(seen) == 1, "the second view comes from the cache"
        assert str(seen[0].url) == "https://tile.openstreetmap.org/15/18063/19683.png"
        assert seen[0].headers["user-agent"].startswith("MyGarage/")
        assert (cache / "15" / "18063" / "19683.png").read_bytes() == PNG

    async def test_stale_tile_is_served_when_osm_fails(
        self, client: AsyncClient, auth_headers, osm
    ):
        seen, state, cache = osm
        path = cache / "3" / "4" / "5.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(PNG)
        week_ago = time.time() - 8 * 24 * 3600
        os.utime(path, (week_ago, week_ago))
        state["status"] = 503

        response = await client.get("/api/map/tiles/3/4/5.png", headers=auth_headers)

        assert response.status_code == 200
        assert response.content == PNG
        assert len(seen) == 1, "an old tile is refreshed first"

    async def test_osm_failure_without_cache_is_502(self, client: AsyncClient, auth_headers, osm):
        osm[1]["status"] = 503
        response = await client.get("/api/map/tiles/3/4/5.png", headers=auth_headers)
        assert response.status_code == 502

    @pytest.mark.parametrize("tile", ["20/0/0", "2/4/0", "2/0/4", "2/-1/0"])
    async def test_out_of_range_tiles_never_reach_osm(
        self, client: AsyncClient, auth_headers, osm, tile
    ):
        response = await client.get(f"/api/map/tiles/{tile}.png", headers=auth_headers)
        assert response.status_code in (404, 422)
        assert osm[0] == []
