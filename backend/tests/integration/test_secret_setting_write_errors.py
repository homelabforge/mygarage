"""How a secret write fails: 503 without a keyring, 422 for a value that is ciphertext.

- Plan test 8, the 503 half (F-2): with the data dir unwritable and no key
  configured, the keyring is unavailable, and every writer from plan test 1
  refuses a secret write. The HTTP routes answer 503 with a detail naming the
  fix; the in-process writers raise `SettingsKeyUnavailable`. Either way the
  stored row is unchanged and holds no plaintext.
- R2-9: a secret given a value that already starts with `enc:v1:` is a 422 on
  every writer, naming the key and never echoing the value. The generic
  settings routes refuse it up front; the others reach the model's
  `SettingCiphertextValue` and the handler maps it.
- R2-3: both mappings hold in debug mode too, which has no catch-all handler.

The raw column is read with plain SQL through a fresh session.
"""

from collections.abc import Awaitable, Callable, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.settings import Setting, SettingCiphertextValue
from app.services.oidc.config import write_oidc_config
from app.services.settings_service import SettingsService
from app.utils import settings_crypto
from app.utils.settings_crypto import SettingsKeyUnavailable, encrypt

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

Keep = Callable[..., Awaitable[None]]
PLAIN = "plain-secret-5be21d"
BEFORE = "the-value-before"


async def _raw(sessionmaker: async_sessionmaker[AsyncSession], key: str) -> str | None:
    """The stored column, as another connection sees it (committed only)."""
    async with sessionmaker() as fresh:
        return (
            await fresh.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key})
        ).scalar_one_or_none()


async def _seed_raw(db: AsyncSession, key: str, raw: str | None) -> None:
    """Leave `key` holding `raw` (None: no row at all)."""
    await db.execute(delete(Setting).where(Setting.key == key))
    if raw is not None:
        db.add(Setting(key=key, stored_value=raw))
    await db.commit()


@pytest.fixture
def make_keyring_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> Iterator[Callable[[], None]]:
    """Call it to leave the keyring with no source but a data dir that can't exist.

    Depends on `client`, which points `settings.data_dir` at a test dir, so the
    override here is set after it and undone before it. A regular file stands
    where the data dir's parent should be, so this holds even as root.
    """
    original = settings.data_dir

    def block() -> None:
        monkeypatch.delenv(settings_crypto.ENV_KEY, raising=False)
        monkeypatch.delenv(settings_crypto.ENV_KEY_FILE, raising=False)
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        settings.data_dir = blocker / "data"
        settings_crypto._reset_keyring_for_tests()  # pyright: ignore[reportPrivateUsage]
        assert settings_crypto.current_kid() is None

    yield block
    # The environment comes back with monkeypatch's own teardown; the keyring
    # loads lazily, so the next use reads the restored key.
    settings.data_dir = original
    settings_crypto._reset_keyring_for_tests()  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------- writers


async def _put(client, headers, key: str, value: str):
    return await client.put(f"/api/settings/{key}", headers=headers, json={"value": value})


async def _batch(client, headers, key: str, value: str):
    return await client.post(
        "/api/settings/batch", headers=headers, json={"settings": {key: value}}
    )


async def _post(client, headers, key: str, value: str):
    return await client.post("/api/settings", headers=headers, json={"key": key, "value": value})


async def _poi_post(client, headers, key: str, value: str):
    return await client.post(
        "/api/settings/poi-providers",
        headers=headers,
        json={"name": "yelp", "api_key": value, "enabled": True},
    )


async def _poi_put(client, headers, key: str, value: str):
    return await client.put(
        "/api/settings/poi-providers/foursquare", headers=headers, json={"api_key": value}
    )


async def _mqtt_put(client, headers, key: str, value: str):
    return await client.put(
        "/api/livelink/mqtt/settings", headers=headers, json={"password": value}
    )


async def _oidc_put(client, headers, key: str, value: str):
    return await client.put(
        "/api/auth/oidc/config/admin",
        headers=headers,
        json={"issuer_url": "https://auth.example.com", "client_secret": value},
    )


OIDC_PUT_KEYS = tuple(
    f"oidc_{k}"
    for k in (
        "enabled",
        "provider_name",
        "issuer_url",
        "client_id",
        "scopes",
        "auto_create_users",
        "admin_group",
        "username_claim",
        "email_claim",
        "full_name_claim",
    )
)

# (route, the secret key it writes, whether that row must exist first, other keys it writes)
HTTP_WRITERS = {
    "put": (_put, "gotify_token", True, ()),
    "batch": (_batch, "pushover_api_token", True, ()),
    "post": (_post, "matrix_access_token", False, ()),
    "poi_post": (_poi_post, "yelp_api_key", True, ("yelp_enabled", "yelp_api_usage")),
    "poi_put": (_poi_put, "foursquare_api_key", True, ()),
    "mqtt_put": (_mqtt_put, "livelink_mqtt_password", True, ()),
    "oidc_put": (_oidc_put, "oidc_client_secret", True, OIDC_PUT_KEYS),
}


