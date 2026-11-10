"""Pydantic schemas for tax/registration records."""

from datetime import date as date_type
from datetime import datetime as datetime_type
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, ValidationInfo, field_validator

from app.constants.tax import TAX_TYPE_VALUES, normalize_tax_type
from app.schemas._money import Money, OptionalMoney
from app.schemas._nullability import reject_null
from app.utils.lenient_vocab import LenientVocab, lenient_reader

#: The codes of `app.constants.tax.TAX_TYPE_VALUES`, spelt out for the type
#: checker and the OpenAPI document; `test_tax_types` keeps the two in step.
TaxType = Literal[
    "registration",
    "registration_tax",
    "co2_malus",
    "weight_malus",
    "circulation_tax",
    "company_vehicle_tax",
    "inspection",
    "property_tax",
    "tolls",
    "vignette",
    "lez_sticker",
    "parking_permit",
    "other",
]
assert set(TaxType.__args__) == set(TAX_TYPE_VALUES)  # type: ignore[attr-defined]


def _accept_legacy(value: object) -> object:
    """A legacy display string (`Property Tax`) or a differently cased code
    means its code; anything else is left for the Literal to refuse."""
    return normalize_tax_type(value) if isinstance(value, str) else value


_read_known = lenient_reader(TaxType)


def _read_tax_type(value: object, info: ValidationInfo) -> object:
    """Read a stored value: a legacy string as its code, an unknown one as null."""
    return _read_known(_accept_legacy(value), info)


# `tax_records.tax_type` has had no CHECK since migration 146, so a value a
# restore or a hand edit put there reads as null instead of 500ing the list.
LenientTaxType = Annotated[TaxType | None, BeforeValidator(_read_tax_type), LenientVocab(None)]


_TAX_TYPE_DESCRIPTION = (
    "Type of tax/fee, as a code. The pre-146 display strings "
    "(Registration, Inspection, Property Tax, Tolls) are accepted as their codes."
)


class TaxRecordBase(BaseModel):
    """Base tax record schema."""

    date: date_type = Field(..., description="Date the fee was paid")
    tax_type: TaxType | None = Field(default=None, description=_TAX_TYPE_DESCRIPTION)
    amount: Money = Field(..., description="Amount paid")
    renewal_date: date_type | None = Field(default=None, description="Next renewal date")
    notes: str | None = None


class TaxRecordCreate(TaxRecordBase):
    """Schema for creating a tax record."""

    vin: str = Field(..., max_length=17)

    _legacy_tax_type = field_validator("tax_type", mode="before")(_accept_legacy)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "tax_type": "registration",
                    "amount": 85.50,
                    "renewal_date": "2026-01-15",
                    "notes": "Annual vehicle registration renewal",
                }
            ]
        }
    }


class TaxRecordUpdate(BaseModel):
    """Schema for updating a tax record."""

    date: date_type | None = None
    tax_type: TaxType | None = None
    amount: OptionalMoney = None
    renewal_date: date_type | None = None
    notes: str | None = None

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("date", "amount")

    _legacy_tax_type = field_validator("tax_type", mode="before")(_accept_legacy)


class TaxRecordResponse(TaxRecordBase):
    """Schema for tax record response."""

    # The same field as the base's, read leniently (the twin keeps the description).
    tax_type: LenientTaxType = Field(default=None, description=_TAX_TYPE_DESCRIPTION)
    # Money without the input bounds, so a stored amount past today's rules
    # still reads instead of 500ing (test_response_contract).
    amount: Decimal = Field(..., description="Amount paid")
    id: int
    vin: str
    created_at: datetime_type

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "tax_type": "registration",
                    "amount": 85.50,
                    "renewal_date": "2026-01-15",
                    "notes": "Annual vehicle registration renewal",
                    "created_at": "2025-01-15T10:30:00",
                }
            ]
        },
    }


class TaxRecordListResponse(BaseModel):
    """Schema for list of tax records."""

    records: list[TaxRecordResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "records": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2025-01-15",
                            "tax_type": "registration",
                            "amount": 85.50,
                            "renewal_date": "2026-01-15",
                            "notes": "Annual vehicle registration renewal",
                            "created_at": "2025-01-15T10:30:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }
