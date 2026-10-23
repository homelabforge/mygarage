"""The POI provider routes mask a key as the placeholder, never its first characters (plan test 11, I4).

`api_key_masked` was the key's first 8 characters plus `***`, so every
provider response handed out a third of a billable key. It is now the same
mask the settings GET uses: `********` when a key is stored, `""` when none is.

A key that can't be decrypted reads as None but is still configured, so it
shows the placeholder too, not `""` (D3a). The PUT that leaves the key alone
(omitted, or the placeholder sent back) reports what is stored, and so does the
POST given the placeholder back (R1-H2).
"""

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Setting
from app.utils.settings_crypto import encrypt
from tests.integration._secret_helpers import Keep, raw_column, seed_rows, unreadable_ciphertext

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


# ------------------------------------------------- the placeholder on the POST


async def _post_placeholder(
    client: AsyncClient, headers: dict[str, str], *, enabled: bool
) -> Response:
    return await client.post(
        "/api/settings/poi-providers",
        headers=headers,
        json={"name": PROVIDER, "api_key": PLACEHOLDER, "enabled": enabled},
    )


@pytest.mark.parametrize(
    "stored",
    [pytest.param(LONG_KEY, id="readable"), pytest.param(None, id="unreadable")],
)
async def test_adding_a_provider_with_the_placeholder_keeps_the_stored_key(
    stored: str | None,
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
) -> None:
    """R1-H2: the POST upsert honours the placeholder as the PUT does.

    The POST answered the placeholder as the mask, so a client that sent it back
    saved literal asterisks over the key, readable or not (D3a).
    """
    await _seed(db_session, keep_rows, stored)
    before = await raw_column(test_sessionmaker, KEY)
    assert before

    response = await _post_placeholder(client, auth_headers, enabled=True)

    assert response.status_code == 200, response.text
    assert response.json()["api_key_masked"] == PLACEHOLDER
    assert await raw_column(test_sessionmaker, KEY) == before
    assert await _listed_mask(client, auth_headers) == PLACEHOLDER


async def test_adding_a_provider_with_the_placeholder_and_no_key_stored_stores_none(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
) -> None:
    """R1-H2: with no key row, the placeholder stands for no key, so the row is created blank.

    The generic batch does the same. Enabling still needs a key, so the same
    save with `enabled` is a 400 that writes nothing; so is one over a blank row.
    """
    await keep_rows(*PROVIDER_KEYS)
    await db_session.execute(delete(Setting).where(Setting.key.in_(PROVIDER_KEYS)))
    await db_session.commit()

    response = await _post_placeholder(client, auth_headers, enabled=True)
    assert response.status_code == 400, response.text
    assert await raw_column(test_sessionmaker, KEY) is None
    assert await raw_column(test_sessionmaker, f"{PROVIDER}_enabled") is None

    response = await _post_placeholder(client, auth_headers, enabled=False)
    assert response.status_code == 200, response.text
    assert response.json()["api_key_masked"] == ""
    assert await raw_column(test_sessionmaker, KEY) == ""
    assert await raw_column(test_sessionmaker, f"{PROVIDER}_enabled") == "false"

    response = await _post_placeholder(client, auth_headers, enabled=True)
    assert response.status_code == 400, response.text
    assert await raw_column(test_sessionmaker, KEY) == ""
    assert await raw_column(test_sessionmaker, f"{PROVIDER}_enabled") == "false"
