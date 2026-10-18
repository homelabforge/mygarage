"""The JWT key file and the key-file writer it shares with the settings keyring.

The writer creates the file with O_EXCL and mode 0600 in one step, so there is
no window in which a umask-default file holds a key, and it never overwrites a
key someone else already wrote. `get_or_create_secret_key` records what it did
in `KEY_SOURCE`, which the lifespan logs once logging is configured.
"""

import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import main as app_main
from app.utils import secret_key
from app.utils.secret_key import create_key_file, get_or_create_secret_key


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture(autouse=True)
def _keep_key_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the module's KEY_SOURCE back after each test."""
    monkeypatch.setattr(secret_key, "KEY_SOURCE", secret_key.KEY_SOURCE)


@pytest.fixture
def open_umask() -> Iterator[None]:
    """Run with umask 0, so only the mode passed at creation can make the file 0600."""
    old = os.umask(0)
    try:
        yield
    finally:
        os.umask(old)


skip_as_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


class TestCreateKeyFile:
    def test_creates_the_file_0600_with_the_content(self, tmp_path: Path, open_umask: None) -> None:
        path = tmp_path / "k.key"

        create_key_file(path, "abc\n")

        assert path.read_text() == "abc\n"
        assert _mode(path) == 0o600

    def test_creates_a_missing_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "k.key"

        create_key_file(path, "abc")

        assert path.read_text() == "abc"

    def test_refuses_an_existing_file_and_leaves_it_alone(self, tmp_path: Path) -> None:
        path = tmp_path / "k.key"
        path.write_text("original")
        path.chmod(0o644)

        with pytest.raises(FileExistsError):
            create_key_file(path, "replacement")

        assert path.read_text() == "original"
        assert _mode(path) == 0o644

    def test_refuses_to_follow_a_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere"
        path = tmp_path / "k.key"
        path.symlink_to(target)

        with pytest.raises(FileExistsError):
            create_key_file(path, "abc")

        assert not target.exists()

    @skip_as_root
    def test_an_unwritable_directory_raises_oserror(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o500)
        try:
            with pytest.raises(PermissionError):
                create_key_file(locked / "k.key", "abc")
        finally:
            locked.chmod(0o700)


class TestGetOrCreateSecretKey:
    def test_generates_and_persists_a_key_when_none_exists(
        self, tmp_path: Path, open_umask: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "secret.key"

        key = get_or_create_secret_key(path)

        assert len(key) >= 43
        assert path.read_text().strip() == key
        assert _mode(path) == 0o600
        assert secret_key.KEY_SOURCE == "generated"
        # No print(): the key status is the lifespan's to log.
        assert capsys.readouterr().out == ""

    def test_loads_an_existing_key(self, tmp_path: Path) -> None:
        path = tmp_path / "secret.key"
        path.write_text("existing-key\n")

        assert get_or_create_secret_key(path) == "existing-key"
        assert secret_key.KEY_SOURCE == "loaded"
        assert path.read_text() == "existing-key\n"

    def test_replaces_an_empty_file(self, tmp_path: Path, open_umask: None) -> None:
        path = tmp_path / "secret.key"
        path.write_text("  \n")

        key = get_or_create_secret_key(path)

        assert key
        assert path.read_text().strip() == key
        assert _mode(path) == 0o600
        assert secret_key.KEY_SOURCE == "generated"

    def test_a_concurrent_writer_wins_the_race(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another process creating the file between the check and the write isn't clobbered."""
        path = tmp_path / "secret.key"
        real_create = secret_key.create_key_file

        def _lose_the_race(target: Path, content: str) -> None:
            real_create(target, "winner-key\n")
            real_create(target, content)  # raises FileExistsError, as the race would

        monkeypatch.setattr(secret_key, "create_key_file", _lose_the_race)

        assert get_or_create_secret_key(path) == "winner-key"
        assert secret_key.KEY_SOURCE == "loaded"

    @skip_as_root
    def test_falls_back_to_memory_when_the_file_cannot_be_written(self, tmp_path: Path) -> None:
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o500)
        try:
            key = get_or_create_secret_key(locked / "secret.key")
        finally:
            locked.chmod(0o700)

        assert len(key) >= 43
        assert not (locked / "secret.key").exists()
        assert secret_key.KEY_SOURCE == "memory"

    def test_an_undecodable_file_falls_back_to_memory_and_is_kept(self, tmp_path: Path) -> None:
        path = tmp_path / "secret.key"
        path.write_bytes(b"\xff\xfe not text")

        key = get_or_create_secret_key(path)

        assert len(key) >= 43
        assert secret_key.KEY_SOURCE == "memory"
        assert path.read_bytes() == b"\xff\xfe not text"

    def test_falls_back_to_memory_when_the_parent_is_a_file(self, tmp_path: Path) -> None:
        """Root-proof variant: a regular file where the directory should be."""
        blocker = tmp_path / "blocker"
        blocker.write_text("")

        key = get_or_create_secret_key(blocker / "secret.key")

        assert len(key) >= 43
        assert secret_key.KEY_SOURCE == "memory"


class TestLifespanKeyStatus:
    """The lifespan logs from KEY_SOURCE, not from whether /data/secret.key exists."""

    @pytest.mark.parametrize(
        ("source", "level", "fragment"),
        [
            ("loaded", logging.INFO, "loaded from /data/secret.key"),
            ("generated", logging.INFO, "Generated a new secret key"),
            ("memory", logging.WARNING, "in-memory"),
        ],
    )
    def test_logs_the_recorded_outcome(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        source: secret_key.KeySource,
        level: int,
        fragment: str,
    ) -> None:
        monkeypatch.delenv("MYGARAGE_SECRET_KEY", raising=False)
        monkeypatch.setattr(secret_key, "KEY_SOURCE", source)

        with caplog.at_level(logging.INFO, logger=app_main.logger.name):
            app_main.log_secret_key_status()

        [record] = [r for r in caplog.records if r.name == app_main.logger.name]
        assert record.levelno == level
        assert fragment in record.getMessage()

    def test_the_env_var_wins(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("MYGARAGE_SECRET_KEY", "from-env")
        monkeypatch.setattr(secret_key, "KEY_SOURCE", "memory")

        with caplog.at_level(logging.INFO, logger=app_main.logger.name):
            app_main.log_secret_key_status()

        [record] = [r for r in caplog.records if r.name == app_main.logger.name]
        assert record.levelno == logging.INFO
        assert "MYGARAGE_SECRET_KEY" in record.getMessage()
        assert "from-env" not in record.getMessage()
