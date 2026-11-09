"""Backup snapshot consistency tests (audit finding F2).

``create_full_backup`` must produce a SELF-CONTAINED ``mygarage.db``
member: every committed transaction present in that single file, with no
dependency on ``-wal``/``-shm`` sidecars. A raw file copy of a live
WAL-mode database fails this - committed rows that still live only in
the WAL are missing from the copied main file, and copying db/wal/shm
sequentially while a writer runs risks a torn, unrestorable archive.

The restore side has a matching hazard: restoring a self-contained db
member while stale live ``-wal``/``-shm`` files remain next to the
target would let SQLite replay the OLD wal over the NEW database.
"""

from __future__ import annotations

import asyncio
import errno
import importlib
import io
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.backup_service import BackupService


def _make_wal_db_with_pending_frames(db_path: Path) -> sqlite3.Connection:
    """Create a WAL-mode DB where the newest committed row lives only in the WAL.

    Row 1 is checkpointed into the main file; row 2 is committed but NOT
    checkpointed. The returned connection is left open so closing does not
    checkpoint the WAL - the caller must close it.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")  # never auto-checkpoint
    conn.execute("CREATE TABLE audit_rows (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO audit_rows (id, v) VALUES (1, 'checkpointed')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("INSERT INTO audit_rows (id, v) VALUES (2, 'wal-only')")
    conn.commit()
    return conn


def _service(tmp_path: Path, db_path: Path | None) -> BackupService:
    data_dir = tmp_path / "data"
    for sub in ("photos", "documents", "attachments"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return BackupService(
        backup_dir=tmp_path / "backups",
        database_path=db_path,
        data_dir=data_dir,
        is_sqlite=True,
    )


def _extract_member(archive: Path, member: str, dest: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tar:
        info = tar.getmember(member)
        extracted = tar.extractfile(info)
        assert extracted is not None
        target = dest / member
        with extracted, open(target, "wb") as fh:
            fh.write(extracted.read())
    return target


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_backup_db_member_is_self_contained(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """F2: the archived mygarage.db must contain ALL committed rows on its own.

    With the raw file-copy approach, row 2 (committed, un-checkpointed)
    exists only in the -wal sidecar and is missing from the db member.
    """
    db_path = tmp_path / "mygarage.db"
    writer = _make_wal_db_with_pending_frames(db_path)
    try:
        service = _service(tmp_path, db_path)
        meta = await service.create_full_backup(db_session)
        archive = service.backup_dir / meta["filename"]

        extracted_db = _extract_member(archive, "mygarage.db", tmp_path)
        check = sqlite3.connect(f"file:{extracted_db}?mode=ro", uri=True)
        try:
            rows = check.execute("SELECT id, v FROM audit_rows ORDER BY id").fetchall()
        finally:
            check.close()

        assert rows == [(1, "checkpointed"), (2, "wal-only")], (
            "backup db member is missing committed WAL-resident rows - the "
            "backup is a raw file copy, not a consistent snapshot "
            f"(audit finding F2); got {rows!r}"
        )

        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
        assert "mygarage.db-wal" not in names and "mygarage.db-shm" not in names, (
            "snapshot backups must be self-contained; wal/shm sidecars in the "
            "archive indicate the live-file-copy path is still in use"
        )
    finally:
        writer.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restore_removes_stale_wal_sidecars(tmp_path: Path, db_session: AsyncSession) -> None:
    """F2 restore hygiene: stale live -wal/-shm don't survive the restore's apply at the next start.

    If they do, SQLite can replay the OLD wal frames over the freshly
    restored database on next open, corrupting it.
    """
    db_path = tmp_path / "mygarage.db"

    # Build the "new" self-contained database we will archive and restore.
    source_db = tmp_path / "source.db"
    src = sqlite3.connect(source_db)
    src.execute("CREATE TABLE audit_rows (id INTEGER PRIMARY KEY, v TEXT)")
    src.execute("INSERT INTO audit_rows (id, v) VALUES (99, 'restored')")
    src.commit()
    src.close()

    service = _service(tmp_path, db_path)
    service.ensure_backup_dir()
    archive = service.backup_dir / "mygarage-full-restoretest.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source_db, arcname="mygarage.db")

    # Live target: an older DB plus stale wal/shm sidecars on disk. Closing a
    # connection checkpoints and removes the real wal, so plant sidecar files
    # explicitly - the restore target must genuinely have leftovers to clean.
    stale = _make_wal_db_with_pending_frames(db_path)
    stale.close()
    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    wal_path.write_bytes(b"stale wal bytes")
    shm_path.write_bytes(b"stale shm bytes")

    await service.restore_full_backup(
        "mygarage-full-restoretest.tar.gz", db_session, create_safety=False
    )
    service.apply_pending_restore()

    assert not wal_path.exists() and not shm_path.exists(), (
        "stale -wal/-shm sidecars survived restore; SQLite may replay the old "
        "WAL over the restored database (audit finding F2, restore side)"
    )

    check = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = check.execute("SELECT id, v FROM audit_rows ORDER BY id").fetchall()
    finally:
        check.close()
    assert rows == [(99, "restored")], f"restored db has wrong content: {rows!r}"


def _read_rows(db_path: Path) -> list[tuple[int, str]]:
    """Read audit_rows read-only. Quoted, so a # in the name stays part of the path."""
    check = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
    try:
        return check.execute("SELECT id, v FROM audit_rows ORDER BY id").fetchall()
    finally:
        check.close()


def _write_one_row_db(db_path: Path, row_id: int, value: str) -> None:
    """A plain rollback-journal database holding a single audit row."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE audit_rows (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO audit_rows (id, v) VALUES (?, ?)", (row_id, value))
    conn.commit()
    conn.close()


def _plant_live_wal_db(db_path: Path) -> None:
    """Leave a closed WAL database at db_path whose newest row lives only in its -wal.

    Closing the writer checkpoints and deletes the WAL, so the writer works in a
    scratch folder and its db, -wal and -shm get copied over while it's still open.
    """
    scratch = db_path.parent / "writer"
    scratch.mkdir()
    source = scratch / "live.db"
    writer = _make_wal_db_with_pending_frames(source)
    try:
        shutil.copyfile(source, db_path)
        for suffix in ("-wal", "-shm"):
            shutil.copyfile(f"{source}{suffix}", f"{db_path}{suffix}")
    finally:
        writer.close()


STAGED = "mygarage-full-staged.tar.gz"


def _write_archive(
    service: BackupService, filename: str, db: Path | None, files: dict[str, bytes] | None = None
) -> None:
    """A full backup in the service's backup folder: `db` as mygarage.db, plus files by archive path."""
    service.ensure_backup_dir()
    with tarfile.open(service.backup_dir / filename, "w:gz") as tar:
        if db is not None:
            tar.add(db, arcname="mygarage.db")
        for arcname, data in (files or {}).items():
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _live_state(service: BackupService, db_path: Path) -> dict[str, bytes | None]:
    """Every live byte a restore could touch: the database, its sidecars and the three folders."""
    state: dict[str, bytes | None] = {}
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{db_path}{suffix}")
        state[f"db{suffix}"] = path.read_bytes() if path.exists() else None
    for name in ("photos", "documents", "attachments"):
        for path in sorted((service.data_dir / name).rglob("*")):
            if path.is_file():
                state[str(path.relative_to(service.data_dir))] = path.read_bytes()
    return state


def _every_file(root: Path) -> dict[str, bytes]:
    """Every file under root with its bytes: what a refused start must leave exactly as it was."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _live_and_archive(tmp_path: Path) -> tuple[BackupService, Path]:
    """Live: a WAL database whose newest row is only in its -wal, and photos/old.jpg.

    Archived as STAGED: one row (99, 'restored') and photos/new.jpg.
    """
    db_path = tmp_path / "garage.db"
    _plant_live_wal_db(db_path)
    service = _service(tmp_path, db_path)
    (service.data_dir / "photos" / "old.jpg").write_bytes(b"old photo")
    source = tmp_path / "source.db"
    _write_one_row_db(source, 99, "restored")
    _write_archive(service, STAGED, source, {"photos/new.jpg": b"new photo"})
    return service, db_path


def _write_db_with_an_index_out_of_step(db_path: Path) -> None:
    """An index that no longer matches its table: quick_check passes it, integrity_check doesn't."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE audit_rows (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("CREATE INDEX ix_v ON audit_rows (v)")
    conn.executemany(
        "INSERT INTO audit_rows (id, v) VALUES (?, ?)", [(i, f"v{i}") for i in range(50)]
    )
    conn.commit()
    # The index's pages still hold v; its definition now says id.
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute(
        "UPDATE sqlite_master SET sql = 'CREATE INDEX ix_v ON audit_rows (id)' WHERE name = 'ix_v'"
    )
    conn.commit()
    conn.close()


