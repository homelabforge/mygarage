from __future__ import annotations

"""Widget API key model for gethomepage / external read-only widget access."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class WidgetApiKey(Base):
    """User-managed read-only API key for homepage widgets.

    Each key belongs to one user and grants scoped read access to widget
    endpoints under /api/widget/*. Keys are never retrievable after creation;
    only the SHA-256 hash is stored, with a short display prefix for UI.
    """

    __tablename__ = "widget_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(
        String(20), nullable=False, default="all_vehicles"
    )  # 'all_vehicles' | 'selected_vins'
    allowed_vins: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<WidgetApiKey(id={self.id}, user={self.user_id}, "
            f"prefix={self.key_prefix}, scope={self.scope})>"
        )
