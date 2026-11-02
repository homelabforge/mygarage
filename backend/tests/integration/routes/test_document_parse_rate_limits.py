"""The document readers are rate-limited like the receipt parse (B6).

Each call can reach a vision model, so the certificate parse and import and
the insurance parse share the receipt parse's per-client upload budget
(`settings.rate_limit_uploads`). A refused upload still spends it, so the
test uses cheap 400s and expects the request past the budget to be 429.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

BUDGET = int(settings.rate_limit_uploads.split("/", 1)[0])


@pytest.mark.parametrize(
    "url",
    [
        "/api/registration-certificate/parse",
        "/api/vehicles/MRLT0000000000000/registration-certificate",
        "/api/insurance/parse-pdf",
    ],
)
async def test_the_upload_budget_applies(client: AsyncClient, auth_headers, url: str):
    upload = {"file": ("notes.txt", b"not a document", "text/plain")}
    for _ in range(BUDGET):
        r = await client.post(url, headers=auth_headers, files=upload)
        assert r.status_code != 429, r.text
    r = await client.post(url, headers=auth_headers, files=upload)
    assert r.status_code == 429, r.text
