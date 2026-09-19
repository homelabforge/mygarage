from __future__ import annotations

"""Insurance database models.

A policy is a HOUSEHOLD record (migration 107): it carries what the whole
policy shares, and each covered vehicle is an `InsurancePolicyVehicle` link
carrying what genuinely differs per vehicle. `previous_policy_id` chains a
policy to the term or insurer it succeeded; that chain is the history.
"""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

POLICY_TYPES = ("Liability", "Comprehensive", "Collision", "Full Coverage", "Minimum", "Other")
PREMIUM_FREQUENCIES = ("Monthly", "Quarterly", "Semi-Annual", "Annual")


class InsurancePolicy(Base):
    """One insurance policy term, covering any number of vehicles."""

    __tablename__ = "insurance_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_number: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: Amount per `premium_frequency` period for the WHOLE policy. The term
    #: cost is always derived from it, never stored.
    premium_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    premium_frequency: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    previous_policy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("insurance_policies.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime)

    vehicle_links: Mapped[list[InsurancePolicyVehicle]] = relationship(
        "InsurancePolicyVehicle",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="InsurancePolicyVehicle.id",
        lazy="selectin",
    )
    #: Every named field of the policy, at BOTH levels. `fields` below is the
    #: policy-level subset; a vehicle's own live on its link.
    all_fields: Mapped[list[InsurancePolicyField]] = relationship(
        "InsurancePolicyField",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="InsurancePolicyField.sort_order, InsurancePolicyField.id",
        lazy="selectin",
    )

    @property
    def fields(self) -> list[InsurancePolicyField]:
        """The policy-level named fields."""
        return [
            f for f in self.all_fields if f.policy_vehicle_id is None and f.policy_vehicle is None
        ]

    __table_args__ = (
        CheckConstraint(
            "premium_frequency IN ('Monthly', 'Quarterly', 'Semi-Annual', 'Annual')",
            name="check_premium_frequency",
        ),
        Index("idx_insurance_policies_end_date", "end_date"),
        Index("idx_insurance_policies_previous", "previous_policy_id"),
    )


class InsurancePolicyVehicle(Base):
    """One vehicle's place on a policy."""

    __tablename__ = "insurance_policy_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False
    )
    vin: Mapped[str] = mapped_column(
        String(17), ForeignKey("vehicles.vin", ondelete="CASCADE"), nullable=False
    )
    policy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    #: NULL = this vehicle takes an even split of whatever the explicit shares
    #: leave (see `app.utils.insurance_shares`).
    premium_share: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    deductible: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    coverage_limits: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    #: Set when the vehicle leaves the policy mid-term; NULL = the whole term.
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    policy: Mapped[InsurancePolicy] = relationship(
        "InsurancePolicy", back_populates="vehicle_links"
    )
    vehicle: Mapped[Vehicle] = relationship("Vehicle", back_populates="insurance_links")
    fields: Mapped[list[InsurancePolicyField]] = relationship(
        "InsurancePolicyField",
        back_populates="policy_vehicle",
        cascade="all, delete-orphan",
        order_by="InsurancePolicyField.sort_order, InsurancePolicyField.id",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("policy_id", "vin", name="uq_insurance_policy_vehicle"),
        CheckConstraint(
            "policy_type IN ('Liability', 'Comprehensive', 'Collision', 'Full Coverage', 'Minimum', 'Other')",
            name="check_policy_vehicle_type",
        ),
        Index("idx_insurance_policy_vehicles_vin", "vin"),
        Index("idx_insurance_policy_vehicles_policy", "policy_id"),
    )


class InsurancePolicyField(Base):
    """A user-named field, on the policy or on one vehicle's link."""

    __tablename__ = "insurance_policy_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False
    )
    #: NULL = a policy-level field.
    policy_vehicle_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("insurance_policy_vehicles.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    policy: Mapped[InsurancePolicy] = relationship("InsurancePolicy", back_populates="all_fields")
    policy_vehicle: Mapped[InsurancePolicyVehicle | None] = relationship(
        "InsurancePolicyVehicle", back_populates="fields"
    )

    __table_args__ = (Index("idx_insurance_policy_fields_policy", "policy_id"),)


from app.models.vehicle import Vehicle
