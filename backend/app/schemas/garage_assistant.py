"""Pydantic schemas for Ask My Garage assistant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AssistantHistoryMessage(BaseModel):
    role: Literal["user", "assistant"] = Field(..., description="Chat turn role")
    content: str = Field(..., min_length=1, max_length=2000)


class GarageAssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="User question")
    history: list[AssistantHistoryMessage] = Field(
        default_factory=list,
        max_length=6,
        description="Optional prior turns (client-held; not persisted server-side)",
    )


class AssistantCitation(BaseModel):
    source: Literal[
        "vehicle_spec",
        "service_visit",
        "note",
        "supply",
        "tire",
        "reminder",
        "dtc",
        "dtc_definition",
        "trailer",
    ]
    label: str = Field(..., max_length=120)
    detail: str | None = Field(None, max_length=300)


class GarageAssistantChatResponse(BaseModel):
    answer: str
    citations: list[AssistantCitation] = Field(default_factory=list)
    missing: list[str] = Field(
        default_factory=list,
        description="Spec fields or data the user asked about that are not in records",
    )
