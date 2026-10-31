"""SSO sign-in needs usable SSO, on every writer of the four sign-in keys (S1c-01, D3).

`auth_mode=oidc` with SSO off, or with a blank issuer URL or client ID, leaves
an instance nobody can sign in to. The settings screen orders its writes so it
never gets there, but the generic settings routes, the OIDC PUT and a settings
restore all wrote those keys with no check, and a dropped reply on the screen's
own switch could land there too. Now each of them refuses, and all of them take
one lock first so two writers can't each pass the check against the other's
old value.

Lives in `tests/integration/` so the PG sidecar runs it too.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, select, text

from app.models.settings import Setting

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Written out, not imported: the route tests have to collect on main, where the
# module that holds these doesn't exist yet.
SIGN_IN_KEYS = ("auth_mode", "oidc_enabled", "oidc_issuer_url", "oidc_client_id")
# Everything else the OIDC PUT writes, so a test puts it all back.
OIDC_PUT_KEYS = (
    "oidc_provider_name",
    "oidc_client_secret",
    "oidc_scopes",
    "oidc_auto_create_users",
    "oidc_admin_group",
    "oidc_username_claim",
    "oidc_email_claim",
    "oidc_full_name_claim",
    "oidc_redirect_uri",
)

SWITCH_TO_SSO = (
    "Turn on SSO and fill in its issuer URL and client ID before switching sign-in to SSO."
)
SSO_IN_USE = (
    "Sign-in is set to SSO. Switch sign-in to local or none before turning SSO off "
    "or clearing its issuer URL or client ID."
)
RESTORE_REFUSED = (
    "This backup would leave sign-in set to SSO with SSO off or missing its issuer URL "
    "or client ID, so nothing was restored."
)

ISSUER = "https://auth.example.com"
CLIENT = "garage-client"
USABLE = {"oidc_enabled": "true", "oidc_issuer_url": ISSUER, "oidc_client_id": CLIENT}

type Seed = Callable[..., Awaitable[None]]


@pytest_asyncio.fixture
async def seed(db_session, keep_rows) -> Seed:
    """Set sign-in rows for one test (None deletes the row); keep_rows puts them back."""
    await keep_rows(*SIGN_IN_KEYS, *OIDC_PUT_KEYS, "ntfy_topic")

    async def _seed(**values: str | None) -> None:
        for key, value in values.items():
            await db_session.execute(delete(Setting).where(Setting.key == key))
            if value is not None:
                db_session.add(Setting(key=key, value=value))
        await db_session.commit()

    return _seed


async def stored(test_sessionmaker, key: str) -> str | None:
    """The committed value under `key`, read in a fresh session; None with no row."""
    async with test_sessionmaker() as db:
        row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return None if row is None else row.value


async def write(
    client: AsyncClient, headers: dict[str, str], endpoint: str, key: str, value: str | None
) -> Response:
    """Write one key through one generic settings route."""
    if endpoint == "create":
        return await client.post(
            "/api/settings", headers=headers, json={"key": key, "value": value}
        )
    if endpoint == "put":
        return await client.put(f"/api/settings/{key}", headers=headers, json={"value": value})
    if endpoint == "batch":
        return await client.post(
            "/api/settings/batch", headers=headers, json={"settings": {key: value}}
        )
    if endpoint == "delete":
        return await client.delete(f"/api/settings/{key}", headers=headers)
    raise AssertionError(f"no request builder for {endpoint}")


SUCCESS = {"create": 201, "put": 200, "batch": 200, "delete": 204}


def admin_payload(**overrides: object) -> dict[str, object]:
    """A full OIDC admin PUT body, the way the SSO settings send it."""
    return {
        "enabled": True,
        "provider_name": "Rauthy",
        "issuer_url": ISSUER,
        "client_id": CLIENT,
        "client_secret": "",
        "scopes": "openid profile email",
        "auto_create_users": True,
        "admin_group": "",
        "username_claim": "preferred_username",
        "email_claim": "email",
        "full_name_claim": "name",
        **overrides,
    }


class TestSwitchingToSso:
    """Batch, PUT and create of auth_mode=oidc need SSO on with an issuer and client ID."""

    @pytest.mark.parametrize("mode", ["oidc", "OIDC"])
    @pytest.mark.parametrize("endpoint", ["create", "put", "batch"])
    @pytest.mark.parametrize(
        "sso",
        [
            {"oidc_enabled": "false", "oidc_issuer_url": ISSUER, "oidc_client_id": CLIENT},
            {"oidc_enabled": None, "oidc_issuer_url": ISSUER, "oidc_client_id": CLIENT},
            {"oidc_enabled": "true", "oidc_issuer_url": "", "oidc_client_id": CLIENT},
            {"oidc_enabled": "true", "oidc_issuer_url": ISSUER, "oidc_client_id": "   "},
            {"oidc_enabled": "true", "oidc_issuer_url": ISSUER, "oidc_client_id": None},
        ],
        ids=["sso-off", "sso-missing", "blank-issuer", "blank-client", "missing-client"],
    )
    async def test_without_usable_sso_it_is_a_409_and_nothing_is_written(
        self, client, auth_headers, seed, test_sessionmaker, mode, endpoint, sso
    ):
        before = None if endpoint == "create" else "local"
        await seed(auth_mode=before, **sso)

        response = await write(client, auth_headers, endpoint, "auth_mode", mode)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == SWITCH_TO_SSO
        assert await stored(test_sessionmaker, "auth_mode") == before

    @pytest.mark.parametrize("mode", ["oidc", "OIDC"])
    @pytest.mark.parametrize("endpoint", ["create", "put", "batch"])
    async def test_with_usable_sso_it_writes(
        self, client, auth_headers, seed, test_sessionmaker, mode, endpoint
    ):
        """Guard: the rule isn't a blanket refusal of SSO mode."""
        await seed(auth_mode=None if endpoint == "create" else "local", **USABLE)

        response = await write(client, auth_headers, endpoint, "auth_mode", mode)

        assert response.status_code == SUCCESS[endpoint], response.text
        assert await stored(test_sessionmaker, "auth_mode") == mode

    async def test_a_batch_that_sets_up_sso_and_switches_to_it_together_is_fine(
        self, client, auth_headers, seed, test_sessionmaker
    ):
        """Guard: the check sees the whole batch, not each key against the old state."""
        await seed(auth_mode="local", oidc_enabled="false", oidc_issuer_url="", oidc_client_id="")

        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {**USABLE, "auth_mode": "oidc"}},
        )

        assert response.status_code == 200, response.text
        assert await stored(test_sessionmaker, "auth_mode") == "oidc"
        assert await stored(test_sessionmaker, "oidc_enabled") == "true"
        assert await stored(test_sessionmaker, "oidc_client_id") == CLIENT


