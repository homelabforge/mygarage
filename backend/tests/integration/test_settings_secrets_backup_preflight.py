"""No backup this app writes may hold a plaintext secret (R1-H1): the preflight.

Plan test 12, and the restore route's `warning`:
- `ensure_secrets_encrypted` encrypts leftover plaintext secret rows and
  commits before it returns, because the snapshot reads through another
  connection; when plaintext would remain it raises `PlaintextSecretsRemain`,
  which is not a RuntimeError and maps to a 503 in either app mode;
- with a legacy plaintext row and no keyring, all four writers (the settings
  backup, the full backup, and a restore of either kind, which writes a safety
  copy first) answer 503 and write no file;
- with the keyring available, the same calls encrypt the row first: the
  settings files hold no plaintext, and neither does the full backup's
  `mygarage.db` member, read from the archive itself. The archive carries
  neither key file;
- a settings restore that skipped secret keys names them in a `warning`.

The routes run against `BackupService(tmp_path, ...)` through a patched
`get_backup_service`, not the `/data`-gated route file: under pytest the routes'
own DATABASE_PATH is the app engine's file, not the test database (F-3).
"""

import json
import sqlite3
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database import sqlite_database_path
from app.routes import backup as backup_routes
from app.services import settings_secrets
from app.services.backup_service import BackupService
from app.services.settings_secrets import (
    PlaintextSecretsRemain,
    SweepReport,
    ensure_secrets_encrypted,
)
from app.utils.settings_crypto import CIPHERTEXT_PREFIX, ENV_KEY, encrypt
from tests.integration._secret_helpers import (
    Keep,
    UseKeys,
    keyring_entry,
    only_these_secret_rows,
    raw_column,
    read_back,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KEY_A = keyring_entry(b"preflight test key A")
KEY_FOREIGN = keyring_entry(b"preflight test key from another instance")

PLAIN_NTFY = "plain-ntfy-before-the-preflight-8d2f"
PLAIN_FULL = "plain-ntfy-before-the-full-backup-6b90"
SETTINGS_FILE = "mygarage-settings-preflight.json"
FULL_FILE = "mygarage-full-preflight.tar.gz"


def _service(tmp_path: Path, database_path: Path | None = None) -> BackupService:
    backups = tmp_path / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    return BackupService(
        backup_dir=backups, database_path=database_path, data_dir=data, is_sqlite=True
    )


def _use_service(monkeypatch: pytest.MonkeyPatch, service: BackupService) -> None:
    monkeypatch.setattr(backup_routes, "get_backup_service", lambda: service)


def _place_backups(service: BackupService) -> None:
    """One settings backup and one full backup for the restore route to pick up."""
    (service.backup_dir / SETTINGS_FILE).write_text(
        json.dumps({"version": "2.1", "type": "settings", "settings": []})
    )
    with tarfile.open(service.backup_dir / FULL_FILE, "w:gz"):
        pass


def _test_database_file(engine: AsyncEngine) -> Path:
    path = sqlite_database_path(engine.url)
    if path is None:
        pytest.skip("the full backup snapshots a SQLite file; PostgreSQL runs pg_dump")
    return path.resolve()


# ------------------------------------------------------- the preflight itself


def test_plaintext_secrets_remain_is_not_a_runtime_error() -> None:
    """R2-2: `create-full`'s `except RuntimeError` must never turn the 503 into a 500."""
    assert not issubclass(PlaintextSecretsRemain, RuntimeError)
    message = str(PlaintextSecretsRemain(("ntfy_token", "llm_api_key")))
    assert "ntfy_token, llm_api_key" in message
    assert ENV_KEY in message


async def test_the_preflight_encrypts_and_commits_before_returning(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    kid = use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})

    await ensure_secrets_encrypted(db_session)

    # A fresh connection sees only committed rows, as the snapshot does.
    stored = await raw_column(test_sessionmaker, "ntfy_token")
    assert stored is not None and stored.startswith(f"{CIPHERTEXT_PREFIX}{kid}:")
    assert await read_back(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


async def test_with_no_keyring_the_preflight_refuses_and_writes_nothing(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    await only_these_secret_rows(
        db_session, keep_rows, {"ntfy_token": PLAIN_NTFY, "slack_webhook_url": ""}
    )
    assert use_keys("not-a-valid-key") is None

    with pytest.raises(PlaintextSecretsRemain) as raised:
        await ensure_secrets_encrypted(db_session)

    assert raised.value.keys == ("ntfy_token",)
    assert PLAIN_NTFY not in str(raised.value)
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


async def test_with_no_keyring_and_no_plaintext_the_preflight_passes(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    """Ciphertext, even one nothing opens now, is safe to copy: no 503 for it."""
    use_keys(KEY_A)
    stored = encrypt("ntfy_token", PLAIN_NTFY)
    await only_these_secret_rows(
        db_session, keep_rows, {"ntfy_token": stored, "slack_webhook_url": ""}
    )
    assert use_keys("not-a-valid-key") is None

    await ensure_secrets_encrypted(db_session)

    assert await raw_column(test_sessionmaker, "ntfy_token") == stored


async def test_plaintext_left_by_the_encrypt_step_is_still_refused(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    """The raw re-check, not the encrypt step's report, decides."""
    use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})

    with (
        patch.object(
            settings_secrets, "encrypt_secret_rows", AsyncMock(return_value=SweepReport())
        ),
        pytest.raises(PlaintextSecretsRemain) as raised,
    ):
        await ensure_secrets_encrypted(db_session)

    assert raised.value.keys == ("ntfy_token",)
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


async def test_a_failed_encrypt_write_with_plaintext_left_is_refused(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
) -> None:
    use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})
    failure = OperationalError("UPDATE settings", {}, Exception("disk I/O error"))

    with (
        patch.object(settings_secrets, "encrypt_secret_rows", AsyncMock(side_effect=failure)),
        pytest.raises(PlaintextSecretsRemain) as raised,
    ):
        await ensure_secrets_encrypted(db_session)

    assert raised.value.__cause__ is failure
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


