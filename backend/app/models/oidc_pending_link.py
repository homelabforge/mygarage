"""OIDC pending link model for username-based account linking with password verification."""

from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, String, DateTime, Integer, Index, JSON
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

    token = Column(String(128), primary_key=True, index=True, nullable=False)
    username = Column(String(100), nullable=False, index=True)
    oidc_claims = Column(JSON, nullable=False)  # Full ID token claims
    userinfo_claims = Column(JSON, nullable=True)  # Optional userinfo endpoint claims
    provider_name = Column(String(100), nullable=False)  # Provider display name
    attempt_count = Column(Integer, default=0, nullable=False)  # Failed password attempts
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Indexes for efficient queries and cleanup
    __table_args__ = (
        Index('ix_oidc_pending_link_username', 'username'),
        Index('ix_oidc_pending_link_expires_at', 'expires_at'),
    )

    def __repr__(self):
        return f"<OIDCPendingLink(token={self.token[:16]}..., username={self.username}, expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the pending link token has expired."""
        # Handle timezone-naive datetimes from SQLite
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    @classmethod
    def get_expiry_time(cls, minutes: int = 5) -> datetime:
        """Get expiry timestamp for a new pending link token (default 5 minutes)."""
        return datetime.now(timezone.utc) + timedelta(minutes=minutes)
