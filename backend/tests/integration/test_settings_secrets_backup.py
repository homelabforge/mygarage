"""Settings backups carry secrets as stored, and the restore handles each case safely (D4).

Plan tests 3, 4, 13 and the legacy-restore part of 14:
- a settings backup, and the restore's safety copy, hold each secret's stored
  ciphertext byte for byte (format 2.1), never its plaintext;
- the restore, per secret key: the mask placeholder is skipped; a current-key
  ciphertext is stored byte for byte; an older-key one is decrypted and stored
  under the current key; one that doesn't open is skipped, keeps the current
  value and is listed in `skipped_secret_keys`; plaintext (a 2.0 file) is
  encrypted; with no keyring, plaintext is skipped and listed too. The file's
  `encrypted` flag plays no part;
- rotation (R1-H2): a backup under key A, restored after rotating to B, still
  reads once A is dropped;
- an unchanged legacy value restored over a plaintext row ends up encrypted (R1-H3).

Every assertion about a file reads the raw JSON text, and every assertion about
the database reads the raw column through a fresh connection.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Setting
from app.services.backup_service import BackupService
from app.services.oidc import MASKED_SECRET_PLACEHOLDER
from app.services.settings_secrets import sweep_secret_settings
from app.utils.settings_crypto import CIPHERTEXT_PREFIX, current_kid, decrypt, encrypt
from tests.integration._secret_helpers import (
    Keep,
    UseKeys,
    keyring_entry,
    only_these_secret_rows,
    raw_column,
    read_back,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KEY_A = keyring_entry(b"backup test key A")
KEY_B = keyring_entry(b"backup test key B")
KEY_FOREIGN = keyring_entry(b"backup test key from another instance")

PROBE = "__backup_secrets_probe__"
PLAIN_NTFY = "plain-ntfy-in-a-backup-31c7"
PLAIN_LLM = "plain-llm-key-in-a-backup-a04e"


def _service(tmp_path: Path) -> BackupService:
    """A service writing into this test's own backup folder."""
    backups = tmp_path / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    return BackupService(
        backup_dir=backups, database_path=None, data_dir=tmp_path / "data", is_sqlite=True
    )


def _write_file(service: BackupService, rows: list[dict[str, Any]], *, version: str = "2.1") -> str:
    filename = f"mygarage-settings-restore-test-{version}.json"
    payload = {"version": version, "type": "settings", "settings": rows}
    (service.backup_dir / filename).write_text(json.dumps(payload))
    return filename


def _entries(text: str) -> dict[str, dict[str, Any]]:
    return {row["key"]: row for row in json.loads(text)["settings"]}


async def _seed_through_setter(db: AsyncSession, rows: dict[str, str]) -> None:
    """Write values the way the app does, through `Setting.value`."""
    for key, value in rows.items():
        row = await db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    await db.commit()


# ---------------------------------------------------------------- test 3


async def test_a_settings_backup_holds_ciphertext_as_stored(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {})
    await keep_rows(PROBE)
    await _seed_through_setter(
        db_session, {"ntfy_token": PLAIN_NTFY, "llm_api_key": PLAIN_LLM, PROBE: "visible"}
    )
    stored_ntfy = await raw_column(test_sessionmaker, "ntfy_token")
    assert stored_ntfy is not None and stored_ntfy.startswith(CIPHERTEXT_PREFIX)
    service = _service(tmp_path)

    info = await service.create_settings_backup(db_session)

    text = (service.backup_dir / info["filename"]).read_text()
    assert PLAIN_NTFY not in text
    assert PLAIN_LLM not in text
    assert json.loads(text)["version"] == "2.1"
    entries = _entries(text)
    assert entries["ntfy_token"]["value"] == stored_ntfy
    assert entries["llm_api_key"]["value"] == await raw_column(test_sessionmaker, "llm_api_key")
    assert entries[PROBE]["value"] == "visible"


