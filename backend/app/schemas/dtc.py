"""Pydantic schemas for DTC (Diagnostic Trouble Code) operations."""

from datetime import datetime

from pydantic import BaseModel, Field

# =============================================================================
# DTC Definition Schemas (lookup database)
# =============================================================================


class DTCDefinitionResponse(BaseModel):
    """Schema for DTC definition lookup response."""

    code: str = Field(..., description="DTC code (e.g., P0657)")
    description: str = Field(..., description="Code description")
    category: str = Field(..., description="Category: powertrain, body, chassis, network")
    subcategory: str | None = Field(None, description="Subcategory for grouping")
    severity: str = Field("warning", description="Severity: info, warning, critical")
    estimated_severity_level: int = Field(
        2, description="Severity level: 1=minor, 2=moderate, 3=serious, 4=critical"
    )
    is_emissions_related: bool = Field(False, description="Whether emissions-related")

    # Future enhancement fields (NULL in Phase 1)
    common_causes: list[str] | None = Field(None, description="Common causes")
    symptoms: list[str] | None = Field(None, description="Common symptoms")
    fix_guidance: str | None = Field(None, description="Fix guidance")

    model_config = {"from_attributes": True}


class DTCSearchResponse(BaseModel):
    """Schema for DTC search response."""

    results: list[DTCDefinitionResponse]
    total: int
    query: str


# =============================================================================
# Vehicle DTC Schemas (active/historical per vehicle)
# =============================================================================


class VehicleDTCBase(BaseModel):
    """Base vehicle DTC schema."""

    code: str = Field(..., description="DTC code")
    description: str | None = Field(None, description="Description (from lookup or user)")
    severity: str = Field("warning", description="Severity level")


class VehicleDTCUpdate(BaseModel):
    """Schema for updating a vehicle DTC."""

    description: str | None = Field(None, description="Custom description")
    severity: str | None = Field(None, description="Custom severity")
    user_notes: str | None = Field(None, description="User notes about this DTC")


class VehicleDTCResponse(VehicleDTCBase):
    """Schema for vehicle DTC response."""

    id: int
    vin: str
    device_id: str
    user_notes: str | None = Field(None, description="User notes")
    first_seen: datetime = Field(..., description="When DTC first appeared")
    last_seen: datetime = Field(..., description="When DTC was last reported")
    cleared_at: datetime | None = Field(None, description="When manually cleared")
    is_active: bool = Field(True, description="Whether DTC is currently active")
    created_at: datetime

    # Enrichment from dtc_definitions lookup
    category: str | None = Field(None, description="Category from lookup")
    subcategory: str | None = Field(None, description="Subcategory from lookup")
    is_emissions_related: bool | None = Field(None, description="Emissions-related from lookup")
    estimated_severity_level: int | None = Field(None, description="Severity level from lookup")

    model_config = {"from_attributes": True}


class VehicleDTCListResponse(BaseModel):
    """Schema for vehicle DTC list response."""

    dtcs: list[VehicleDTCResponse]
    total: int
    active_count: int = Field(0, description="Number of currently active DTCs")
    critical_count: int = Field(0, description="Number of critical DTCs")


class DTCClearRequest(BaseModel):
    """Schema for clearing a DTC."""

    notes: str | None = Field(None, description="Notes about why/how DTC was cleared")


class DTCClearResponse(BaseModel):
    """Schema for DTC clear response."""

    success: bool = True
    dtc_id: int
    code: str
    cleared_at: datetime
