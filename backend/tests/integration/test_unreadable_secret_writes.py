"""A secret that can't be decrypted is configured, and a placeholder save keeps it (D3a).

Plan test 6, and the "keep stored" sites from the inventory:
- the settings GET shows such a secret as the placeholder with `unreadable: true`;
- saving the placeholder back through PUT, batch, the OIDC PUT, the MQTT PUT or
  the POI PUT writes nothing, so the ciphertext stays byte-identical and the
  right key can still recover it later;
- readers keep seeing None;
- the OIDC admin GET and the MQTT GET report it as configured, with their own
  unreadable flag, and the OIDC test route stops with the re-enter advice
  instead of testing with a blank secret (R2-1).

"Unreadable" is seeded as a real ciphertext bound to another key name, so it is
well-formed and fails only on the associated data. The raw column is read with
plain SQL through a fresh session, so neither the identity map nor the hybrid
property stands between the assertion and the stored bytes.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.utils.settings_crypto import encrypt
from tests.integration._secret_helpers import (
    Keep,
    raw_column,
    read_back,
    seed_rows,
    unreadable_ciphertext,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PLACEHOLDER = "********"
REENTER = "can't be decrypted; re-enter it"


# ------------------------------------------------------------------ settings GET


async def test_the_settings_get_shows_an_unreadable_secret_as_configured(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(
        db_session,
        keep_rows,
        {
            "gotify_token": unreadable_ciphertext("gotify_token"),
            "pushover_api_token": encrypt("pushover_api_token", "readable"),
            "slack_webhook_url": "",
            "app_name": "MyGarage",
        },
    )

    response = await client.get("/api/settings", headers=auth_headers)
    assert response.status_code == 200, response.text
    served = {s["key"]: s for s in response.json()["settings"]}
    assert served["gotify_token"]["value"] == PLACEHOLDER
    assert served["gotify_token"]["unreadable"] is True
    assert served["pushover_api_token"]["value"] == PLACEHOLDER
    assert served["pushover_api_token"]["unreadable"] is False
    assert served["slack_webhook_url"]["value"] == ""
    assert served["slack_webhook_url"]["unreadable"] is False
    assert served["app_name"]["unreadable"] is False
    assert "enc:v1:" not in response.text

    single = await client.get("/api/settings/gotify_token", headers=auth_headers)
    assert single.status_code == 200, single.text
    assert single.json()["value"] == PLACEHOLDER
    assert single.json()["unreadable"] is True


# ------------------------------------------------------- placeholder saves


async def _save_put(client: AsyncClient, headers, key: str) -> None:
    response = await client.put(
        f"/api/settings/{key}", headers=headers, json={"value": PLACEHOLDER}
    )
    assert response.status_code == 200, response.text
    assert response.json()["value"] == PLACEHOLDER
    assert response.json()["unreadable"] is True


async def _save_batch(client: AsyncClient, headers, key: str) -> None:
    response = await client.post(
        "/api/settings/batch", headers=headers, json={"settings": {key: PLACEHOLDER}}
    )
    assert response.status_code == 200, response.text
    served = {s["key"]: s for s in response.json()["settings"]}
    assert served[key]["value"] == PLACEHOLDER
    assert served[key]["unreadable"] is True


OIDC_FORM = {
    "enabled": True,
    "provider_name": "Authentik",
    "issuer_url": "https://auth.example.com",
    "client_id": "test-id",
    "scopes": "openid profile email",
    "auto_create_users": True,
    "admin_group": "",
    "username_claim": "preferred_username",
    "email_claim": "email",
    "full_name_claim": "name",
}


async def _save_oidc_placeholder(client: AsyncClient, headers, key: str) -> None:
    response = await client.put(
        "/api/auth/oidc/config/admin",
        headers=headers,
        json={**OIDC_FORM, "client_secret": PLACEHOLDER},
    )
    assert response.status_code == 200, response.text


async def _save_oidc_blank(client: AsyncClient, headers, key: str) -> None:
    response = await client.put(
        "/api/auth/oidc/config/admin", headers=headers, json={**OIDC_FORM, "client_secret": ""}
    )
    assert response.status_code == 200, response.text


async def _save_mqtt(client: AsyncClient, headers, key: str) -> None:
    response = await client.put(
        "/api/livelink/mqtt/settings",
        headers=headers,
        json={"broker_host": "mqtt.example.com", "password": PLACEHOLDER},
    )
    assert response.status_code == 200, response.text


async def _save_poi(client: AsyncClient, headers, key: str) -> None:
    response = await client.put(
        "/api/settings/poi-providers/yelp",
        headers=headers,
        json={"enabled": True, "api_key": PLACEHOLDER},
    )
    assert response.status_code == 200, response.text


# Every key the OIDC PUT writes besides the secret, restored afterwards.
OIDC_KEYS = tuple(f"oidc_{k}" for k in OIDC_FORM)

# (save, the secret key it must leave alone, other keys it writes and must restore)
SAVES = {
    "put": (_save_put, "email_smtp_password", ()),
    "batch": (_save_batch, "telegram_bot_token", ()),
    "oidc_put_placeholder": (_save_oidc_placeholder, "oidc_client_secret", OIDC_KEYS),
    "oidc_put_blank": (_save_oidc_blank, "oidc_client_secret", OIDC_KEYS),
    "mqtt_put": (_save_mqtt, "livelink_mqtt_password", ("livelink_mqtt_broker_host",)),
    "poi_put": (_save_poi, "yelp_api_key", ("yelp_enabled",)),
}


@pytest.mark.parametrize("save", list(SAVES))
async def test_a_placeholder_save_leaves_an_unreadable_secret_byte_identical(
    save: str,
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_sessionmaker,
    keep_rows: Keep,
) -> None:
    """Plan test 6: "keep stored" writes nothing, so the ciphertext survives."""
    write, key, also = SAVES[save]
    await keep_rows(*also)
    ciphertext = unreadable_ciphertext(key)
    await seed_rows(db_session, keep_rows, {key: ciphertext})

    await write(client, auth_headers, key)

    assert await raw_column(test_sessionmaker, key) == ciphertext
    assert await read_back(test_sessionmaker, key) is None


async def test_a_batch_keeps_the_secret_and_writes_the_rest(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_sessionmaker, keep_rows: Keep
) -> None:
    """A kept secret beside real writes, in one batch.

    The other keys land, a placeholder for a key with no row still creates it
    blank (nothing stored, so "" as before), and the response keeps batch order.
    """
    ciphertext = unreadable_ciphertext("discord_webhook_url")
    await seed_rows(
        db_session,
        keep_rows,
        {
            "ntfy_topic": "Before",
            "discord_webhook_url": ciphertext,
            "ntfy_server": "https://old.example.com",
        },
    )
    await keep_rows("matrix_access_token")
    await db_session.execute(delete(Setting).where(Setting.key == "matrix_access_token"))
    await db_session.commit()

    response = await client.post(
        "/api/settings/batch",
        headers=auth_headers,
        json={
            "settings": {
                "ntfy_topic": "After",
                "discord_webhook_url": PLACEHOLDER,
                "matrix_access_token": PLACEHOLDER,
                "ntfy_server": "https://new.example.com",
            }
        },
    )
    assert response.status_code == 200, response.text
    assert [s["key"] for s in response.json()["settings"]] == [
        "ntfy_topic",
        "discord_webhook_url",
        "matrix_access_token",
        "ntfy_server",
    ]
    assert await raw_column(test_sessionmaker, "discord_webhook_url") == ciphertext
    assert await raw_column(test_sessionmaker, "matrix_access_token") == ""
    assert await raw_column(test_sessionmaker, "ntfy_topic") == "After"
    assert await raw_column(test_sessionmaker, "ntfy_server") == "https://new.example.com"


# ------------------------------------------------- OIDC and MQTT "configured"


async def test_the_oidc_admin_get_reports_an_unreadable_secret(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(
        db_session, keep_rows, {"oidc_client_secret": unreadable_ciphertext("oidc_client_secret")}
    )

    response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["client_secret"] == PLACEHOLDER
    assert response.json()["client_secret_unreadable"] is True
    assert "enc:v1:" not in response.text

    await seed_rows(
        db_session, keep_rows, {"oidc_client_secret": encrypt("oidc_client_secret", "readable")}
    )
    response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
    assert response.json()["client_secret"] == PLACEHOLDER
    assert response.json()["client_secret_unreadable"] is False


async def test_the_oidc_test_route_stops_on_an_unreadable_stored_secret(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    """R2-1: 200 with the §5.4(4) failure envelope, and no test run with a blank secret."""
    await seed_rows(
        db_session, keep_rows, {"oidc_client_secret": unreadable_ciphertext("oidc_client_secret")}
    )
    probe = AsyncMock(return_value={"success": True, "metadata": {"issuer": "x"}})

    with patch("app.services.oidc.test_oidc_connection", probe):
        for sent in (PLACEHOLDER, ""):
            response = await client.post(
                "/api/auth/oidc/test",
                headers=auth_headers,
                json={
                    "issuer_url": "https://auth.example.com",
                    "client_id": "test-id",
                    "client_secret": sent,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["ok"] is False
            assert body["error"] == "secret_unreadable"
            assert REENTER in body["detail"]
            assert "OIDC client secret" in body["detail"]
        probe.assert_not_called()

        # A secret typed into the form is tested as typed, unreadable row or not.
        response = await client.post(
            "/api/auth/oidc/test",
            headers=auth_headers,
            json={
                "issuer_url": "https://auth.example.com",
                "client_id": "test-id",
                "client_secret": "typed-secret",
            },
        )
        assert response.json()["ok"] is True, response.text
        probe.assert_called_once()
        assert probe.call_args.args[0]["client_secret"] == "typed-secret"


async def test_the_mqtt_get_reports_an_unreadable_password_as_configured(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(
        db_session,
        keep_rows,
        {"livelink_mqtt_password": unreadable_ciphertext("livelink_mqtt_password")},
    )

    response = await client.get("/api/livelink/mqtt/settings", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["has_password"] is True
    assert response.json()["password_unreadable"] is True

    await seed_rows(db_session, keep_rows, {"livelink_mqtt_password": ""})
    response = await client.get("/api/livelink/mqtt/settings", headers=auth_headers)
    assert response.json()["has_password"] is False
    assert response.json()["password_unreadable"] is False