def _app(*, debug: bool) -> FastAPI:
    """An app registered the way main.py registers its own, with one refusing route."""
    from app.utils.error_handlers import register_error_handlers

    app = FastAPI(debug=debug)
    register_error_handlers(app, debug=debug)

    @app.post("/backup")
    async def backup() -> None:
        raise PlaintextSecretsRemain(("ntfy_token",))

    return app


@pytest.mark.parametrize("debug", [False, True], ids=["production", "debug"])
async def test_the_refusal_is_a_503_in_either_mode(debug: bool) -> None:
    """R2-3: registered after the debug branch, so debug has it too."""
    transport = ASGITransport(app=_app(debug=debug))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/backup")

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert "ntfy_token" in detail
    assert ENV_KEY in detail


# ------------------------------------------------------- the four writers


@pytest.mark.parametrize(
    "path",
    [
        "/api/backup/create",
        "/api/backup/create-full",
        f"/api/backup/restore/{SETTINGS_FILE}",
        f"/api/backup/restore/{FULL_FILE}",
    ],
    ids=["settings-backup", "full-backup", "settings-restore", "full-restore"],
)
async def test_every_writer_refuses_while_plaintext_remains(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_engine: AsyncEngine,
    path: str,
) -> None:
    database = sqlite_database_path(test_engine.url)
    service = _service(tmp_path, database.resolve() if database else None)
    _place_backups(service)
    _use_service(monkeypatch, service)
    before = sorted(p.name for p in service.backup_dir.iterdir())
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})
    assert use_keys("not-a-valid-key") is None

    response = await client.post(path, headers=auth_headers)

    assert response.status_code == 503, response.text
    assert "ntfy_token" in response.json()["detail"]
    assert PLAIN_NTFY not in response.text
    assert sorted(p.name for p in service.backup_dir.iterdir()) == before
    assert not (service.data_dir / ".restore-pending").exists()
    assert await raw_column(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


async def test_a_settings_backup_encrypts_first(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_keys(KEY_A)
    service = _service(tmp_path)
    _use_service(monkeypatch, service)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})

    response = await client.post("/api/backup/create", headers=auth_headers)

    assert response.status_code == 200, response.text
    text = (service.backup_dir / response.json()["backup"]["filename"]).read_text()
    assert PLAIN_NTFY not in text
    stored = await raw_column(test_sessionmaker, "ntfy_token")
    assert stored is not None and stored.startswith(CIPHERTEXT_PREFIX)
    entries = {row["key"]: row["value"] for row in json.loads(text)["settings"]}
    assert entries["ntfy_token"] == stored