@pytest.mark.parametrize("writer", list(HTTP_WRITERS))
async def test_a_secret_write_without_a_keyring_is_a_503(
    writer: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_sessionmaker,
    keep_rows: Keep,
    make_keyring_unavailable: Callable[[], None],
) -> None:
    """Plan test 8 (F-2): the detail names the fix, and nothing is stored.

    Plaintext rows keep working (D3a): a non-secret write still lands, so the
    503 is about the secret, not the whole settings API.
    """
    write, key, row_first, also = HTTP_WRITERS[writer]
    await keep_rows(key, *also, "ntfy_topic")
    before = encrypt(key, BEFORE) if row_first else None
    await _seed_raw(db_session, key, before)
    await _seed_raw(db_session, "ntfy_topic", "Before")
    make_keyring_unavailable()

    response = await write(client, auth_headers, key, PLAIN)

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert "MYGARAGE_SETTINGS_KEY" in detail
    assert "writable" in detail
    assert PLAIN not in response.text
    assert await _raw(test_sessionmaker, key) == before

    response = await _put(client, auth_headers, "ntfy_topic", "After")
    assert response.status_code == 200, response.text
    assert await _raw(test_sessionmaker, "ntfy_topic") == "After"


async def _service_set(db: AsyncSession, key: str, value: str) -> None:
    await SettingsService.set(db, key, value)
    await db.commit()


async def _write_oidc_config(db: AsyncSession, key: str, value: str) -> None:
    await write_oidc_config(db, {"client_secret": value})


IN_PROCESS_WRITERS = {
    "settings_service_set": (_service_set, "llm_api_key"),
    "write_oidc_config": (_write_oidc_config, "oidc_client_secret"),
}


@pytest.mark.parametrize("writer", list(IN_PROCESS_WRITERS))
@pytest.mark.parametrize("row_first", [True, False], ids=["existing_row", "new_row"])
async def test_an_in_process_secret_write_without_a_keyring_raises(
    writer: str,
    row_first: bool,
    db_session: AsyncSession,
    test_sessionmaker,
    keep_rows: Keep,
    make_keyring_unavailable: Callable[[], None],
) -> None:
    """Plan test 8 (F-2), for the writers no route stands in front of."""
    write, key = IN_PROCESS_WRITERS[writer]
    await keep_rows(key)
    before = encrypt(key, BEFORE) if row_first else None
    await _seed_raw(db_session, key, before)
    make_keyring_unavailable()

    with pytest.raises(SettingsKeyUnavailable):
        await write(db_session, key, PLAIN)
    await db_session.rollback()

    assert await _raw(test_sessionmaker, key) == before


# ----------------------------------------------------- value is ciphertext


@pytest.mark.parametrize("writer", list(HTTP_WRITERS))
async def test_a_ciphertext_value_for_a_secret_is_a_422(
    writer: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_sessionmaker,
    keep_rows: Keep,
) -> None:
    """R2-9: refused on every writer, naming the key and never echoing the value."""
    write, key, row_first, also = HTTP_WRITERS[writer]
    await keep_rows(key, *also)
    before = encrypt(key, BEFORE) if row_first else None
    await _seed_raw(db_session, key, before)
    pasted = encrypt(key, "pasted-inner-secret")

    response = await write(client, auth_headers, key, pasted)

    assert response.status_code == 422, response.text
    assert key in response.json()["detail"]
    assert pasted not in response.text
    assert pasted.split(":")[-1] not in response.text
    assert await _raw(test_sessionmaker, key) == before


# ------------------------------------------------------- handler registration


def _app(*, debug: bool) -> FastAPI:
    """An app registered the way main.py registers its own, with two failing routes."""
    from app.utils.error_handlers import register_error_handlers

    app = FastAPI(debug=debug)
    register_error_handlers(app, debug=debug)

    @app.get("/no-key")
    async def no_key() -> None:
        raise SettingsKeyUnavailable(settings_crypto.ENV_KEY, "it is not valid base64url")

    @app.get("/ciphertext")
    async def ciphertext() -> None:
        raise SettingCiphertextValue("llm_api_key")

    return app


@pytest.mark.parametrize("debug", [False, True], ids=["production", "debug"])
async def test_both_mappings_hold_in_either_mode(debug: bool) -> None:
    """R2-3: registered after the debug branch, so debug has them too."""
    transport = ASGITransport(app=_app(debug=debug))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/no-key")
        assert response.status_code == 503, response.text
        assert "MYGARAGE_SETTINGS_KEY" in response.json()["detail"]

        response = await client.get("/ciphertext")
        assert response.status_code == 422, response.text
        assert "llm_api_key" in response.json()["detail"]
