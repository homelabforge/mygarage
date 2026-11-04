"""Clearing a user's name or relationship clears it.

Both user-update routes guarded every field with `if x is not None`, so the
admin Edit User dialog, which posts null for an emptied name or a "None"
relationship, said saved and kept the old values. Omitted still keeps, and a
null on a NOT NULL preference is a 422 instead of being skipped.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def fresh_user(db_session: AsyncSession):
    """A throwaway user with every clearable field set, deleted afterwards."""
    tag = uuid.uuid4().hex[:10]
    user = User(
        username=f"clear_{tag}",
        email=f"clear_{tag}@example.com",
        hashed_password="$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI",
        is_active=True,
        is_admin=False,
        full_name="Pat Example",
        relationship="other",
        relationship_custom="Neighbour",
        accent_color="teal",
        theme="dark",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


def _headers_for(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


async def _stored(db_session: AsyncSession, user_id: int) -> User:
    db_session.expire_all()
    return (await db_session.execute(select(User).where(User.id == user_id))).scalar_one()


class TestAdminUserUpdate:
    @pytest.mark.parametrize("field", ["full_name", "relationship_custom"])
    async def test_null_clears(
        self, client: AsyncClient, auth_headers, db_session, fresh_user, field
    ):
        r = await client.put(
            f"/api/auth/users/{fresh_user.id}", json={field: None}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert getattr(await _stored(db_session, fresh_user.id), field) is None

    async def test_relationship_none_clears_it_and_its_custom_text(
        self, client: AsyncClient, auth_headers, db_session, fresh_user
    ):
        # What AddEditUserModal posts for the "None" option.
        r = await client.put(
            f"/api/auth/users/{fresh_user.id}",
            json={"relationship": None, "relationship_custom": None},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        stored = await _stored(db_session, fresh_user.id)
        assert stored.relationship is None
        assert stored.relationship_custom is None

    async def test_relationship_null_alone_still_clears_custom(
        self, client: AsyncClient, auth_headers, db_session, fresh_user
    ):
        r = await client.put(
            f"/api/auth/users/{fresh_user.id}", json={"relationship": None}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        stored = await _stored(db_session, fresh_user.id)
        assert stored.relationship is None
        assert stored.relationship_custom is None

    async def test_omitted_fields_are_kept(
        self, client: AsyncClient, auth_headers, db_session, fresh_user
    ):
        r = await client.put(
            f"/api/auth/users/{fresh_user.id}", json={"is_active": True}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        stored = await _stored(db_session, fresh_user.id)
        assert stored.full_name == "Pat Example"
        assert stored.relationship == "other"
        assert stored.relationship_custom == "Neighbour"

    @pytest.mark.parametrize(
        "field",
        [
            "email",
            "is_active",
            "is_admin",
            "show_both_units",
            "time_format",
            "date_format",
            "mobile_quick_entry_enabled",
            "language",
            "currency_code",
            "show_on_family_dashboard",
            "family_dashboard_order",
        ],
    )
    async def test_null_on_a_required_field_is_a_422(
        self, client: AsyncClient, auth_headers, fresh_user, field
    ):
        r = await client.put(
            f"/api/auth/users/{fresh_user.id}", json={field: None}, headers=auth_headers
        )
        assert r.status_code == 422, r.text


class TestSelfUpdate:
    @pytest.mark.parametrize("field", ["full_name", "accent_color", "theme"])
    async def test_null_clears(self, client: AsyncClient, db_session, fresh_user, field):
        r = await client.put("/api/auth/me", json={field: None}, headers=_headers_for(fresh_user))
        assert r.status_code == 200, r.text
        assert getattr(await _stored(db_session, fresh_user.id), field) is None

    async def test_omitted_fields_are_kept(self, client: AsyncClient, db_session, fresh_user):
        r = await client.put(
            "/api/auth/me", json={"time_format": "24h"}, headers=_headers_for(fresh_user)
        )
        assert r.status_code == 200, r.text
        stored = await _stored(db_session, fresh_user.id)
        assert stored.time_format == "24h"
        assert stored.full_name == "Pat Example"
        assert stored.theme == "dark"

    @pytest.mark.parametrize(
        "field",
        [
            "email",
            "show_both_units",
            "time_format",
            "date_format",
            "mobile_quick_entry_enabled",
            "language",
            "currency_code",
            "dashboard_sort",
        ],
    )
    async def test_null_on_a_required_field_is_a_422(self, client: AsyncClient, fresh_user, field):
        r = await client.put("/api/auth/me", json={field: None}, headers=_headers_for(fresh_user))
        assert r.status_code == 422, r.text

    async def test_date_format_is_saved_and_returned(
        self, client: AsyncClient, db_session, fresh_user
    ):
        headers = _headers_for(fresh_user)
        assert (await client.get("/api/auth/me", headers=headers)).json()["date_format"] == "mdy"

        r = await client.put("/api/auth/me", json={"date_format": "dmy"}, headers=headers)

        assert r.status_code == 200, r.text
        assert r.json()["date_format"] == "dmy"
        assert (await _stored(db_session, fresh_user.id)).date_format == "dmy"

    @pytest.mark.parametrize("value", ["ymd", "DMY", "24/10/2026", ""])
    async def test_unknown_date_format_is_a_422(self, client: AsyncClient, fresh_user, value):
        r = await client.put(
            "/api/auth/me", json={"date_format": value}, headers=_headers_for(fresh_user)
        )
        assert r.status_code == 422, r.text
