"""Authentication routes."""

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.oidc import SSO_RELINK_WINDOW_MINUTES
from app.database import get_db
from app.models.csrf_token import CSRFToken
from app.models.settings import Setting
from app.models.user import User
from app.schemas.user import (
    AdminPasswordReset,
    AdminUserCreate,
    AdminUserUpdate,
    HasUsersResponse,
    LoginRequest,
    Token,
    UnitPreferenceUpdate,
    UserCreate,
    UserPasswordUpdate,
    UserResponse,
    UserSelfUpdate,
)
from app.services.audit_logger import AuditLogger
from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_current_admin_user,
    get_current_user,
    hash_password,
    optional_auth,
    require_auth,
    verify_password,
)
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.request_scheme import get_cookie_secure
from app.utils.unit_resolution import new_user_unit_kwargs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Initialize rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)

_LAST_ADMIN_UPDATE = "Cannot disable or demote the last active admin"
_LAST_ADMIN_DELETE = "Cannot delete the last active admin"


async def _locked_active_admin_count(db: AsyncSession) -> int:
    """Count the active admins, row-locking them on PostgreSQL.

    The last-admin guard's one pre-read. PostgreSQL rejects `count(*) ... FOR
    UPDATE`, so it selects the ids and counts them here. SQLite drops the
    FOR UPDATE; the guard's flush and re-count cover it there. The rows lock
    in id order, so two guards queue on them instead of deadlocking.
    """
    result = await db.execute(
        select(User.id)
        .where(User.is_admin.is_(True), User.is_active.is_(True))
        .order_by(User.id)
        .with_for_update()
    )
    return len(result.all())


async def _active_admin_count(db: AsyncSession) -> int:
    """Count the active admins with a plain count.

    The last-admin guard's re-count, run after its write is flushed. It's a
    separate function from the pre-read on purpose: tests patch the pre-read
    to a stale value and need this one to still see the truth.
    """
    result = await db.execute(
        select(func.count(User.id)).where(User.is_admin.is_(True), User.is_active.is_(True))
    )
    return result.scalar_one()


async def _locked_target(db: AsyncSession, user_id: int) -> User:
    """Re-read the guard's target after the pre-read, row-locked on PostgreSQL.

    The route's first read can be stale: a disabled admin might have been
    enabled since. PostgreSQL holds this lock to commit, so the flags can't
    move again; on SQLite the re-count after the flush covers it.
    """
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_auth)
async def register(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user.

    First user is automatically an admin and activated.
    Registration is disabled after the first user is created for security.
    Subsequent users must be created by an admin via the admin user management endpoints.
    """
    # Check if any users exist
    result = await db.execute(select(func.count(User.id)))
    user_count = result.scalar_one()
    is_first_user = user_count == 0

    # Block registration after first user for security
    if not is_first_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Please contact an administrator to create an account.",
        )

    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create first user as admin
    hashed_password = hash_password(user_data.password)
    unit_kwargs = await new_user_unit_kwargs(db)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hashed_password,
        is_active=True,  # First user is auto-activated
        is_admin=True,  # First user is admin
        **unit_kwargs,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info("First admin user registered: %s", sanitize_for_log(new_user.username))

    return new_user


@router.post("/login", response_model=Token)
@limiter.limit(settings.rate_limit_auth)
async def login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and set JWT token in httpOnly cookie."""
    user = await authenticate_user(db, login_data.username, login_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    # Update last login
    user.last_login = utc_now()

    # Clean up expired CSRF tokens for this user
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == user.id,
            CSRFToken.expires_at <= utc_now(),
        )
    )

    # Generate CSRF token (Security Enhancement v2.10.0)
    csrf_token_value = secrets.token_urlsafe(48)  # 64-character token
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=user.id,
        expires_at=CSRFToken.get_expiry_time(),
    )
    db.add(csrf_token)

    await db.commit()

    # Create access token
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=access_token_expires,
    )

    # Set httpOnly cookie (Security Enhancement v2.10.0)
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=access_token,
        httponly=settings.jwt_cookie_httponly,
        secure=get_cookie_secure(request),
        samesite=settings.jwt_cookie_samesite,
        max_age=settings.jwt_cookie_max_age,
    )

    logger.info("User logged in: %s", sanitize_for_log(user.username))

    # Return token and CSRF token for frontend
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "csrf_token": csrf_token_value,  # Frontend needs this for state-changing requests
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Logout user by clearing the authentication cookie and CSRF tokens."""
    # Delete all CSRF tokens for this user
    await db.execute(delete(CSRFToken).where(CSRFToken.user_id == current_user.id))
    await db.commit()

    # Clear authentication cookie
    response.delete_cookie(
        key=settings.jwt_cookie_name,
        httponly=settings.jwt_cookie_httponly,
        secure=get_cookie_secure(request),
        samesite=settings.jwt_cookie_samesite,
    )
    logger.info("User logged out: %s", sanitize_for_log(current_user.username))
    return {"message": "Successfully logged out"}


@router.get("/users/count", response_model=HasUsersResponse)
async def get_has_users(
    db: AsyncSession = Depends(get_db),
) -> HasUsersResponse:
    """Say whether anyone has registered yet.

    Public on purpose, since the Register page asks before anyone can log in.
    It's a yes or no, so strangers don't get the head count.
    """
    result = await db.execute(select(exists(select(User.id))))
    return HasUsersResponse(has_users=result.scalar_one())


@router.get("/relationship-presets")
async def get_relationship_presets():
    """Get list of available relationship presets for user management.

    Returns a list of relationship types that can be assigned to users
    to indicate their relationship to the admin/account owner.

    Available presets:
    - spouse: Spouse/Partner
    - child: Child
    - parent: Parent
    - sibling: Sibling
    - grandparent: Grandparent
    - grandchild: Grandchild
    - in_law: In-Law
    - friend: Friend
    - other: Other (allows custom text)
    """
    from app.schemas.user import RELATIONSHIP_PRESETS

    return {"presets": RELATIONSHIP_PRESETS}


@router.get("/csrf-token")
async def refresh_csrf_token(
    current_user: User | None = Depends(optional_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get a fresh CSRF token for the current session.

    This allows recovery when sessionStorage loses the token
    without requiring full re-authentication. When auth is enabled,
    requires valid JWT cookie. When auth_mode='none', returns null.
    """
    # When auth_mode='none' or no credentials provided
    if not current_user:
        return {"csrf_token": None}

    # Clean up any expired tokens for this user
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == current_user.id,
            CSRFToken.expires_at <= utc_now(),
        )
    )

    # Generate new CSRF token
    csrf_token_value = secrets.token_urlsafe(48)
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=current_user.id,
        expires_at=CSRFToken.get_expiry_time(),
    )
    db.add(csrf_token)
    await db.commit()

    logger.info("CSRF token refreshed for user: %s", sanitize_for_log(current_user.username))

    return {"csrf_token": csrf_token_value}


