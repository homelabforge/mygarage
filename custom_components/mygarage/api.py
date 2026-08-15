"""HTTP client for MyGarage widget API v2 + inbound webhooks."""

from __future__ import annotations

from typing import Any

import httpx


class MyGarageApiError(Exception):
    """Raised when the MyGarage API returns an error."""


class MyGarageApiClient:
    """Async client for MyGarage REST / widget endpoints."""

    def __init__(
        self,
        host: str,
        api_key: str = "",
        webhook_token: str = "",
    ) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._webhook_token = webhook_token
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._host,
                headers=self._headers(),
                timeout=15.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = await self._get_client()
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as err:
            raise MyGarageApiError(str(err)) from err
        if response.status_code >= 400:
            raise MyGarageApiError(f"{response.status_code}: {response.text}")
        if response.status_code == 204:
            return None
        if not response.content:
            return None
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def summary(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v2/widget/summary")

    async def list_vehicles(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v2/widget/vehicles")

    async def vehicle(self, vin: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v2/widget/vehicle/{vin}")

    async def log_fuel(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._webhook_token:
            headers["X-Webhook-Token"] = self._webhook_token
        return await self._request(
            "POST", "/api/v1/webhooks/fuel", json=payload, headers=headers
        )

    async def set_odometer(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._webhook_token:
            headers["X-Webhook-Token"] = self._webhook_token
        return await self._request(
            "POST", "/api/v1/webhooks/odometer", json=payload, headers=headers
        )

    async def complete_reminder(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self._webhook_token:
            headers["X-Webhook-Token"] = self._webhook_token
        return await self._request(
            "POST",
            "/api/v1/webhooks/reminders/complete",
            json=payload,
            headers=headers,
        )
