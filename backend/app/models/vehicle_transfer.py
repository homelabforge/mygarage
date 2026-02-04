"""Vehicle transfer model for ownership transfer audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vehicle import Vehicle


class VehicleTransfer(Base):
    """Audit record for vehicle ownership transfers.

    Tracks when a vehicle is transferred from one user to another,
    including who performed the transfer and what data categories
    were included in the transfer.
    """

    __tablename__ = "vehicle_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_vin: Mapped[str] = mapped_column(
        String(17),
        ForeignKey("vehicles.vin", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    to_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    transferred_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    transferred_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    transfer_notes: Mapped[str | None] = mapped_column(Text)
    # JSON stored as text - records which data categories were included
    # Example: {"service_records": true, "fuel_logs": true, "documents": false}
    data_included: Mapped[str | None] = mapped_column(Text)

    # Relationships
    vehicle: Mapped[Vehicle] = relationship(
        "Vehicle",
        foreign_keys="[VehicleTransfer.vehicle_vin]",
    )
    from_user: Mapped[User] = relationship(
        "User",
        foreign_keys="[VehicleTransfer.from_user_id]",
    )
    to_user: Mapped[User] = relationship(
        "User",
        foreign_keys="[VehicleTransfer.to_user_id]",
    )
    transferred_by_user: Mapped[User] = relationship(
        "User",
        foreign_keys="[VehicleTransfer.transferred_by]",
    )

    def __repr__(self) -> str:
        return (
            f"<VehicleTransfer(id={self.id}, vin={self.vehicle_vin}, "
            f"from={self.from_user_id}, to={self.to_user_id})>"
        )
