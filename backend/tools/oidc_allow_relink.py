"""Allow a one-time SSO relink for a MyGarage account, from the command line.

When a user's identity provider account is re-created (an IdP reinstall or
swap, or the user removed and added back), its OIDC subject changes. MyGarage
then refuses that user's SSO login instead of relinking the account on an email
or username match. An admin allows the relink from the user's card in Family
Management; this tool does the same for the operator when the locked-out user is
the only admin.

For the next --minutes (default and maximum 30), the first SSO login whose email
or username matches the account links it without asking for a password, then
the window closes. --minutes 0 cancels an open one. Each run writes the same
audit row the admin page does.

Run it inside the container:

    docker exec -w /app mygarage python tools/oidc_allow_relink.py --username X
    docker exec -w /app mygarage python tools/oidc_allow_relink.py --username X --minutes 0
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import DBAPIError

sys.path.insert(0, ".")

from app.constants.oidc import SSO_RELINK_WINDOW_MINUTES  # noqa: E402
from app.database import Base  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.datetime_utils import utc_now  # noqa: E402
from tools._tool_db import create_tool_engine  # noqa: E402

# Core tables rather than the ORM classes: a standalone ORM query would need
# every model imported first so the mappers can configure.
_USERS = Base.metadata.tables[User.__tablename__]
_AUDIT_LOGS = Base.metadata.tables[AuditLog.__tablename__]


def allow_relink(conn: Connection, username: str, minutes: int) -> datetime | None:
    """Open (or with 0 minutes, cancel) the account's SSO relink and audit it.

    The caller owns the transaction, so the change and its audit row commit
    together.

    Args:
        conn: A connection inside a transaction
        username: The MyGarage username
        minutes: How long the relink stays open, 0 to cancel

    Returns:
        When the relink closes, or None when it was cancelled.

    Raises:
        ValueError: ``minutes`` is outside 0..SSO_RELINK_WINDOW_MINUTES.
        LookupError: No account has this username.
    """
    if not 0 <= minutes <= SSO_RELINK_WINDOW_MINUTES:
        raise ValueError(f"minutes must be 0 to {SSO_RELINK_WINDOW_MINUTES}, got {minutes}")

    user_id = conn.execute(
        select(_USERS.c.id).where(_USERS.c.username == username)
    ).scalar_one_or_none()
    if user_id is None:
        raise LookupError(f"No user named {username!r}.")

    now = utc_now()
    until = now + timedelta(minutes=minutes) if minutes else None
    conn.execute(
        update(_USERS).where(_USERS.c.id == user_id).values(oidc_relink_until=until, updated_at=now)
    )
    conn.execute(
        insert(_AUDIT_LOGS).values(
            timestamp=now,
            user_id=None,
            username="system",
            action="oidc_relink_allowed" if until else "oidc_relink_revoked",
            resource_type="user",
            resource_id=str(user_id),
            details={
                "username": username,
                "until": until.isoformat() if until else None,
                "via": "cli",
            },
            success=1,
        )
    )
    return until


def _minutes(value: str) -> int:
    """Parse --minutes, refusing anything outside the window."""
    try:
        minutes = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {value!r}") from None
    if not 0 <= minutes <= SSO_RELINK_WINDOW_MINUTES:
        raise argparse.ArgumentTypeError(f"must be 0 to {SSO_RELINK_WINDOW_MINUTES}, got {minutes}")
    return minutes


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--username", required=True, help="The MyGarage username to relink.")
    parser.add_argument(
        "--minutes",
        type=_minutes,
        default=SSO_RELINK_WINDOW_MINUTES,
        help=(
            f"How long the relink stays open, 0 to {SSO_RELINK_WINDOW_MINUTES} "
            f"(default {SSO_RELINK_WINDOW_MINUTES}). 0 cancels an open one."
        ),
    )
    parser.add_argument(
        "--db",
        help=(
            "Database to operate on: a path to mygarage.db, or a full SQLAlchemy URL "
            "(postgresql+asyncpg://...). Omit to use the instance's configured database, "
            "which is the right choice when running inside the container."
        ),
    )
    return parser.parse_args(argv)


def _first_line(exc: BaseException) -> str:
    """An error's message cut to one line, for the operator's terminal."""
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def main(argv: list[str] | None = None) -> int:
    """Allow or cancel an SSO relink from the command line."""
    args = _parse_args(argv)
    try:
        engine = create_tool_engine(args.db)
    except ValueError as exc:
        # A --db dialect the tools don't support, or no database configured.
        print(exc, file=sys.stderr)
        return 1
    except DBAPIError as exc:
        # On PG the factory reads schema_migrations, so an unreachable server fails here.
        print(f"Database error: {_first_line(exc.orig or exc)}", file=sys.stderr)
        return 1
    try:
        with engine.begin() as conn:
            until = allow_relink(conn, args.username, args.minutes)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    except DBAPIError as exc:
        # Can't reach the database, or its schema is from before migration 123
        # (SQLite calls that OperationalError, psycopg2 ProgrammingError).
        print(f"Database error: {_first_line(exc.orig or exc)}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    if until is None:
        print(f"SSO relink cancelled for {args.username}.")
    else:
        print(
            f"SSO relink allowed for {args.username} until {until:%Y-%m-%d %H:%M} UTC. "
            "Their next SSO login links the account."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
