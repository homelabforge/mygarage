from __future__ import annotations

"""Insurance policy database model."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class InsurancePolicy(Base):
    """Insurance policy record model."""

    __tablename__ = "insurance_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_number: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    premium_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    premium_frequency: Mapped[str | None] = mapped_column(String(20))
    deductible: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    coverage_limits: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="insurance_policies")

    __table_args__ = (
        CheckConstraint(
            "policy_type IN ('Liability', 'Comprehensive', 'Collision', 'Full Coverage', 'Minimum', 'Other')",
            name="check_policy_type",
        ),
        CheckConstraint(
            "premium_frequency IN ('Monthly', 'Quarterly', 'Semi-Annual', 'Annual')",
            name="check_premium_frequency",
        ),
        Index("idx_insurance_policies_vin", "vin"),
        Index("idx_insurance_policies_end_date", "end_date"),
    )


from app.models.vehicle import Vehicle
