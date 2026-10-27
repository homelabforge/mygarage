"""The operator's way to allow an SSO relink when the locked-out user is the only admin.

`tools/oidc_allow_relink.py` does what the admin card's relink action does:
it opens (or with `--minutes 0` closes) the account's relink window and writes
the same audit row. It runs over its own sync connection, so every assertion
re-reads the row through the test's session with `refresh()`.
"""

import datetime as dt
import sqlite3
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User
from app.utils.datetime_utils import utc_now
from app.utils.db_url import to_sync_url
from app.utils.pg_session import create_utc_engine
from tools.oidc_allow_relink import allow_relink, main

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_ACTIONS = ("oidc_relink_allowed", "oidc_relink_revoked")


def _db_url() -> str:
    """The suite's own database, as the tool's --db takes it."""
    from tests.conftest import TEST_DATABASE_URL

    return to_sync_url(TEST_DATABASE_URL)


@pytest_asyncio.fixture
async def account(db_session: AsyncSession) -> AsyncIterator[User]:
    """An SSO-only account of this test's own, removed with its relink audit rows afterwards."""
    tag = uuid.uuid4().hex[:10]
    user = User(
        username=f"cli_relink_{tag}",
        email=f"cli_relink_{tag}@example.com",
        hashed_password=None,
        is_active=True,
        is_admin=True,
        oidc_subject=f"sub-{tag}",
        oidc_provider="Rauthy",
        auth_method="oidc",
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id
    yield user
    await db_session.rollback()
    await db_session.execute(
        delete(AuditLog).where(AuditLog.action.in_(_ACTIONS), AuditLog.resource_id == str(user_id))
    )
    await db_session.execute(delete(User).where(User.id == user_id))
    await db_session.commit()


async def _audit_rows(db_session: AsyncSession, action: str, user_id: int) -> list[AuditLog]:
    rows = await db_session.execute(
        select(AuditLog).where(AuditLog.action == action, AuditLog.resource_id == str(user_id))
    )
    return list(rows.scalars())


class TestAllowRelink:
    """The named function, called straight against the suite's database."""

    async def test_arms_by_username_for_the_minutes_given(
        self, db_session: AsyncSession, account: User
    ):
        before = utc_now()
        engine = create_utc_engine(_db_url())
        try:
            with engine.begin() as conn:
                until = allow_relink(conn, account.username, 5)
        finally:
            engine.dispose()
        after = utc_now()

        await db_session.refresh(account)
        assert account.oidc_relink_until == until
        assert until is not None
        assert before + dt.timedelta(minutes=5) <= until <= after + dt.timedelta(minutes=5)

        rows = await _audit_rows(db_session, "oidc_relink_allowed", account.id)
        assert len(rows) == 1
        assert rows[0].user_id is None
        assert rows[0].resource_type == "user"
        assert rows[0].details is not None
        assert rows[0].details["username"] == account.username
        assert rows[0].details["via"] == "cli"

    async def test_an_unknown_username_raises_and_writes_nothing(self, db_session: AsyncSession):
        name = f"nobody_{uuid.uuid4().hex[:10]}"
        engine = create_utc_engine(_db_url())
        try:
            with pytest.raises(LookupError, match=name), engine.begin() as conn:
                allow_relink(conn, name, 30)
        finally:
            engine.dispose()

    @pytest.mark.parametrize("minutes", [-1, 31])
    async def test_minutes_outside_the_window_are_refused(
        self, db_session: AsyncSession, account: User, minutes: int
    ):
        engine = create_utc_engine(_db_url())
        try:
            with pytest.raises(ValueError), engine.begin() as conn:
                allow_relink(conn, account.username, minutes)
        finally:
            engine.dispose()
        await db_session.refresh(account)
        assert account.oidc_relink_until is None


class TestMain:
    """The command line, as the operator runs it."""

    async def test_arms_by_username_for_30_minutes_by_default(
        self, db_session: AsyncSession, account: User, capsys: pytest.CaptureFixture[str]
    ):
        before = utc_now()

        code = main(["--username", account.username, "--db", _db_url()])

        after = utc_now()
        assert code == 0
        await db_session.refresh(account)
        until = account.oidc_relink_until
        assert until is not None
        assert before + dt.timedelta(minutes=30) <= until <= after + dt.timedelta(minutes=30)
        assert account.username in capsys.readouterr().out
        assert len(await _audit_rows(db_session, "oidc_relink_allowed", account.id)) == 1

    async def test_minutes_0_disarms(
        self, db_session: AsyncSession, account: User, capsys: pytest.CaptureFixture[str]
    ):
        account.oidc_relink_until = utc_now() + dt.timedelta(minutes=20)
        await db_session.commit()

        code = main(["--username", account.username, "--minutes", "0", "--db", _db_url()])

        assert code == 0
        await db_session.refresh(account)
        assert account.oidc_relink_until is None
        assert len(await _audit_rows(db_session, "oidc_relink_revoked", account.id)) == 1

    async def test_an_unknown_username_exits_non_zero_with_a_message(
        self, db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
    ):
        name = f"nobody_{uuid.uuid4().hex[:10]}"

        code = main(["--username", name, "--db", _db_url()])

        assert code != 0
        assert name in capsys.readouterr().err

    @pytest.mark.parametrize("minutes", ["-1", "31", "ten"])
    async def test_minutes_outside_0_to_30_are_rejected(
        self,
        db_session: AsyncSession,
        account: User,
        capsys: pytest.CaptureFixture[str],
        minutes: str,
    ):
        with pytest.raises(SystemExit) as exited:
            main(["--username", account.username, "--minutes", minutes, "--db", _db_url()])

        assert exited.value.code == 2
        assert "--minutes" in capsys.readouterr().err
        await db_session.refresh(account)
        assert account.oidc_relink_until is None

    async def test_an_unsupported_db_dialect_is_one_line_and_exit_1(
        self, capsys: pytest.CaptureFixture[str]
    ):
        code = main(["--username", "anyone", "--db", "mysql://db.example/mygarage"])

        assert code == 1
        err = capsys.readouterr().err
        assert "unsupported database dialect 'mysql'" in err
        assert err.strip().count("\n") == 0, f"expected one line, got:\n{err}"

    async def test_a_schema_without_the_relink_column_is_one_line_and_exit_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        """A database from before migration 123, which added oidc_relink_until."""
        db_file = tmp_path / "pre_123.db"
        conn = sqlite3.connect(db_file)
        try:
            conn.execute(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50), "
                "updated_at DATETIME)"
            )
            conn.execute("INSERT INTO users (username) VALUES ('old_admin')")
            conn.commit()
        finally:
            conn.close()

        code = main(["--username", "old_admin", "--db", str(db_file)])

        assert code == 1
        err = capsys.readouterr().err
        assert "oidc_relink_until" in err
        assert err.strip().count("\n") == 0, f"expected one line, got:\n{err}"

    async def test_a_pg_schema_error_is_one_line_and_exit_1(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """psycopg2 reports a missing column as ProgrammingError, not OperationalError."""

        def _undefined_column(*_args: object, **_kwargs: object) -> None:
            raise ProgrammingError(
                "UPDATE users ...",
                {},
                Exception('column "oidc_relink_until" does not exist\nLINE 1: ...'),
            )

        monkeypatch.setattr("tools.oidc_allow_relink.allow_relink", _undefined_column)

        code = main(["--username", "old_admin", "--db", str(tmp_path / "any.db")])

        assert code == 1
        err = capsys.readouterr().err
        assert "oidc_relink_until" in err
        assert err.strip().count("\n") == 0, f"expected one line, got:\n{err}"
