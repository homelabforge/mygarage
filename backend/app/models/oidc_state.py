from __future__ import annotations

"""OIDC state model for secure OAuth2/OIDC flow tracking."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Column, DateTime, Index, String

from app.database import Base


class OIDCState(Base):
    """OIDC state model for tracking OAuth2/OIDC authentication flows.

    Stores state parameters for OIDC authentication flows to prevent
    CSRF attacks and maintain flow integrity across multi-worker deployments.
    Replaces in-memory storage for production reliability.
    """

    __tablename__ = "oidc_states"

    state = Column(String(128), primary_key=True, index=True, nullable=False)
    nonce = Column(String(128), nullable=False)
    redirect_uri = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    expires_at = Column(DateTime, nullable=False)

    # Index for efficient cleanup of expired states
    __table_args__ = (Index("ix_oidc_expires_at", "expires_at"),)

    def __repr__(self):
        return f"<OIDCState(state={self.state[:16]}..., expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the OIDC state has expired."""
        # Handle timezone-naive datetimes from SQLite
        now = datetime.now(UTC)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return now > expires  # type: ignore[return-value]

    @classmethod
    def get_expiry_time(cls, minutes: int = 10) -> datetime:
        """Get expiry timestamp for a new state (default 10 minutes for OIDC flow)."""
        return datetime.now(UTC) + timedelta(minutes=minutes)
