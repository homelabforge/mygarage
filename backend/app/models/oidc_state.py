from __future__ import annotations

"""OIDC state model for secure OAuth2/OIDC flow tracking."""

from datetime import datetime, timedelta

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.utils.datetime_utils import utc_now


class OIDCState(Base):
    """OIDC state model for tracking OAuth2/OIDC authentication flows.

    Stores state parameters for OIDC authentication flows to prevent
    CSRF attacks and maintain flow integrity across multi-worker deployments.
    Replaces in-memory storage for production reliability.
    """

    __tablename__ = "oidc_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True, index=True, nullable=False)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Index for efficient cleanup of expired states
    __table_args__ = (Index("ix_oidc_expires_at", "expires_at"),)

    def __repr__(self) -> str:
        return f"<OIDCState(state={self.state[:16]}..., expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the OIDC state has expired."""
        now = utc_now()
        expires = self.expires_at
        if expires.tzinfo is not None:
            expires = expires.replace(tzinfo=None)
        return now > expires

    @classmethod
    def get_expiry_time(cls, minutes: int = 10) -> datetime:
        """Get expiry timestamp for a new state (default 10 minutes for OIDC flow)."""
        return utc_now() + timedelta(minutes=minutes)
