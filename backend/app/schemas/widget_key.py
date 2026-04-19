"""Pydantic schemas for user-facing widget-key management.

These endpoints live on the `/api/auth/me/widget-keys` surface — per-user,
not admin. Full plaintext secrets are returned exactly once (at create time)
and never again.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class WidgetKeyCreate(BaseModel):
    """Request body for POST /api/auth/me/widget-keys."""

    name: str = Field(..., min_length=1, max_length=100, description="User label")
    scope: Literal["all_vehicles", "selected_vins"] = "all_vehicles"
    allowed_vins: list[str] | None = None

    @model_validator(mode="after")
    def _vins_required_for_selected(self) -> WidgetKeyCreate:
        if self.scope == "selected_vins":
            if not self.allowed_vins:
                raise ValueError(
                    "allowed_vins must contain at least one VIN when scope='selected_vins'"
                )
        return self


class WidgetKeySummary(BaseModel):
    """Metadata-only view of a widget key. Hash and plaintext never exposed."""

    id: int
    name: str
    key_prefix: str
    scope: str
    allowed_vins: list[str] | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class WidgetKeyCreated(WidgetKeySummary):
    """Response to creation — includes the plaintext `secret` ONCE."""

    secret: str


class WidgetKeyList(BaseModel):
    keys: list[WidgetKeySummary]