def _manifest(service: BackupService) -> dict[str, object]:
    """The staged restore's manifest."""
    return json.loads((service.data_dir / ".restore-pending" / "manifest.json").read_text())


def _prerestore_archives(service: BackupService) -> list[Path]:
    """The safety archives the start writes just before a swap."""
    return sorted(service.backup_dir.glob("mygarage-full-safety-prerestore-*.tar.gz"))


def _archived_rows(archive: Path, scratch: Path) -> list[tuple[int, str]]:
    """The audit rows of an archive's mygarage.db."""
    scratch.mkdir()
    return _read_rows(_extract_member(archive, "mygarage.db", scratch))


def _write_after_staging(db_path: Path) -> None:
    """Add row 3 to the live database the way the running app would: committed, still in the -wal.

    Written through a copy, since closing the last connection on the live files would checkpoint.
    """
    scratch = db_path.parent / "late-writer"
    scratch.mkdir()
    copy = scratch / "live.db"
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(f"{db_path}{suffix}", f"{copy}{suffix}")
    writer = sqlite3.connect(copy)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO audit_rows (id, v) VALUES (3, 'after-staging')")
        writer.commit()
        for suffix in ("", "-wal", "-shm"):
            shutil.copyfile(f"{copy}{suffix}", f"{db_path}{suffix}")
    finally:
        writer.close()


class _KilledError(Exception):
    """Stands in for a kill right after a step finished."""


def _kill_after_changes(patched: pytest.MonkeyPatch, changes: int) -> None:
    """Let the next `changes` renames or deletes happen, each made durable, then stop dead."""
    staging_module = importlib.import_module("app.services.restore_staging")
    done = 0

    def _counted(real: Callable[..., None]) -> Callable[..., None]:
        def _change(*paths: Path) -> None:
            nonlocal done
            real(*paths)
            done += 1
            if done == changes:
                raise _KilledError

        return _change

    for name in ("_replace", "_unlink"):
        patched.setattr(staging_module, name, _counted(getattr(staging_module, name)))


Trace = list[tuple[str, tuple[Path, ...]]]


def _record_durability(patched: pytest.MonkeyPatch) -> Trace:
    """Record restore_staging's fsyncs and changes in order, letting each one happen."""
    staging_module = importlib.import_module("app.services.restore_staging")
    trace: Trace = []
    happens: dict[str, Callable[[Path], bool]] = {
        "unlink": lambda p: p.exists() or p.is_symlink(),
        "mkdir": lambda p: not p.is_dir(),
        "remove_tree": lambda p: p.exists(),
    }

    def _recorded(op: str, real: Callable[..., None]) -> Callable[..., None]:
        def _step(*paths: Path) -> None:
            if op not in happens or happens[op](paths[0]):
                trace.append((op, tuple(Path(p) for p in paths)))
            real(*paths)

        return _step

    for op in ("fsync_file", "fsync_dir", "replace", "unlink", "mkdir", "remove_tree"):
        patched.setattr(staging_module, f"_{op}", _recorded(op, getattr(staging_module, f"_{op}")))
    return trace


def _assert_each_change_is_durable_before_the_next(trace: Trace) -> None:
    """After every rename, delete or new folder, the folders it touched are fsynced before the next change."""
    owed: set[Path] = set()
    for op, paths in trace:
        if op == "fsync_dir":
            owed.discard(paths[0])
        elif op != "fsync_file":
            assert not owed, f"{op} {paths} ran before {sorted(map(str, owed))} were fsynced"
            owed = {path.parent for path in paths}
    assert not owed, f"{sorted(map(str, owed))} were never fsynced"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["garage.db", "my#garage.db", "mygarage.db"])
