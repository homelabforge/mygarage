"""Insurance policy schemas."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InsurancePolicyBase(BaseModel):
    """Base insurance policy schema."""

    provider: str = Field(..., description="Insurance provider name")
    policy_number: str = Field(..., description="Policy number")
    policy_type: str = Field(..., description="Type of insurance coverage")
    start_date: date_type = Field(..., description="Policy start date")
    end_date: date_type = Field(..., description="Policy end date")
    premium_amount: Decimal | None = Field(None, description="Premium amount", ge=0)
    premium_frequency: str | None = Field(
        None, description="How often premium is paid"
    )
    deductible: Decimal | None = Field(None, description="Deductible amount", ge=0)
    coverage_limits: str | None = Field(None, description="Coverage limits details")
    notes: str | None = Field(None, description="Additional notes")


class InsurancePolicyCreate(InsurancePolicyBase):
    """Schema for creating an insurance policy."""

    pass


class InsurancePolicyUpdate(BaseModel):
    """Schema for updating an insurance policy."""

    provider: str | None = None
    policy_number: str | None = None
    policy_type: str | None = None
    start_date: date_type | None = None
    end_date: date_type | None = None
    premium_amount: Decimal | None = Field(None, ge=0)
    premium_frequency: str | None = None
    deductible: Decimal | None = Field(None, ge=0)
    coverage_limits: str | None = None
    notes: str | None = None


class InsurancePolicy(InsurancePolicyBase):
    """Schema for insurance policy response."""

    id: int
    vin: str
    created_at: datetime

    class Config:
        from_attributes = True