async def test_the_restore_safety_copy_holds_ciphertext_as_stored(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {})
    await keep_rows(PROBE)
    await _seed_through_setter(db_session, {"ntfy_token": PLAIN_NTFY})
    stored_ntfy = await raw_column(test_sessionmaker, "ntfy_token")
    service = _service(tmp_path)
    filename = _write_file(service, [{"key": PROBE, "value": "restored"}])

    details = await service.restore_settings_backup(filename, db_session)

    text = (service.backup_dir / details["safety_backup"]).read_text()
    assert PLAIN_NTFY not in text
    assert json.loads(text)["version"] == "2.1"
    assert _entries(text)["ntfy_token"]["value"] == stored_ntfy


# ---------------------------------------------------------------- test 4


async def test_a_legacy_plaintext_file_is_encrypted_on_restore(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """A 2.0 file: plaintext secrets, and an `encrypted` flag that says otherwise."""
    kid = use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {})
    service = _service(tmp_path)
    filename = _write_file(
        service,
        [
            {"key": "ntfy_token", "value": PLAIN_NTFY, "encrypted": True},
            {"key": "llm_api_key", "value": PLAIN_LLM, "encrypted": False},
            {"key": "slack_webhook_url", "value": "", "encrypted": True},
        ],
        version="2.0",
    )

    details = await service.restore_settings_backup(filename, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == []
    assert details["restored_count"] == 3
    for key, plain in (("ntfy_token", PLAIN_NTFY), ("llm_api_key", PLAIN_LLM)):
        stored = await raw_column(test_sessionmaker, key)
        assert stored is not None and stored.startswith(f"{CIPHERTEXT_PREFIX}{kid}:"), key
        assert plain not in stored
        assert await read_back(test_sessionmaker, key) == plain
    assert await raw_column(test_sessionmaker, "slack_webhook_url") == ""


async def test_a_current_key_ciphertext_is_stored_byte_for_byte(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """Same-key round trip: back up, change the value, restore, get the backup's bytes back."""
    use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {})
    await _seed_through_setter(db_session, {"ntfy_token": PLAIN_NTFY})
    service = _service(tmp_path)
    backup = (await service.create_settings_backup(db_session))["filename"]
    in_file = _entries((service.backup_dir / backup).read_text())["ntfy_token"]["value"]
    await _seed_through_setter(db_session, {"ntfy_token": "changed-after-the-backup"})

    details = await service.restore_settings_backup(backup, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == []
    assert await raw_column(test_sessionmaker, "ntfy_token") == in_file
    assert await read_back(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


async def test_an_older_key_ciphertext_is_stored_under_the_current_key(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """R1-H2: not byte for byte, or dropping the old key later would lose it."""
    use_keys(KEY_A)
    under_a = encrypt("ntfy_token", PLAIN_NTFY)
    current = use_keys(KEY_B, KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {})
    service = _service(tmp_path)
    filename = _write_file(service, [{"key": "ntfy_token", "value": under_a}])

    details = await service.restore_settings_backup(filename, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == []
    stored = await raw_column(test_sessionmaker, "ntfy_token")
    assert stored is not None and stored != under_a
    assert decrypt("ntfy_token", stored).kid == current
    use_keys(KEY_B)
    assert await read_back(test_sessionmaker, "ntfy_token") == PLAIN_NTFY


async def test_a_ciphertext_that_does_not_open_is_skipped_and_listed(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """Another instance's key, and a malformed value: the current values stay, the keys are listed."""
    use_keys(KEY_FOREIGN)
    foreign = encrypt("llm_api_key", "the-other-instance-secret")
    use_keys(KEY_A)
    current_llm = encrypt("llm_api_key", PLAIN_LLM)
    await only_these_secret_rows(db_session, keep_rows, {"llm_api_key": current_llm})
    await keep_rows(PROBE)
    service = _service(tmp_path)
    filename = _write_file(
        service,
        [
            {"key": "llm_api_key", "value": foreign, "encrypted": True},
            {"key": "gotify_token", "value": f"{CIPHERTEXT_PREFIX}not-a-kid:AAAA"},
            {"key": PROBE, "value": "restored"},
        ],
    )

    details = await service.restore_settings_backup(filename, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == ["gotify_token", "llm_api_key"]
    assert details["restored_count"] == 1
    assert await raw_column(test_sessionmaker, "llm_api_key") == current_llm
    assert await raw_column(test_sessionmaker, "gotify_token") is None
    assert await raw_column(test_sessionmaker, PROBE) == "restored"


async def test_the_mask_placeholder_is_skipped(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    use_keys(KEY_A)
    current_ntfy = encrypt("ntfy_token", PLAIN_NTFY)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": current_ntfy})
    service = _service(tmp_path)
    filename = _write_file(service, [{"key": "ntfy_token", "value": MASKED_SECRET_PLACEHOLDER}])

    details = await service.restore_settings_backup(filename, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == []
    assert details["restored_count"] == 0
    assert await raw_column(test_sessionmaker, "ntfy_token") == current_ntfy


async def test_with_no_keyring_plaintext_is_skipped_and_listed(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """D3a fails closed: nothing is stored in the clear, and the rest still restores."""
    use_keys(KEY_A)
    current_ntfy = encrypt("ntfy_token", "the-current-ntfy-token")
    in_file = encrypt("gotify_token", "a-gotify-token")
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": current_ntfy})
    await keep_rows(PROBE)
    assert use_keys("not-a-valid-key") is None
    service = _service(tmp_path)
    filename = _write_file(
        service,
        [
            {"key": "ntfy_token", "value": PLAIN_NTFY},
            {"key": "gotify_token", "value": in_file},
            {"key": "slack_webhook_url", "value": ""},
            {"key": PROBE, "value": "restored"},
        ],
        version="2.0",
    )

    details = await service.restore_settings_backup(filename, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == ["gotify_token", "ntfy_token"]
    assert details["restored_count"] == 2
    assert await raw_column(test_sessionmaker, "ntfy_token") == current_ntfy
    assert await raw_column(test_sessionmaker, "gotify_token") is None
    assert await raw_column(test_sessionmaker, "slack_webhook_url") == ""
    assert await raw_column(test_sessionmaker, PROBE) == "restored"


# ---------------------------------------------------------------- test 13


async def test_a_backup_under_an_old_key_survives_rotation(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """R1-H2: back up under A, rotate to B (restart, sweep), restore, drop A: it all reads."""
    kid_a = use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {})
    secrets = {"ntfy_token": PLAIN_NTFY, "llm_api_key": PLAIN_LLM}
    await _seed_through_setter(db_session, secrets)
    service = _service(tmp_path)
    backup = (await service.create_settings_backup(db_session))["filename"]
    entries = _entries((service.backup_dir / backup).read_text())
    for key in secrets:
        assert entries[key]["value"].startswith(f"{CIPHERTEXT_PREFIX}{kid_a}:"), key

    # Rotate: the new key first, the old one kept to decrypt; then "restart".
    kid_b = use_keys(KEY_B, KEY_A)
    report = await sweep_secret_settings(db_session)
    assert report.rekeyed == tuple(sorted(secrets))
    await _seed_through_setter(db_session, {"ntfy_token": "changed-after-the-rotation"})

    details = await service.restore_settings_backup(backup, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == []
    for key in secrets:
        stored = await raw_column(test_sessionmaker, key)
        assert stored is not None and stored.startswith(f"{CIPHERTEXT_PREFIX}{kid_b}:"), key
    assert use_keys(KEY_B) == kid_b
    for key, plain in secrets.items():
        assert await read_back(test_sessionmaker, key) == plain, key


# ---------------------------------------------------------------- test 14 (legacy restore)


async def test_an_unchanged_legacy_value_restored_over_plaintext_ends_encrypted(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    keep_rows: Keep,
    use_keys: UseKeys,
    tmp_path: Path,
) -> None:
    """R1-H3: the same plaintext the row already holds is still written as ciphertext."""
    kid = use_keys(KEY_A)
    await only_these_secret_rows(db_session, keep_rows, {"ntfy_token": PLAIN_NTFY})
    service = _service(tmp_path)
    filename = _write_file(service, [{"key": "ntfy_token", "value": PLAIN_NTFY}], version="2.0")

    details = await service.restore_settings_backup(filename, db_session, create_safety=False)

    assert details["skipped_secret_keys"] == []
    stored = await raw_column(test_sessionmaker, "ntfy_token")
    assert stored is not None and stored.startswith(f"{CIPHERTEXT_PREFIX}{kid}:")
    assert current_kid() == kid
    assert await read_back(test_sessionmaker, "ntfy_token") == PLAIN_NTFY
