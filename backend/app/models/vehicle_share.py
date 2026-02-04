"""Vehicle share model for sharing vehicles with other users."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vehicle import Vehicle


class VehicleShare(Base):
    """Share record for granting vehicle access to other users.

    Allows vehicle owners (or admins) to share vehicles with other users,
    granting either read-only or read-write access.

    Permissions:
    - 'read': User can view the vehicle and all its data
    - 'write': User can view and add records (service, fuel, notes, etc.)

    Note: Write permission does NOT allow deleting the vehicle or transferring it.
    """

    __tablename__ = "vehicle_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_vin: Mapped[str] = mapped_column(
        String(17),
        ForeignKey("vehicles.vin", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="read",
    )
    shared_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    shared_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    vehicle: Mapped[Vehicle] = relationship(
        "Vehicle",
        foreign_keys="[VehicleShare.vehicle_vin]",
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys="[VehicleShare.user_id]",
    )
    shared_by_user: Mapped[User] = relationship(
        "User",
        foreign_keys="[VehicleShare.shared_by]",
    )

    __table_args__ = (
        UniqueConstraint("vehicle_vin", "user_id", name="uq_vehicle_shares_vin_user"),
    )

    def __repr__(self) -> str:
        return (
            f"<VehicleShare(id={self.id}, vin={self.vehicle_vin}, "
            f"user={self.user_id}, permission={self.permission})>"
        )
