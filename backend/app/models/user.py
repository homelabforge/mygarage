from __future__ import annotations

"""User model for authentication."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    """User model for authentication and authorization."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Nullable for OIDC-only users
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # OIDC/SSO authentication fields
    oidc_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )  # 'sub' claim from OIDC provider
    oidc_provider: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # Provider name (e.g., 'Authentik', 'Keycloak')
    auth_method: Mapped[str] = mapped_column(
        String(20), default="local", nullable=False, index=True
    )  # 'local' or 'oidc'

    # Unit preference
    unit_preference: Mapped[str] = mapped_column(
        String(20), default="imperial", nullable=False
    )  # 'imperial' or 'metric'
    show_both_units: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Family/relationship fields
    relationship: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # spouse, child, parent, sibling, grandparent, grandchild, in_law, friend, other
    relationship_custom: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Custom text when relationship='other'
    show_on_family_dashboard: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    family_dashboard_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<User(username={self.username}, email={self.email})>"