@router.get("/me", response_model=UserResponse | None)
async def get_current_user_info(
    current_user: User | None = Depends(require_auth),
):
    """Get current authenticated user information.

    Uses the mode-aware require_auth dependency: returns the authenticated user
    normally, returns None (HTTP 200 with a null body) when auth_mode='none',
    and raises 401 only when auth is enabled but the caller is unauthenticated.
    Returning None instead of 401 in 'none' mode keeps auth-disabled clients off
    the login-redirect path (bug #98).
    """
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserSelfUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user information (non-admin fields only)."""
    # An omitted field keeps its value and an explicit null clears a nullable
    # one; the schema refuses null on the NOT NULL preferences. Every field
    # used to be `if x is not None`, so nothing here could be cleared.
    changes = user_update.model_dump(exclude_unset=True)
    if "email" in changes:
        # Check if email is already taken by another user
        result = await db.execute(
            select(User).where(User.email == changes["email"], User.id != current_user.id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
    for field, value in changes.items():
        setattr(current_user, field, value)

    # Users cannot change their own is_active or is_admin status
    current_user.updated_at = utc_now()

    await db.commit()
    await db.refresh(current_user)

    logger.info("User updated their profile: %s", sanitize_for_log(current_user.username))

    return current_user


@router.put("/me/units", response_model=UserResponse)
async def update_current_user_units(
    payload: UnitPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the current user's units, clearing or materialising every override.

    Spec D3: a preset clears all eleven override columns, because
    `resolve_units` is "preset base, overrides on top" and a surviving override
    would mask the preset the user just chose. Custom materialises all eleven,
    so nothing resolves from the base.

    Which columns to write is `UnitPreferenceUpdate.column_values`'s decision,
    not this route's. It sits beside the validator that guarantees the
    clear-versus-materialise invariant, so the two cannot drift apart across
    two files, and it derives the column set from `UNIT_COLUMN_NAMES` so a
    twelfth quantity cannot silently escape either branch.
    """
    for column, value in payload.column_values().items():
        setattr(current_user, column, value)
    current_user.unit_preference = payload.unit_preference

    if payload.show_both_units is not None:
        current_user.show_both_units = payload.show_both_units

    current_user.updated_at = utc_now()
    await db.commit()
    await db.refresh(current_user)

    logger.info(
        "User set unit preference to %s: %s",
        sanitize_for_log(payload.unit_preference),
        sanitize_for_log(current_user.username),
    )

    return current_user


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit_auth)
async def update_password(
    request: Request,
    password_update: UserPasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user password."""
    # Verify current password
    if not verify_password(password_update.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    current_user.hashed_password = hash_password(password_update.new_password)
    current_user.updated_at = utc_now()

    await db.commit()

    logger.info("User changed password: %s", sanitize_for_log(current_user.username))


# Admin-only endpoints


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)."""
    result = await db.execute(select(User).offset(skip).limit(limit))
    users = result.scalars().all()

    return users


@router.get("/users/shareable")
async def get_shareable_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get list of users available for vehicle sharing.

    Returns minimal user info (id, display_name, relationship) for all active
    users except the current user. This is used to populate the "Share with"
    dropdown when sharing vehicles.

    **Security:**
    - Requires authentication (any authenticated user)
    - Excludes current user and disabled users
    - Returns minimal data only (no email, admin status, etc.)
    """
    from app.services.sharing_service import SharingService

    service = SharingService(db)
    users = await service.get_shareable_users(current_user)
    return {"users": users}


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: AdminUserCreate,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only).

    This is the only way to create users after the first admin account is created.
    New users are created as inactive by default and must be activated by an admin.
    Requires multi_user_enabled setting to be true.

    Supports setting relationship type during creation:
    - relationship: One of spouse, child, parent, sibling, grandparent, grandchild, in_law, friend, other
    - relationship_custom: Custom text when relationship is 'other'
    - show_on_family_dashboard: Whether to show on family dashboard (default: false)
    """
    # Check if multi-user mode is enabled
    result = await db.execute(select(Setting).where(Setting.key == "multi_user_enabled"))
    multi_user_setting = result.scalar_one_or_none()

    if multi_user_setting and multi_user_setting.value != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-user mode is disabled. Enable it in Settings > System to create additional users.",
        )

    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user (inactive by default, non-admin by default)
    hashed_password = hash_password(user_data.password)
    unit_kwargs = await new_user_unit_kwargs(db)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hashed_password,
        is_active=False,  # Inactive by default, admin must activate
        is_admin=False,  # Non-admin by default
        # Family/relationship fields
        relationship=user_data.relationship,
        relationship_custom=user_data.relationship_custom,
        show_on_family_dashboard=user_data.show_on_family_dashboard,
        **unit_kwargs,
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "Admin %s created new user: %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
        sanitize_for_log(new_user.username),
    )

    return new_user


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific user by ID (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: AdminUserUpdate,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a user (admin only).

    Cannot disable or demote the last active admin.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # An omitted field keeps its value and an explicit null clears a nullable
    # one. Every field used to be `if x is not None`, so the Edit User dialog's
    # null for an emptied name or a "None" relationship said saved and stayed.
    changes = user_update.model_dump(exclude_unset=True)
    if "email" in changes:
        # Check if email is already taken
        result = await db.execute(
            select(User).where(User.email == changes["email"], User.id != user_id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    # Turning off an active admin could leave none. Any false flag takes the
    # lock, even when the first read says the target isn't an active admin:
    # it might have been enabled since, so it's judged from the re-read. The
    # dialog re-sends true on an untouched save, so only an actual false counts.
    active_admins = 0
    if changes.get("is_active") is False or changes.get("is_admin") is False:
        active_admins = await _locked_active_admin_count(db)
        # On PostgreSQL a target enabled between the two reads isn't in the
        # locked count, so this can 400 it. That fails closed; a retry works.
        user = await _locked_target(db, user_id)
        if user.is_admin and user.is_active and active_admins <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_LAST_ADMIN_UPDATE)

    relationship_custom_sent = "relationship_custom" in changes
    relationship_custom = changes.pop("relationship_custom", None)
    for field, value in changes.items():
        setattr(user, field, value)
    # Clear the custom relationship when switching away from 'other', null
    # included; a custom value sent in the same request still wins.
    if "relationship" in changes and changes["relationship"] != "other":
        user.relationship_custom = None
    if relationship_custom_sent:
        user.relationship_custom = relationship_custom

    user.updated_at = utc_now()

    if active_admins >= 1:
        # The flush takes SQLite's write lock (PostgreSQL has its row locks),
        # so this count is current. Admins at the pre-read and none now means
        # this write took the last one. None at the pre-read is the recovery
        # path, and it's left alone.
        await db.flush()
        if await _active_admin_count(db) == 0:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_LAST_ADMIN_UPDATE)

    await db.commit()
    await db.refresh(user)

    logger.info(
        "Admin %s updated user: %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
        sanitize_for_log(user.username),
    )

    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user (admin only).

    Cannot delete yourself or the last active admin.
    """
    # None means auth is off, so there's no caller to compare against.
    if current_user is not None and user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    # Same guard as update_user, and every delete takes it: a target that reads
    # as a disabled admin or a plain user might have been enabled or promoted
    # since. The locked re-read is also the 404. A disabled admin can still go.
    active_admins = await _locked_active_admin_count(db)
    # Same PostgreSQL race as update_user: a target enabled since the count can
    # 400 here. Fail closed, and a retry works.
    user = await _locked_target(db, user_id)
    if user.is_admin and user.is_active and active_admins <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_LAST_ADMIN_DELETE)

    # FK hygiene: shares GRANTED by this user (shared_by) and transfer-history
    # rows naming this user carry NOT NULL FKs with no ON DELETE action, so an
    # FK-enforcing engine (PG always; SQLite since foreign_keys=ON) rejects the
    # delete while they exist. Shares the user RECEIVED (user_id), their CSRF
    # tokens, widget keys, and their vehicles (with all child records) cascade
    # via the FKs themselves.
    from sqlalchemy import or_

    from app.models.vehicle_share import VehicleShare
    from app.models.vehicle_transfer import VehicleTransfer

    await db.execute(delete(VehicleShare).where(VehicleShare.shared_by == user_id))
    await db.execute(
        delete(VehicleTransfer).where(
            or_(
                VehicleTransfer.from_user_id == user_id,
                VehicleTransfer.to_user_id == user_id,
                VehicleTransfer.transferred_by == user_id,
            )
        )
    )

    await db.delete(user)

    if active_admins >= 1:
        await db.flush()
        if await _active_admin_count(db) == 0:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_LAST_ADMIN_DELETE)

    await db.commit()

    logger.info(
        "Admin %s deleted user: %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
        sanitize_for_log(user.username),
    )


@router.put("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit_auth)
async def admin_reset_user_password(
    request: Request,
    user_id: int,
    password_data: AdminPasswordReset,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password (admin only).

    Only available for local auth users (not OIDC users).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Cannot reset password for OIDC users
    if user.auth_method == "oidc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reset password for OIDC users. Password is managed by identity provider.",
        )

    # Update password (validation handled by AdminPasswordReset schema)
    user.hashed_password = hash_password(password_data.new_password)
    user.updated_at = utc_now()

    await db.commit()

    logger.info(
        "Admin %s reset password for user: %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
        sanitize_for_log(user.username),
    )


async def _set_oidc_relink(
    db: AsyncSession,
    request: Request,
    user_id: int,
    until: datetime | None,
    current_user: User | None,
) -> User:
    """Arm (a moment) or disarm (None) a user's SSO relink, audited in the same commit.

    Args:
        db: Database session
        request: The request, for the audit row's IP and user agent
        user_id: The account to arm or disarm
        until: When the relink closes, or None to cancel it
        current_user: The admin, or None when auth is off

    Returns:
        The updated user.

    Raises:
        HTTPException: 404 if there's no such user.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.oidc_relink_until = until
    user.updated_at = utc_now()
    # log_event commits, so the change and its audit row land together.
    await AuditLogger.log_event(
        db,
        action="oidc_relink_allowed" if until else "oidc_relink_revoked",
        user=current_user,
        resource_type="user",
        resource_id=str(user.id),
        details={"username": user.username, "until": until.isoformat() if until else None},
        request=request,
    )
    await db.refresh(user)

    logger.info(
        "Admin %s %s the SSO relink for user: %s",
        sanitize_for_log(current_user.username) if current_user else "<auth disabled>",
        "allowed" if until else "cancelled",
        sanitize_for_log(user.username),
    )
    return user


@router.post("/users/{user_id}/oidc-relink", response_model=UserResponse)
async def allow_oidc_relink(
    request: Request,
    user_id: int,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Allow a one-time SSO relink for a user (admin only).

    For the next 30 minutes, the first SSO login whose email or username matches
    this account links it to that sign-in without asking for a password, then the
    window closes. It's the way back in when the user's identity provider account
    was re-created. Allowing it again restarts the window.
    """
    until = utc_now() + timedelta(minutes=SSO_RELINK_WINDOW_MINUTES)
    return await _set_oidc_relink(db, request, user_id, until, current_user)


@router.delete("/users/{user_id}/oidc-relink", response_model=UserResponse)
async def cancel_oidc_relink(
    request: Request,
    user_id: int,
    current_user: User | None = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Cancel an allowed SSO relink for a user (admin only)."""
    return await _set_oidc_relink(db, request, user_id, None, current_user)
