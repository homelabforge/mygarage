"""Pydantic schemas for parts & supplies (light inventory)."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null
from app.utils.lenient_vocab import LenientVocab, lenient_reader

SupplyUnitType = Literal["volume", "count"]
SupplyVolumeUnit = Literal["mL", "L", "fl_oz_us", "fl_oz_uk", "qt_us", "qt_uk", "gal_us", "gal_uk"]

# Responses only: the column has no CHECK, so an odd stored token reads as null
# (the legacy binary pick) instead of 500ing the list.
LenientSupplyVolumeUnit = Annotated[
    SupplyVolumeUnit | None, BeforeValidator(lenient_reader(SupplyVolumeUnit)), LenientVocab(None)
]

#: The largest quantity a Numeric(25,13) supply ledger column holds (purchases
#: and usages alike). What the column holds and no tighter: a household cap
#: would be invented, and past the column PostgreSQL refuses the row. SQLite
#: keeps it as a REAL, so the max and any entry of 16+ significant digits read
#: back with noise in the last digit, and OpenAPI renders it as the float 1e12.
SUPPLY_QUANTITY_MAX = Decimal("999999999999.9999999999999")
#: The column's grain. 13 places hold a US fl oz (0.0295735295625 L) and every
#: other supported unit exactly, so a typed amount reads back as typed.
SUPPLY_QUANTITY_GRAIN = Decimal("1E-13")
#: The smallest amount the ledger takes: 1 mL, or a thousandth of a count. A
#: product rule, not the column's limit; the history modal checks the same.
SUPPLY_QUANTITY_MIN = Decimal("0.001")


class SupplyBase(BaseModel):
    """Shared catalog fields."""

    name: str = Field(..., min_length=1, max_length=120)
    part_number: str | None = Field(None, max_length=60)
    barcode: str | None = Field(None, max_length=64, description="UPC/EAN/QR product barcode")
    category: str | None = Field(None, max_length=40)
    unit_type: SupplyUnitType = Field(..., description="volume (stored L) or count")
    vin: str | None = Field(
        None, max_length=17, description="Pin to a vehicle; null = shared across all"
    )
    notes: str | None = Field(None, max_length=5000)


class SupplyCreate(SupplyBase):
    """Create a catalog supply."""

    volume_unit: SupplyVolumeUnit | None = Field(
        None, description="Per-supply display unit for a volume supply; null = legacy binary pick"
    )

    @model_validator(mode="after")
    def _count_has_no_volume_unit(self) -> SupplyCreate:
        """A count supply has nothing to measure in a volume unit."""
        if self.unit_type == "count" and self.volume_unit is not None:
            raise ValueError("A count supply cannot carry a volume unit")
        return self


class SupplyUpdate(BaseModel):
    """Patch a catalog supply. unit_type is intentionally immutable (ledger interpretation)."""

    name: str | None = Field(None, min_length=1, max_length=120)
    part_number: str | None = Field(None, max_length=60)
    barcode: str | None = Field(None, max_length=64)
    category: str | None = Field(None, max_length=40)
    vin: str | None = Field(None, max_length=17)
    notes: str | None = Field(None, max_length=5000)
    is_active: bool | None = Field(None, description="false = archive, true = restore")
    volume_unit: SupplyVolumeUnit | None = Field(
        None, description="Omitted keeps the stored unit; null clears back to the legacy pick"
    )

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("name", "is_active")


class SupplyResponse(SupplyBase):
    """Catalog row with ledger-derived on-hand + average cost."""

    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    name: str
    part_number: str | None = None
    barcode: str | None = Field(None, description="UPC/EAN/QR product barcode")
    category: str | None = None
    vin: str | None = Field(None, description="Pin to a vehicle; null = shared across all")
    notes: str | None = None
    id: int
    is_active: bool
    on_hand: Decimal = Field(description="Σ purchases − Σ usages, canonical units")
    avg_unit_cost: Decimal | None = Field(
        None, description="Lifetime weighted avg per canonical unit; null if no costed purchases"
    )
    is_negative: bool = Field(description="on_hand < 0 (logged usage exceeds recorded purchases)")
    created_at: datetime
    updated_at: datetime | None = None
    volume_unit: LenientSupplyVolumeUnit = Field(
        None, description="Per-supply display unit; null means the legacy binary pick"
    )

    model_config = {"from_attributes": True}


class SupplyListResponse(BaseModel):
    supplies: list[SupplyResponse]
    total: int


class SupplyReceiptSummary(BaseModel):
    id: int
    file_type: str | None = None

    model_config = {"from_attributes": True}


def _storable_quantity(value: Decimal) -> Decimal:
    """The quantity at the column's 13 places, so the response echoes what's
    stored. Anything under 1 mL (0.001) is refused: too small to be a real
    measurement, and the history modal won't send it either."""
    quantized = value.quantize(SUPPLY_QUANTITY_GRAIN, rounding=ROUND_HALF_UP)
    if quantized < SUPPLY_QUANTITY_MIN:
        raise ValueError("quantity is below the smallest amount tracked (0.001, 1 mL)")
    return quantized


class SupplyPurchaseCreate(BaseModel):
    date: date_type
    quantity: Decimal = Field(
        ..., gt=0, le=SUPPLY_QUANTITY_MAX, description="Canonical units (L or count)"
    )
    total_cost: OptionalMoney = None
    supplier_id: int | None = None
    part_number: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=5000)

    _quantity_grain = field_validator("quantity")(_storable_quantity)


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

    quantity: Decimal = Field(..., gt=0, le=SUPPLY_QUANTITY_MAX, description="Canonical units")

    _quantity_grain = field_validator("quantity")(_storable_quantity)


class SupplyUsageInput(BaseModel):
    """Consume-picker input carried on a service line item."""

    supply_id: int
    quantity: Decimal = Field(
        ..., gt=0, le=SUPPLY_QUANTITY_MAX, description="Canonical units (L or count)"
    )

    _quantity_grain = field_validator("quantity")(_storable_quantity)


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
    volume_unit: LenientSupplyVolumeUnit = Field(
        None, description="Per-supply display unit; null means the legacy binary pick"
    )

    model_config = {"from_attributes": True}


class SupplyLedgerEntry(BaseModel):
    entry_type: Literal["purchase", "usage"]
    id: int
    at: datetime = Field(
        description="Effective ledger time on the household clock, with its offset: "
        "purchase.date (midnight), a job usage's OWNING VISIT date (midnight), or a "
        "standalone adjustment's created_at (R1-H3 ordering)"
    )
    ledger_date: date_type = Field(
        description="The household calendar day the entry falls on (the date of `at`)"
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
