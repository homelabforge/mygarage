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

import sqlite3
import tarfile
from pathlib import Path

import pytest

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


def _service(tmp_path: Path, db_path: Path) -> BackupService:
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_backup_db_member_is_self_contained(tmp_path: Path) -> None:
    """F2: the archived mygarage.db must contain ALL committed rows on its own.

    With the raw file-copy approach, row 2 (committed, un-checkpointed)
    exists only in the -wal sidecar and is missing from the db member.
    """
    db_path = tmp_path / "mygarage.db"
    writer = _make_wal_db_with_pending_frames(db_path)
    try:
        service = _service(tmp_path, db_path)
        meta = await service.create_full_backup()
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restore_removes_stale_wal_sidecars(tmp_path: Path) -> None:
    """F2 restore hygiene: stale live -wal/-shm must not survive a restore.

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

    await service.restore_full_backup("mygarage-full-restoretest.tar.gz", create_safety=False)

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
