"""Log lines that name a user can't be forged through the username.

Nothing constrains a username's alphabet in the database (an SSO claim lands
there as the IdP sent it), so a raw one carrying a newline writes a second,
made-up line into the log. Each line here runs it through sanitize_for_log.
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.models.vehicle_transfer import VehicleTransfer
from app.schemas.family import (
    FamilyMemberUpdateRequest,
    VehicleShareCreate,
    VehicleShareUpdate,
    VehicleTransferRequest,
)
from app.services.auth import authenticate_user
from app.services.family_dashboard_service import FamilyDashboardService
from app.services.sharing_service import SharingService
from app.services.transfer_service import TransferService

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

# argon2id of "testpassword123", as in tests/conftest.py.
_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
# 17 characters, a VIN's column width, with a newline in the middle.
_VIN = "LOGFORGE\nD1234567"
_VIN_LOGGED = "LOGFORGE\\nD1234567"


@dataclass
class _Named:
    """A user whose username tries to forge a log line, and how it should log."""

    user: User
    logged: str


@dataclass
class _Cast:
    admin: _Named
    member: _Named
    sso_only: _Named
    legacy: _Named


def _named(db_session: AsyncSession, tag: str, raw: str, logged: str, **fields: object) -> _Named:
    user = User(
        username=f"{tag}_{raw}",
        email=f"{tag}_{uuid.uuid4().hex[:8]}@example.com",
        is_active=True,
        **fields,
    )
    db_session.add(user)
    return _Named(user=user, logged=f"{tag}_{logged}")


async def _drop_rows(db_session: AsyncSession, user_ids: list[int]) -> None:
    await db_session.execute(delete(VehicleTransfer).where(VehicleTransfer.vehicle_vin == _VIN))
    await db_session.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin == _VIN))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == _VIN))
    if user_ids:
        await db_session.execute(delete(User).where(User.id.in_(user_ids)))
    await db_session.commit()


@pytest_asyncio.fixture
async def cast(db_session: AsyncSession) -> AsyncGenerator[_Cast]:
    """Four forged usernames and a vehicle with a forged VIN, all removed afterwards.

    The suite shares one database, so a killed run's VIN row is cleared first.
    """
    await _drop_rows(db_session, [])
    tag = uuid.uuid4().hex[:8]
    people = _Cast(
        admin=_named(
            db_session,
            f"adm{tag}",
            "x\nFORGED admin line",
            "x\\nFORGED admin line",
            hashed_password=_HASH,
            is_admin=True,
        ),
        member=_named(
            db_session,
            f"mem{tag}",
            "x\rFORGED member line",
            "x\\rFORGED member line",
            hashed_password=_HASH,
            is_admin=False,
        ),
        sso_only=_named(
            db_session,
            f"sso{tag}",
            "x\nFORGED sso line",
            "x\\nFORGED sso line",
            hashed_password=None,
            auth_method="oidc",
            oidc_subject=f"sub-{tag}",
            oidc_provider="idp",
            is_admin=False,
        ),
        legacy=_named(
            db_session,
            f"old{tag}",
            "x\nFORGED legacy line",
            "x\\nFORGED legacy line",
            hashed_password="$2b$12$not-a-real-bcrypt-hash-just-its-prefix",
            is_admin=False,
        ),
    )
    await db_session.commit()
    user_ids = [p.user.id for p in (people.admin, people.member, people.sso_only, people.legacy)]
    db_session.add(
        Vehicle(
            vin=_VIN,
            user_id=people.admin.user.id,
            nickname="Forged",
            vehicle_type="Car",
            year=2020,
            make="Toyota",
            model="Camry",
        )
    )
    await db_session.commit()
    yield people
    await db_session.rollback()
    await _drop_rows(db_session, user_ids)


async def _seed_share(db_session: AsyncSession, people: _Cast) -> int:
    share = VehicleShare(
        vehicle_vin=_VIN,
        user_id=people.member.user.id,
        permission="read",
        shared_by=people.admin.user.id,
    )
    db_session.add(share)
    await db_session.commit()
    return share.id


def _line(caplog: pytest.LogCaptureFixture, needle: str) -> str:
    """The one captured message containing ``needle``, which must have no raw CR or LF."""
    lines = [r.getMessage() for r in caplog.records if needle in r.getMessage()]
    assert len(lines) == 1, [r.getMessage() for r in caplog.records]
    assert "\n" not in lines[0] and "\r" not in lines[0], lines[0]
    return lines[0]


async def test_the_share_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    await SharingService(db_session).share_vehicle(
        _VIN, VehicleShareCreate(user_id=cast.member.user.id), cast.admin.user
    )

    line = _line(caplog, "shared with user")
    assert _VIN_LOGGED in line
    assert cast.member.logged in line
    assert cast.admin.logged in line


async def test_the_share_update_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    share_id = await _seed_share(db_session, cast)
    caplog.set_level(logging.INFO)
    await SharingService(db_session).update_share(
        share_id, VehicleShareUpdate(permission="write"), cast.admin.user
    )

    assert cast.admin.logged in _line(caplog, "permission updated")


async def test_the_share_revoke_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    share_id = await _seed_share(db_session, cast)
    caplog.set_level(logging.INFO)
    await SharingService(db_session).revoke_share(share_id, cast.admin.user)

    assert cast.admin.logged in _line(caplog, "revoked by user")


async def test_the_transfer_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    await TransferService(db_session).transfer_vehicle(
        _VIN, VehicleTransferRequest(to_user_id=cast.member.user.id), cast.admin.user
    )

    assert cast.admin.logged in _line(caplog, "transferred from user")


async def test_the_family_dashboard_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    await FamilyDashboardService(db_session).update_member_display(
        cast.member.user.id,
        FamilyMemberUpdateRequest(show_on_family_dashboard=True),
        cast.admin.user,
    )

    line = _line(caplog, "Updated family dashboard settings")
    assert cast.member.logged in line
    assert cast.admin.logged in line


async def test_the_sso_only_login_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    """The login username comes straight off the form."""
    caplog.set_level(logging.INFO)
    assert await authenticate_user(db_session, cast.sso_only.user.username, "whatever") is None

    assert cast.sso_only.logged in _line(caplog, "OIDC-only user")


async def test_the_rehash_line(
    db_session: AsyncSession, cast: _Cast, caplog: pytest.LogCaptureFixture
) -> None:
    """bcrypt isn't installed here, so the legacy hash's verify is stubbed to pass."""
    caplog.set_level(logging.INFO)
    with mock.patch("app.services.auth.verify_password", return_value=True):
        user = await authenticate_user(db_session, cast.legacy.user.username, "testpassword123")

    assert user is not None
    assert cast.legacy.logged in _line(caplog, "Auto-migrating password hash")
