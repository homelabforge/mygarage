"""Every backend reader of an on/off setting reads R5's vocabulary (D4a, R4, R5).

Each reader compared the stored text to "true" exactly, so a switch stored as
"1" (an import, an old restore, a hand edit) read as off at that reader while
``SettingsService.get_bool`` read it as on. One test per reader stores "1"
straight to the row's raw column, past every write path, so a canonicalizing
writer can't hide a reader that was missed; each is red on main.

The two readers that already accepted "1" (Family & Friends and the dashboard's
multi-user flag) are tested with the words they didn't accept instead.

The R4 split cases keep each site's own verdict for a missing row and a blank
one: ``oidc_auto_create_users`` missing is on and blank is off, and
``multi_user_enabled`` missing allows creating a user while blank refuses. Those
pass on main by design and are labelled regression guards.

The scheduled-job readers (``notify_milestones``, ``notify_def_low``) are
tested in their jobs' own suites under ``tests/unit/tasks/``.
"""

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.exceptions import OIDCLoginRefusedError
from app.models.audit_log import AuditLog
from app.models.settings import Setting
from app.models.user import User
from app.routes.external_vehicles import _family_friends_enabled
from app.services.livelink_service import LiveLinkService
from app.services.mqtt_subscriber import MQTTSubscriber
from app.services.oidc import create_or_update_user_from_oidc
from app.services.poi.registry import POIProviderRegistry
from app.services.shop_discovery import ShopDiscoveryService
from app.tasks import livelink_tasks
from app.utils.settings_crypto import encrypt
from tests.integration._secret_helpers import Keep, seed_rows

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_PASSWORD = "NewSecureP@ss1"


async def _forget(db: AsyncSession, keep: Keep, *keys: str) -> None:
    """No row for these keys for this test; ``keep`` puts the originals back."""
    await keep(*keys)
    await db.execute(delete(Setting).where(Setting.key.in_(keys)))
    await db.commit()


@pytest_asyncio.fixture
async def made_users(db_session: AsyncSession) -> AsyncIterator[list[str]]:
    """Usernames a test creates, deleted with their link audit rows afterwards."""
    names: list[str] = []
    yield names
    await db_session.rollback()
    user_ids = list(
        (await db_session.execute(select(User.id).where(User.username.in_(names)))).scalars()
    )
    await db_session.execute(
        delete(AuditLog).where(
            AuditLog.action == "oidc_account_linked", AuditLog.user_id.in_(user_ids)
        )
    )
    await db_session.execute(delete(User).where(User.username.in_(names)))
    await db_session.commit()


# --------------------------------------------------------------------------- LiveLink

MQTT = {
    "livelink_mqtt_enabled": "1",
    "livelink_mqtt_broker_host": "mqtt.example.com",
    "livelink_mqtt_username": "",
    "livelink_mqtt_password": "",
}


