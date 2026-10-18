"""The settings encryption module: format, associated data, keyring sources.

Covers plan tests 7 (a ciphertext moved to another key's row doesn't open), 8
(the keyring half: precedence, no fallthrough, unavailable not cached, 0600,
multi-key, unwritable data dir) and the crypto-level part of 17 (tampered and
malformed ciphertext, malformed key sources).

Every test runs against an isolated keyring: both env vars cleared, the data
dir pointed at tmp_path, and the cached keyring reset before and after.
"""

import base64
import hashlib
import logging
import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import settings
from app.utils import settings_crypto
from app.utils.settings_crypto import (
    CIPHERTEXT_PREFIX,
    DecryptStatus,
    SettingsKeyUnavailable,
    _reset_keyring_for_tests,  # pyright: ignore[reportPrivateUsage] - the suite's reset hook
    current_kid,
    decrypt,
    encrypt,
    is_ciphertext,
)

ENV_KEY = "MYGARAGE_SETTINGS_KEY"
ENV_KEY_FILE = "MYGARAGE_SETTINGS_KEY_FILE"
FORMAT = re.compile(r"^enc:v1:[0-9a-f]{8}:[A-Za-z0-9_-]+$")
LOGGER = settings_crypto.logger.name

skip_as_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


def _new_key() -> tuple[str, bytes]:
    raw = os.urandom(32)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), raw


def _kid(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:8]


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """An isolated keyring whose only possible source is a fresh data dir."""
    monkeypatch.delenv(ENV_KEY, raising=False)
    monkeypatch.delenv(ENV_KEY_FILE, raising=False)
    path = tmp_path / "data"
    path.mkdir()
    monkeypatch.setattr(settings, "data_dir", path)
    _reset_keyring_for_tests()
    yield path
    _reset_keyring_for_tests()


