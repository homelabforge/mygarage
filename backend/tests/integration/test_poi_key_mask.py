"""The POI provider routes mask a key as the placeholder, never its first characters (plan test 11, I4).

`api_key_masked` was the key's first 8 characters plus `***`, so every
provider response handed out a third of a billable key. It is now the same
mask the settings GET uses: `********` when a key is stored, `""` when none is.

A key that can't be decrypted reads as None but is still configured, so it
shows the placeholder too, not `""` (D3a). The PUT that leaves the key alone
(omitted, or the placeholder sent back) reports what is stored.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.settings_crypto import encrypt
from tests.integration._secret_helpers import Keep, seed_rows, unreadable_ciphertext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PLACEHOLDER = "********"
PROVIDER = "yelp"
KEY = f"{PROVIDER}_api_key"
PROVIDER_KEYS = (f"{PROVIDER}_enabled", KEY, f"{PROVIDER}_api_usage")
LONG_KEY = "yelp-billable-key-0123456789abcdef"


async def _seed(db: AsyncSession, keep: Keep, stored_key: str | None) -> None:
    """Store the provider's key: its ciphertext, blank for "" and unreadable for None.

    Encrypted here, not at collection, so the ciphertext is under the keyring this test runs with.
    """
    if stored_key is None:
        raw = unreadable_ciphertext(KEY)
    else:
        raw = encrypt(KEY, stored_key) if stored_key else ""
    await keep(*PROVIDER_KEYS)
    await seed_rows(db, keep, {KEY: raw, f"{PROVIDER}_enabled": "true"})


async def _listed_mask(client: AsyncClient, headers) -> str | None:
    response = await client.get("/api/settings/poi-providers", headers=headers)
    assert response.status_code == 200, response.text
    assert LONG_KEY[:8] not in response.text
    listed = {p["name"]: p for p in response.json()["providers"]}
    return listed[PROVIDER]["api_key_masked"]


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        pytest.param(LONG_KEY, PLACEHOLDER, id="long-key"),
        pytest.param("short", PLACEHOLDER, id="short-key"),
        pytest.param(None, PLACEHOLDER, id="unreadable"),
        pytest.param("", "", id="blank"),
    ],
)
async def test_the_list_masks_a_stored_key_as_the_placeholder(
    stored: str | None,
    expected: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    keep_rows: Keep,
) -> None:
    await _seed(db_session, keep_rows, stored)

    assert await _listed_mask(client, auth_headers) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param({"api_key": LONG_KEY, "enabled": True}, PLACEHOLDER, id="key"),
        pytest.param({"api_key": "", "enabled": False}, "", id="no-key"),
    ],
)
async def test_adding_a_provider_answers_the_placeholder(
    body: dict[str, object],
    expected: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    keep_rows: Keep,
) -> None:
    await _seed(db_session, keep_rows, "")

    response = await client.post(
        "/api/settings/poi-providers", headers=auth_headers, json={"name": PROVIDER, **body}
    )

    assert response.status_code == 200, response.text
    assert LONG_KEY[:8] not in response.text
    assert response.json()["api_key_masked"] == expected


@pytest.mark.parametrize(
    ("stored", "body", "expected"),
    [
        pytest.param("", {"api_key": LONG_KEY}, PLACEHOLDER, id="new-key"),
        pytest.param(LONG_KEY, {"api_key": ""}, "", id="cleared"),
        pytest.param(LONG_KEY, {"enabled": True}, PLACEHOLDER, id="omitted-kept"),
        pytest.param(LONG_KEY, {"api_key": PLACEHOLDER}, PLACEHOLDER, id="placeholder-kept"),
        pytest.param(None, {"enabled": True}, PLACEHOLDER, id="omitted-unreadable"),
        pytest.param("", {"enabled": False}, "", id="omitted-none-stored"),
        pytest.param("", {"api_key": PLACEHOLDER}, "", id="placeholder-none-stored"),
    ],
)
async def test_editing_a_provider_answers_what_is_stored(
    stored: str | None,
    body: dict[str, object],
    expected: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    keep_rows: Keep,
) -> None:
    await _seed(db_session, keep_rows, stored)

    response = await client.put(
        f"/api/settings/poi-providers/{PROVIDER}", headers=auth_headers, json=body
    )

    assert response.status_code == 200, response.text
    assert LONG_KEY[:8] not in response.text
    assert response.json()["api_key_masked"] == expected
    assert await _listed_mask(client, auth_headers) == expected
