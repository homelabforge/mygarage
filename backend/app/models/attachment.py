"""Attachment database model."""

from sqlalchemy import String, Integer, DateTime, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional

from app.database import Base


class Attachment(Base):
    """File attachment model."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(10))
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "record_type IN ('service', 'fuel', 'upgrade', 'collision', 'tax', 'note')",
            name="check_record_type"
        ),
        Index("idx_attachments_record", "record_type", "record_id"),
    )
