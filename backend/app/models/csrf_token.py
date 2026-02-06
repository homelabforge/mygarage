from __future__ import annotations

"""CSRF token model for cross-site request forgery protection."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class CSRFToken(Base):
    """CSRF token model using synchronizer token pattern.

    Stores CSRF tokens associated with user sessions to prevent
    cross-site request forgery attacks on state-changing operations.
    """

    __tablename__ = "csrf_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationship to user
    user: Mapped[User] = relationship("User", backref="csrf_tokens")

    # Composite index for efficient queries
    __table_args__ = (Index("ix_csrf_user_token", "user_id", "token"),)

    def __repr__(self) -> str:
        return f"<CSRFToken(user_id={self.user_id}, expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the CSRF token has expired."""
        return datetime.now(UTC) > self.expires_at

    @classmethod
    def get_expiry_time(cls, hours: int = 24) -> datetime:
        """Get expiry timestamp for a new token (default 24 hours)."""
        return datetime.now(UTC) + timedelta(hours=hours)
