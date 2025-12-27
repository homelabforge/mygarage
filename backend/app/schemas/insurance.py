"""Insurance policy schemas."""

from pydantic import BaseModel, Field
from datetime import date as date_type, datetime
from typing import Optional
from decimal import Decimal


class InsurancePolicyBase(BaseModel):
    """Base insurance policy schema."""

    provider: str = Field(..., description="Insurance provider name")
    policy_number: str = Field(..., description="Policy number")
    policy_type: str = Field(..., description="Type of insurance coverage")
    start_date: date_type = Field(..., description="Policy start date")
    end_date: date_type = Field(..., description="Policy end date")
    premium_amount: Optional[Decimal] = Field(None, description="Premium amount", ge=0)
    premium_frequency: Optional[str] = Field(
        None, description="How often premium is paid"
    )
    deductible: Optional[Decimal] = Field(None, description="Deductible amount", ge=0)
    coverage_limits: Optional[str] = Field(None, description="Coverage limits details")
    notes: Optional[str] = Field(None, description="Additional notes")


class InsurancePolicyCreate(InsurancePolicyBase):
    """Schema for creating an insurance policy."""

    pass


class InsurancePolicyUpdate(BaseModel):
    """Schema for updating an insurance policy."""

    provider: Optional[str] = None
    policy_number: Optional[str] = None
    policy_type: Optional[str] = None
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    premium_amount: Optional[Decimal] = Field(None, ge=0)
    premium_frequency: Optional[str] = None
    deductible: Optional[Decimal] = Field(None, ge=0)
    coverage_limits: Optional[str] = None
    notes: Optional[str] = None


class InsurancePolicy(InsurancePolicyBase):
    """Schema for insurance policy response."""

    id: int
    vin: str
    created_at: datetime

    class Config:
        from_attributes = True
