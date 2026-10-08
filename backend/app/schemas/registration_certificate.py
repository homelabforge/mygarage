"""What the registration certificate import returns (#211)."""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.document import DocumentResponse


class SuggestedTaxRecord(BaseModel):
    """A tax amount printed on the certificate (Y.1, Y.3, Y.6), offered as a
    tax record the person may create; nothing is created unasked."""

    code: str = Field(description="The certificate field the amount comes from (Y.1, Y.3, Y.6)")
    tax_type: str = Field(description="The tax type code the amount maps to")
    amount: Decimal = Field(description="The amount as printed")
    # `date_type`: a field named `date` annotated `date` is a pydantic clash.
    date: date_type = Field(description="The date of first registration (field B)")


class RegistrationParseResponse(BaseModel):
    """A certificate read, before anything is applied."""

    source: Literal["text", "llm"] = Field(
        description="text: the PDF's own text layer; llm: images read by the vision model"
    )
    country: str | None = Field(None, description="The issuing country, when recognised")
    confidence: float = Field(description="0 to 100, from the fields found")
    fields: dict[str, Any] = Field(description="Every harmonised field read, by name")
    field_confidence: dict[str, str] = Field(
        description="high, medium or low per field that was read"
    )
    vehicle_patch: dict[str, Any] = Field(
        description="The vehicle fields the certificate fills, already validated"
    )
    last_inspection_date: date_type | None = Field(
        None, description="Field X.1, the last periodic inspection"
    )
    suggested_tax_records: list[SuggestedTaxRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str | None = Field(None, description="The vision model that read it, on the llm path")
    pages: int = Field(0, description="How many images were sent, on the llm path")


class RegistrationImportResponse(BaseModel):
    """A certificate stored on a vehicle and applied to it."""

    document: DocumentResponse
    applied: list[str] = Field(description="The vehicle fields written")
    skipped: list[str] = Field(
        description="The vehicle fields left alone (already set, and overwrite was off)"
    )
    inspection_recorded: bool = Field(
        description="Whether field X.1 was recorded as a service visit"
    )
    parse: RegistrationParseResponse
