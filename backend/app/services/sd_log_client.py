"""Read-only HTTP client for a WiCAN device's SD-card OBD log API.

Only GET /obd_logs and GET /obd_logs/<file> are used — never /check_status or
/load_config (those return WiFi credentials in plaintext).
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")


class SdLogClientError(Exception):
    """Base error for SD log client operations."""


class SdLogUnreachable(SdLogClientError):  # noqa: N818
    """Device could not be reached."""


class SdLogClient:
    """Fetches SD-card log databases from a WiCAN device over HTTP."""

    def __init__(self, base_url: str, timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_logs(self) -> list[dict]:
        """Return the device's list of SD log databases (filename/status/size)."""
        data = await self._get_json("/obd_logs")
        return data.get("databases", [])

    async def download_log(self, filename: str) -> bytes:
        """Download one log database's raw bytes."""
        if not _SAFE_FILENAME.match(filename):
            raise ValueError(f"unsafe SD log filename: {filename!r}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/obd_logs/{filename}")
                resp.raise_for_status()
                return resp.content
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise SdLogUnreachable(f"{self.base_url}: {e}") from e
        except httpx.HTTPError as e:
            raise SdLogClientError(f"download {filename} failed: {e}") from e

    async def _get_json(self, path: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}{path}")
                resp.raise_for_status()
                return resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise SdLogUnreachable(f"{self.base_url}: {e}") from e
        except httpx.HTTPError as e:
            raise SdLogClientError(f"GET {path} failed: {e}") from e
