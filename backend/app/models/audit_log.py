"""Audit log model for tracking sensitive operations."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text, JSON
from app.database import Base


class AuditLog(Base):
    """Audit log for tracking sensitive system operations."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    user_id = Column(Integer, nullable=True, index=True)  # Null for system operations
    username = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True, index=True)
    resource_id = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    user_agent = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True)
    success = Column(
        Integer, default=1, nullable=False
    )  # SQLite uses INTEGER for boolean
    error_message = Column(Text, nullable=True)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, user={self.username}, timestamp={self.timestamp})>"
