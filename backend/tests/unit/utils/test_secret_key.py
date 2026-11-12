"""The JWT key file and the key-file writer it shares with the settings keyring.

The writer puts the key in an O_EXCL, mode 0600 temp file and hard-links it into
place, so the file never holds a key under the umask's mode, never shows up
empty, and never overwrites a key someone else already wrote. `get_or_create_secret_key` records what it did
in `KEY_SOURCE`, which the lifespan logs once logging is configured.
"""

import errno
import fcntl
import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app import main as app_main
from app.utils import secret_key
from app.utils.secret_key import create_key_file, get_or_create_secret_key
from tests.unit.utils._key_race_child import jwt_key_child, race_warnings, run_race

RACERS = 8


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture(autouse=True)
def _keep_key_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the module's KEY_SOURCE and KEY_FILE back after each test, and
    point the pre-B2-6 location somewhere empty, so a real /data/secret.key on
    the test machine is never carried over."""
    monkeypatch.setattr(secret_key, "KEY_SOURCE", secret_key.KEY_SOURCE)
    monkeypatch.setattr(secret_key, "KEY_FILE", secret_key.KEY_FILE)
    monkeypatch.setattr(secret_key, "DEFAULT_KEY_FILE", Path("/nonexistent-mygarage/secret.key"))


@pytest.fixture
def open_umask() -> Iterator[None]:
    """Run with umask 0, so only the mode passed at creation can make the file 0600."""
    old = os.umask(0)
    try:
        yield
    finally:
        os.umask(old)


skip_as_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


@pytest.fixture
def no_hard_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filesystem with no hard links (vfat, some FUSE), where link says EPERM."""

    def refuse(src: object, dst: object, **kwargs: object) -> None:
        raise OSError(errno.EPERM, os.strerror(errno.EPERM))

    monkeypatch.setattr(secret_key.os, "link", refuse)