async def test_a_settings_restore_encrypts_before_its_safety_copy(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_keys(KEY_A)
    service = _service(tmp_path)
    _place_backups(service)
    _use_service(monkeypatch, service)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})

    response = await client.post(f"/api/backup/restore/{SETTINGS_FILE}", headers=auth_headers)

    assert response.status_code == 200, response.text
    safety = response.json()["details"]["safety_backup"]
    text = (service.backup_dir / safety).read_text()
    assert PLAIN_NTFY not in text
    entries = {row["key"]: row["value"] for row in json.loads(text)["settings"]}
    assert entries["ntfy_token"] == await raw_column(test_sessionmaker, "ntfy_token")
    assert entries["ntfy_token"].startswith(CIPHERTEXT_PREFIX)


async def test_a_full_backup_encrypts_first_and_leaves_the_key_files_out(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    use_keys: UseKeys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_engine: AsyncEngine,
) -> None:
    """The archive's own `mygarage.db`, not the live session, is what's checked (F-3, R2-2)."""
    database = _test_database_file(test_engine)
    use_keys(KEY_A)
    service = _service(tmp_path, database)
    for name in ("settings.key", "secret.key"):
        (service.data_dir / name).write_text("key material that stays out of the archive")
    (service.data_dir / "photos").mkdir()
    (service.data_dir / "photos" / "car.jpg").write_bytes(b"jpeg")
    _use_service(monkeypatch, service)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_FULL})

    response = await client.post("/api/backup/create-full", headers=auth_headers)

    assert response.status_code == 200, response.text
    archive = service.backup_dir / response.json()["backup"]["filename"]
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        member = tar.extractfile("mygarage.db")
        assert member is not None
        snapshot = member.read()
    assert "photos/car.jpg" in names
    assert not {"settings.key", "secret.key"} & {Path(n).name for n in names}
    # No plaintext anywhere in the file, freed cells included.
    assert PLAIN_FULL.encode() not in snapshot
    copy = tmp_path / "snapshot.db"
    copy.write_bytes(snapshot)
    conn = sqlite3.connect(copy)
    try:
        (stored,) = conn.execute("SELECT value FROM settings WHERE key = 'ntfy_token'").fetchone()
    finally:
        conn.close()
    assert stored.startswith(CIPHERTEXT_PREFIX)


# ------------------------------------------------------- the restore's warning


async def test_a_restore_that_skipped_secrets_names_them_in_a_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    use_keys: UseKeys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_keys(KEY_FOREIGN)
    foreign = {key: encrypt(key, "another-instance") for key in ("llm_api_key", "gotify_token")}
    use_keys(KEY_A)
    service = _service(tmp_path)
    _use_service(monkeypatch, service)
    await only_these_secret_rows(db_session, keep_rows, {})
    (service.backup_dir / SETTINGS_FILE).write_text(
        json.dumps(
            {
                "version": "2.1",
                "type": "settings",
                "settings": [{"key": k, "value": v} for k, v in foreign.items()],
            }
        )
    )

    response = await client.post(f"/api/backup/restore/{SETTINGS_FILE}", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["details"]["skipped_secret_keys"] == ["gotify_token", "llm_api_key"]
    assert "gotify_token, llm_api_key" in body["warning"]
    assert CIPHERTEXT_PREFIX not in response.text


async def test_a_clean_restore_has_no_warning(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    keep_rows: Keep,
    use_keys: UseKeys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    use_keys(KEY_A)
    service = _service(tmp_path)
    _place_backups(service)
    _use_service(monkeypatch, service)
    await only_these_secret_rows(db_session, keep_rows, {})

    response = await client.post(f"/api/backup/restore/{SETTINGS_FILE}", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["details"]["skipped_secret_keys"] == []
    assert "warning" not in response.json()
