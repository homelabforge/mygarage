"""Vehicle photo database model."""

from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional

from app.database import Base


class VehiclePhoto(Base):
    """Vehicle photo gallery model."""

    __tablename__ = "vehicle_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(255))
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    caption: Mapped[Optional[str]] = mapped_column(String(200))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="photos")

    __table_args__ = (
        Index("idx_vehicle_photos_vin", "vin"),
        Index("idx_vehicle_photos_main", "is_main"),
    )


from app.models.vehicle import Vehicle
