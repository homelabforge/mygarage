"""Pydantic schemas for parts & supplies (light inventory)."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

SupplyUnitType = Literal["volume", "count"]


class SupplyBase(BaseModel):
    """Shared catalog fields."""

    name: str = Field(..., min_length=1, max_length=120)
    part_number: str | None = Field(None, max_length=60)
    category: str | None = Field(None, max_length=40)
    unit_type: SupplyUnitType = Field(..., description="volume (stored L) or count")
    vin: str | None = Field(
        None, max_length=17, description="Pin to a vehicle; null = shared across all"
    )
    notes: str | None = Field(None, max_length=5000)


class SupplyCreate(SupplyBase):
    """Create a catalog supply."""


class SupplyUpdate(BaseModel):
    """Patch a catalog supply. unit_type is intentionally immutable (ledger interpretation)."""

    name: str | None = Field(None, min_length=1, max_length=120)
    part_number: str | None = Field(None, max_length=60)
    category: str | None = Field(None, max_length=40)
    vin: str | None = Field(None, max_length=17)
    notes: str | None = Field(None, max_length=5000)
    is_active: bool | None = Field(None, description="false = archive, true = restore")


class SupplyResponse(SupplyBase):
    """Catalog row with ledger-derived on-hand + average cost."""

    id: int
    is_active: bool
    on_hand: Decimal = Field(description="Σ purchases − Σ usages, canonical units")
    avg_unit_cost: Decimal | None = Field(
        None, description="Lifetime weighted avg per canonical unit; null if no costed purchases"
    )
    is_negative: bool = Field(description="on_hand < 0 (logged usage exceeds recorded purchases)")
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SupplyListResponse(BaseModel):
    supplies: list[SupplyResponse]
    total: int


class SupplyReceiptSummary(BaseModel):
    id: int
    file_type: str | None = None

    model_config = {"from_attributes": True}


class SupplyPurchaseCreate(BaseModel):
    date: date_type
    quantity: Decimal = Field(..., gt=0, description="Canonical units (L or count)")
    total_cost: Decimal | None = Field(None, ge=0)
    supplier_id: int | None = None
    part_number: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=5000)


class SupplyPurchaseResponse(BaseModel):
    id: int
    supply_id: int
    date: date_type
    quantity: Decimal
    total_cost: Decimal | None = None
    supplier_id: int | None = None
    part_number: str | None = None
    notes: str | None = None
    created_at: datetime
    receipt: SupplyReceiptSummary | None = None

    model_config = {"from_attributes": True}


class SupplyAdjustmentCreate(BaseModel):
    """A standalone stock-out (not tied to a service line item)."""

    quantity: Decimal = Field(..., gt=0, description="Canonical units")


class SupplyUsageInput(BaseModel):
    """Consume-picker input carried on a service line item."""

    supply_id: int
    quantity: Decimal = Field(..., gt=0, description="Canonical units (L or count)")


class SupplyUsageResponse(BaseModel):
    id: int
    supply_id: int
    supply_name: str
    unit_type: SupplyUnitType = Field(
        description="Owning supply's unit_type — lets read-only views convert the "
        "canonical quantity to display units (L↔qt) instead of showing raw liters"
    )
    quantity: Decimal
    unit_cost_snapshot: Decimal | None = None
    cost_snapshot: Decimal | None = None
    service_line_item_id: int | None = None
    service_visit_id: int | None = Field(
        None, description="Owning service visit (null for standalone adjustments) — R1-H3"
    )
    service_visit_date: date_type | None = Field(
        None, description="Owning visit's date; the real consumption date (not created_at)"
    )
    created_at: datetime

    model_config = {"from_attributes": True}


class SupplyLedgerEntry(BaseModel):
    entry_type: Literal["purchase", "usage"]
    id: int
    at: datetime = Field(
        description="Effective ledger date: purchase.date (midnight), a job usage's OWNING "
        "VISIT date, or a standalone adjustment's created_at (R1-H3 ordering)"
    )
    quantity: Decimal = Field(description="signed: + for purchase, − for usage")
    running_balance: Decimal
    cost: Decimal | None = Field(None, description="purchase total_cost or usage cost_snapshot")
    supplier_id: int | None = None
    service_line_item_id: int | None = None
    service_visit_id: int | None = Field(None, description="Owning visit for a job usage")
    service_visit_date: date_type | None = None
    receipt: SupplyReceiptSummary | None = Field(
        None, description="Receipt metadata for a purchase entry (R1-H4)"
    )


class SupplyHistoryResponse(BaseModel):
    supply_id: int
    on_hand: Decimal
    avg_unit_cost: Decimal | None = None
    entries: list[SupplyLedgerEntry]


class VehicleSupplyUsagesResponse(BaseModel):
    usages: list[SupplyUsageResponse]
    total: int