def _entries(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


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

    def test_the_file_never_shows_up_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another process reading it mid-create used to find it empty, take it for an
        emptied key file, write its own key and warn that old secrets were lost."""
        path = tmp_path / "k.key"
        seen: list[bytes] = []
        real_open, real_link = os.open, os.link

        def look() -> None:
            if path.exists():
                seen.append(path.read_bytes())

        def spy_open(*args: Any, **kwargs: Any) -> int:
            fd = real_open(*args, **kwargs)
            look()
            return fd

        def spy_link(*args: Any, **kwargs: Any) -> None:
            real_link(*args, **kwargs)
            look()

        monkeypatch.setattr(secret_key.os, "open", spy_open)
        monkeypatch.setattr(secret_key.os, "link", spy_link)

        create_key_file(path, "abc\n")

        assert seen
        assert set(seen) == {b"abc\n"}

    def test_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "k.key"

        create_key_file(path, "abc\n")
        with pytest.raises(FileExistsError):
            create_key_file(path, "def\n")

        assert _entries(tmp_path) == ["k.key"]
        assert path.read_text() == "abc\n"

    def test_a_failed_write_leaves_nothing_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "k.key"

        def disk_full(fd: int, data: bytes, offset: int) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(secret_key.os, "pwrite", disk_full)

        with pytest.raises(OSError):
            create_key_file(path, "abc\n")

        assert _entries(tmp_path) == []

    @pytest.mark.parametrize(
        "code",
        [errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EACCES, errno.EXDEV, errno.EIO],
        ids=["EPERM", "EOPNOTSUPP", "ENOSYS", "EACCES", "EXDEV", "EIO"],
    )
    def test_any_link_failure_but_exists_falls_back_to_creating_in_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, open_umask: None, code: int
    ) -> None:
        """CIFS reports a share with no hard links as EACCES, so guessing which errnos
        mean "no hard links" would lose the key; the old in-place create is always safe."""
        path = tmp_path / "k.key"

        def broken(src: object, dst: object, **kwargs: object) -> None:
            raise OSError(code, os.strerror(code))

        monkeypatch.setattr(secret_key.os, "link", broken)

        assert create_key_file(path, "abc\n") == "abc"

        assert path.read_text() == "abc\n"
        assert _mode(path) == 0o600
        assert _entries(tmp_path) == ["k.key"]

    def test_a_leftover_temp_with_the_same_name_gets_a_new_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A collision on the temp name must not read as the key file already existing."""
        path = tmp_path / "k.key"
        tokens = iter(["0" * 16, "0" * 16, "1" * 16])
        monkeypatch.setattr(secret_key.secrets, "token_hex", lambda n: next(tokens))
        (tmp_path / f".k.key.{'0' * 16}.tmp").write_text("leftover")

        assert create_key_file(path, "abc\n") == "abc"

        assert path.read_text() == "abc\n"
        assert _entries(tmp_path) == [f".k.key.{'0' * 16}.tmp", "k.key"]

    def test_temp_names_running_out_never_read_as_the_key_file_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Callers take FileExistsError to mean the key file is there and go join it."""
        path = tmp_path / "k.key"
        monkeypatch.setattr(secret_key.secrets, "token_hex", lambda n: "0" * 16)
        (tmp_path / f".k.key.{'0' * 16}.tmp").write_text("leftover")

        with pytest.raises(OSError) as raised:
            create_key_file(path, "abc\n")

        assert not isinstance(raised.value, FileExistsError)
        assert _entries(tmp_path) == [f".k.key.{'0' * 16}.tmp"]

    def test_without_hard_links_it_creates_the_file_in_place(
        self, tmp_path: Path, open_umask: None, no_hard_links: None
    ) -> None:
        path = tmp_path / "k.key"

        assert create_key_file(path, "abc\n") == "abc"

        assert path.read_text() == "abc\n"
        assert _mode(path) == 0o600
        assert _entries(tmp_path) == ["k.key"]


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

    def test_fills_an_empty_file_in_place(self, tmp_path: Path) -> None:
        """Same inode: a single-file bind mount can't be unlinked (EBUSY), so
        unlinking first left an in-memory key (B2-13)."""
        path = tmp_path / "secret.key"
        path.write_text("")
        path.chmod(0o644)
        inode = path.stat().st_ino

        key = get_or_create_secret_key(path)

        assert path.stat().st_ino == inode
        assert path.read_text().strip() == key
        assert _mode(path) == 0o600
        assert secret_key.KEY_SOURCE == "generated"

    def test_an_empty_file_that_cannot_be_unlinked_still_gets_a_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bind-mount case itself: unlink raises EBUSY, the key persists."""
        path = tmp_path / "secret.key"
        path.write_text("")

        def busy(self: Path, missing_ok: bool = False) -> None:
            raise OSError(16, "Device or resource busy")

        monkeypatch.setattr(Path, "unlink", busy)

        key = get_or_create_secret_key(path)

        assert secret_key.KEY_SOURCE == "generated"
        assert path.read_text().strip() == key

    def test_a_writable_file_it_cannot_chmod_still_gets_the_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A chmod 666 bind mount owned by root: fchmod is EPERM, the write works."""
        path = tmp_path / "secret.key"
        path.write_text("")

        def not_owner(fd: int, mode: int) -> None:
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(secret_key.os, "fchmod", not_owner)

        key = get_or_create_secret_key(path)

        assert secret_key.KEY_SOURCE == "generated"
        assert path.read_text().strip() == key

    @skip_as_root
    def test_an_empty_file_it_cannot_open_is_replaced(self, tmp_path: Path) -> None:
        """Read-only to us in a directory we own: unlink-and-create, as before."""
        path = tmp_path / "secret.key"
        path.write_text("")
        path.chmod(0o444)

        key = get_or_create_secret_key(path)

        assert secret_key.KEY_SOURCE == "generated"
        assert path.read_text().strip() == key
        assert _mode(path) == 0o600

    def test_a_moved_data_dir_carries_the_old_key_over(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Before B2-6 the key sat at /data/secret.key whatever the data dir
        said: copy it over so nobody is signed out (Fable F-5)."""
        legacy = tmp_path / "old" / "secret.key"
        legacy.parent.mkdir()
        legacy.write_text("legacy-key\n")
        monkeypatch.setattr(secret_key, "DEFAULT_KEY_FILE", legacy)
        path = tmp_path / "new" / "secret.key"

        assert get_or_create_secret_key(path) == "legacy-key"
        assert secret_key.KEY_SOURCE == "loaded"
        assert path.read_text().strip() == "legacy-key"
        assert _mode(path) == 0o600

    def test_no_old_key_means_a_new_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "new" / "secret.key"

        key = get_or_create_secret_key(path)

        assert secret_key.KEY_SOURCE == "generated"
        assert path.read_text().strip() == key

    def test_the_config_keeps_the_key_in_the_data_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`MYGARAGE_DATA_DIR` moves the key with the rest of the data (B2-6)."""
        from app.config import Settings

        monkeypatch.delenv("MYGARAGE_SECRET_KEY", raising=False)
        monkeypatch.setenv("MYGARAGE_DATA_DIR", str(tmp_path))

        key = Settings().secret_key

        assert (tmp_path / "secret.key").read_text().strip() == key
        assert secret_key.KEY_FILE == tmp_path / "secret.key"

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


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == secret_key.logger.name and r.levelno >= logging.WARNING
    ]


class TestKeyFileWriters:
    """Every writer fills under an exclusive lock, so whoever locks first writes
    and everyone else reads that key back. Nobody keeps a key that isn't on disk."""

    def test_processes_racing_for_a_missing_key_all_keep_the_one_on_disk(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "secret.key"

        results = run_race(jwt_key_child, str(path), RACERS)

        assert [r for r in results if r[1] == "error"] == []
        assert len({r[0] for r in results}) == RACERS
        assert {r[1] for r in results} == {path.read_text().strip()}
        sources = [r[2] for r in results]
        # Each child really used the file: one wrote it, the rest read it back.
        assert sources.count("generated") == 1
        assert set(sources) <= {"generated", "loaded"}
        # A racer that found the file mid-create used to take it for an emptied one.
        assert not [m for m in race_warnings(results) if "empty" in m]

    def test_a_create_race_loser_waits_for_the_creator_to_fill_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_hard_links: None
    ) -> None:
        """With no hard links the creator makes the file in place, and it's empty
        until the creator locks it.

        A loser that only read the file would find nothing there. It fills it
        under the lock instead, and the creator then reads that key back.
        """
        path = tmp_path / "secret.key"
        real_flock = fcntl.flock
        real_read = secret_key._read_key
        loser: dict[str, object] = {}

        def read_before_the_create(target: Path) -> str | None:
            if target == path and "read" not in loser:
                loser["read"] = True
                return None
            return real_read(target)

        def flock(fd: int, operation: int) -> None:
            if not loser:
                monkeypatch.setattr(secret_key, "_read_key", read_before_the_create)
                loser["key"] = get_or_create_secret_key(path)
                loser["source"] = secret_key.KEY_SOURCE
                monkeypatch.setattr(secret_key, "_read_key", real_read)
            real_flock(fd, operation)

        monkeypatch.setattr(secret_key.fcntl, "flock", flock)

        creator = get_or_create_secret_key(path)

        assert loser["key"]
        assert creator == loser["key"] == path.read_text().strip()
        assert loser["source"] == "generated"
        assert secret_key.KEY_SOURCE == "loaded"

    def test_two_fillers_of_an_empty_file_end_with_the_same_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One filler read the empty file, then the other filled it before the first
        opened it. The first must not wipe that key and write its own."""
        path = tmp_path / "secret.key"
        path.write_text("")
        real_fill = secret_key.fill_empty_key_file
        other: dict[str, object] = {}

        def paused_fill(target: Path, content: str) -> str:
            if not other:
                other["running"] = True
                other["key"] = get_or_create_secret_key(target)
                other["source"] = secret_key.KEY_SOURCE
            return real_fill(target, content)

        monkeypatch.setattr(secret_key, "fill_empty_key_file", paused_fill)

        with caplog.at_level(logging.DEBUG, logger=secret_key.logger.name):
            first = get_or_create_secret_key(path)

        assert first == other["key"] == path.read_text().strip()
        assert other["source"] == "generated"
        assert secret_key.KEY_SOURCE == "loaded"
        # Only the filler whose key landed says it generated one.
        assert len([m for m in _warnings(caplog) if "empty" in m]) == 1

    @pytest.mark.parametrize("existing", [None, b""], ids=["missing", "empty"])
    @pytest.mark.parametrize("written", [0, 5], ids=["nothing-written", "short-write"])
    def test_a_failed_write_leaves_no_half_key_and_the_next_start_writes_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bytes | None, written: int
    ) -> None:
        """A full disk mid-write never leaves half a key: a missing file stays missing,
        an empty one stays empty."""
        path = tmp_path / "secret.key"
        if existing is not None:
            path.write_bytes(existing)
        real_pwrite = os.pwrite

        def disk_full(fd: int, data: bytes, offset: int) -> int:
            if written:
                real_pwrite(fd, data[:written], offset)
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(secret_key.os, "pwrite", disk_full)
        get_or_create_secret_key(path)
        assert secret_key.KEY_SOURCE == "memory"
        if existing is None:
            assert _entries(tmp_path) == []
        else:
            assert path.read_bytes() == b""

        monkeypatch.setattr(secret_key.os, "pwrite", real_pwrite)
        key = get_or_create_secret_key(path)
        assert secret_key.KEY_SOURCE == "generated"
        assert path.read_text().strip() == key

    def test_without_hard_links_a_failed_write_keeps_the_empty_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A racing process may already be waiting on it, so it isn't removed."""
        path = tmp_path / "k.key"
        real_pwrite = os.pwrite
        refused: list[bool] = []

        def refuse(src: object, dst: object, **kwargs: object) -> None:
            refused.append(True)
            raise OSError(errno.EPERM, os.strerror(errno.EPERM))

        def disk_full_after_the_link(fd: int, data: bytes, offset: int) -> int:
            # The temp file gets written; the in-place write is the one that fails.
            if not refused:
                return real_pwrite(fd, data, offset)
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(secret_key.os, "link", refuse)
        monkeypatch.setattr(secret_key.os, "pwrite", disk_full_after_the_link)

        with pytest.raises(OSError):
            create_key_file(path, "abc\n")

        assert refused
        assert path.read_bytes() == b""
        assert _entries(tmp_path) == ["k.key"]

    def test_a_carry_over_that_loses_the_race_keeps_the_key_on_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        legacy = tmp_path / "old" / "secret.key"
        legacy.parent.mkdir()
        legacy.write_text("legacy-key\n")
        monkeypatch.setattr(secret_key, "DEFAULT_KEY_FILE", legacy)
        path = tmp_path / "new" / "secret.key"
        real_create = secret_key.create_key_file

        def _lose_the_race(target: Path, content: str) -> str:
            real_create(target, "winner-key\n")
            return real_create(target, content)  # raises FileExistsError, as the race would

        monkeypatch.setattr(secret_key, "create_key_file", _lose_the_race)

        with caplog.at_level(logging.DEBUG, logger=secret_key.logger.name):
            key = get_or_create_secret_key(path)

        assert key == "winner-key" == path.read_text().strip()
        assert secret_key.KEY_SOURCE == "loaded"
        assert not [m for m in _warnings(caplog) if "Copied" in m]

    @pytest.mark.parametrize("content", ["existing-key\n", "existing-key", "  existing-key \n\n"])
    def test_an_existing_key_loads_and_the_file_is_untouched(
        self, tmp_path: Path, content: str
    ) -> None:
        path = tmp_path / "secret.key"
        path.write_text(content)
        inode = path.stat().st_ino

        assert get_or_create_secret_key(path) == "existing-key"
        assert secret_key.KEY_SOURCE == "loaded"
        assert path.read_text() == content
        assert path.stat().st_ino == inode


class TestFilesystemWithoutLocks:
    """A mount with no advisory locks (NFSv3 without lockd, some FUSE or 9p)
    can't flock. The key still gets written, unlocked, as it was before the
    lock existed, rather than falling back to a memory key."""

    @pytest.mark.parametrize(
        "code",
        [errno.ENOLCK, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS, errno.EINVAL],
        ids=["ENOLCK", "EOPNOTSUPP", "ENOTSUP", "ENOSYS", "EINVAL"],
    )
    @pytest.mark.parametrize("existing", [None, b""], ids=["missing", "empty"])
    def test_the_key_is_written_without_the_lock(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        code: int,
        existing: bytes | None,
        no_hard_links: None,
    ) -> None:
        """A missing file only takes the lock where it's made in place (no hard links)."""
        path = tmp_path / "secret.key"
        if existing is not None:
            path.write_bytes(existing)

        def no_locks(fd: int, operation: int) -> None:
            raise OSError(code, os.strerror(code))

        monkeypatch.setattr(secret_key.fcntl, "flock", no_locks)

        with caplog.at_level(logging.DEBUG, logger=secret_key.logger.name):
            key = get_or_create_secret_key(path)

        assert secret_key.KEY_SOURCE == "generated"
        assert path.read_text() == key + "\n"
        (lock_warning,) = [m for m in _warnings(caplog) if "lock" in m]
        assert os.strerror(code) in lock_warning
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    def test_a_new_file_needs_no_lock_where_hard_links_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "secret.key"

        def no_locks(fd: int, operation: int) -> None:
            raise OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))

        monkeypatch.setattr(secret_key.fcntl, "flock", no_locks)

        with caplog.at_level(logging.DEBUG, logger=secret_key.logger.name):
            key = get_or_create_secret_key(path)

        assert path.read_text() == key + "\n"
        assert not [m for m in _warnings(caplog) if "lock" in m]

    @pytest.mark.parametrize(
        "code", [errno.EIO, errno.EBADF, errno.EINTR], ids=["EIO", "EBADF", "EINTR"]
    )
    def test_any_other_lock_failure_still_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, no_hard_links: None
    ) -> None:
        path = tmp_path / "k.key"

        def broken(fd: int, operation: int) -> None:
            raise OSError(code, os.strerror(code))

        monkeypatch.setattr(secret_key.fcntl, "flock", broken)

        with pytest.raises(OSError) as raised:
            create_key_file(path, "abc\n")

        assert raised.value.errno == code
        assert path.read_bytes() == b""


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
        monkeypatch.setattr(secret_key, "KEY_FILE", Path("/data/secret.key"))

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