@pytest.fixture
def env_key(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> bytes:
    """One random key in MYGARAGE_SETTINGS_KEY; returns its raw bytes."""
    text, raw = _new_key()
    monkeypatch.setenv(ENV_KEY, text)
    return raw


def _block_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the data dir under a regular file, so it can't be created even as root."""
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    monkeypatch.setattr(settings, "data_dir", blocker / "data")


def _assert_unavailable() -> None:
    with pytest.raises(SettingsKeyUnavailable):
        encrypt("llm_api_key", "x")
    assert current_kid() is None


class TestFormatAndRoundTrip:
    def test_round_trip(self, env_key: bytes) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")

        result = decrypt("llm_api_key", stored)

        assert result.status is DecryptStatus.DECRYPTED
        assert result.plaintext == "sk-live-123"
        assert result.kid == _kid(env_key)
        assert not result.unreadable

    def test_format_and_kid(self, env_key: bytes) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")

        assert FORMAT.match(stored)
        assert stored.startswith(f"{CIPHERTEXT_PREFIX}{_kid(env_key)}:")
        assert current_kid() == _kid(env_key)
        assert "sk-live-123" not in stored
        assert stored.isascii()

    def test_a_fresh_nonce_each_time(self, env_key: bytes) -> None:
        assert encrypt("llm_api_key", "same") != encrypt("llm_api_key", "same")

    def test_unicode_and_empty_values(self, env_key: bytes) -> None:
        for value in ("", "pässwörd ✓", "x" * 5000):
            assert decrypt("k", encrypt("k", value)).plaintext == value

    def test_is_ciphertext(self, env_key: bytes) -> None:
        assert is_ciphertext(encrypt("k", "v"))
        assert is_ciphertext("enc:v1:garbage")
        assert not is_ciphertext("plain")
        assert not is_ciphertext("")
        assert not is_ciphertext(None)


class TestLegacyPlaintext:
    def test_a_value_without_the_prefix_reads_as_legacy(self, env_key: bytes) -> None:
        result = decrypt("llm_api_key", "sk-plain")

        assert result.status is DecryptStatus.LEGACY
        assert result.plaintext == "sk-plain"
        assert result.kid is None
        assert not result.unreadable

    def test_legacy_reads_without_any_keyring(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        _block_data_dir(monkeypatch, tmp_path)

        assert decrypt("llm_api_key", "sk-plain").plaintext == "sk-plain"
        _assert_unavailable()


class TestAssociatedData:
    """Plan test 7, crypto level: the setting key name is the associated data."""

    def test_a_ciphertext_moved_to_another_key_does_not_open(self, env_key: bytes) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")

        result = decrypt("slack_webhook_url", stored)

        assert result.status is DecryptStatus.UNREADABLE
        assert result.plaintext is None
        assert result.unreadable
        assert decrypt("llm_api_key", stored).plaintext == "sk-live-123"


class TestTamperedAndMalformedCiphertext:
    """Plan test 17, crypto level: unreadable, never raises, never garbage."""

    def test_a_flipped_payload_byte(self, env_key: bytes) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")
        head, payload = stored.rsplit(":", 1)
        raw = bytearray(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        raw[-1] ^= 0x01
        tampered = f"{head}:{base64.urlsafe_b64encode(bytes(raw)).rstrip(b'=').decode()}"

        result = decrypt("llm_api_key", tampered)

        assert result.status is DecryptStatus.UNREADABLE
        assert result.plaintext is None

    def test_an_unknown_kid(self, env_key: bytes) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")
        other_kid = "0" * 8 if not stored[7:15] == "0" * 8 else "1" * 8
        moved = f"{CIPHERTEXT_PREFIX}{other_kid}:{stored.rsplit(':', 1)[1]}"

        result = decrypt("llm_api_key", moved)

        assert result.status is DecryptStatus.UNREADABLE
        assert result.kid == other_kid

    @pytest.mark.parametrize(
        "stored",
        [
            "enc:v1:",
            "enc:v1:abcd",
            "enc:v1:abcdef01",
            "enc:v1:abcdef01:",
            "enc:v1:ABCDEF01:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "enc:v1:zzzzzzzz:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "enc:v1:abcdef01:!!!!",
            "enc:v1:abcdef01:AAAA",  # shorter than nonce + tag
            "enc:v1:abcdef01:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:extra",
            "enc:v1:abcdef01:AAAA+AAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "enc:v1:abcdef01:A",
        ],
    )
    def test_malformed_ciphertext(self, env_key: bytes, stored: str) -> None:
        result = decrypt("llm_api_key", stored)

        assert result.status is DecryptStatus.UNREADABLE
        assert result.plaintext is None

    def test_a_ciphertext_reads_as_unreadable_when_the_keyring_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, env_key: bytes
    ) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")
        monkeypatch.setenv(ENV_KEY, "not-a-key")
        _reset_keyring_for_tests()

        result = decrypt("llm_api_key", stored)

        assert result.status is DecryptStatus.UNREADABLE
        assert result.plaintext is None

    def test_unreadable_is_logged_once_per_key_and_kid(
        self, env_key: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        stored = encrypt("llm_api_key", "sk-live-123")

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            for _ in range(3):
                decrypt("slack_webhook_url", stored)
            decrypt("discord_webhook_url", stored)

        lines = [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING]
        assert len(lines) == 2
        assert "slack_webhook_url" in lines[0].getMessage()
        assert "discord_webhook_url" in lines[1].getMessage()
        assert all("sk-live-123" not in r.getMessage() for r in caplog.records)
        assert all(stored.rsplit(":", 1)[1] not in r.getMessage() for r in caplog.records)


class TestKeyringPrecedence:
    """Plan test 8: env beats file beats the data-dir file."""

    def test_env_beats_file_beats_data_dir(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        env_text, env_raw = _new_key()
        file_text, file_raw = _new_key()
        dir_text, dir_raw = _new_key()
        key_file = tmp_path / "docker-secret"
        key_file.write_text(file_text + "\n")
        (data_dir / "settings.key").write_text(dir_text + "\n")
        monkeypatch.setenv(ENV_KEY, env_text)
        monkeypatch.setenv(ENV_KEY_FILE, str(key_file))

        assert current_kid() == _kid(env_raw)

        monkeypatch.delenv(ENV_KEY)
        _reset_keyring_for_tests()
        assert current_kid() == _kid(file_raw)

        monkeypatch.delenv(ENV_KEY_FILE)
        _reset_keyring_for_tests()
        assert current_kid() == _kid(dir_raw)

    def test_an_empty_env_var_counts_as_unset(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        """Compose's `${MYGARAGE_SETTINGS_KEY}` with nothing behind it passes an empty string."""
        dir_text, dir_raw = _new_key()
        (data_dir / "settings.key").write_text(dir_text)
        monkeypatch.setenv(ENV_KEY, "  ")
        monkeypatch.setenv(ENV_KEY_FILE, "")

        assert current_kid() == _kid(dir_raw)

    def test_padded_keys_are_accepted(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        raw = os.urandom(32)
        monkeypatch.setenv(ENV_KEY, base64.urlsafe_b64encode(raw).decode())

        assert current_kid() == _kid(raw)


class TestNoFallthrough:
    """Plan test 8: the first present source wins, even when it is broken."""

    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-key",
            base64.urlsafe_b64encode(b"\x00" * 16).decode(),  # 16 bytes, not 32
            base64.urlsafe_b64encode(b"\x00" * 33).decode(),
            "AAAA+AAA/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # standard alphabet
            ",",
            "\n,\n",
        ],
    )
    def test_a_broken_env_var_does_not_fall_through(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, bad: str
    ) -> None:
        file_text, _ = _new_key()
        dir_text, _ = _new_key()
        key_file = tmp_path / "docker-secret"
        key_file.write_text(file_text)
        (data_dir / "settings.key").write_text(dir_text)
        monkeypatch.setenv(ENV_KEY, bad)
        monkeypatch.setenv(ENV_KEY_FILE, str(key_file))

        _assert_unavailable()
        assert (data_dir / "settings.key").read_text() == dir_text

    def test_one_bad_entry_in_a_list_breaks_the_source(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        good, _ = _new_key()
        monkeypatch.setenv(ENV_KEY, f"{good},not-a-key")

        _assert_unavailable()

    def test_a_missing_key_file_path_does_not_fall_through_or_generate(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(ENV_KEY_FILE, str(tmp_path / "missing"))

        _assert_unavailable()
        assert not (data_dir / "settings.key").exists()
        assert not (tmp_path / "missing").exists()

    def test_a_broken_key_file_does_not_fall_through(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        dir_text, _ = _new_key()
        (data_dir / "settings.key").write_text(dir_text)
        key_file = tmp_path / "docker-secret"
        key_file.write_text("garbage")
        monkeypatch.setenv(ENV_KEY_FILE, str(key_file))

        _assert_unavailable()
        assert key_file.read_text() == "garbage"

    @pytest.mark.parametrize("content", [b"garbage", b"", b"\n", b"\xff\xfe binary"])
    def test_a_broken_data_dir_file_is_not_regenerated(
        self, data_dir: Path, content: bytes
    ) -> None:
        path = data_dir / "settings.key"
        path.write_bytes(content)

        _assert_unavailable()
        assert path.read_bytes() == content

    @skip_as_root
    def test_an_unreadable_data_dir_file_is_not_regenerated(self, data_dir: Path) -> None:
        path = data_dir / "settings.key"
        text, _ = _new_key()
        path.write_text(text)
        path.chmod(0o000)
        try:
            _assert_unavailable()
        finally:
            path.chmod(0o600)
        assert path.read_text() == text


class TestUnavailableIsNotCached:
    """Plan test 8 (F-5): fixing the source takes effect on the next call."""

    def test_fixing_the_data_dir_file_without_a_reset(self, data_dir: Path) -> None:
        path = data_dir / "settings.key"
        path.write_text("garbage")
        _assert_unavailable()

        text, raw = _new_key()
        path.write_text(text)

        assert current_kid() == _kid(raw)
        assert decrypt("k", encrypt("k", "v")).plaintext == "v"

    def test_setting_the_env_var_without_a_reset(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        _block_data_dir(monkeypatch, tmp_path)
        _assert_unavailable()

        text, raw = _new_key()
        monkeypatch.setenv(ENV_KEY, text)

        assert current_kid() == _kid(raw)

    def test_a_loaded_keyring_is_cached(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        text, raw = _new_key()
        monkeypatch.setenv(ENV_KEY, text)
        assert current_kid() == _kid(raw)

        monkeypatch.setenv(ENV_KEY, "not-a-key")

        assert current_kid() == _kid(raw)

    def test_unavailable_is_logged_once_per_process(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(ENV_KEY, "SENTINEL-not-a-key")

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            for _ in range(5):
                with pytest.raises(SettingsKeyUnavailable):
                    encrypt("llm_api_key", "x")
                current_kid()
                decrypt("llm_api_key", "enc:v1:abcdef01:AAAA")

        errors = [r for r in caplog.records if r.name == LOGGER and r.levelno >= logging.ERROR]
        assert len(errors) == 1
        assert ENV_KEY in errors[0].getMessage()
        assert all("SENTINEL" not in r.getMessage() for r in caplog.records)

    def test_the_exception_names_the_source_and_the_fix_but_not_the_value(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        monkeypatch.setenv(ENV_KEY, "SENTINEL-not-a-key")

        with pytest.raises(SettingsKeyUnavailable) as excinfo:
            encrypt("llm_api_key", "x")

        message = str(excinfo.value)
        assert excinfo.value.source == ENV_KEY
        assert ENV_KEY in message
        assert "SENTINEL" not in message
        assert not isinstance(excinfo.value, RuntimeError)


class TestGeneration:
    """Plan test 8: generated on first use, 0600, only when nothing is present."""

    def test_generates_a_0600_key_file_on_first_use(self, data_dir: Path) -> None:
        old_umask = os.umask(0)
        try:
            stored = encrypt("llm_api_key", "sk-live-123")
        finally:
            os.umask(old_umask)

        path = data_dir / "settings.key"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        text = path.read_text().strip()
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        assert len(raw) == 32
        assert current_kid() == _kid(raw)

        # A "restart" loads the same key rather than generating another.
        _reset_keyring_for_tests()
        assert decrypt("llm_api_key", stored).plaintext == "sk-live-123"
        assert path.read_text().strip() == text

    def test_creates_a_missing_data_dir(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        monkeypatch.setattr(settings, "data_dir", data_dir / "not-yet")

        assert current_kid() is not None
        assert (data_dir / "not-yet" / "settings.key").exists()

    def test_a_concurrent_writer_wins_the_race(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path
    ) -> None:
        winner_text, winner_raw = _new_key()
        real_create = settings_crypto.create_key_file

        def _lose_the_race(path: Path, content: str) -> None:
            real_create(path, winner_text + "\n")
            real_create(path, content)

        monkeypatch.setattr(settings_crypto, "create_key_file", _lose_the_race)

        assert current_kid() == _kid(winner_raw)

    @skip_as_root
    def test_an_unwritable_data_dir_is_unavailable(self, data_dir: Path) -> None:
        data_dir.chmod(0o500)
        try:
            _assert_unavailable()
            assert decrypt("llm_api_key", "plain").plaintext == "plain"
        finally:
            data_dir.chmod(0o700)
        assert not (data_dir / "settings.key").exists()

    def test_a_data_dir_that_cannot_exist_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        """Root-proof variant: a regular file where the data dir's parent should be."""
        _block_data_dir(monkeypatch, tmp_path)

        _assert_unavailable()
        with pytest.raises(SettingsKeyUnavailable) as excinfo:
            encrypt("llm_api_key", "x")
        assert "settings.key" in excinfo.value.source

    def test_no_ephemeral_key_after_a_failed_generation(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        """A failed generation stays unavailable; it never encrypts under a key it didn't persist."""
        _block_data_dir(monkeypatch, tmp_path)
        for _ in range(3):
            _assert_unavailable()


class TestMultiKey:
    """Plan test 8: a keyring decrypts with any key and encrypts with the first."""

    @pytest.mark.parametrize("separator", [",", "\n", " , ", "\n\n"])
    def test_decrypts_with_any_and_encrypts_with_the_first(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, separator: str
    ) -> None:
        a_text, a_raw = _new_key()
        b_text, b_raw = _new_key()
        monkeypatch.setenv(ENV_KEY, a_text)
        under_a = encrypt("llm_api_key", "sk-old")

        monkeypatch.setenv(ENV_KEY, f"{b_text}{separator}{a_text}\n")
        _reset_keyring_for_tests()

        assert current_kid() == _kid(b_raw)
        old = decrypt("llm_api_key", under_a)
        assert old.status is DecryptStatus.DECRYPTED
        assert old.plaintext == "sk-old"
        assert old.kid == _kid(a_raw)
        fresh = encrypt("llm_api_key", "sk-new")
        assert fresh.startswith(f"{CIPHERTEXT_PREFIX}{_kid(b_raw)}:")

        # Drop A: what it encrypted becomes unreadable, B's still opens.
        monkeypatch.setenv(ENV_KEY, b_text)
        _reset_keyring_for_tests()
        assert decrypt("llm_api_key", under_a).status is DecryptStatus.UNREADABLE
        assert decrypt("llm_api_key", fresh).plaintext == "sk-new"

    def test_a_multi_key_file(
        self, monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
    ) -> None:
        a_text, _ = _new_key()
        b_text, b_raw = _new_key()
        monkeypatch.setenv(ENV_KEY, a_text)
        under_a = encrypt("llm_api_key", "sk-old")
        monkeypatch.delenv(ENV_KEY)
        key_file = tmp_path / "docker-secret"
        key_file.write_text(f"{b_text}\n{a_text}\n")
        monkeypatch.setenv(ENV_KEY_FILE, str(key_file))
        _reset_keyring_for_tests()

        assert current_kid() == _kid(b_raw)
        assert decrypt("llm_api_key", under_a).plaintext == "sk-old"


class TestTestEnvironmentKey:
    """The suite runs with a fixed key in the env (conftest), so secret writes never 503."""

    def test_conftest_sets_a_valid_key(self) -> None:
        value = os.environ.get(ENV_KEY)
        assert value
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        assert len(raw) == 32
