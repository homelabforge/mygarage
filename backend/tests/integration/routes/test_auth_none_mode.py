"""Auth off (auth_mode=none) on the admin user routes and the family routes.

With auth off, `get_current_admin_user` and `require_auth` hand the route None.
Creating a user and resetting a password committed and then 500'd logging
`current_user.username`, and the family, sharing and transfer services 500'd on
`current_user.is_admin`. None now gets through their checks like an admin.
Creating a share and transferring a vehicle have to record a person (`shared_by`
and `transferred_by` can't be null), so those two 400 with `requires_sign_in`
and write nothing.

`TestSignedInStaysScoped` holds controls that pass on main by design. They pin
the owner and admin checks the None branch now sits in front of, where nothing
else would catch the check going missing. The admin-only routes 403 a non-admin
in the dependency, so those service checks get called directly.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.models.vehicle_transfer import VehicleTransfer
from app.routes.auth import limiter as auth_limiter
from app.schemas.family import FamilyMemberUpdateRequest
from app.services.auth import create_access_token, verify_password
from app.services.family_dashboard_service import FamilyDashboardService
from tests.integration.routes.conftest import AUTHZ_VIN

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# argon2id of "testpassword123", as in tests/conftest.py.
_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
_NEW_PASSWORD = "NewSecureP@ss1"


# --- Fixtures -----------------------------------------------------------------


@pytest_asyncio.fixture
async def made_users(db_session: AsyncSession) -> AsyncIterator[list[str]]:
    """Usernames a test creates, deleted afterwards."""
    names: list[str] = []
    yield names
    await db_session.rollback()
    await db_session.execute(delete(User).where(User.username.in_(names)))
    await db_session.commit()


@dataclass(frozen=True)
class _Made:
    """Plain values of a throwaway user. A rollback expires the ORM object, these don't."""

    id: int
    name: str

    @property
    def headers(self) -> dict[str, str]:
        """A bearer token of its own."""
        token = create_access_token(data={"sub": str(self.id), "username": self.name})
        return {"Authorization": f"Bearer {token}"}


async def _user(
    db_session: AsyncSession,
    made_users: list[str],
    *,
    admin: bool = False,
    on_dashboard: bool = False,
) -> _Made:
    """A throwaway active user."""
    name = f"noauth_{uuid.uuid4().hex[:10]}"
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=_HASH,
        is_active=True,
        is_admin=admin,
        show_on_family_dashboard=on_dashboard,
    )
    db_session.add(user)
    await db_session.commit()
    made_users.append(name)
    return _Made(user.id, name)


@pytest_asyncio.fixture
async def multi_user_on(db_session: AsyncSession) -> AsyncIterator[None]:
    """multi_user_enabled on for one test, then put back.

    A stored "false" stops create_user at its 403, before the write and the log line.
    """
    row = (
        await db_session.execute(select(Setting).where(Setting.key == "multi_user_enabled"))
    ).scalar_one_or_none()
    before = row.value if row is not None else None
    if row is None:
        db_session.add(Setting(key="multi_user_enabled", value="true"))
    else:
        row.value = "true"
    await db_session.commit()
    yield
    await db_session.rollback()
    row = (
        await db_session.execute(select(Setting).where(Setting.key == "multi_user_enabled"))
    ).scalar_one_or_none()
    if before is None:
        if row is not None:
            await db_session.delete(row)
    elif row is not None:
        row.value = before
    await db_session.commit()


@pytest.fixture
def fresh_auth_limits() -> Iterator[None]:
    """The password reset route is 5/minute per IP, and test_auth.py spends some of it."""
    auth_limiter.reset()
    yield
    auth_limiter.reset()


