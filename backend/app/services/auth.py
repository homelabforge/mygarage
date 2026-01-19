"""Authentication service for JWT token management."""

# pyright: reportGeneralTypeIssues=false, reportArgumentType=false, reportAttributeAccessIssue=false, reportAssignmentType=false

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from authlib.jose import jwt, JoseError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.user import TokenData

# HTTP Bearer token
security = HTTPBearer(auto_error=False)


def get_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """Extract JWT token from cookie or Authorization header.

    Priority:
    1. Cookie (primary method as of v2.9.0)
    2. Authorization header (backward compatibility)
    """
    # Try cookie first (new method)
    token = request.cookies.get(settings.jwt_cookie_name)
    if token:
        return token

    # Fall back to Authorization header (backward compatibility)
    if credentials:
        return credentials.credentials

    return None


# Initialize Argon2 password hasher with recommended parameters
# time_cost=2, memory_cost=102400 (100MB), parallelism=8
ph = PasswordHasher(time_cost=2, memory_cost=102400, parallelism=8)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash.

    Supports both Argon2 (new) and bcrypt (legacy) hashes for gradual migration.
    Argon2 hashes start with '$argon2', bcrypt hashes start with '$2b$'.
    """
    import logging

    logger = logging.getLogger(__name__)

    # Detect hash type
    if hashed_password.startswith("$argon2"):
        # Argon2 hash - use argon2-cffi
        try:
            ph.verify(hashed_password, plain_password)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False
    else:
        # Legacy bcrypt hash - use bcrypt for verification
        # This allows gradual migration without breaking existing passwords
        try:
            import bcrypt

            password_bytes = plain_password.encode("utf-8")

            # bcrypt v5.0+ has 72-byte limitation
            if len(password_bytes) > 72:
                logger.debug(
                    "Password verification failed: exceeds 72 bytes (bcrypt legacy)"
                )
                return False

            return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
        except Exception as e:
            logger.error("Error verifying bcrypt password: %s", e)
            return False


def hash_password(password: str) -> str:
    """Hash a password using Argon2id.

    Uses Argon2id with recommended parameters:
    - time_cost=2
    - memory_cost=102400 (100MB)
    - parallelism=8

    Note: Argon2 has no password length limitation (unlike bcrypt's 72 bytes).
    """
    return ph.hash(password)


def create_access_token(
    data: dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    header = {"alg": settings.algorithm}
    encoded_jwt = jwt.encode(header, to_encode, settings.secret_key)
    # jwt.encode from authlib always returns bytes
    return encoded_jwt.decode("utf-8")


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(get_token_from_request),
) -> User:
    """Get the current authenticated user from JWT token (cookie or header)."""
    import logging

    logger = logging.getLogger(__name__)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        # Enhanced logging to help diagnose authentication issues
        logger.error(
            "No credentials provided - %s %s", request.method, request.url.path
        )
        raise credentials_exception

    # Security: Do not log token data
    logger.debug("Processing authentication token")

    try:
        payload = jwt.decode(token, settings.secret_key)
        user_id_str: Optional[str] = payload.get("sub")
        username: Optional[str] = payload.get("username")

        if user_id_str is None or username is None:
            logger.error("Token missing user_id or username")
            raise credentials_exception

        try:
            user_id = int(user_id_str)
        except (ValueError, TypeError):
            logger.error("Invalid user_id format: %s", user_id_str)
            raise credentials_exception

        # Security: Do not log decoded token contents
        logger.debug("Token decoded successfully")
        token_data = TokenData(user_id=user_id, username=username)
    except JoseError as e:
        logger.error("JWT decode error: %s", e)
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(get_token_from_request),
) -> Optional[User]:
    """Get the current user if credentials are provided, None otherwise.

    This is useful for endpoints that need to be accessible without authentication
    but should still validate credentials if they are provided.
    """
    if not token:
        return None

    # Token provided - validate it using get_current_user
    try:
        return await get_current_user(request, db, token)
    except HTTPException:
        # Invalid token - return None instead of raising
        return None


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get the current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    return current_user


async def get_current_admin_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(get_token_from_request),
) -> Optional[User]:
    """Get the current admin user.

    Returns None when auth_mode='none' (authentication disabled).
    Returns User when authenticated as admin.
    Raises 401 when auth is enabled but user is not authenticated.
    Raises 403 when authenticated but not admin.
    """
    auth_mode = await get_auth_mode(db)

    # If auth is disabled, return None (allow all access)
    if auth_mode == "none":
        return None

    # Auth is enabled - get current user
    current_user = await get_current_user(request, db, token)

    # Check admin privileges
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have admin privileges",
        )
    return current_user


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[User]:
    """Authenticate a user by username and password.

    Auto-rehashes legacy bcrypt passwords to Argon2 on successful login.
    """
    import logging

    logger = logging.getLogger(__name__)

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user:
        return None

    # SECURITY: Reject password login for OIDC-only users (no password set)
    if user.hashed_password is None:
        logger.warning("Password login attempted for OIDC-only user: %s", username)
        return None

    if not verify_password(password, user.hashed_password):
        return None

    # Auto-migrate legacy bcrypt hashes to Argon2
    if not user.hashed_password.startswith("$argon2"):
        logger.info("Auto-migrating password hash to Argon2 for user: %s", username)
        user.hashed_password = hash_password(password)
        await db.commit()

    return user


# Optional: Allow disabling authentication for development
async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(get_token_from_request),
) -> Optional[User]:
    """Get the current user, but return None if no authentication is provided.

    This is useful for endpoints that work differently when authenticated vs not.
    """
    if not token:
        return None

    try:
        return await get_current_user(request, db, token)
    except HTTPException:
        return None


async def get_auth_mode(db: AsyncSession) -> str:
    """Get the current authentication mode from settings."""
    from app.models.settings import Setting

    result = await db.execute(select(Setting).where(Setting.key == "auth_mode"))
    auth_mode_setting = result.scalar_one_or_none()

    if auth_mode_setting and auth_mode_setting.value:
        return auth_mode_setting.value.lower()

    # Default to 'local' if not set
    return "local"


async def optional_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(get_token_from_request),
) -> Optional[User]:
    """Optional authentication based on auth_mode setting.

    Returns User if authenticated, None if auth_mode='none' or no credentials provided.
    This is useful for endpoints that work differently when authenticated vs not.
    """
    auth_mode = await get_auth_mode(db)

    if auth_mode == "none":
        return None

    # Auth optional - try to get current user, but don't raise if missing
    if not token:
        return None

    try:
        return await get_current_user(request, db, token)
    except HTTPException:
        return None


async def require_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Depends(get_token_from_request),
) -> Optional[User]:
    """Require authentication - checks auth_mode setting.

    Returns User if authenticated.
    Returns None if auth_mode='none' (authentication disabled).
    Raises 401 if auth is enabled but user is not authenticated.
    """
    auth_mode = await get_auth_mode(db)

    # If auth is disabled, return None (no user)
    if auth_mode == "none":
        return None

    # Auth is enabled - enforce authentication
    return await get_current_user(request, db, token)


async def get_vehicle_or_403(vin: str, current_user: Optional[User], db: AsyncSession):
    """Get vehicle if user owns it or is admin, else raise 403.

    Args:
        vin: Vehicle VIN
        current_user: Current authenticated user (None if auth_mode='none')
        db: Database session

    Returns:
        Vehicle object if user has access

    Raises:
        HTTPException 404: Vehicle not found
        HTTPException 403: User does not have access to this vehicle
    """
    from app.models.vehicle import Vehicle

    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # If auth is disabled (auth_mode='none'), allow access to all vehicles
    if current_user is None:
        return vehicle

    # Admin users can access all vehicles
    if current_user.is_admin:
        return vehicle

    # Check if vehicle belongs to user
    if not hasattr(vehicle, "user_id") or vehicle.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to access this vehicle"
        )

    return vehicle


def check_vehicle_ownership(vehicle: Vehicle, current_user: Optional[User]) -> None:
    """Check if user owns vehicle or is admin, else raise 403.

    Args:
        vehicle: Vehicle object
        current_user: Current authenticated user (None if auth_mode='none')

    Raises:
        HTTPException 403: User does not have access to this vehicle
    """
    # If auth is disabled (auth_mode='none'), allow access to all vehicles
    if current_user is None:
        return

    # Admin users can access all vehicles
    if current_user.is_admin:
        return

    # Check if vehicle belongs to user
    if not hasattr(vehicle, "user_id") or vehicle.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to access this vehicle"
        )