async def test_restore_writes_the_configured_database_file(
    tmp_path: Path, name: str, db_session: AsyncSession
) -> None:
    """The archive's mygarage.db lands in the file the app opens at the next start, whatever it's called.

    It used to land at `mygarage.db` beside the configured file, and the WAL
    hygiene then deleted the live file's -wal: the app kept its old data, minus
    every row that hadn't been checkpointed. The `mygarage.db` case passes at
    t=0: it's the guard for the default deployment, and extracting the database
    members to `self.data_dir` instead of the database's own folder kills it.
    """
    db_path = tmp_path / name
    _plant_live_wal_db(db_path)
    assert Path(f"{db_path}-wal").stat().st_size > 0, "the live WAL frame wasn't planted"

    source_db = tmp_path / "source.db"
    _write_one_row_db(source_db, 99, "restored")
    service = _service(tmp_path, db_path)
    service.ensure_backup_dir()
    with tarfile.open(service.backup_dir / "mygarage-full-configured.tar.gz", "w:gz") as tar:
        tar.add(source_db, arcname="mygarage.db")

    await service.restore_full_backup(
        "mygarage-full-configured.tar.gz", db_session, create_safety=False
    )
    service.apply_pending_restore()

    assert not Path(f"{db_path}-wal").exists() and not Path(f"{db_path}-shm").exists()
    assert _read_rows(db_path) == [(99, "restored")], f"{name!r} wasn't the file restored"
    if name != "mygarage.db":
        assert not (tmp_path / "mygarage.db").exists(), "the restore wrote a stray mygarage.db"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_old_archives_wal_is_folded_into_the_staged_database(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """A pre-snapshot archive keeps its newest rows in a -wal member; the staged file holds them itself.

    Replaces test_an_old_archives_wal_member_follows_the_configured_file. Teeth: skip the -wal
    member, or skip the fold and check through a read-only connection (row 2 is lost with the
    work folder, probed). The journal_mode line pins the fold itself: a read-write check
    connection folds the rows on close anyway, but leaves the file in WAL mode.
    """
    db_path = tmp_path / "garage.db"
    _write_one_row_db(db_path, 7, "live")
    service = _service(tmp_path, db_path)
    service.ensure_backup_dir()
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    writer = _make_wal_db_with_pending_frames(old_dir / "old.db")
    try:
        with tarfile.open(service.backup_dir / "mygarage-full-old.tar.gz", "w:gz") as tar:
            tar.add(old_dir / "old.db", arcname="mygarage.db")
            tar.add(old_dir / "old.db-wal", arcname="mygarage.db-wal")
            tar.add(old_dir / "old.db-shm", arcname="mygarage.db-shm")
    finally:
        writer.close()

    await service.restore_full_backup("mygarage-full-old.tar.gz", db_session, create_safety=False)

    pending = Path(f"{db_path}.restore-pending")
    assert pending.exists(), "nothing was staged"
    assert not Path(f"{pending}-wal").exists() and not Path(f"{pending}-shm").exists()
    assert _read_rows(pending) == [(1, "checkpointed"), (2, "wal-only")]
    check = sqlite3.connect(f"file:{quote(str(pending))}?mode=ro", uri=True)
    try:
        assert check.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    finally:
        check.close()
    assert not list(tmp_path.rglob("mygarage.db-wal")), "a WAL member landed on disk"
    assert _read_rows(db_path) == [(7, "live")]

    service.apply_pending_restore()
    assert _read_rows(db_path) == [(1, "checkpointed"), (2, "wal-only")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_memory_sqlite_stays_on_the_sqlite_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_session: AsyncSession,
) -> None:
    """In-memory SQLite has no file to size or snapshot, but it's still SQLite.

    With no path it fell through to the PostgreSQL branches: stats said
    "PostgreSQL" and a full backup ran pg_dump.
    """
    service = _service(tmp_path, None)
    (service.data_dir / "photos" / "car.jpg").write_bytes(b"not really a jpeg")

    def _no_pg_dump(output_path: Path) -> None:
        raise AssertionError("pg_dump ran for an in-memory SQLite database")

    monkeypatch.setattr(service, "_pg_dump", _no_pg_dump)

    assert service.get_database_stats() == {
        "path": "in-memory",
        "size_mb": 0,
        "last_modified": None,
        "exists": False,
    }

    with caplog.at_level(logging.WARNING, logger="app.services.backup_service"):
        meta = await service.create_full_backup(db_session)

    with tarfile.open(service.backup_dir / meta["filename"], "r:gz") as tar:
        names = tar.getnames()
    assert not set(names) & BackupService._SAFE_FILE_ENTRIES, f"archived a database: {names!r}"
    assert "photos/car.jpg" in names
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["in-memory SQLite has no file to back up"]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["my#garage.db", "my?garage.db", "my%41garage.db"])
async def test_full_backup_snapshots_a_path_with_uri_characters(
    tmp_path: Path, name: str, db_session: AsyncSession
) -> None:
    """`#`, `?` and `%` in the database path stay part of the path.

    The snapshot opens a `file:` URI. Unescaped, `#garage.db?mode=ro` read as
    the fragment, so SQLite opened (and created) `.../my` read-write and the
    archive held an empty database. `%41` decoded to a file that isn't there.
    """
    db_path = tmp_path / name
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE audit_rows (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO audit_rows (id, v) VALUES (1, 'kept')")
    conn.commit()
    conn.close()

    service = _service(tmp_path, db_path)
    meta = await service.create_full_backup(db_session)
    archive = service.backup_dir / meta["filename"]

    extracted_db = _extract_member(archive, "mygarage.db", tmp_path)
    check = sqlite3.connect(extracted_db)
    try:
        tables = [
            row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        rows = check.execute("SELECT id, v FROM audit_rows").fetchall() if tables else []
    finally:
        check.close()

    assert tables == ["audit_rows"], f"archived an empty database for {name!r}"
    assert rows == [(1, "kept")]
    assert not (tmp_path / "my").exists(), "the snapshot created a stray database file"


@pytest.mark.unit
def test_pg_dump_names_the_database_the_engine_opens() -> None:
    """SQLAlchemy 2.1 decodes the URL's database name, so pg_dump has to as well."""
    url = "postgresql+asyncpg://u:p@h/my%41db"
    service = BackupService(
        backup_dir=Path("/nonexistent/backups"),
        database_path=None,
        data_dir=Path("/nonexistent"),
        database_url=url,
        is_sqlite=False,
    )

    assert service._parse_pg_url()["dbname"] == make_url(url).database == "myAdb"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_full_restore_leaves_the_live_data_alone_until_the_restart(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """Staging writes nothing the running app has open.

    It used to truncate the live file and unlink its -wal under pooled connections. No safety
    backup here: that's a reader, and any reader may touch -shm.
    """
    service, db_path = _live_and_archive(tmp_path)
    before = _live_state(service, db_path)

    result = await service.restore_full_backup(STAGED, db_session, create_safety=False)

    assert _live_state(service, db_path) == before, (
        "the restore changed live data before the restart"
    )
    assert result["message"] == "Restore staged. Restart MyGarage to finish."
    assert _read_rows(Path(f"{db_path}.restore-pending")) == [(99, "restored")]
    staging = service.data_dir / ".restore-pending"
    assert (staging / "photos" / "new.jpg").read_bytes() == b"new photo"
    manifest = _manifest(service)
    assert manifest["format"] == 1
    assert manifest["source_backup"] == STAGED
    assert manifest["database"] == str(db_path.resolve())
    assert str(manifest["staged_at"]).endswith("+00:00")
    assert str(manifest["prerestore_backup"]).startswith("mygarage-full-safety-prerestore-")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_next_start_swaps_the_staged_restore_in(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """The start applies it: database and folders swapped, the live WAL gone, nothing left staged.

    A guard on the apply. Mutants: skip the -wal/-shm unlink (the planted WAL is the old
    file's, and SQLite replays it over the new one), or skip step (d) (the marker, the
    manifest and the staging folder stay).
    """
    service, db_path = _live_and_archive(tmp_path)
    (service.data_dir / "documents" / "old.pdf").write_bytes(b"old doc")
    await service.restore_full_backup(STAGED, db_session, create_safety=False)

    assert service.apply_pending_restore() == STAGED

    assert not Path(f"{db_path}-wal").exists() and not Path(f"{db_path}-shm").exists()
    assert _read_rows(db_path) == [(99, "restored")]
    assert sorted(p.name for p in (service.data_dir / "photos").iterdir()) == ["new.jpg"]
    assert list((service.data_dir / "documents").iterdir()) == [], (
        "a folder the archive lacks comes back empty"
    )
    assert not (service.data_dir / ".restore-pending").exists()
    assert not Path(f"{db_path}.restore-pending").exists()
    assert service.apply_pending_restore() is None
    assert len(_prerestore_archives(service)) == 1, "a second start wrote another safety archive"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_start_archives_the_data_it_replaces_first(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """Rows written after the staging, still in the live WAL, are in the start's safety archive.

    The staging-time safety backup can't have them: they came later. A guard; mutants: skip
    the snapshot (no archive), or take it after the -wal/-shm unlink (rows 2 and 3 go
    with the WAL).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    _write_after_staging(db_path)

    service.apply_pending_restore()

    (archive,) = _prerestore_archives(service)
    assert _archived_rows(archive, tmp_path / "check") == [
        (1, "checkpointed"),
        (2, "wal-only"),
        (3, "after-staging"),
    ]
    with tarfile.open(archive, "r:gz") as tar:
        assert "photos/old.jpg" in tar.getnames()
    (listed,) = [b for b in service.get_backup_files("full") if b["filename"] == archive.name]
    assert listed["is_safety"] is True
    # It restores like any other full backup.
    await service.restore_full_backup(archive.name, db_session, create_safety=False)
    assert _read_rows(Path(f"{db_path}.restore-pending")) == [
        (1, "checkpointed"),
        (2, "wal-only"),
        (3, "after-staging"),
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_safety_archive_cut_off_mid_write_is_written_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """The start died inside the archive writer, after bytes were written: the next start writes it again.

    Nothing live changes until the archive is whole under its name. -shm is left out of the
    comparison: it's shared memory, and the snapshot is a reader. A kill runs no Python, so
    the writer's own cleanup of a failed write is switched off here too. A guard; mutant: write
    the archive straight to its final name (the cut-off archive then counts as done, with no
    photos).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    before = {k: v for k, v in _live_state(service, db_path).items() if k != "db-shm"}
    real_add = tarfile.TarFile.add
    staging_module = importlib.import_module("app.services.restore_staging")

    def _dies_at_the_photos(self: tarfile.TarFile, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("arcname") == "photos":
            raise _KilledError
        real_add(self, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(tarfile.TarFile, "add", _dies_at_the_photos)
        patched.setattr(staging_module, "discard_partial", lambda partial: None)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()

    name = str(_manifest(service)["prerestore_backup"])
    assert (service.backup_dir / f"{name}.partial").stat().st_size > 0, (
        "the writer hadn't written anything"
    )
    assert not (service.backup_dir / name).exists()
    after = {k: v for k, v in _live_state(service, db_path).items() if k != "db-shm"}
    assert after == before, "something live changed before the archive was whole"

    assert service.apply_pending_restore() == STAGED

    assert not (service.backup_dir / f"{name}.partial").exists()
    assert _archived_rows(service.backup_dir / name, tmp_path / "check") == [
        (1, "checkpointed"),
        (2, "wal-only"),
    ]
    with tarfile.open(service.backup_dir / name, "r:gz") as tar:
        assert "photos/old.jpg" in tar.getnames()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["request", "start"])
async def test_a_safety_archive_that_fails_to_write_leaves_no_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str, db_session: AsyncSession
) -> None:
    """The writer fails partway (the disk fills at the photos): its .partial goes with it.

    The request's safety archive is named by the second, so every failed restore would leave
    another one behind, never listed and never cleaned up. A kill can't clean up, and the
    cut-off test above covers that. Mutant: skip the cleanup.
    """
    service, _ = _live_and_archive(tmp_path)
    if when == "start":
        await service.restore_full_backup(STAGED, db_session, create_safety=False)
    real_add = tarfile.TarFile.add
    partials_at_failure: list[Path] = []

    def _disk_full_at_the_photos(self: tarfile.TarFile, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("arcname") == "photos":
            partials_at_failure.extend(service.backup_dir.glob("*.partial"))
            raise OSError(errno.ENOSPC, "No space left on device")
        real_add(self, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(tarfile.TarFile, "add", _disk_full_at_the_photos)
        with pytest.raises((OSError, RuntimeError), match="No space left on device"):
            if when == "request":
                await service.restore_full_backup(STAGED, db_session, create_safety=True)
            else:
                service.apply_pending_restore()

    assert len(partials_at_failure) == 1, "the write didn't fail partway"
    assert list(service.backup_dir.glob("*.partial")) == []
    assert list(service.backup_dir.glob("mygarage-full-safety-*")) == []


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["cant_finish", "missing_archive", "applied"])
async def test_names_read_from_the_staging_cant_forge_a_log_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
    db_session: AsyncSession,
) -> None:
    """The manifest and the marker are files on disk, so what the start logs from them is sanitized.

    A newline in a hand-edited name would start a log line of its own. The cases reach the
    marker's names in _cannot_finish, the manifest's archive name in the missing-archive
    refusal, and the same name in the log lines of an apply that goes through. Mutant: log
    any of those names as read.
    """
    service, _ = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    staging = service.data_dir / ".restore-pending"
    forged = "pre\nFORGED log line.tar.gz"
    if case != "applied":
        with monkeypatch.context() as patched:
            _kill_after_changes(patched, 5)
            with pytest.raises(_KilledError):
                service.apply_pending_restore()
    if case == "cant_finish":
        marker = json.loads((staging / "applying").read_text())
        marker["prerestore_backup"] = forged
        marker["database"] = f"{marker['database']}\rFORGED"
        (staging / "applying").write_text(json.dumps(marker))
        (staging / "manifest.json").write_text("{ cut off")
    else:
        manifest = json.loads((staging / "manifest.json").read_text())
        manifest["prerestore_backup"] = forged
        (staging / "manifest.json").write_text(json.dumps(manifest))
    caplog.clear()

    with caplog.at_level(logging.INFO):
        if case == "applied":
            assert service.apply_pending_restore() == STAGED
        else:
            with pytest.raises(RuntimeError):
                service.apply_pending_restore()

    logged = [
        r.getMessage()
        for r in caplog.records
        if r.name in ("app.services.restore_staging", "app.services.backup_service")
    ]
    assert any("pre\\nFORGED log line" in message for message in logged), logged
    assert not [m for m in logged if "\n" in m or "\r" in m], logged


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("left", ["everything", "nothing"])
async def test_an_unfinished_staging_is_thrown_away_at_start(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, left: str, db_session: AsyncSession
) -> None:
    """No manifest and no applying marker means the staging never finished: the start drops it.

    A guard on the manifest rule; mutant: skip the no-manifest branch (the staging stays for
    every later start). "nothing" is a cancel killed in its last step, an empty staging folder:
    no restore went in, so it still gets the WARNING. Mutant: drop the previous/ check (it reads
    as the cleanup of an applied restore).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    staging = service.data_dir / ".restore-pending"
    (staging / "manifest.json").unlink()
    if left == "nothing":
        Path(f"{db_path}.restore-pending").unlink()
        for name in ("photos", "documents", "attachments"):
            shutil.rmtree(staging / name)
        assert staging.exists() and not any(staging.iterdir())
    before = _live_state(service, db_path)

    with caplog.at_level(logging.WARNING, logger="app.services.restore_staging"):
        assert service.apply_pending_restore() is None

    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending").exists()
    assert not Path(f"{db_path}.restore-pending").exists()
    assert _prerestore_archives(service) == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == ["Discarded an unfinished restore; the current data stays"]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem",
    ["other_database", "unreadable_manifest", "staged_database_gone", "no_archive_name"],
)
async def test_a_staged_restore_that_doesnt_fit_waits_and_can_be_cancelled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, problem: str, db_session: AsyncSession
) -> None:
    """Untouched staging that can't be applied: the start logs it, swaps nothing and starts.

    The setting changed, the manifest broke or names no safety archive, or the staged database
    went missing. The tab still shows it, and Cancel still works and leaves no stray staged
    file. A guard; mutants: drop the partly-staged check (staged_database_gone: the staged
    folders land on a database that was never restored), drop the archive-name check
    (no_archive_name: a KeyError in the swap instead of the log line), or refuse to start
    without the applying marker (a harmless mismatch stops the app). Dropping the target check
    passes here: without the marker a changed setting also reads as partly staged, since the
    staged database is named after the file it replaces. The half-applied test kills that one.
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    live = db_path
    starter = service
    if problem == "other_database":
        live = tmp_path / "other.db"
        _write_one_row_db(live, 5, "other")
        starter = _service(tmp_path, live)
    elif problem == "unreadable_manifest":
        (service.data_dir / ".restore-pending" / "manifest.json").write_text("{ cut off")
    elif problem == "no_archive_name":
        manifest_path = service.data_dir / ".restore-pending" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["prerestore_backup"]
        manifest_path.write_text(json.dumps(manifest))
    else:
        Path(f"{db_path}.restore-pending").unlink()
    before = _live_state(starter, live)

    with caplog.at_level(logging.ERROR, logger="app.services.restore_staging"):
        assert starter.apply_pending_restore() is None

    assert _live_state(starter, live) == before
    assert (starter.data_dir / ".restore-pending" / "manifest.json").exists()
    assert _prerestore_archives(starter) == []
    staging_logs = [r.levelno for r in caplog.records if r.name == "app.services.restore_staging"]
    assert staging_logs == [logging.ERROR]
    expected_source = None if problem == "unreadable_manifest" else STAGED
    assert (starter.pending_restore() or {}).get("source_backup") == expected_source

    await starter.cancel_pending_restore()

    assert starter.pending_restore() is None
    assert not (starter.data_dir / ".restore-pending").exists()
    assert not Path(f"{db_path}.restore-pending").exists()
    assert _live_state(starter, live) == before


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("killed_after", range(1, 14))
async def test_a_start_killed_after_any_change_finishes_the_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    killed_after: int,
    db_session: AsyncSession,
) -> None:
    """A start killed right after any of the apply's 13 changes: the next start lands on the restored state.

    The changes, in order:
    - (1) the safety archive;
    - (2) the applying marker;
    - (3, 4) the live -wal and -shm;
    - (5) the database;
    - (6 to 11) each folder set aside and moved in, for photos, documents and attachments;
    - (12) the marker gone;
    - (13) the manifest gone.

    A guard; mutants:
    - unlink without the existence check (3);
    - no staged database means nothing to apply (5);
    - set the live folder aside without checking it's there (6).

    The archive mutants (written with the marker down, no existence check, no cleanup-only path)
    leave the archive alone here, so their own tests below kill them.

    After 13 the restore is in and only the cleanup is left, so the log says so: a WARNING that
    the restore was discarded would send someone to restore it again. Mutant: log the old WARNING.
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, killed_after)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.services.restore_staging"):
        # Up to 12 the manifest is still there, so the next start resumes; after 13 only cleanup is left.
        assert service.apply_pending_restore() == (STAGED if killed_after < 13 else None)

    if killed_after == 13:
        staging_logs = [
            (r.levelno, r.getMessage())
            for r in caplog.records
            if r.name == "app.services.restore_staging"
        ]
        assert staging_logs == [
            (logging.INFO, "Removed the leftover staging of an applied restore")
        ]

    assert not Path(f"{db_path}-wal").exists()
    assert _read_rows(db_path) == [(99, "restored")]
    assert sorted(p.name for p in (service.data_dir / "photos").iterdir()) == ["new.jpg"]
    assert not (service.data_dir / ".restore-pending").exists()
    (archive,) = _prerestore_archives(service)
    assert not archive.with_name(archive.name + ".partial").exists()
    archived = _archived_rows(archive, tmp_path / "check")
    assert archived == [(1, "checkpointed"), (2, "wal-only")], (
        "the safety archive holds a half-swapped state"
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("killed_after", [5, 6], ids=["database_replaced", "photos_set_aside"])
@pytest.mark.parametrize("problem", ["other_database", "unreadable_manifest"])
async def test_a_half_applied_restore_that_cant_finish_stops_the_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    killed_after: int,
    problem: str,
    db_session: AsyncSession,
) -> None:
    """Half swapped, then the start can't finish (the setting changed, or the manifest broke): it refuses.

    Serving would mix old and new data, and dropping the staging would lose what was swapped
    out. So the start raises with what to do by hand, every file stays, and Cancel is refused.
    A guard; mutants: log and start anyway with the marker down, let a discard ignore the
    marker, never write the marker, drop the target check (the other_database cases swap onto
    the new database).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, killed_after)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()
    starter = service
    if problem == "other_database":
        other = tmp_path / "other.db"
        _write_one_row_db(other, 5, "other")
        starter = _service(tmp_path, other)
    else:
        (service.data_dir / ".restore-pending" / "manifest.json").write_text("{ cut off")
    before = _every_file(tmp_path)

    with pytest.raises(RuntimeError) as refused:
        starter.apply_pending_restore()

    assert _every_file(tmp_path) == before, "the refused start changed files"
    text = str(refused.value)
    assert "Its files are kept" in text
    assert _prerestore_archives(service)[0].name in text
    assert "MYGARAGE_MAINTENANCE_MODE=1" in text
    if problem == "other_database":
        assert f"point MYGARAGE_DATABASE_URL at {db_path.resolve()}" in text
    with pytest.raises(RuntimeError, match="interrupted while it was being applied"):
        await starter.cancel_pending_restore()
    assert _every_file(tmp_path) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_change_is_on_disk_before_the_next_step_relies_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """The fsync order a power cut needs, recorded from the real staging, apply and cancel.

    A killed test process keeps the page cache, so a power cut can't be staged here; the
    order is the proof. The staged database sits outside data_dir, so its folder is a
    separate fsync. A guard; mutants:
    - drop that folder's fsync;
    - drop the source-folder fsync in _replace;
    - publish the safety archive with a bare os.replace;
    - write the applying marker after the first live change;
    - make a folder without persisting it.
    """
    service, db_path = _live_and_archive(tmp_path)
    staging = service.data_dir / ".restore-pending"
    manifest = staging / "manifest.json"
    pending = Path(f"{db_path.resolve()}.restore-pending")

    with monkeypatch.context() as patched:
        trace = _record_durability(patched)
        await service.restore_full_backup(STAGED, db_session, create_safety=False)

    published = trace.index(("replace", (staging / "manifest.json.partial", manifest)))
    fsynced = {paths[0] for op, paths in trace[:published] if op.startswith("fsync")}
    staged = {p for p in staging.rglob("*") if p != manifest} | {staging}
    assert staged | {pending, pending.parent, service.data_dir} <= fsynced
    _assert_each_change_is_durable_before_the_next(trace)

    with monkeypatch.context() as patched:
        trace = _record_durability(patched)
        assert service.apply_pending_restore() == STAGED

    (archive,) = _prerestore_archives(service)
    partial = archive.with_name(archive.name + ".partial")
    applying = staging / "applying"
    archive_published = trace.index(("replace", (partial, archive)))
    marker_published = trace.index(("replace", (staging / "applying.partial", applying)))
    first_live_change = trace.index(("unlink", (Path(f"{db_path.resolve()}-wal"),)))
    assert trace.index(("fsync_file", (partial,))) < archive_published
    assert archive_published < trace.index(("fsync_dir", (service.backup_dir,))) < marker_published
    assert marker_published < first_live_change
    marker_gone = trace.index(("unlink", (applying,)))
    assert (
        marker_gone
        < trace.index(("unlink", (manifest,)))
        < trace.index(("remove_tree", (staging,)))
    )
    _assert_each_change_is_durable_before_the_next(trace)

    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        trace = _record_durability(patched)
        await service.cancel_pending_restore()

    assert trace.index(("unlink", (manifest,))) < trace.index(("remove_tree", (staging,)))
    _assert_each_change_is_durable_before_the_next(trace)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["not_a_database", "index_out_of_step"])
async def test_a_damaged_backup_database_is_refused_and_nothing_is_staged(
    tmp_path: Path, damage: str, db_session: AsyncSession
) -> None:
    """A database that would break the next start is refused now, with the live data untouched.

    Mutants: skip integrity_check, or run quick_check instead (index_out_of_step stages);
    let sqlite3.DatabaseError through (not_a_database raises that, not ValueError); skip the
    cleanup on failure (the staging folder stays).
    """
    service, db_path = _live_and_archive(tmp_path)
    bad = tmp_path / "bad.db"
    if damage == "not_a_database":
        bad.write_bytes(b"not a database " * 600)
    else:
        _write_db_with_an_index_out_of_step(bad)
    _write_archive(service, "mygarage-full-bad.tar.gz", bad, {"photos/new.jpg": b"new photo"})
    before = _live_state(service, db_path)

    with pytest.raises(ValueError, match="backup's database"):
        await service.restore_full_backup(
            "mygarage-full-bad.tar.gz", db_session, create_safety=False
        )

    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending").exists()
    assert not Path(f"{db_path}.restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refusal", "keeps_the_first"),
    [
        ("bad_name", True),
        ("missing_file", True),
        ("safety_archive_fails", True),
        ("damaged_archive", False),
    ],
)
async def test_a_refused_restore_keeps_or_drops_the_earlier_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refusal: str,
    keeps_the_first: bool,
    db_session: AsyncSession,
) -> None:
    """Refused before the discard, the earlier staging stays; refused after it, nothing is staged.

    The discard comes after the name check, the file check and the safety archive, and before
    the archive's own checks. A guard; mutant: discard before the safety archive
    (safety_archive_fails then drops the first staging).
    """
    service, _ = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    name, create_safety = STAGED, False
    if refusal == "bad_name":
        name = "../outside.tar.gz"
    elif refusal == "missing_file":
        name = "mygarage-full-missing.tar.gz"
    elif refusal == "safety_archive_fails":
        create_safety = True

        def _disk_full(self: BackupService, archive: Path) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(BackupService, "_write_safety_archive", _disk_full)
    else:
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"not a database " * 600)
        _write_archive(service, "mygarage-full-bad.tar.gz", bad)
        name = "mygarage-full-bad.tar.gz"

    with pytest.raises((OSError, ValueError)):
        await service.restore_full_backup(name, db_session, create_safety=create_safety)

    pending = service.pending_restore()
    if keeps_the_first:
        assert pending is not None and pending["source_backup"] == STAGED
    else:
        assert pending is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_symlinked_database_restores_the_file_it_points_at(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """The staged file waits beside the real file, and the swap replaces the real file, not the link.

    SQLite names the WAL after the real file too (probed), so that's the -wal that goes. A
    guard; mutant: drop the resolve() in pending_database (the staged file lands beside the
    link, and os.replace swaps the link for a plain file).
    """
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "garage.db"
    _plant_live_wal_db(real)
    link = tmp_path / "mygarage.db"
    link.symlink_to(real)
    service = _service(tmp_path, link)
    source = tmp_path / "source.db"
    _write_one_row_db(source, 99, "restored")
    _write_archive(service, "mygarage-full-link.tar.gz", source)

    await service.restore_full_backup("mygarage-full-link.tar.gz", db_session, create_safety=False)

    assert Path(f"{real}.restore-pending").exists()
    assert not Path(f"{link}.restore-pending").exists()

    service.apply_pending_restore()

    assert link.is_symlink() and link.resolve() == real
    assert not Path(f"{real}-wal").exists() and not Path(f"{real}-shm").exists()
    assert _read_rows(real) == [(99, "restored")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_memory_sqlite_refuses_a_full_restore(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """In-memory SQLite has no file to restore into.

    It wrote mygarage.db into data_dir, for an engine that never opens it, and emptied the
    live folders on top.
    """
    service = _service(tmp_path, None)
    (service.data_dir / "photos" / "old.jpg").write_bytes(b"old photo")
    source = tmp_path / "source.db"
    _write_one_row_db(source, 99, "restored")
    _write_archive(service, "mygarage-full-mem.tar.gz", source)

    with pytest.raises(ValueError, match="In-memory SQLite"):
        await service.restore_full_backup(
            "mygarage-full-mem.tar.gz", db_session, create_safety=False
        )

    assert not (service.data_dir / "mygarage.db").exists()
    assert (service.data_dir / "photos" / "old.jpg").read_bytes() == b"old photo"
    assert not (service.data_dir / ".restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("member", ["photos/new.jpg", "mygarage.pgdump"])
async def test_an_archive_without_a_sqlite_database_is_refused(
    tmp_path: Path, member: str, db_session: AsyncSession
) -> None:
    """A full restore restores the database; an archive without mygarage.db isn't one for SQLite.

    A photos-only or PostgreSQL archive emptied the live folders, kept the old database, and
    (pgdump) dropped a stray dump beside it.
    """
    db_path = tmp_path / "garage.db"
    _write_one_row_db(db_path, 7, "live")
    service = _service(tmp_path, db_path)
    (service.data_dir / "photos" / "old.jpg").write_bytes(b"old photo")
    _write_archive(service, "mygarage-full-nodb.tar.gz", None, {member: b"payload"})
    before = _live_state(service, db_path)

    with pytest.raises(ValueError, match="no SQLite database"):
        await service.restore_full_backup(
            "mygarage-full-nodb.tar.gz", db_session, create_safety=False
        )

    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending").exists()
    assert not (tmp_path / "mygarage.pgdump").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_name_outside_the_backup_folder_is_not_restored(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """The name is a file in the backup folder, as download and delete take it.

    `../` reached past it: a valid archive one folder up was staged. Mutant: build the
    path from the raw name again.
    """
    service, _ = _live_and_archive(tmp_path)
    shutil.copyfile(service.backup_dir / STAGED, tmp_path / "outside.tar.gz")

    with pytest.raises(FileNotFoundError):
        await service.restore_full_backup("../outside.tar.gz", db_session, create_safety=False)

    assert not (service.data_dir / ".restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_second_restore_replaces_the_first(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """Restoring again before the restart stages the new backup alone.

    A guard; mutant: skip the discard at the start of staging (the first backup's photo
    stays staged beside the second's).
    """
    db_path = tmp_path / "garage.db"
    _write_one_row_db(db_path, 7, "live")
    service = _service(tmp_path, db_path)
    first, second = tmp_path / "first.db", tmp_path / "second.db"
    _write_one_row_db(first, 1, "first")
    _write_one_row_db(second, 2, "second")
    _write_archive(service, "mygarage-full-first.tar.gz", first, {"photos/a.jpg": b"a"})
    _write_archive(service, "mygarage-full-second.tar.gz", second, {"photos/b.jpg": b"b"})

    await service.restore_full_backup("mygarage-full-first.tar.gz", db_session, create_safety=False)
    await service.restore_full_backup(
        "mygarage-full-second.tar.gz", db_session, create_safety=False
    )

    pending = Path(f"{db_path}.restore-pending")
    staging = service.data_dir / ".restore-pending"
    assert pending.exists(), "nothing was staged"
    assert _read_rows(pending) == [(2, "second")]
    assert sorted(p.name for p in (staging / "photos").iterdir()) == ["b.jpg"]
    assert _manifest(service)["source_backup"] == "mygarage-full-second.tar.gz"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_staging_runs_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """The tar, gzip and SQLite work runs in a thread, so the app keeps answering meanwhile.

    The check is held until the loop has seen it in progress. A guard; mutant: call the
    staging directly instead of through asyncio.to_thread (the loop only gets back once the
    staging is over, after the 2-second hold).
    """
    service, _ = _live_and_archive(tmp_path)
    in_check, release, done = threading.Event(), threading.Event(), threading.Event()
    real_check = BackupService._fold_and_check

    def _held_check(database: Path) -> None:
        in_check.set()
        release.wait(timeout=2)
        real_check(database)
        done.set()

    monkeypatch.setattr(BackupService, "_fold_and_check", staticmethod(_held_check))
    seen: list[bool] = []

    async def _the_loop_meanwhile() -> None:
        for _ in range(200):
            if in_check.is_set():
                break
            await asyncio.sleep(0.01)
        seen.append(in_check.is_set() and not done.is_set())
        release.set()

    await asyncio.gather(
        service.restore_full_backup(STAGED, db_session, create_safety=False), _the_loop_meanwhile()
    )

    assert seen == [True], "the event loop was blocked while the restore staged"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_restores_at_once_stage_one_after_the_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    init_test_db: None,
) -> None:
    """Two restores started together stage one at a time and leave one whole staging.

    A guard; mutant: drop the restore lock around the staging (both threads are inside the
    check at once, or one discards the other's half-built staging).
    """
    service, db_path = _live_and_archive(tmp_path)
    second = tmp_path / "second.db"
    _write_one_row_db(second, 2, "second")
    _write_archive(service, "mygarage-full-second.tar.gz", second, {"photos/b.jpg": b"b"})
    inside = 0
    most = 0
    count_lock = threading.Lock()
    real_check = BackupService._fold_and_check

    def _counting_check(database: Path) -> None:
        nonlocal inside, most
        with count_lock:
            inside += 1
            most = max(most, inside)
        time.sleep(0.2)
        with count_lock:
            inside -= 1
        real_check(database)

    monkeypatch.setattr(BackupService, "_fold_and_check", staticmethod(_counting_check))

    # A session each: one session can't run two statements at once.
    async with test_sessionmaker() as first_db, test_sessionmaker() as second_db:
        await asyncio.gather(
            service.restore_full_backup(STAGED, first_db, create_safety=False),
            service.restore_full_backup(
                "mygarage-full-second.tar.gz", second_db, create_safety=False
            ),
        )

    assert most == 1, "two stagings ran at once"
    expected = {
        STAGED: ([(99, "restored")], ["new.jpg"]),
        "mygarage-full-second.tar.gz": ([(2, "second")], ["b.jpg"]),
    }[str(_manifest(service)["source_backup"])]
    assert _read_rows(Path(f"{db_path}.restore-pending")) == expected[0]
    staged_photos = service.data_dir / ".restore-pending" / "photos"
    assert sorted(p.name for p in staged_photos.iterdir()) == expected[1]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_drops_the_staging_and_keeps_the_live_data(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    """Cancel before the restart: nothing is staged any more and nothing live changed.

    A second cancel finds nothing.
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    before = _live_state(service, db_path)
    assert service.pending_restore() == {
        "source_backup": STAGED,
        "staged_at": _manifest(service)["staged_at"],
    }

    await service.cancel_pending_restore()

    assert service.pending_restore() is None
    assert not (service.data_dir / ".restore-pending").exists()
    assert not Path(f"{db_path}.restore-pending").exists()
    assert _live_state(service, db_path) == before
    assert service.apply_pending_restore() is None
    with pytest.raises(FileNotFoundError, match="No restore is staged"):
        await service.cancel_pending_restore()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("killed_after", [1, 2], ids=["manifest_gone", "staged_database_gone"])
async def test_a_cancel_cut_short_still_reads_as_no_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, killed_after: int, db_session: AsyncSession
) -> None:
    """A cancel killed partway leaves no restore for the next start: the manifest went first.

    A guard; mutant: remove the manifest after the rest (killed after its first change, the
    cancel leaves a manifest, and the next start applies what's left of a cancelled restore).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    before = _live_state(service, db_path)

    with monkeypatch.context() as patched:
        _kill_after_changes(patched, killed_after)
        with pytest.raises(_KilledError):
            await service.cancel_pending_restore()

    assert service.pending_restore() is None
    assert service.apply_pending_restore() is None
    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_media_folder_on_another_filesystem_is_refused_before_anything_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """The swap renames folders, which can't cross filesystems, so that layout is refused at the request.

    Refused before the safety archive and the discard, so an earlier staging stays. A guard;
    mutant: drop the check (the start would then stop on EXDEV mid-swap).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    photos = service.data_dir / "photos"
    real_stat = os.stat

    def _photos_elsewhere(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        st = real_stat(path, *args, **kwargs)
        if isinstance(path, (str, Path)) and Path(path) == photos:
            fields = (
                st.st_mode,
                st.st_ino,
                st.st_dev + 1,
                st.st_nlink,
                st.st_uid,
                st.st_gid,
                st.st_size,
                int(st.st_atime),
                int(st.st_mtime),
                int(st.st_ctime),
            )
            return os.stat_result(fields)
        return st

    before = _live_state(service, db_path)
    with monkeypatch.context() as patched:
        patched.setattr(os, "stat", _photos_elsewhere)
        with pytest.raises(ValueError, match="different filesystem"):
            await service.restore_full_backup(STAGED, db_session, create_safety=True)

    assert _live_state(service, db_path) == before
    assert (service.pending_restore() or {}).get("source_backup") == STAGED
    assert not list(service.backup_dir.glob("mygarage-full-safety-2*.tar.gz"))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_swap_that_keeps_failing_stops_the_start_with_the_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """An OS error partway through the swap (photos on another filesystem) stops the start, with the way out.

    Each later start meets it again and changes nothing, Cancel is refused, and once the
    cause is gone the next start finishes. A guard; mutant: let the OSError through (a bare
    traceback at every start, and no way out in the log).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    staging_module = importlib.import_module("app.services.restore_staging")
    real_replace = staging_module._replace
    live_photos = service.data_dir / "photos"

    def _photos_elsewhere(src: Path, dst: Path) -> None:
        if src == live_photos:
            raise OSError(errno.EXDEV, "Invalid cross-device link", str(src))
        real_replace(src, dst)

    with monkeypatch.context() as patched:
        patched.setattr(staging_module, "_replace", _photos_elsewhere)
        with pytest.raises(RuntimeError) as first:
            service.apply_pending_restore()
        kept = _every_file(tmp_path)
        with pytest.raises(RuntimeError):
            service.apply_pending_restore()
        assert _every_file(tmp_path) == kept, "a later start changed files"
        with pytest.raises(RuntimeError, match="interrupted while it was being applied"):
            await service.cancel_pending_restore()

    text = str(first.value)
    assert "Invalid cross-device link" in text
    assert "To finish it, fix that and start MyGarage again" in text
    assert "MYGARAGE_MAINTENANCE_MODE=1" in text
    assert (live_photos / "old.jpg").exists(), "the live photos moved"
    assert service.apply_pending_restore() == STAGED
    assert sorted(p.name for p in live_photos.iterdir()) == ["new.jpg"]
    assert _read_rows(db_path) == [(99, "restored")]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["disk_full", "unreadable_database", "bad_archive_name"])
async def test_a_start_that_cant_write_its_safety_archive_stops_before_touching_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str, db_session: AsyncSession
) -> None:
    """The pre-restore archive can't be written: the start stops, nothing live changed, and the log says how to cancel.

    bad_archive_name is a hand-edited manifest whose name validate_filename refuses. A guard;
    mutants: let the error through (a bare traceback at every start), or leave ValueError out
    of the catch (bad_archive_name).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    before = _live_state(service, db_path)
    manifest_path = service.data_dir / ".restore-pending" / "manifest.json"
    manifest: dict[str, Any] = {}

    def _disk_full(self: BackupService, archive: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    def _unreadable(self: BackupService, output_path: Path) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    with monkeypatch.context() as patched:
        if cause == "disk_full":
            patched.setattr(BackupService, "_write_safety_archive", _disk_full)
        elif cause == "unreadable_database":
            patched.setattr(BackupService, "_snapshot_sqlite", _unreadable)
        else:
            manifest = json.loads(manifest_path.read_text())
            manifest["good_name"] = manifest["prerestore_backup"]
            manifest["prerestore_backup"] = "../outside.txt"
            manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(RuntimeError) as refused:
            service.apply_pending_restore()

    text = str(refused.value)
    assert "Nothing live was touched" in text
    assert "To cancel it instead, delete" in text
    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending" / "applying").exists()
    if manifest:
        manifest["prerestore_backup"] = manifest.pop("good_name")
        manifest_path.write_text(json.dumps(manifest))
    assert service.apply_pending_restore() == STAGED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_missing_pre_restore_archive_stops_a_half_applied_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Half swapped, and the pre-restore archive is gone: the start refuses rather than write it again.

    Written now, it would file the half-swapped data as "before the restore". A guard;
    mutant: write the archive whenever the start reaches it, marker or not.
    """
    service, _ = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, 5)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()
    (archive,) = _prerestore_archives(service)
    archive.unlink()
    before = _every_file(tmp_path)

    with pytest.raises(RuntimeError, match="pre-restore safety archive .* is missing"):
        service.apply_pending_restore()

    assert _every_file(tmp_path) == before
    assert _prerestore_archives(service) == []


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("killed_after", [3, 4])
async def test_a_marker_deleted_by_hand_keeps_the_pre_restore_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, killed_after: int, db_session: AsyncSession
) -> None:
    """Killed after the live -wal (3) or -shm (4) went, then the marker deleted by hand: the archive is kept.

    It is the only copy of the rows that lived in that -wal. The next start finds no marker
    and every staged piece in place, so it takes the first-start path, and the writer must
    leave the archive alone. A guard; mutant: drop the writer's existence check (the archive
    is rewritten from a database whose WAL rows are gone).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, killed_after)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()
    (archive,) = _prerestore_archives(service)
    kept = archive.read_bytes()
    (service.data_dir / ".restore-pending" / "applying").unlink()

    assert service.apply_pending_restore() == STAGED

    assert archive.read_bytes() == kept, "the pre-restore archive was rewritten"
    assert _archived_rows(archive, tmp_path / "check") == [(1, "checkpointed"), (2, "wal-only")]
    assert _read_rows(db_path) == [(99, "restored")]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("killed_after", [6, 10])
async def test_a_swap_begun_and_marker_deleted_by_hand_stops_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, killed_after: int, db_session: AsyncSession
) -> None:
    """Killed after a live folder was set aside, then the marker deleted by hand: the start refuses.

    The folders in previous/ show the swap had begun, so this is a half-applied restore, not a
    broken staging, and serving it would mix old and new data. A guard; mutant: drop the
    previous/ check (the start logs a broken staging and serves the half-swapped data).
    """
    service, _ = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, killed_after)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()
    (service.data_dir / ".restore-pending" / "applying").unlink()
    before = _every_file(tmp_path)

    with pytest.raises(RuntimeError, match="its swap had begun") as refused:
        service.apply_pending_restore()

    assert _every_file(tmp_path) == before, "the refused start changed files"
    assert _prerestore_archives(service)[0].name in str(refused.value)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("killed_after", [6, 10])
@pytest.mark.parametrize("manifest", ["deleted", "unreadable"])
async def test_a_swap_begun_with_marker_and_manifest_gone_stops_the_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    killed_after: int,
    manifest: str,
    db_session: AsyncSession,
) -> None:
    """Killed mid-swap, then the marker deleted by hand and the manifest gone or broken: the start refuses.

    Folders in previous/ and folders still staged mean half swapped, whatever the manifest says.
    It used to throw the staging away, previous/ and all, or log it as a broken staging and
    serve the half-swapped data. With both files gone the steps name the database MyGarage opens
    now and the archive by its pattern. Mutant: call it the cleanup of an applied restore as
    soon as previous/ is there (drop the nothing-staged check).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, killed_after)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()
    staging = service.data_dir / ".restore-pending"
    (staging / "applying").unlink()
    if manifest == "deleted":
        (staging / "manifest.json").unlink()
    else:
        (staging / "manifest.json").write_text("{ cut off")
    before = _every_file(tmp_path)

    with pytest.raises(RuntimeError, match="its swap had begun") as refused:
        service.apply_pending_restore()

    assert _every_file(tmp_path) == before, "the refused start changed files"
    assert (staging / "previous" / "photos" / "old.jpg").exists(), "the set-aside photos went"
    assert (staging / "attachments").exists(), "a staged folder went"
    text = str(refused.value)
    assert "the mygarage-full-safety-prerestore archive" in text
    assert f"{db_path.resolve()}.restore-pending" in text
    assert "MYGARAGE_MAINTENANCE_MODE=1" in text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_start_killed_in_the_cleanup_writes_no_new_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Killed after the marker went (change 12), and the archive then deleted: the next start only cleans up.

    Everything is swapped, so a new "pre-restore" archive would hold the restored data. A
    guard; mutant: drop the cleanup-only path (the start takes the first-start path and writes
    one).
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    with monkeypatch.context() as patched:
        _kill_after_changes(patched, 12)
        with pytest.raises(_KilledError):
            service.apply_pending_restore()
    for archive in _prerestore_archives(service):
        archive.unlink()

    assert service.apply_pending_restore() == STAGED

    assert _prerestore_archives(service) == []
    assert not (service.data_dir / ".restore-pending").exists()
    assert _read_rows(db_path) == [(99, "restored")]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_cleanup_that_fails_says_the_restore_is_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """Everything is swapped and only removing the staging fails: the start stops and says the restore is in place.

    The next start finds no manifest and clears the rest. A guard; mutant: let the OSError
    through.
    """
    service, db_path = _live_and_archive(tmp_path)
    await service.restore_full_backup(STAGED, db_session, create_safety=False)
    staging_module = importlib.import_module("app.services.restore_staging")

    def _not_allowed(path: Path) -> None:
        raise PermissionError(errno.EACCES, "Permission denied", str(path))

    with monkeypatch.context() as patched:
        patched.setattr(staging_module, "_remove_tree", _not_allowed)
        with pytest.raises(RuntimeError, match="is in place"):
            service.apply_pending_restore()

    assert _read_rows(db_path) == [(99, "restored")]
    assert service.apply_pending_restore() is None
    assert not (service.data_dir / ".restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_unreadable_live_database_is_refused_when_the_restore_is_asked_for(
    tmp_path: Path,
    db_session: AsyncSession,
) -> None:
    """The request's safety archive is the gate: a live database it can't read is a 400 now.

    Not a 500 now, and not a start stopped later. RED: sqlite3.DatabaseError escaped. Mutant:
    drop the conversion.
    """
    service, db_path = _live_and_archive(tmp_path)
    for suffix in ("-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink()
    db_path.write_bytes(b"not a database " * 600)

    with pytest.raises(ValueError, match="current database can't be read"):
        await service.restore_full_backup(STAGED, db_session, create_safety=True)

    assert not (service.data_dir / ".restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["truncated", "not_gzip"])
async def test_a_backup_that_isnt_a_readable_archive_is_refused(
    tmp_path: Path, damage: str, db_session: AsyncSession
) -> None:
    """A truncated or non-gzip file is a 400 with a plain message.

    RED: tarfile's EOFError and ReadError are neither OSError nor ValueError, so they escaped
    as a 500. Mutant: drop the conversion.
    """
    service, db_path = _live_and_archive(tmp_path)
    good = (service.backup_dir / STAGED).read_bytes()
    blob = good[: len(good) // 2] if damage == "truncated" else b"not a gzip file " * 100
    (service.backup_dir / "mygarage-full-broken.tar.gz").write_bytes(blob)
    before = _live_state(service, db_path)

    with pytest.raises(ValueError, match="can't be read as a tar.gz archive"):
        await service.restore_full_backup(
            "mygarage-full-broken.tar.gz", db_session, create_safety=False
        )

    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending").exists()


_Member = tuple[str, bytes, str]  # name, tar type, link target ("" for a file or folder)

# Each case: the links a media folder can hold that lead to no file in the archive, plus what
# else the case needs in the archive.
_MEDIA_LINKS_TO_NO_FILE: dict[str, tuple[list[_Member], list[_Member]]] = {
    "dangling_hardlink": ([("photos/x.jpg", tarfile.LNKTYPE, "photos/missing.jpg")], []),
    "dangling_symlink": ([("photos/x.jpg", tarfile.SYMTYPE, "missing.jpg")], []),
    "absolute_symlink": ([("photos/x.jpg", tarfile.SYMTYPE, "/mnt/media/x.jpg")], []),
    "symlink_loop": (
        [("photos/a.jpg", tarfile.SYMTYPE, "b.jpg"), ("photos/b.jpg", tarfile.SYMTYPE, "a.jpg")],
        [],
    ),
    "folder_symlink": (
        [("photos/album-link", tarfile.SYMTYPE, "album")],
        [("photos/album", tarfile.DIRTYPE, ""), ("photos/album/a.jpg", tarfile.REGTYPE, "")],
    ),
}


def _add_members(tar: tarfile.TarFile, members: list[_Member]) -> None:
    """Add hand-made members: links and folders as they are, files with their own name as content."""
    for name, kind, target in members:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = target
        data = name.encode() if kind == tarfile.REGTYPE else b""
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data) if data else None)


def _files_under(folder: Path) -> list[str]:
    """Every file and link under a folder, by path relative to it."""
    return sorted(
        str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file() or p.is_symlink()
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(_MEDIA_LINKS_TO_NO_FILE))
async def test_a_media_link_to_no_file_is_skipped_and_the_rest_restores(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, case: str, db_session: AsyncSession
) -> None:
    """A photo that's a link to no file in the archive is left out with a WARNING; the rest restores.

    tarfile reads a link through its target: KeyError if the target isn't in the archive,
    RecursionError if the links loop, nothing at all if it's a folder. The backup writer keeps a
    media symlink as a link member, and the restore never makes links, so failing on one made
    the app's own backup unrestorable. RED: the restore failed. Mutants: let KeyError or
    RecursionError through, or skip without the WARNING.
    """
    links, extra = _MEDIA_LINKS_TO_NO_FILE[case]
    service, db_path = _live_and_archive(tmp_path)
    with tarfile.open(service.backup_dir / "mygarage-full-links.tar.gz", "w:gz") as tar:
        tar.add(tmp_path / "source.db", arcname="mygarage.db")
        _add_members(tar, [("photos/new.jpg", tarfile.REGTYPE, ""), *extra, *links])

    with caplog.at_level(logging.WARNING, logger="app.services.backup_service"):
        await service.restore_full_backup(
            "mygarage-full-links.tar.gz", db_session, create_safety=False
        )

    kept = [
        "new.jpg",
        *(name.removeprefix("photos/") for name, kind, _ in extra if kind == tarfile.REGTYPE),
    ]
    staged = service.data_dir / ".restore-pending" / "photos"
    assert _files_under(staged) == sorted(kept)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == len(links), warnings
    for (name, _, target), message in zip(links, warnings, strict=True):
        assert name in message and target in message, message

    assert service.apply_pending_restore() == "mygarage-full-links.tar.gz"
    assert _files_under(service.data_dir / "photos") == sorted(kept)
    assert _read_rows(db_path) == [(99, "restored")]


_DATABASE_LINKS_TO_NO_FILE: dict[str, list[_Member]] = {
    "dangling": [("mygarage.db", tarfile.SYMTYPE, "missing.db")],
    "dangling_with_a_wal": [
        ("mygarage.db", tarfile.SYMTYPE, "missing.db"),
        ("mygarage.db-wal", tarfile.REGTYPE, ""),
    ],
    "loop": [("mygarage.db", tarfile.SYMTYPE, "mygarage.db")],
}


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(_DATABASE_LINKS_TO_NO_FILE))
async def test_a_database_member_that_links_to_no_file_is_refused(
    tmp_path: Path, case: str, db_session: AsyncSession
) -> None:
    """mygarage.db as a link to no file is still a 400, and nothing is staged: only media links are skipped.

    A guard; mutants: skip a link to no file for the database members too (with a -wal member
    beside it, SQLite would then make an empty database out of nothing, and the restore would
    stage that), or leave KeyError or RecursionError out of the conversion.
    """
    service, db_path = _live_and_archive(tmp_path)
    with tarfile.open(service.backup_dir / "mygarage-full-links.tar.gz", "w:gz") as tar:
        _add_members(tar, _DATABASE_LINKS_TO_NO_FILE[case])
    before = _live_state(service, db_path)

    with pytest.raises(ValueError, match="can't be read as a tar.gz archive"):
        await service.restore_full_backup(
            "mygarage-full-links.tar.gz", db_session, create_safety=False
        )

    assert _live_state(service, db_path) == before
    assert not (service.data_dir / ".restore-pending").exists()
    assert not Path(f"{db_path}.restore-pending").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_apps_own_backup_of_linked_photos_restores(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, db_session: AsyncSession
) -> None:
    """The app's own backup of a photos folder holding links stages and applies.

    tar.add keeps every link as a link member. A symlink or hard link to a photo in the backup
    comes back as a copy of that photo. A symlink to a file outside the backup, or to a folder,
    is left out with a WARNING; the folder's own files come back under its real name. RED: the
    outside symlink failed the whole restore. A guard too; mutant: refuse every link member.
    """
    db_path = tmp_path / "garage.db"
    _write_one_row_db(db_path, 7, "live")
    service = _service(tmp_path, db_path)
    photos = service.data_dir / "photos"
    (photos / "car.jpg").write_bytes(b"car photo")
    (photos / "alias.jpg").symlink_to("car.jpg")
    os.link(photos / "car.jpg", photos / "twin.jpg")
    (tmp_path / "outside.jpg").write_bytes(b"outside photo")
    (photos / "elsewhere.jpg").symlink_to(tmp_path / "outside.jpg")
    (photos / "album").mkdir()
    (photos / "album" / "a.jpg").write_bytes(b"album photo")
    (photos / "album-link").symlink_to("album")
    meta = await service.create_full_backup(db_session)
    with tarfile.open(service.backup_dir / meta["filename"], "r:gz") as tar:
        kinds = {
            m.name: (m.issym(), m.islnk()) for m in tar.getmembers() if m.name.startswith("photos/")
        }
    assert kinds == {
        "photos/album": (False, False),
        "photos/album/a.jpg": (False, False),
        "photos/album-link": (True, False),
        "photos/alias.jpg": (True, False),
        "photos/car.jpg": (False, False),
        "photos/elsewhere.jpg": (True, False),
        "photos/twin.jpg": (False, True),
    }, "the backup doesn't hold the link members this test is about"
    shutil.rmtree(photos)
    photos.mkdir()
    (photos / "other.jpg").write_bytes(b"other photo")

    with caplog.at_level(logging.WARNING, logger="app.services.backup_service"):
        await service.restore_full_backup(meta["filename"], db_session, create_safety=False)
    assert service.apply_pending_restore() == meta["filename"]

    restored = {
        str(p.relative_to(photos)): p.read_bytes() for p in photos.rglob("*") if p.is_file()
    }
    assert restored == {
        "album/a.jpg": b"album photo",
        "alias.jpg": b"car photo",
        "car.jpg": b"car photo",
        "twin.jpg": b"car photo",
    }
    assert not [p for p in photos.rglob("*") if p.is_symlink()], "the restore made a link"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2, warnings
    for skipped in ("photos/album-link", "photos/elsewhere.jpg"):
        assert [m for m in warnings if skipped in m], (skipped, warnings)
