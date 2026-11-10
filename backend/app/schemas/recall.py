"""Recall Pydantic schemas for validation and serialization."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.schemas._nullability import reject_null
from app.utils.lenient_vocab import LenientVocab, lenient_reader

#: Where a recall came from (#211). Stored without a CHECK; the response
#: reads an unknown value as null rather than 500ing the list.
RecallSource = Literal["nhtsa", "rappelconso", "manual"]
LenientRecallSource = Annotated[
    RecallSource | None, BeforeValidator(lenient_reader(RecallSource)), LenientVocab(None)
]


#: How a resolved recall got resolved (D10). No CHECK; NULL is a legacy row,
#: read as manual.
ResolvedVia = Literal["manual", "service_visit"]
LenientResolvedVia = Annotated[
    ResolvedVia | None, BeforeValidator(lenient_reader(ResolvedVia)), LenientVocab(None)
]


class RecallLinkedVisit(BaseModel):
    """The service visit whose line item fixed the recall."""

    visit_id: int
    line_item_id: int
    date: dt.date = Field(..., description="The visit's date, the day the recall was fixed")
    vendor_name: str | None = Field(default=None, description="Where the work was done")


class RecallBase(BaseModel):
    """Base recall schema with common fields."""

    # The column is VARCHAR(20). SQLite never enforced it, PostgreSQL 500s.
    nhtsa_campaign_number: str | None = Field(
        default=None, description="NHTSA campaign number", max_length=20
    )
    external_url: str | None = Field(
        default=None, description="Link to the recall notice online", max_length=500
    )
    component: str = Field(
        ..., description="Component affected by recall", min_length=1, max_length=200
    )
    summary: str = Field(..., description="Summary of the recall issue", min_length=1)
    consequence: str | None = Field(default=None, description="Potential consequences")
    remedy: str | None = Field(default=None, description="Remedy for the recall")
    date_announced: dt.date | None = Field(default=None, description="Date recall was announced")
    notes: str | None = Field(default=None, description="User notes about the recall")


class RecallCreate(RecallBase):
    """Schema for creating a new recall."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)
    is_resolved: bool = Field(default=False, description="Whether recall has been resolved")


class RecallUpdate(BaseModel):
    """Schema for updating an existing recall."""

    nhtsa_campaign_number: str | None = Field(
        default=None, description="NHTSA campaign number", max_length=20
    )
    external_url: str | None = Field(
        default=None, description="Link to the recall notice online", max_length=500
    )
    component: str | None = Field(
        default=None, description="Component affected by recall", min_length=1, max_length=200
    )
    summary: str | None = Field(
        default=None, description="Summary of the recall issue", min_length=1
    )
    consequence: str | None = Field(default=None, description="Potential consequences")
    remedy: str | None = Field(default=None, description="Remedy for the recall")
    date_announced: dt.date | None = Field(default=None, description="Date recall was announced")
    notes: str | None = Field(default=None, description="User notes about the recall")
    is_resolved: bool | None = Field(default=None, description="Whether recall has been resolved")

    # NOT NULL column: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("is_resolved")


class RecallResponse(RecallBase):
    """Schema for recall response."""

    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    nhtsa_campaign_number: str | None = Field(default=None, description="NHTSA campaign number")
    external_url: str | None = Field(default=None, description="Link to the recall notice online")
    # Both columns are nullable and a sync or an import can leave them empty,
    # so a missing one reads as null instead of 500ing the list.
    component: str | None = Field(default=None, description="Component affected by recall")
    summary: str | None = Field(default=None, description="Summary of the recall issue")
    id: int
    vin: str
    is_resolved: bool
    resolved_at: dt.datetime | None = None
    created_at: dt.datetime
    # Where it came from (#211).
    source: LenientRecallSource = Field(default=None, description="nhtsa, rappelconso or manual")
    external_id: str | None = Field(default=None, description="The provider's own identifier")
    match_confidence: int | None = Field(
        default=None, description="0 to 100: how surely the notice concerns this vehicle"
    )
    resolved_via: LenientResolvedVia = Field(
        default=None, description="manual or service_visit; null on an older row, read as manual"
    )
    # Not an ORM attribute, so from_attributes leaves it null; whoever loads
    # the link sets it.
    linked_visit: RecallLinkedVisit | None = Field(
        default=None, description="The service visit that fixed it, when a line item links it"
    )

    model_config = ConfigDict(from_attributes=True)


class RecallListResponse(BaseModel):
    """Schema for list of recalls."""

    recalls: list[RecallResponse]
    total: int
    active_count: int
    resolved_count: int


class RecallCheckResponse(RecallListResponse):
    """The list after a check of every source that covers the vehicle (#211)."""

    providers_checked: list[str] = Field(
        default_factory=list,
        description="The sources asked, in order; empty when none covers the vehicle's country",
    )
    new_count: int = Field(default=0, description="How many recalls the check stored")
    warnings: list[str] = Field(
        default_factory=list, description="A source that could not be asked, and why"
    )