async def test_the_mqtt_subscriber_reads_a_stored_one_as_enabled(
    db_session: AsyncSession,
    keep_rows: Keep,
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await seed_rows(db_session, keep_rows, MQTT)

    with patch("app.services.mqtt_subscriber.AsyncSessionLocal", test_sessionmaker):
        config = await MQTTSubscriber()._get_config()  # pyright: ignore[reportPrivateUsage]

    assert config is not None
    assert config["host"] == "mqtt.example.com"


async def test_the_mqtt_subscriber_reads_a_stored_one_as_tls(
    db_session: AsyncSession,
    keep_rows: Keep,
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await seed_rows(
        db_session,
        keep_rows,
        {**MQTT, "livelink_mqtt_enabled": "true", "livelink_mqtt_use_tls": "1"},
    )

    with patch("app.services.mqtt_subscriber.AsyncSessionLocal", test_sessionmaker):
        config = await MQTTSubscriber()._get_config()  # pyright: ignore[reportPrivateUsage]

    assert config is not None
    assert config["use_tls"] is True


async def test_the_topic_prefix_reads_a_stored_one_as_enabled(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, MQTT)

    assert await MQTTSubscriber().configured_topic_prefix(db_session) is not None


async def test_livelink_reads_a_stored_one_as_enabled(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, {"livelink_enabled": "1"})

    assert await LiveLinkService(db_session).is_enabled() is True


async def test_the_mqtt_task_reads_a_stored_one_as_enabled(
    db_session: AsyncSession,
    keep_rows: Keep,
    test_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await seed_rows(db_session, keep_rows, {"livelink_mqtt_enabled": "1"})

    with patch("app.tasks.livelink_tasks.AsyncSessionLocal", test_sessionmaker):
        assert await livelink_tasks.is_mqtt_enabled() is True


# --------------------------------------------------------------------------- POI

POI = ["tomtom", "google_places", "yelp", "foursquare"]


def _provider_rows(name: str) -> dict[str, str]:
    key = f"{name}_api_key"
    return {f"{name}_enabled": "1", key: encrypt(key, f"readable-{name}")}


@pytest.mark.parametrize("name", POI)
async def test_the_poi_registry_reads_a_stored_one_as_enabled(
    name: str, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, _provider_rows(name))

    configs = await POIProviderRegistry(db_session)._load_provider_configs()  # pyright: ignore[reportPrivateUsage]

    assert name in [c["name"] for c in configs]


async def test_shop_discovery_reads_a_stored_one_as_tomtom_on(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, _provider_rows("tomtom"))
    service = ShopDiscoveryService(db_session)

    await service._load_settings()  # pyright: ignore[reportPrivateUsage]

    assert service.tomtom_enabled is True


async def test_the_poi_provider_list_reads_a_stored_one_as_enabled(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, _provider_rows("tomtom"))

    response = await client.get("/api/settings/poi-providers", headers=auth_headers)

    assert response.status_code == 200, response.text
    tomtom = [p for p in response.json()["providers"] if p["name"] == "tomtom"]
    assert [p["enabled"] for p in tomtom] == [True]


# --------------------------------------------------------------------------- OIDC


def _claims() -> dict[str, str]:
    tag = uuid.uuid4().hex[:10]
    return {
        "sub": f"sub-{tag}",
        "email": f"switch_{tag}@example.com",
        "preferred_username": f"switch_{tag}",
    }


async def _provision(
    db: AsyncSession, made_users: list[str], config: dict[str, str]
) -> User | None:
    claims = _claims()
    made_users.append(claims["preferred_username"])
    return await create_or_update_user_from_oidc(db, claims, None, config)


async def test_oidc_sign_in_reads_a_stored_one_as_auto_create(
    db_session: AsyncSession, made_users: list[str]
) -> None:
    user = await _provision(db_session, made_users, {"auto_create_users": "1"})

    assert user is not None


async def test_oidc_sign_in_auto_creates_when_the_setting_is_missing(
    db_session: AsyncSession, made_users: list[str]
) -> None:
    """Regression guard (R4): no row falls back to "true", so on. Passes on main."""
    user = await _provision(db_session, made_users, {})

    assert user is not None


async def test_oidc_sign_in_refuses_when_the_setting_is_blank(
    db_session: AsyncSession, made_users: list[str]
) -> None:
    """Regression guard (R4): a blank row is off, unlike a missing one. Passes on main."""
    with pytest.raises(OIDCLoginRefusedError):
        await _provision(db_session, made_users, {"auto_create_users": ""})


async def test_the_public_oidc_config_reads_a_stored_one_as_enabled(
    client: AsyncClient, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, {"oidc_enabled": "1"})

    response = await client.get("/api/auth/oidc/config")

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True


async def test_the_admin_oidc_config_reads_a_stored_one_as_enabled(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, {"oidc_enabled": "1"})

    response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True


async def test_the_admin_oidc_config_reads_a_stored_one_as_auto_create(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(db_session, keep_rows, {"oidc_auto_create_users": "1"})

    response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["auto_create_users"] is True


async def test_the_admin_oidc_config_shows_auto_create_split(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession, keep_rows: Keep
) -> None:
    """Regression guard (R4): missing reads on and blank reads off. Passes on main."""
    await _forget(db_session, keep_rows, "oidc_auto_create_users")
    response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["auto_create_users"] is True

    await seed_rows(db_session, keep_rows, {"oidc_auto_create_users": ""})
    response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["auto_create_users"] is False


async def test_oidc_login_reads_a_stored_one_as_enabled(
    client: AsyncClient, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await seed_rows(
        db_session,
        keep_rows,
        {
            "oidc_enabled": "1",
            "oidc_issuer_url": "https://auth.example.com/",
            "oidc_client_id": "test-client-id",
        },
    )

    with (
        patch(
            "app.services.oidc.get_provider_metadata",
            new_callable=AsyncMock,
            return_value={"authorization_endpoint": "https://auth.example.com/authorize"},
        ),
        patch(
            "app.services.oidc.create_authorization_url",
            new_callable=AsyncMock,
            return_value=("https://auth.example.com/authorize?client_id=test", "state123"),
        ),
    ):
        response = await client.get("/api/auth/oidc/login", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://auth.example.com/")


# --------------------------------------------------------------------------- multi-user


async def _create_user(
    client: AsyncClient, auth_headers: dict[str, str], made_users: list[str]
) -> int:
    name = f"switch_{uuid.uuid4().hex[:10]}"
    made_users.append(name)
    response = await client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"username": name, "email": f"{name}@example.com", "password": _PASSWORD},
    )
    assert response.status_code in (201, 403), response.text
    return response.status_code


async def test_creating_a_user_reads_a_stored_one_as_multi_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    made_users: list[str],
) -> None:
    await seed_rows(db_session, keep_rows, {"multi_user_enabled": "1"})

    assert await _create_user(client, auth_headers, made_users) == 201


async def test_creating_a_user_with_multi_user_missing_is_allowed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    made_users: list[str],
) -> None:
    """Regression guard (R4): no row allows creating a user. Passes on main."""
    await _forget(db_session, keep_rows, "multi_user_enabled")

    assert await _create_user(client, auth_headers, made_users) == 201


async def test_creating_a_user_with_multi_user_blank_is_refused(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    made_users: list[str],
) -> None:
    """Regression guard (R4): a blank row refuses, unlike a missing one. Passes on main."""
    await seed_rows(db_session, keep_rows, {"multi_user_enabled": ""})

    assert await _create_user(client, auth_headers, made_users) == 403


@pytest.mark.parametrize("value", ["1", " Yes "])
async def test_the_dashboard_reads_multi_user_as_on(
    value: str,
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
) -> None:
    """Red on main for " Yes " only: the dashboard already accepted "1" and "on" (Fable F-5)."""
    await seed_rows(db_session, keep_rows, {"multi_user_enabled": value})

    response = await client.get("/api/dashboard", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["multi_user_enabled"] is True


# --------------------------------------------------------------------------- Family & Friends


@pytest.mark.parametrize("value", ["on", " Yes "])
async def test_family_and_friends_reads_r5s_on_words(
    value: str, db_session: AsyncSession, keep_rows: Keep
) -> None:
    """It already accepted "1"; neither "on" nor whitespace was on (R1-M1)."""
    await seed_rows(db_session, keep_rows, {"family_friends_enabled": value})

    assert await _family_friends_enabled(db_session) is True
