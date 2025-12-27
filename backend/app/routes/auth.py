"""Authentication routes."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.csrf_token import CSRFToken
from app.models.settings import Setting
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserUpdate,
    UserPasswordUpdate,
    LoginRequest,
    Token,
)
from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_current_admin_user,
    hash_password,
    verify_password,
    optional_auth,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Initialize rate limiter for auth endpoints
limiter = Limiter(key_func=get_remote_address)


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
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
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hashed_password,
        is_active=True,  # First user is auto-activated
        is_admin=True,  # First user is admin
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info("First admin user registered: %s", new_user.username)

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
    user.last_login = datetime.now(timezone.utc)

    # Clean up expired CSRF tokens for this user
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == user.id,
            CSRFToken.expires_at <= datetime.now(timezone.utc),
        )
    )

    # Generate CSRF token (Security Enhancement v2.10.0)
    csrf_token_value = secrets.token_urlsafe(48)  # 64-character token
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=user.id,
        expires_at=CSRFToken.get_expiry_time(hours=24),  # Same as JWT expiry
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
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
        max_age=settings.jwt_cookie_max_age,
    )

    logger.info("User logged in: %s", user.username)

    # Return token and CSRF token for frontend
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "csrf_token": csrf_token_value,  # Frontend needs this for state-changing requests
    }


@router.post("/logout")
async def logout(
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
        secure=settings.jwt_cookie_secure,
        samesite=settings.jwt_cookie_samesite,
    )
    logger.info("User logged out: %s", current_user.username)
    return {"message": "Successfully logged out"}


@router.get("/users/count")
async def get_user_count(
    db: AsyncSession = Depends(get_db),
):
    """Get total number of registered users (public endpoint for registration page)."""
    result = await db.execute(select(func.count(User.id)))
    count = result.scalar_one()
    return {"count": count}


@router.get("/csrf-token")
async def refresh_csrf_token(
    current_user: Optional[User] = Depends(optional_auth),
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
            CSRFToken.expires_at <= datetime.now(timezone.utc),
        )
    )

    # Generate new CSRF token
    csrf_token_value = secrets.token_urlsafe(48)
    csrf_token = CSRFToken(
        token=csrf_token_value,
        user_id=current_user.id,
        expires_at=CSRFToken.get_expiry_time(hours=24),
    )
    db.add(csrf_token)
    await db.commit()

    logger.info("CSRF token refreshed for user: %s", current_user.username)

    return {"csrf_token": csrf_token_value}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current authenticated user information."""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user information (non-admin fields only)."""
    # Users can only update their own email and full_name
    if user_update.email is not None:
        # Check if email is already taken by another user
        result = await db.execute(
            select(User).where(
                User.email == user_update.email, User.id != current_user.id
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        current_user.email = user_update.email

    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name

    # Users cannot change their own is_active or is_admin status
    current_user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(current_user)

    logger.info("User updated their profile: %s", current_user.username)

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
    if not verify_password(
        password_update.current_password, current_user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    current_user.hashed_password = hash_password(password_update.new_password)
    current_user.updated_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info("User changed password: %s", current_user.username)


# Admin-only endpoints


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)."""
    result = await db.execute(select(User).offset(skip).limit(limit))
    users = result.scalars().all()

    return users


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only).

    This is the only way to create users after the first admin account is created.
    New users are created as inactive by default and must be activated by an admin.
    Requires multi_user_enabled setting to be true.
    """
    # Check if multi-user mode is enabled
    result = await db.execute(
        select(Setting).where(Setting.key == "multi_user_enabled")
    )
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
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=hashed_password,
        is_active=False,  # Inactive by default, admin must activate
        is_admin=False,  # Non-admin by default
    )

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "Admin %s created new user: %s", current_user.username, new_user.username
    )

    return new_user


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_admin_user),
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
    user_update: UserUpdate,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a user (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Update fields
    if user_update.email is not None:
        # Check if email is already taken
        result = await db.execute(
            select(User).where(User.email == user_update.email, User.id != user_id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        user.email = user_update.email

    if user_update.full_name is not None:
        user.full_name = user_update.full_name

    if user_update.is_active is not None:
        user.is_active = user_update.is_active

    if user_update.is_admin is not None:
        user.is_admin = user_update.is_admin

    user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(user)

    logger.info("Admin %s updated user: %s", current_user.username, user.username)

    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user (admin only).

    Cannot delete yourself or the last admin.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check if this is the last admin
    if user.is_admin:
        result = await db.execute(
            select(func.count(User.id)).where(User.is_admin.is_(True))
        )
        admin_count = result.scalar_one()

        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last admin user",
            )

    await db.delete(user)
    await db.commit()

    logger.info("Admin %s deleted user: %s", current_user.username, user.username)


@router.put("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.rate_limit_auth)
async def admin_reset_user_password(
    request: Request,
    user_id: int,
    password_data: dict,
    current_user: User = Depends(get_current_admin_user),
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

    # Validate new password
    from app.schemas.user import passwordSchema

    try:
        new_password = password_data.get("new_password")
        if not new_password:
            raise ValueError("new_password is required")
        passwordSchema.validate_password(new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Update password
    user.hashed_password = hash_password(new_password)
    user.updated_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "Admin %s reset password for user: %s", current_user.username, user.username
    )
