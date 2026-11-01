"""
Integration tests for authentication routes.

Tests user registration, login, logout, and protected endpoints.
"""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from joserfc import jws
from joserfc import jwt as jose_jwt
from joserfc.jwk import OctKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, configure_sqlite_engine, get_db
from app.main import app
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import create_access_token
from tests._users import TEST_PASSWORD_HASH

_REGISTRATION_DISABLED = (
    "Registration is disabled. Please contact an administrator to create an account."
)
_BAD_CREDENTIALS = "Could not validate credentials"
_NEW_PASSWORD = "NewSecureP@ss1"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def empty_db(
    client: AsyncClient, tmp_path: Path
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A private SQLite database with nobody in it, for this test's requests only.

    The zero-user tests used to delete every user in the shared database, and
    the cascade took every vehicle and record with them. It's SQLite in the
    PostgreSQL job too, so first-user registration only runs on SQLite.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    configure_sqlite_engine(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    async def private_get_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    shared = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = private_get_db
    yield maker
    app.dependency_overrides[get_db] = shared
    await engine.dispose()


async def _make_user(db_session: AsyncSession, made_users: list[str]) -> tuple[int, str]:
    """A throwaway active non-admin user; its email is `<name>@example.com`."""
    name = f"dup_{uuid.uuid4().hex[:10]}"
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=TEST_PASSWORD_HASH,
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    made_users.append(name)
    return user.id, name


async def _count_users(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    username: str | None = None,
    email: str | None = None,
) -> int:
    """Committed users matching every filter given, read over a second session."""
    query = select(func.count(User.id))
    if username is not None:
        query = query.where(User.username == username)
    if email is not None:
        query = query.where(User.email == email)
    async with sessionmaker() as fresh:
        return await fresh.scalar(query) or 0


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestUserRegistration:
    """Test user registration endpoint."""

    async def test_register_first_user_success(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        new_vehicle: Callable[..., Awaitable[str]],
        empty_db: async_sessionmaker[AsyncSession],
    ):
        """Test that the first user can register and becomes admin."""
        # A vehicle in the shared database, which this test must leave alone.
        bystander = await new_vehicle()

        # Register first user
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "firstuser",
                "email": "first@example.com",
                "password": "SecurePassword123!",
                "full_name": "First User",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "firstuser"
        assert data["email"] == "first@example.com"
        assert data["is_admin"] is True
        assert data["is_active"] is True
        assert "hashed_password" not in data  # Password should not be returned
        async with empty_db() as private:
            assert await private.scalar(select(func.count(User.id))) == 1
        # Nobody else's garage pays for the empty database.
        async with test_sessionmaker() as fresh:
            assert await fresh.get(Vehicle, bystander) is not None

    async def test_register_second_user_blocked(
        self,
        client: AsyncClient,
        test_user,
        test_sessionmaker: async_sessionmaker[AsyncSession],
    ):
        """Test that registration is blocked after first user."""
        # test_user fixture ensures a user exists, so registration should be blocked
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "seconduser",
                "email": "second@example.com",
                "password": "Password123!",
            },
        )

        # Every limiter starts each test unspent, so a 429 here is a real failure.
        assert response.status_code == 403
        assert response.json()["detail"] == _REGISTRATION_DISABLED
        assert await _count_users(test_sessionmaker, username="seconduser") == 0

    async def test_register_invalid_email(
        self, client: AsyncClient, empty_db: async_sessionmaker[AsyncSession]
    ):
        """Test that invalid email addresses are rejected."""
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "not-an-email",  # Invalid email
                "password": "Password123!",
            },
        )

        assert response.status_code == 422  # Validation error


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestHasUsers:
    """The public first-user check says yes or no, never how many."""

    async def test_no_users_reads_false(
        self, client: AsyncClient, empty_db: async_sessionmaker[AsyncSession]
    ):
        """With nobody registered, anonymous callers get has_users false."""
        response = await client.get("/api/auth/users/count")

        assert response.status_code == 200
        body = response.json()
        assert body == {"has_users": False}
        # 0 == False in Python, so pin the type too.
        assert body["has_users"] is False
        assert "count" not in body

    async def test_one_user_reads_true(
        self, client: AsyncClient, empty_db: async_sessionmaker[AsyncSession]
    ):
        """Once someone exists, anonymous callers get has_users true and no count."""
        async with empty_db() as private:
            private.add(
                User(
                    username="hasusersprobe",
                    email="hasusersprobe@example.com",
                    hashed_password="unused",
                    is_active=True,
                    is_admin=False,
                )
            )
            await private.commit()

        response = await client.get("/api/auth/users/count")

        assert response.status_code == 200
        body = response.json()
        assert body == {"has_users": True}
        # 1 == True too, so a leaked count of one would sneak past the equality.
        assert body["has_users"] is True
        assert "count" not in body


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestUserLogin:
    """Test user login endpoint."""

    async def test_login_success(self, client: AsyncClient, test_user, db_session):
        """Test successful login with valid credentials."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",  # From conftest.py
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Check that JWT cookie was set
        assert settings.jwt_cookie_name in response.cookies

    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """Test login fails with wrong password."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login fails with nonexistent username."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": "nonexistent",
                "password": "anypassword",
            },
        )

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    async def test_login_inactive_user(self, client: AsyncClient, test_user, db_session):
        """Test that inactive users cannot log in."""
        # Deactivate user
        user = await db_session.get(User, test_user["id"])
        user.is_active = False
        await db_session.commit()

        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
        )

        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()

    async def test_login_updates_last_login(self, client: AsyncClient, test_user, db_session):
        """Test that last_login timestamp is updated on successful login."""
        # Get user before login
        user_before = await db_session.get(User, test_user["id"])
        last_login_before = user_before.last_login

        # Login
        await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
        )

        # Get user after login
        await db_session.refresh(user_before)
        last_login_after = user_before.last_login

        # last_login should be updated
        if last_login_before:
            assert last_login_after > last_login_before
        else:
            assert last_login_after is not None


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestProtectedEndpoints:
    """Test protected endpoints requiring authentication."""

    async def test_get_current_user_authenticated(
        self, client: AsyncClient, auth_headers, test_user
    ):
        """Test accessing /me endpoint with valid authentication."""
        response = await client.get("/api/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user["id"]
        assert data["username"] == test_user["username"]
        assert data["email"] == test_user["email"]

    async def test_me_returns_raw_and_resolved_units(
        self, client: AsyncClient, auth_headers, test_user
    ):
        """The frontend needs both: raw columns drive the settings selects, and
        the resolved set drives every formatter. Serialising only one of them
        makes the other impossible."""
        response = await client.get("/api/auth/me", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert set(body["resolved_units"]) == {
            "distance",
            "speed",
            "length",
            "volume",
            "consumption",
            "pressure",
            "temperature",
            "mass",
            "torque",
            "tread",
            "secondary_gallon",
        }
        # The raw column is present and distinct from the resolved value: NULL
        # here means "no override", which is not the same as the resolved unit.
        assert "unit_pressure" in body
        assert body["unit_pressure"] is None
        assert body["resolved_units"]["pressure"] == "psi"  # imperial test_user

    async def test_get_current_user_no_auth(self, client: AsyncClient):
        """Test accessing /me endpoint without authentication."""
        response = await client.get("/api/auth/me")

        assert response.status_code == 401
        # API returns "Could not validate credentials" when no auth provided
        assert "could not validate credentials" in response.json()["detail"].lower()

    async def test_get_current_user_invalid_token(self, client: AsyncClient):
        """Test accessing /me endpoint with invalid token."""
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token_here"},
        )

        assert response.status_code == 401

    async def test_get_current_user_expired_token(self, client: AsyncClient, test_user):
        """An expired token for a real user gets 401, and a live one for them gets 200.

        It used to mint for user 999, who doesn't exist, so the user lookup
        answered 401 and the expiry check never had to.
        """
        claims = {"sub": str(test_user["id"]), "username": str(test_user["username"])}
        live = create_access_token(claims)
        expired = create_access_token(claims, expires_delta=timedelta(seconds=-100))

        control = await client.get("/api/auth/me", headers=_bearer(live))
        assert control.status_code == 200
        assert control.json()["id"] == test_user["id"]

        response = await client.get("/api/auth/me", headers=_bearer(expired))

        assert response.status_code == 401
        assert response.json()["detail"] == _BAD_CREDENTIALS

    async def test_token_without_exp_is_refused(self, client: AsyncClient, test_user):
        """A signed token with no exp claim gets 401 instead of never expiring.

        The control is the same token with an exp, so the 401 can only be the
        missing claim, not a bad signature.
        """
        claims: dict[str, object] = {
            "sub": str(test_user["id"]),
            "username": str(test_user["username"]),
        }
        key = OctKey.import_key(settings.secret_key)
        header = {"alg": settings.algorithm}
        with_exp = jose_jwt.encode(header, {**claims, "exp": int(time.time()) + 600}, key)
        without_exp = jose_jwt.encode(header, claims, key)

        control = await client.get("/api/auth/me", headers=_bearer(with_exp))
        assert control.status_code == 200
        assert control.json()["id"] == test_user["id"]

        response = await client.get("/api/auth/me", headers=_bearer(without_exp))

        assert response.status_code == 401
        assert response.json()["detail"] == _BAD_CREDENTIALS

    @pytest.mark.parametrize("exp_json", ['"9"', "Infinity", "NaN"])
    async def test_token_with_a_non_finite_or_non_numeric_exp_is_refused(
        self, client: AsyncClient, test_user, exp_json: str
    ):
        """A signed token whose exp isn't a finite number gets 401.

        A string used to blow up the comparison (500), and `now > inf` or
        `now > nan` is False, so those tokens never expired. The payload is
        written as raw JSON so it really carries the bare Infinity/NaN tokens.
        """
        claims = f'"sub": "{test_user["id"]}", "username": "{test_user["username"]}"'
        key = OctKey.import_key(settings.secret_key)
        header = {"alg": settings.algorithm}

        def sign(exp: str) -> str:
            return jws.serialize_compact(header, f"{{{claims}, {exp}}}".encode(), key)

        control = await client.get(
            "/api/auth/me", headers=_bearer(sign(f'"exp": {int(time.time()) + 600}'))
        )
        assert control.status_code == 200
        assert control.json()["id"] == test_user["id"]

        response = await client.get("/api/auth/me", headers=_bearer(sign(f'"exp": {exp_json}')))

        assert response.status_code == 401
        assert response.json()["detail"] == _BAD_CREDENTIALS

    async def test_get_current_user_auth_mode_none_returns_null(
        self, client: AsyncClient, db_session
    ):
        """In auth_mode='none' there is no user, so /me returns 200 with a null
        body — not 401. A 401 here is what bounced auth-disabled users to the
        login page (bug #98); the endpoint uses the mode-aware require_auth
        dependency so it never raises when authentication is turned off.
        """
        from app.models.settings import Setting

        result = await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        auth_setting = result.scalar_one_or_none()
        if auth_setting:
            auth_setting.value = "none"
        else:
            db_session.add(Setting(key="auth_mode", value="none"))
        await db_session.commit()

        response = await client.get("/api/auth/me")

        assert response.status_code == 200
        assert response.json() is None


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestLogout:
    """Test user logout endpoint."""

    async def test_logout_success(self, client: AsyncClient, auth_headers):
        """Test successful logout clears JWT cookie."""
        # Use auth_headers fixture (creates token directly, bypasses rate-limited login)
        # Logout is exempt from CSRF (idempotent operation, protected by JWT)
        response = await client.post(
            "/api/auth/logout",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "logged out" in data["message"].lower()

        # Check that JWT cookie was cleared (set to empty with max_age=0)
        cookie_header = response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        # Cookie should be cleared (max-age=0 or expires in past)
        assert "max-age=0" in cookie_header.lower() or "expires=" in cookie_header.lower()

    async def test_logout_without_auth(self, client: AsyncClient):
        """Test logout without authentication returns 401."""
        response = await client.post("/api/auth/logout")

        # Logout requires authentication - should return 401 or 403
        assert response.status_code in [401, 403]


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestCookieSecureFlag:
    """Test cookie Secure flag behavior based on request scheme.

    Regression tests for GitHub issue #35: Local auth login fails over HTTP
    because the Secure flag causes browsers to silently drop the cookie.
    """

    @pytest.fixture(autouse=True)
    async def _ensure_local_auth(self, db_session):
        """Ensure auth_mode is 'local' for all tests in this class."""
        from app.models.settings import Setting

        result = await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        auth_setting = result.scalar_one_or_none()
        if auth_setting:
            auth_setting.value = "local"
        else:
            db_session.add(Setting(key="auth_mode", value="local"))
        await db_session.commit()

    async def test_login_over_http_no_secure_flag(
        self, client: AsyncClient, test_user, monkeypatch
    ):
        """Login over HTTP must NOT set Secure flag on cookie.

        This is the core regression test for #35. The same AsyncClient is used
        for login and /auth/me — the client's cookie jar decides whether to
        retain the cookie, mirroring browser behavior.
        """
        # Ensure auto-detection mode (no explicit override)
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)

        # Login — test client runs over http://test (conftest.py:135)
        login_response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
        )
        assert login_response.status_code == 200

        # Verify Set-Cookie does NOT contain Secure flag
        cookie_header = login_response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        # The Secure flag should NOT be present for HTTP connections
        assert "; secure" not in cookie_header.lower()

        # Use the SAME client to call /auth/me — cookie jar handles retention
        me_response = await client.get("/api/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["username"] == test_user["username"]

    async def test_login_with_forwarded_proto_https_sets_secure(
        self, client: AsyncClient, test_user, monkeypatch
    ):
        """Login behind a TLS-terminating proxy must set Secure flag on cookie.

        When X-Forwarded-Proto: https is present, the cookie should include
        the Secure flag since the browser-to-proxy connection is HTTPS.
        """
        # Ensure auto-detection mode
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)

        # Login with X-Forwarded-Proto: https header
        login_response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
            headers={"X-Forwarded-Proto": "https"},
        )
        assert login_response.status_code == 200

        # Verify Set-Cookie DOES contain Secure flag
        cookie_header = login_response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        assert "; secure" in cookie_header.lower()


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestAdminPasswordReset:
    """Test admin password reset endpoint."""

    async def test_admin_reset_password_success(
        self, client: AsyncClient, auth_headers, non_admin_user
    ):
        """Test that an admin can reset another user's password."""
        response = await client.put(
            f"/api/auth/users/{non_admin_user['id']}/password",
            json={"new_password": "NewSecureP@ss1"},
            headers=auth_headers,
        )
        assert response.status_code == 204

    async def test_admin_reset_password_weak(
        self, client: AsyncClient, auth_headers, non_admin_user
    ):
        """Test that weak passwords are rejected with 422."""
        response = await client.put(
            f"/api/auth/users/{non_admin_user['id']}/password",
            json={"new_password": "weak"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_admin_reset_password_oidc_user(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Test that password reset is rejected for OIDC users."""
        # Create an OIDC user
        oidc_user = User(
            username="oidcuser",
            email="oidc@example.com",
            hashed_password="unused",
            is_active=True,
            is_admin=False,
            auth_method="oidc",
        )
        db_session.add(oidc_user)
        await db_session.commit()
        await db_session.refresh(oidc_user)

        response = await client.put(
            f"/api/auth/users/{oidc_user.id}/password",
            json={"new_password": "NewSecureP@ss1"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "OIDC" in response.json()["detail"]

    async def test_self_update_rejects_privileged_fields(self, client: AsyncClient, auth_headers):
        """Test that PUT /api/auth/me rejects is_admin/is_active with 422."""
        response = await client.put(
            "/api/auth/me",
            json={"is_admin": True},
            headers=auth_headers,
        )
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestDuplicateUserChecks:
    """Admin create and both profile updates refuse a taken username or email.

    Without these checks the unique index catches the duplicate instead, and
    nothing turns its IntegrityError into a 400.
    """

    async def test_create_user_duplicate_username(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
        multi_user_on: None,
    ):
        """A second user with a taken username is a 400, and no row is written."""
        _, taken = await _make_user(db_session, made_users)
        email = f"other_{taken}@example.com"

        response = await client.post(
            "/api/auth/users",
            json={"username": taken, "email": email, "password": _NEW_PASSWORD},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Username already registered"
        assert await _count_users(test_sessionmaker, username=taken) == 1
        assert await _count_users(test_sessionmaker, email=email) == 0

    async def test_create_user_duplicate_email(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
        multi_user_on: None,
    ):
        """A second user with a taken email is a 400, and no row is written."""
        _, owner = await _make_user(db_session, made_users)
        taken = f"{owner}@example.com"
        name = f"dup_{uuid.uuid4().hex[:10]}"
        made_users.append(name)

        response = await client.post(
            "/api/auth/users",
            json={"username": name, "email": taken, "password": _NEW_PASSWORD},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Email already registered"
        assert await _count_users(test_sessionmaker, email=taken) == 1
        assert await _count_users(test_sessionmaker, username=name) == 0

    async def test_update_me_to_another_users_email(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
    ):
        """PUT /me with someone else's email is a 400, and the caller's email stays."""
        me_id, me = await _make_user(db_session, made_users)
        _, other = await _make_user(db_session, made_users)
        token = create_access_token(data={"sub": str(me_id), "username": me})

        response = await client.put(
            "/api/auth/me", json={"email": f"{other}@example.com"}, headers=_bearer(token)
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Email already registered"
        assert await _count_users(test_sessionmaker, username=me, email=f"{me}@example.com") == 1

    async def test_admin_update_user_to_another_users_email(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[str],
    ):
        """An admin moving a user onto someone else's email is a 400, and nothing changes."""
        target_id, target = await _make_user(db_session, made_users)
        _, other = await _make_user(db_session, made_users)

        response = await client.put(
            f"/api/auth/users/{target_id}",
            json={"email": f"{other}@example.com"},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Email already registered"
        assert (
            await _count_users(test_sessionmaker, username=target, email=f"{target}@example.com")
            == 1
        )


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestSessionLifetime:
    """Test that JWT, cookie, and CSRF lifetimes are aligned."""

    async def test_login_cookie_max_age(self, client: AsyncClient, test_user):
        """Test login response cookie Max-Age matches configured lifetime."""
        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200

        cookie_header = response.headers.get("set-cookie", "")
        assert f"max-age={settings.jwt_cookie_max_age}" in cookie_header.lower()

    async def test_login_jwt_exp(self, client: AsyncClient, test_user):
        """Test login JWT exp claim matches configured lifetime."""
        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200

        token = response.json()["access_token"]
        payload = jwt.decode(token, options={"verify_signature": False})

        expected_seconds = settings.access_token_expire_minutes * 60
        actual_seconds = payload["exp"] - payload.get("iat", payload["exp"] - expected_seconds)
        assert abs(actual_seconds - expected_seconds) < 5

    async def test_login_csrf_expiry(self, client: AsyncClient, test_user, db_session):
        """Test CSRF token expiry matches configured lifetime."""
        from app.models.csrf_token import CSRFToken
        from app.utils.datetime_utils import utc_now

        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200

        csrf_token_value = response.json()["csrf_token"]
        result = await db_session.execute(
            select(CSRFToken).where(CSRFToken.token == csrf_token_value)
        )
        csrf_record = result.scalar_one()

        now = utc_now()
        expected_minutes = settings.access_token_expire_minutes
        delta_minutes = (csrf_record.expires_at - now).total_seconds() / 60
        assert abs(delta_minutes - expected_minutes) < 1

    async def test_login_expires_in_matches_config(self, client: AsyncClient, test_user):
        """Test login response expires_in matches configured lifetime."""
        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200
        assert response.json()["expires_in"] == settings.access_token_expire_minutes * 60
