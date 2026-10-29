"""The JSON import has the upload rate limit the other imports have (B3-2, K6)."""

import json
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_the_21st_json_import_in_a_minute_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    new_vehicle: Callable[..., Awaitable[str]],
) -> None:
    # The routes conftest empties the bucket before each test.
    vin = await new_vehicle()
    body = json.dumps({"export_version": "9", "units": "metric"}).encode()
    codes: list[int] = []
    for _ in range(21):
        response = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={"file": ("vehicle.json", body, "application/json")},
            data={"skip_duplicates": "true"},
        )
        codes.append(response.status_code)
    # main: no limit at all, so the 21st is a 200 too.
    assert codes[:20] == [200] * 20
    assert codes[20] == 429
