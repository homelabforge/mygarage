"""Unit tests for financing record schemas."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas._money import MONEY_MAX
from app.schemas.financing import (
    FinancingRecordCreate,
    FinancingRecordResponse,
    FinancingRecordUpdate,
)


def test_financing_record_create_accepts_valid_category():
    record = FinancingRecordCreate(
        vin="1HGBH41JXMN109186",
        date=dt.date(2026, 1, 1),
        amount=Decimal("450.00"),
        category="lease_payment",
    )
    assert record.category == "lease_payment"


def test_financing_record_create_rejects_invalid_category():
    with pytest.raises(ValidationError):
        FinancingRecordCreate.model_validate(
            {
                "vin": "1HGBH41JXMN109186",
                "date": dt.date(2026, 1, 1),
                "amount": Decimal("450.00"),
                "category": "not_a_real_category",
            }
        )


def test_financing_record_create_rejects_negative_amount():
    with pytest.raises(ValidationError):
        FinancingRecordCreate(
            vin="1HGBH41JXMN109186",
            date=dt.date(2026, 1, 1),
            amount=Decimal("-1.00"),
            category="loan_payment",
        )


def test_financing_record_create_rejects_amount_above_max():
    # The max is what the column holds, so a forint or yen payment fits.
    top = FinancingRecordCreate(
        vin="1HGBH41JXMN109186",
        date=dt.date(2026, 1, 1),
        amount=MONEY_MAX,
        category="loan_payment",
    )
    assert top.amount == MONEY_MAX
    with pytest.raises(ValidationError):
        FinancingRecordCreate(
            vin="1HGBH41JXMN109186",
            date=dt.date(2026, 1, 1),
            amount=MONEY_MAX + Decimal("0.01"),
            category="loan_payment",
        )


def test_financing_record_create_rejects_amount_with_too_many_decimal_places():
    with pytest.raises(ValidationError):
        FinancingRecordCreate(
            vin="1HGBH41JXMN109186",
            date=dt.date(2026, 1, 1),
            amount=Decimal("450.001"),
            category="loan_payment",
        )


def test_financing_record_update_all_fields_optional():
    update = FinancingRecordUpdate()
    assert update.amount is None
    assert update.category is None


def test_financing_record_response_from_attributes():
    class _FakeORMRecord:
        id = 1
        vin = "1HGBH41JXMN109186"
        date = dt.date(2026, 1, 1)
        amount = Decimal("450.00")
        category = "lease_payment"
        vendor_id = None
        notes = None
        created_at = dt.datetime(2026, 1, 1, 10, 0, 0)
        updated_at = None

    response = FinancingRecordResponse.model_validate(_FakeORMRecord())
    assert response.id == 1
    assert response.category == "lease_payment"
    assert response.lender is None


def test_financing_record_response_lender_from_vendor_relationship():
    class _FakeVendor:
        id = 7
        name = "Acme Auto Finance"
        city = "Austin"
        state = "TX"

    class _FakeORMRecord:
        id = 2
        vin = "1HGBH41JXMN109186"
        date = dt.date(2026, 1, 1)
        amount = Decimal("450.00")
        category = "lease_payment"
        vendor_id = 7
        vendor = _FakeVendor()
        notes = None
        created_at = dt.datetime(2026, 1, 1, 10, 0, 0)
        updated_at = None

    response = FinancingRecordResponse.model_validate(_FakeORMRecord())
    assert response.lender is not None
    assert response.lender.name == "Acme Auto Finance"
    assert response.lender.city == "Austin"
