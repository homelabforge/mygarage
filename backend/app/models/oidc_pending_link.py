from __future__ import annotations

"""OIDC pending link model for username-based account linking with password verification."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OIDCPendingLink(Base):
    """OIDC pending link model for username-based account linking.

    Stores temporary tokens for linking OIDC accounts to existing local accounts
    when usernames match but no OIDC subject link exists. Requires password
    verification before linking.

    Security features:
    - Short expiration (5 minutes default)
    - Limited password attempts (3 default)
    - One-time use (token deleted after successful link)
    - Cryptographically random tokens
    """

    __tablename__ = "oidc_pending_links"

    token: Mapped[str] = mapped_column(String(128), primary_key=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    oidc_claims: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )  # Full ID token claims
    userinfo_claims: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # Optional userinfo endpoint claims
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)  # Provider display name
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Failed password attempts
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Indexes for efficient queries and cleanup
    __table_args__ = (
        Index("ix_oidc_pending_link_username", "username"),
        Index("ix_oidc_pending_link_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<OIDCPendingLink(token={self.token[:16]}..., username={self.username}, expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the pending link token has expired."""
        # Handle timezone-naive datetimes from SQLite
        now = datetime.now(UTC)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return now > expires

    @classmethod
    def get_expiry_time(cls, minutes: int = 5) -> datetime:
        """Get expiry timestamp for a new pending link token (default 5 minutes)."""
        return datetime.now(UTC) + timedelta(minutes=minutes)