async def _share_id(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> int | None:
    """The committed share on the authz vehicle for `user_id`, read over a second session."""
    async with sessionmaker() as fresh:
        return (
            await fresh.execute(
                select(VehicleShare.id).where(
                    VehicleShare.vehicle_vin == AUTHZ_VIN, VehicleShare.user_id == user_id
                )
            )
        ).scalar_one_or_none()


async def _permission(sessionmaker: async_sessionmaker[AsyncSession], share_id: int) -> str | None:
    """The committed permission of a share, or None once it's gone."""
    async with sessionmaker() as fresh:
        share = await fresh.get(VehicleShare, share_id)
        return share.permission if share is not None else None


async def _counts(sessionmaker: async_sessionmaker[AsyncSession]) -> tuple[int, int, int | None]:
    """Committed shares and transfers on the authz vehicle, plus its owner."""
    async with sessionmaker() as fresh:
        shares = await fresh.scalar(
            select(func.count())
            .select_from(VehicleShare)
            .where(VehicleShare.vehicle_vin == AUTHZ_VIN)
        )
        transfers = await fresh.scalar(
            select(func.count())
            .select_from(VehicleTransfer)
            .where(VehicleTransfer.vehicle_vin == AUTHZ_VIN)
        )
        owner = await fresh.scalar(select(Vehicle.user_id).where(Vehicle.vin == AUTHZ_VIN))
        return shares or 0, transfers or 0, owner


# --- Admin user routes --------------------------------------------------------


class TestAdminUserRoutesWithAuthOff:
    async def test_create_user_is_201_and_the_row_exists(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
        multi_user_on: None,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        name = f"noauth_{uuid.uuid4().hex[:10]}"
        made_users.append(name)
        await set_auth_mode("none")

        response = await client.post(
            "/api/auth/users",
            json={"username": name, "email": f"{name}@example.com", "password": _NEW_PASSWORD},
        )

        assert response.status_code == 201, response.text
        assert response.json()["username"] == name
        async with test_sessionmaker() as fresh:
            stored = (
                await fresh.execute(select(User).where(User.username == name))
            ).scalar_one_or_none()
        assert stored is not None

    async def test_password_reset_is_204_and_the_new_password_works(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
        fresh_auth_limits: None,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        user_id = (await _user(db_session, made_users)).id
        await set_auth_mode("none")

        response = await client.put(
            f"/api/auth/users/{user_id}/password", json={"new_password": _NEW_PASSWORD}
        )

        assert response.status_code == 204, response.text
        async with test_sessionmaker() as fresh:
            stored = await fresh.get(User, user_id)
        assert stored is not None
        assert verify_password(_NEW_PASSWORD, stored.hashed_password)


# --- Family reads -------------------------------------------------------------


class TestFamilyReadsWithAuthOff:
    async def test_vehicle_shares_list_every_share(
        self,
        client: AsyncClient,
        owned_vehicle: Vehicle,
        reader_user: User,
        writer_user: User,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        expected = sorted([reader_user.id, writer_user.id])
        await set_auth_mode("none")

        response = await client.get(f"/api/family/vehicles/{AUTHZ_VIN}/shares")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert sorted(share["user"]["id"] for share in body["shares"]) == expected

    async def test_family_dashboard_is_200(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        made_users: list[str],
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        member_id = (await _user(db_session, made_users, on_dashboard=True)).id
        await set_auth_mode("none")

        response = await client.get("/api/family/dashboard")

        assert response.status_code == 200, response.text
        body = response.json()
        assert member_id in [member["id"] for member in body["members"]]
        assert body["total_members"] == len(body["members"])

    async def test_dashboard_members_is_200(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        made_users: list[str],
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        member_id = (await _user(db_session, made_users)).id
        await set_auth_mode("none")

        response = await client.get("/api/family/dashboard/members")

        assert response.status_code == 200, response.text
        assert member_id in [member["id"] for member in response.json()]

    async def test_eligible_recipients_is_200(
        self,
        client: AsyncClient,
        owned_vehicle: Vehicle,
        owner_user: User,
        unrelated_user: User,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        owner_id, unrelated_id = owner_user.id, unrelated_user.id
        await set_auth_mode("none")

        response = await client.get(f"/api/family/vehicles/{AUTHZ_VIN}/eligible-recipients")

        assert response.status_code == 200, response.text
        ids = [user["id"] for user in response.json()]
        assert unrelated_id in ids
        assert owner_id not in ids


# --- Family writes that don't need a person -----------------------------------


class TestFamilyWritesWithAuthOff:
    async def test_update_share_changes_the_permission(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        owned_vehicle: Vehicle,
        reader_user: User,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        share_id = await _share_id(test_sessionmaker, reader_user.id)
        assert share_id is not None
        await set_auth_mode("none")

        response = await client.put(f"/api/family/shares/{share_id}", json={"permission": "write"})

        assert response.status_code == 200, response.text
        assert response.json()["permission"] == "write"
        assert await _permission(test_sessionmaker, share_id) == "write"

    async def test_revoke_share_deletes_it(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        owned_vehicle: Vehicle,
        reader_user: User,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        share_id = await _share_id(test_sessionmaker, reader_user.id)
        assert share_id is not None
        await set_auth_mode("none")

        response = await client.delete(f"/api/family/shares/{share_id}")

        assert response.status_code == 204, response.text
        assert await _permission(test_sessionmaker, share_id) is None

    async def test_update_dashboard_member_saves_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        member_id = (await _user(db_session, made_users)).id
        await set_auth_mode("none")

        response = await client.put(
            f"/api/family/dashboard/members/{member_id}",
            json={"show_on_family_dashboard": True, "family_dashboard_order": 7},
        )

        assert response.status_code == 200, response.text
        async with test_sessionmaker() as fresh:
            stored = await fresh.get(User, member_id)
        assert stored is not None
        assert (stored.show_on_family_dashboard, stored.family_dashboard_order) == (True, 7)


# --- Family writes that have to record a person -------------------------------


class TestWritesThatNeedAPerson:
    async def test_create_share_is_400_and_writes_nothing(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        owned_vehicle: Vehicle,
        unrelated_user: User,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        unrelated_id = unrelated_user.id
        before = await _counts(test_sessionmaker)
        await set_auth_mode("none")

        response = await client.post(
            f"/api/family/vehicles/{AUTHZ_VIN}/shares",
            json={"user_id": unrelated_id, "permission": "read"},
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"]["detail"] == "requires_sign_in"
        assert await _counts(test_sessionmaker) == before

    async def test_transfer_is_400_and_writes_nothing(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        owned_vehicle: Vehicle,
        owner_user: User,
        unrelated_user: User,
        set_auth_mode: Callable[[str], Awaitable[None]],
    ) -> None:
        owner_id, unrelated_id = owner_user.id, unrelated_user.id
        before = await _counts(test_sessionmaker)
        assert before[2] == owner_id
        await set_auth_mode("none")

        response = await client.post(
            f"/api/family/vehicles/{AUTHZ_VIN}/transfer", json={"to_user_id": unrelated_id}
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"]["detail"] == "requires_sign_in"
        assert await _counts(test_sessionmaker) == before


# --- Controls: signed in, nothing changed -------------------------------------


class TestSignedInStaysScoped:
    async def test_a_stranger_cannot_change_a_share(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        owned_vehicle: Vehicle,
        reader_user: User,
        unrelated_headers: dict[str, str],
    ) -> None:
        share_id = await _share_id(test_sessionmaker, reader_user.id)
        assert share_id is not None

        response = await client.put(
            f"/api/family/shares/{share_id}",
            json={"permission": "write"},
            headers=unrelated_headers,
        )

        assert response.status_code == 403, response.text
        assert await _permission(test_sessionmaker, share_id) == "read"

    async def test_the_dashboard_still_puts_the_admin_first(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        made_users: list[str],
    ) -> None:
        # Off the dashboard, so the only way in is the insert at the top.
        admin = await _user(db_session, made_users, admin=True, on_dashboard=False)

        response = await client.get("/api/family/dashboard", headers=admin.headers)

        assert response.status_code == 200, response.text
        assert response.json()["members"][0]["id"] == admin.id

    async def test_the_dashboard_services_still_refuse_a_non_admin(
        self,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
        owner_user: User,
    ) -> None:
        member_id = (await _user(db_session, made_users)).id
        service = FamilyDashboardService(db_session)

        with pytest.raises(HTTPException) as dashboard:
            await service.get_family_dashboard(owner_user)
        with pytest.raises(HTTPException) as members:
            await service.get_all_users_for_dashboard_management(owner_user)
        with pytest.raises(HTTPException) as update:
            await service.update_member_display(
                member_id,
                FamilyMemberUpdateRequest(show_on_family_dashboard=True),
                owner_user,
            )

        assert [dashboard.value.status_code, members.value.status_code] == [403, 403]
        assert update.value.status_code == 403
        async with test_sessionmaker() as fresh:
            stored = await fresh.get(User, member_id)
        assert stored is not None
        assert stored.show_on_family_dashboard is False
