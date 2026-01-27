from __future__ import annotations

"""User model for authentication."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


class User(Base):
    """User model for authentication and authorization."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)  # Nullable for OIDC-only users
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)

    # OIDC/SSO authentication fields
    oidc_subject = Column(
        String(255), nullable=True, unique=True, index=True
    )  # 'sub' claim from OIDC provider
    oidc_provider = Column(
        String(100), nullable=True, index=True
    )  # Provider name (e.g., 'Authentik', 'Keycloak')
    auth_method = Column(
        String(20), default="local", nullable=False, index=True
    )  # 'local' or 'oidc'

    # Unit preference
    unit_preference = Column(
        String(20), default="imperial", nullable=False
    )  # 'imperial' or 'metric'
    show_both_units = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_login = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User(username={self.username}, email={self.email})>"