# (endpoint, key, value): what would take SSO away while sign-in uses it.
_TAKE_SSO_AWAY = [
    ("put", "oidc_enabled", "false"),
    ("batch", "oidc_enabled", "false"),
    ("batch", "oidc_enabled", "off"),
    ("put", "oidc_issuer_url", ""),
    ("put", "oidc_issuer_url", "   "),
    ("batch", "oidc_issuer_url", "   "),
    # Login rstrips the slash, so "/" is no issuer at all.
    ("put", "oidc_issuer_url", "/"),
    ("batch", "oidc_issuer_url", "/"),
    ("put", "oidc_client_id", "  "),
    ("batch", "oidc_client_id", ""),
    ("delete", "oidc_enabled", None),
    ("delete", "oidc_issuer_url", None),
    ("delete", "oidc_client_id", None),
]


class TestTakingSsoAwayInSsoMode:
    """Turning SSO off, or blanking or deleting its issuer or client ID, needs a non-SSO mode."""

    @pytest.mark.parametrize(("endpoint", "key", "value"), _TAKE_SSO_AWAY)
    async def test_while_the_mode_is_oidc_it_is_a_409_and_nothing_changes(
        self, client, auth_headers, seed, test_sessionmaker, endpoint, key, value
    ):
        await seed(auth_mode="oidc", **USABLE)

        response = await write(client, auth_headers, endpoint, key, value)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == SSO_IN_USE
        assert await stored(test_sessionmaker, key) == USABLE[key]

    @pytest.mark.parametrize(("endpoint", "key", "value"), _TAKE_SSO_AWAY)
    async def test_while_the_mode_is_local_it_goes_through(
        self, client, auth_headers, seed, test_sessionmaker, endpoint, key, value
    ):
        """Guard: the rule only bites in SSO mode."""
        await seed(auth_mode="local", **USABLE)

        response = await write(client, auth_headers, endpoint, key, value)

        assert response.status_code == SUCCESS[endpoint], response.text
        # A switch word is stored canonically; a blank is stored as sent.
        expected = None if value is None else {"off": "false"}.get(value, value)
        assert await stored(test_sessionmaker, key) == expected

    async def test_a_batch_that_leaves_sso_mode_and_turns_sso_off_together_is_fine(
        self, client, auth_headers, seed, test_sessionmaker
    ):
        """Guard: leaving SSO mode in the same batch makes turning SSO off fine."""
        await seed(auth_mode="oidc", **USABLE)

        response = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"auth_mode": "local", "oidc_enabled": "false"}},
        )

        assert response.status_code == 200, response.text
        assert await stored(test_sessionmaker, "auth_mode") == "local"
        assert await stored(test_sessionmaker, "oidc_enabled") == "false"


