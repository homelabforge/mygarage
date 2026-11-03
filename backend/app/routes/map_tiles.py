"""OpenStreetMap tiles, fetched by the server and cached on disk.

The maps used to load tiles straight from tile.openstreetmap.org in the
browser. OSM's volunteer-run tile servers refuse those requests from a
self-hosted MyGarage: every tile came back 503 in Chrome and Safari, from
localhost and from a public https domain alike, so the maps drew their
markers on a blank grey square. The same request from the server, carrying
an identifying User-Agent, is answered. OSM's tile usage policy asks apps for
exactly that, and for caching tiles locally, which also keeps repeat views
off their servers.

The route is auth-only so a public deploy is not an open tile proxy.
"""

import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import Path as PathParam

from app.config import settings
from app.models.user import User
from app.services.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/map", tags=["Map"])

_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_USER_AGENT = f"MyGarage/{settings.app_version} (+https://github.com/homelabforge/mygarage)"
_MAX_ZOOM = 19
# OSM's policy asks for at least 7 days of caching.
_MAX_AGE_S = 7 * 24 * 3600
_HEADERS = {"Cache-Control": f"private, max-age={_MAX_AGE_S}"}

TILE_CACHE_DIR = settings.data_dir / "cache" / "tiles"


def _tile_path(z: int, x: int, y: int) -> Path:
    return TILE_CACHE_DIR / str(z) / str(x) / f"{y}.png"


@router.get("/tiles/{z}/{x}/{y}.png")
async def get_tile(
    z: int = PathParam(..., ge=0, le=_MAX_ZOOM),
    x: int = PathParam(..., ge=0),
    y: int = PathParam(..., ge=0),
    current_user: User | None = Depends(require_auth),
):
    """One 256px OSM tile. Served from the cache when it is under 7 days old."""
    if x >= 2**z or y >= 2**z:
        raise HTTPException(status_code=404, detail="Tile out of range")

    path = _tile_path(z, x, y)
    if path.exists() and time.time() - path.stat().st_mtime < _MAX_AGE_S:
        return Response(path.read_bytes(), media_type="image/png", headers=_HEADERS)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.get(
                _TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": _USER_AGENT}
            )
            upstream.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("OSM tile %s/%s/%s failed: %s", z, x, y, e)
        # A stale tile beats a hole in the map.
        if path.exists():
            return Response(path.read_bytes(), media_type="image/png", headers=_HEADERS)
        raise HTTPException(status_code=502, detail="Map tile service unavailable") from e

    if upstream.headers.get("content-type", "").startswith("image/"):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(upstream.content)
        tmp.replace(path)
    return Response(upstream.content, media_type="image/png", headers=_HEADERS)
