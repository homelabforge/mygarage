"""Helpers for the 3b JSON backup suites: export, import and a v9 file shell."""

import json
from typing import Any

from httpx import AsyncClient

#: A v9 file with no sections; a test adds the ones it needs.
V9: dict[str, Any] = {"export_version": "9", "units": "metric"}


async def export_json(client: AsyncClient, headers: dict[str, str], vin: str) -> dict[str, Any]:
    """The vehicle's JSON backup, as the export route writes it."""
    response = await client.get(f"/api/export/vehicles/{vin}/json", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def post_json(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    payload: dict[str, Any],
    *,
    skip_duplicates: bool = True,
):
    """Post `payload` to the JSON import and hand back the raw response."""
    return await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true" if skip_duplicates else "false"},
    )


async def import_json(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    payload: dict[str, Any],
    *,
    skip_duplicates: bool = True,
) -> dict[str, Any]:
    """Import `payload` into `vin` and hand back the 200 response body."""
    response = await post_json(client, headers, vin, payload, skip_duplicates=skip_duplicates)
    assert response.status_code == 200, response.text
    return response.json()