class TestOidcPut:
    """The SSO settings PUT writes all three SSO keys, so it gets the same rule."""

    @pytest.mark.parametrize(
        "overrides",
        [
            {"enabled": False},
            {"issuer_url": ""},
            {"issuer_url": "   "},
            {"client_id": ""},
            {"client_id": "   "},
        ],
        ids=["sso-off", "blank-issuer", "spaces-issuer", "blank-client", "spaces-client"],
    )
    async def test_in_sso_mode_taking_sso_away_is_a_409_and_the_config_stays(
        self, client, auth_headers, seed, test_sessionmaker, overrides
    ):
        await seed(auth_mode="oidc", oidc_provider_name="Before", **USABLE)

        response = await client.put(
            "/api/auth/oidc/config/admin",
            headers=auth_headers,
            json=admin_payload(provider_name="After", **overrides),
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == SSO_IN_USE
        for key, value in USABLE.items():
            assert await stored(test_sessionmaker, key) == value
        assert await stored(test_sessionmaker, "oidc_provider_name") == "Before"

    @pytest.mark.parametrize(
        "overrides",
        [{"enabled": False}, {"issuer_url": "   "}, {"client_id": ""}],
        ids=["sso-off", "spaces-issuer", "blank-client"],
    )
    async def test_in_local_mode_the_same_put_goes_through(
        self, client, auth_headers, seed, test_sessionmaker, overrides
    ):
        """Guard: the rule only bites in SSO mode."""
        await seed(auth_mode="local", **USABLE)

        response = await client.put(
            "/api/auth/oidc/config/admin", headers=auth_headers, json=admin_payload(**overrides)
        )

        assert response.status_code == 200, response.text
        assert await stored(test_sessionmaker, "oidc_provider_name") == "Rauthy"

    @pytest.mark.parametrize("mode", ["local", "oidc"])
    async def test_a_client_id_with_spaces_is_stored_stripped(
        self, client, auth_headers, seed, test_sessionmaker, mode
    ):
        """And the check sees the stripped value, so SSO mode accepts it."""
        await seed(auth_mode=mode, **USABLE)

        response = await client.put(
            "/api/auth/oidc/config/admin",
            headers=auth_headers,
            json=admin_payload(client_id="  spaced-client  "),
        )

        assert response.status_code == 200, response.text
        assert await stored(test_sessionmaker, "oidc_client_id") == "spaced-client"


def _backup_file(directory: Path, name: str, values: dict[str, str]) -> str:
    """A settings backup in the exporter's shape, holding `values`."""
    rows = [{"key": key, "value": value} for key, value in values.items()]
    payload = {"version": "2.1", "type": "settings", "settings": rows}
    (directory / name).write_text(json.dumps(payload))
    return name


@pytest.fixture
def backup_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the backup routes at an empty folder of this test's own."""
    from app.routes import backup as backup_routes

    folder = tmp_path / "backups"
    folder.mkdir()
    monkeypatch.setattr(backup_routes, "BACKUP_DIR", folder)
    return folder


class TestSettingsRestore:
    """A settings restore checks the state it leaves, not the rows one by one."""

    async def test_a_file_that_would_leave_sso_mode_with_sso_off_is_a_409_and_restores_nothing(
        self, client, auth_headers, seed, test_sessionmaker, backup_dir
    ):
        await seed(auth_mode="local", oidc_enabled="false", ntfy_topic="dark")
        name = _backup_file(
            backup_dir,
            "mygarage-settings-bad.json",
            {"ntfy_topic": "light", "auth_mode": "oidc", "oidc_enabled": "false"},
        )

        response = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == RESTORE_REFUSED
        assert await stored(test_sessionmaker, "auth_mode") == "local"
        assert await stored(test_sessionmaker, "ntfy_topic") == "dark"
        # Nothing changed, so the safety copy it wrote is a stray and goes (R12).
        assert sorted(p.name for p in backup_dir.iterdir()) == [name]

    async def test_a_consistent_sso_file_still_restores(
        self, client, auth_headers, seed, test_sessionmaker, backup_dir
    ):
        """Guard: SSO mode with usable SSO restores like any other file."""
        await seed(auth_mode="local", oidc_enabled="false", ntfy_topic="dark")
        name = _backup_file(
            backup_dir,
            "mygarage-settings-good.json",
            {"ntfy_topic": "light", "auth_mode": "oidc", **USABLE},
        )

        response = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert await stored(test_sessionmaker, "auth_mode") == "oidc"
        assert await stored(test_sessionmaker, "oidc_client_id") == CLIENT
        assert await stored(test_sessionmaker, "ntfy_topic") == "light"

    async def test_an_instance_already_broken_still_restores_a_file_without_sign_in_keys(
        self, client, auth_headers, seed, test_sessionmaker, backup_dir
    ):
        """Guard (F1-1): the check runs only when the file touched a sign-in key.

        Mutation: run the check unconditionally after the apply loop and this goes red.
        """
        await seed(auth_mode="oidc", oidc_enabled="false", ntfy_topic="dark")
        name = _backup_file(backup_dir, "mygarage-settings-theme.json", {"ntfy_topic": "light"})

        response = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert await stored(test_sessionmaker, "ntfy_topic") == "light"


class _FrozenClock(datetime):
    """Every `now()` lands in the same second, as two quick restores do."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls(2026, 10, 31, 12, 0, 0)


class TestRestoreSafetyFile:
    """The safety copy is only left behind when a restore actually ran."""

    @pytest.mark.parametrize(
        "content",
        [
            '{"version": "2.1", "type": "settings"}',
            '{"settings": {"theme": "dark"}}',
            "{not json",
            "5",
            "null",
            '"settings"',
        ],
        ids=[
            "missing-settings",
            "settings-not-a-list",
            "not-json",
            "top-level-number",
            "top-level-null",
            "top-level-string",
        ],
    )
    async def test_a_malformed_file_is_a_400_and_leaves_no_safety_copy(
        self, client, auth_headers, backup_dir, content
    ):
        name = "mygarage-settings-malformed.json"
        (backup_dir / name).write_text(content)

        response = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)

        assert response.status_code == 400, response.text
        assert sorted(p.name for p in backup_dir.iterdir()) == [name]

    async def test_two_restores_in_one_second_keep_two_safety_copies(
        self, client, auth_headers, seed, backup_dir, monkeypatch
    ):
        from app.services import backup_service as backup_module

        monkeypatch.setattr(backup_module, "datetime", _FrozenClock)
        await seed(ntfy_topic="dark")
        name = _backup_file(backup_dir, "mygarage-settings-topic.json", {"ntfy_topic": "light"})

        first = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)
        second = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        copies = {r.json()["details"]["safety_backup"] for r in (first, second)}
        assert len(copies) == 2
        assert all((backup_dir / copy).exists() for copy in copies)

    async def test_a_refused_restore_keeps_the_safety_copy_of_one_made_the_same_second(
        self, client, auth_headers, seed, backup_dir, monkeypatch
    ):
        """The refusal deletes its own stray, never the earlier restore's copy."""
        from app.services import backup_service as backup_module

        monkeypatch.setattr(backup_module, "datetime", _FrozenClock)
        await seed(auth_mode="local", oidc_enabled="false", ntfy_topic="dark")
        good = _backup_file(backup_dir, "mygarage-settings-ok.json", {"ntfy_topic": "light"})
        bad = _backup_file(
            backup_dir, "mygarage-settings-sso.json", {"auth_mode": "oidc", "oidc_enabled": "false"}
        )

        first = await client.post(f"/api/backup/restore/{good}", headers=auth_headers)
        refused = await client.post(f"/api/backup/restore/{bad}", headers=auth_headers)

        assert first.status_code == 200, first.text
        assert refused.status_code == 409, refused.text
        assert (backup_dir / first.json()["details"]["safety_backup"]).exists()


@pytest.fixture
def lock_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every writer's calls to the lock and the check, in order, then run the real ones."""
    from app.routes import oidc as oidc_routes
    from app.routes import settings as settings_routes
    from app.services import auth_settings
    from app.services import backup_service as backup_module

    calls: list[str] = []
    real_lock = auth_settings.lock_auth_settings
    real_ensure = auth_settings.ensure_sso_mode_usable

    async def lock(db):
        calls.append("lock")
        await real_lock(db)

    async def ensure(db, pending):
        calls.append("ensure")
        await real_ensure(db, pending)

    for module in (settings_routes, oidc_routes, backup_module):
        monkeypatch.setattr(module, "lock_auth_settings", lock)
        monkeypatch.setattr(module, "ensure_sso_mode_usable", ensure)
    return calls


class TestEveryWriterLocksFirst:
    """The check is only sound under the lock, so each writer takes it before checking."""

    @pytest.mark.parametrize("endpoint", ["create", "put", "batch", "delete"])
    async def test_a_settings_route_locks_then_checks(
        self, client, auth_headers, seed, lock_spy, endpoint
    ):
        await seed(auth_mode="local", **{**USABLE, "oidc_client_id": None})
        if endpoint != "create":
            await seed(oidc_client_id=CLIENT)

        response = await write(client, auth_headers, endpoint, "oidc_client_id", "other-client")

        assert response.status_code == SUCCESS[endpoint], response.text
        assert lock_spy == ["lock", "ensure"]

    async def test_the_oidc_put_locks_then_checks(self, client, auth_headers, seed, lock_spy):
        await seed(auth_mode="local", **USABLE)

        response = await client.put(
            "/api/auth/oidc/config/admin", headers=auth_headers, json=admin_payload()
        )

        assert response.status_code == 200, response.text
        assert lock_spy == ["lock", "ensure"]

    async def test_the_settings_restore_locks_then_checks(
        self, client, auth_headers, seed, lock_spy, backup_dir
    ):
        await seed(auth_mode="local", **USABLE)
        name = _backup_file(backup_dir, "mygarage-settings-lock.json", {"oidc_client_id": CLIENT})

        response = await client.post(f"/api/backup/restore/{name}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert lock_spy == ["lock", "ensure"]

    async def test_a_batch_without_sign_in_keys_takes_no_lock(
        self, client, auth_headers, seed, lock_spy
    ):
        """Guard (R8): a notification save mustn't queue behind a sign-in change.

        Mutation: drop the `AUTH_KEYS` condition in `batch_update_settings` and this goes red.
        """
        response = await client.post(
            "/api/settings/batch", headers=auth_headers, json={"settings": {"ntfy_topic": "dark"}}
        )

        assert response.status_code == 200, response.text
        assert lock_spy == []


class TestTheLockSerialises:
    async def test_a_second_holder_waits_for_the_first_to_commit(
        self, test_sessionmaker, init_test_db
    ):
        """Two real connections: the second lock returns only after the first commits."""
        from app.services.auth_settings import lock_auth_settings

        events: list[str] = []

        async def take(db) -> None:
            await lock_auth_settings(db)
            events.append("second locked")

        async with test_sessionmaker() as first, test_sessionmaker() as second:
            await lock_auth_settings(first)
            waiter = asyncio.create_task(take(second))
            try:
                await asyncio.sleep(0.5)
                assert not waiter.done(), "the second lock didn't wait for the first holder"
                events.append("first committed")
                await first.commit()
                await asyncio.wait_for(waiter, timeout=10)
            finally:
                # First lets go before second is touched, or a failure hangs here. The
                # waiter is only drained, so a failure above surfaces as itself.
                await first.rollback()
                await asyncio.wait({waiter}, timeout=40)
                if not waiter.done():
                    # Let the cancel land before second is touched.
                    waiter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await waiter
                elif not waiter.cancelled():
                    waiter.exception()
                await second.rollback()

        assert events == ["first committed", "second locked"]

    async def test_it_refuses_to_nest_inside_an_open_transaction(self, test_sessionmaker):
        """Guard: a misplaced call is a programming error, not a 503.

        Mutation: drop the `in_transaction` check in `sqlite_begin_immediate` and this goes red.
        """
        from app.services.auth_settings import AUTH_LOCK_CONTRACT, lock_auth_settings

        async with test_sessionmaker() as db:
            if db.get_bind().dialect.name != "sqlite":
                pytest.skip("the nesting guard exists for SQLite's BEGIN IMMEDIATE only")
            await db.execute(text("BEGIN IMMEDIATE"))
            try:
                with pytest.raises(RuntimeError, match=AUTH_LOCK_CONTRACT):
                    await lock_auth_settings(db)
            finally:
                await db.rollback()

    async def test_it_succeeds_after_a_plain_read(self, test_sessionmaker):
        """Guard: the admin check reads settings first, and that mustn't trip the guard."""
        from app.services.auth_settings import lock_auth_settings

        async with test_sessionmaker() as db:
            await db.execute(select(Setting.key).limit(1))
            await lock_auth_settings(db)
            await db.rollback()
