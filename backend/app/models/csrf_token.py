"""CSRF token model for cross-site request forgery protection."""

from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.database import Base


class CSRFToken(Base):
    """CSRF token model using synchronizer token pattern.

    Stores CSRF tokens associated with user sessions to prevent
    cross-site request forgery attacks on state-changing operations.
    """

    __tablename__ = "csrf_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at = Column(DateTime, nullable=False)

    # Relationship to user
    user = relationship("User", backref="csrf_tokens")

    # Composite index for efficient queries
    __table_args__ = (Index("ix_csrf_user_token", "user_id", "token"),)

    def __repr__(self):
        return f"<CSRFToken(user_id={self.user_id}, expires_at={self.expires_at})>"

    def is_expired(self) -> bool:
        """Check if the CSRF token has expired."""
        return datetime.now(timezone.utc) > self.expires_at  # type: ignore[return-value]

    @classmethod
    def get_expiry_time(cls, hours: int = 24) -> datetime:
        """Get expiry timestamp for a new token (default 24 hours)."""
        return datetime.now(timezone.utc) + timedelta(hours=hours)
