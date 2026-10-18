"""Secret settings are encrypted at rest, whichever writer stored them.

Plan tests:
- 1: every ORM writer leaves a raw column that starts with `enc:v1:` and does
  not contain the plaintext, and reading the row back gives the plaintext.
- 2: `GET /api/settings` masks the three POI keys too (seeded here: the test DB
  is `create_all` only, so migration 027 never ran).
- 14 (the PUT and batch half): writing back an unchanged legacy plaintext value
  still rewrites the row as ciphertext (R1-H3).

The raw column is read with plain SQL through a fresh session, so neither the
ORM identity map nor the hybrid property can stand between the assertion and
the stored bytes.
"""

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Setting
from app.services.oidc.config import write_oidc_config
from app.services.settings_service import SettingsService
from app.utils.settings_crypto import CIPHERTEXT_PREFIX

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PLAIN = "plain-secret-7f3a9c"

Keep = Callable[..., Awaitable[None]]


async def _raw(sessionmaker: async_sessionmaker[AsyncSession], key: str) -> str | None:
    """The stored column, as another connection sees it (committed only)."""
    async with sessionmaker() as fresh:
        return (
            await fresh.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key})
        ).scalar_one_or_none()


async def _read_back(sessionmaker: async_sessionmaker[AsyncSession], key: str) -> str | None:
    """The value as an ORM reader sees it, through a fresh session."""
    async with sessionmaker() as fresh:
        row = (await fresh.execute(select(Setting).where(Setting.key == key))).scalar_one()
        return row.value


async def _upsert_raw(db: AsyncSession, key: str, raw: str) -> None:
    """Store `raw` in the column as is, as a pre-encryption release would have."""
    await db.execute(delete(Setting).where(Setting.key == key))
    db.add(Setting(key=key, stored_value=raw))
    await db.commit()


async def _write_put(client, headers, db, key: str, value: str) -> None:
    await _upsert_raw(db, key, "")
    response = await client.put(f"/api/settings/{key}", headers=headers, json={"value": value})
    assert response.status_code == 200, response.text


async def _write_batch(client, headers, db, key: str, value: str) -> None:
    response = await client.post(
        "/api/settings/batch", headers=headers, json={"settings": {key: value}}
    )
    assert response.status_code == 200, response.text


async def _write_post(client, headers, db, key: str, value: str) -> None:
    await db.execute(delete(Setting).where(Setting.key == key))
    await db.commit()
    response = await client.post(
        "/api/settings", headers=headers, json={"key": key, "value": value}
    )
    assert response.status_code == 201, response.text


async def _write_oidc(client, headers, db, key: str, value: str) -> None:
    await write_oidc_config(db, {"client_secret": value})


async def _write_poi_post(client, headers, db, key: str, value: str) -> None:
    response = await client.post(
        "/api/settings/poi-providers",
        headers=headers,
        json={"name": "yelp", "api_key": value, "enabled": True},
    )
    assert response.status_code == 200, response.text


async def _write_mqtt_put(client, headers, db, key: str, value: str) -> None:
    response = await client.put(
        "/api/livelink/mqtt/settings", headers=headers, json={"password": value}
    )
    assert response.status_code == 200, response.text


async def _write_service_set(client, headers, db, key: str, value: str) -> None:
    await SettingsService.set(db, key, value)
    await db.commit()


# (writer, the secret key it writes, other keys it touches and must restore)
WRITERS = {
    "put": (_write_put, "gotify_token", ()),
    "batch": (_write_batch, "pushover_api_token", ()),
    "post": (_write_post, "matrix_access_token", ()),
    "write_oidc_config": (_write_oidc, "oidc_client_secret", ()),
    "poi_post": (_write_poi_post, "yelp_api_key", ("yelp_enabled", "yelp_api_usage")),
    "mqtt_put": (_write_mqtt_put, "livelink_mqtt_password", ()),
    "settings_service_set": (_write_service_set, "llm_api_key", ()),
}


@pytest.mark.parametrize("writer", list(WRITERS))
async def test_every_writer_stores_ciphertext_that_reads_back(
    writer: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_sessionmaker,
    keep_rows: Keep,
) -> None:
    """Plan test 1."""
    write, key, also = WRITERS[writer]
    await keep_rows(key, *also)

    await write(client, auth_headers, db_session, key, PLAIN)

    raw = await _raw(test_sessionmaker, key)
    assert raw is not None
    assert raw.startswith(CIPHERTEXT_PREFIX)
    assert PLAIN not in raw
    assert await _read_back(test_sessionmaker, key) == PLAIN


POI_KEYS = ("google_places_api_key", "yelp_api_key", "foursquare_api_key")


async def test_the_poi_keys_are_masked_in_the_settings_list(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    """Plan test 2: the three POI keys used to be served in clear."""
    await keep_rows(*POI_KEYS)
    for key in POI_KEYS:
        await SettingsService.set(db_session, key, f"{key}-billable-1234567890")
    await db_session.commit()

    response = await client.get("/api/settings", headers=auth_headers)
    assert response.status_code == 200, response.text
    served = {s["key"]: s for s in response.json()["settings"]}
    for key in POI_KEYS:
        assert served[key]["value"] == "********", key
        assert served[key]["encrypted"] is True, key
    assert "billable" not in response.text


async def _legacy_put(client, headers, key: str) -> None:
    response = await client.put(f"/api/settings/{key}", headers=headers, json={"value": PLAIN})
    assert response.status_code == 200, response.text


async def _legacy_batch(client, headers, key: str) -> None:
    response = await client.post(
        "/api/settings/batch", headers=headers, json={"settings": {key: PLAIN}}
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("write", [_legacy_put, _legacy_batch], ids=["put", "batch"])
async def test_an_unchanged_legacy_value_is_rewritten_as_ciphertext(
    write,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_sessionmaker,
    keep_rows: Keep,
) -> None:
    """Plan test 14, PUT and batch: the same value sent back still encrypts the row."""
    key = "discord_webhook_url"
    await keep_rows(key)
    await db_session.execute(delete(Setting).where(Setting.key == key))
    await db_session.commit()
    await db_session.execute(
        text("INSERT INTO settings (key, value, category) VALUES (:k, :v, 'notifications')"),
        {"k": key, "v": PLAIN},
    )
    await db_session.commit()
    db_session.expire_all()
    assert await _raw(test_sessionmaker, key) == PLAIN

    await write(client, auth_headers, key)

    raw = await _raw(test_sessionmaker, key)
    assert raw is not None
    assert raw.startswith(CIPHERTEXT_PREFIX)
    assert PLAIN not in raw
    assert await _read_back(test_sessionmaker, key) == PLAIN
