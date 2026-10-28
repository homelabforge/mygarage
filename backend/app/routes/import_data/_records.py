"""Financing, tax, toll, warranty and spot rental rows from a JSON backup."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import ColumnElement

from app.models import (
    FinancingRecord,
    SpotRental,
    SpotRentalBilling,
    TaxRecord,
    TollTag,
    TollTransaction,
    WarrantyRecord,
)
from app.routes.import_data._common import (
    _FINANCING_CATEGORIES,
    _TAX_TYPES,
    _TOLL_TAG_STATUSES,
    _WARRANTY_TYPES,
    _blank_to_none,
    _in_vocabulary,
    _json_decimal,
    _json_optional_date,
    _json_row_date,
    _json_text,
    _RowError,
    _within_api_bounds,
    _within_length,
)
from app.routes.import_data._matching import (
    _MONEY_STEP,
    _at_scale,
    _matches,
    _money_matches,
    _same_figure,
    _text_matches,
)
from app.schemas.financing import FinancingRecordCreate
from app.schemas.spot_rental import SpotRentalCreate
from app.schemas.spot_rental_billing import SpotRentalBillingCreate
from app.schemas.tax import TaxRecordCreate
from app.schemas.toll import (
    TollTransactionCreate,
    normalize_toll_system_name,
    tidy_toll_system_name,
)
from app.schemas.warranty import WarrantyRecordCreate


def _json_amount(row: Mapping[str, Any]) -> Decimal:
    """A row's required `amount`; a missing one is a row error.

    Each caller names its schema to `_within_api_bounds` itself, so
    test_money_input_bounds reads the call from the source and checks that
    schema's bounds.
    """
    amount = _json_decimal(row, "amount")
    if amount is None:
        raise _RowError("amount is missing")
    return amount


def _financing_record_from_json(vin: str, row: Mapping[str, Any]) -> FinancingRecord:
    """A v9 financing row as an unsaved record, the API's rules re-applied (R2).

    The lender travels by name; the caller looks it up or makes it in the
    row's savepoint (R6).
    """
    date = _json_row_date(row)
    amount = _json_amount(row)
    _within_api_bounds(FinancingRecordCreate, amount=amount)
    category = _in_vocabulary(
        _blank_to_none(row.get("category")), "category", _FINANCING_CATEGORIES
    )
    if category is None:
        raise _RowError("category is missing")
    return FinancingRecord(
        vin=vin, date=date, amount=amount, category=category, notes=_json_text(row, "notes")
    )


def _json_financing_key(record: FinancingRecord) -> list[ColumnElement[bool]]:
    """R5's financing key but the lender, which the caller compares on the loaded rows."""
    return [
        FinancingRecord.date == record.date,
        _money_matches(FinancingRecord.amount, record.amount),
        FinancingRecord.category == record.category,
    ]


def _tax_record_from_json(vin: str, row: Mapping[str, Any]) -> TaxRecord:
    """A v9 tax row as an unsaved record. No type is allowed: NULL passes the CHECK."""
    date = _json_row_date(row)
    tax_type = _in_vocabulary(_blank_to_none(row.get("tax_type")), "tax_type", _TAX_TYPES)
    amount = _json_amount(row)
    _within_api_bounds(TaxRecordCreate, amount=amount)
    return TaxRecord(
        vin=vin,
        date=date,
        tax_type=tax_type,
        amount=amount,
        renewal_date=_json_optional_date(row, "renewal_date"),
        notes=_json_text(row, "notes"),
    )


def _json_tax_key(row: Mapping[str, Any], record: TaxRecord) -> list[ColumnElement[bool]]:
    """R5's tax key, each optional part only when the row has it (T-16).

    A type-less row matches a stored NULL type, so it dedups too.
    """
    key = [TaxRecord.date == record.date, _money_matches(TaxRecord.amount, record.amount)]
    if "tax_type" in row:
        key.append(_matches(TaxRecord.tax_type, record.tax_type))
    if "renewal_date" in row:
        key.append(_matches(TaxRecord.renewal_date, record.renewal_date))
    return key


def _toll_system_name(raw: str) -> str:
    """A toll system under its listed name: the create schema's tidy, then its alias map.

    A stored name goes through it too: the update path kept "ezpass" as typed
    until it normalized, and no migration renamed the rows, so a stored and a
    file name compare only once both are listed names.
    """
    return normalize_toll_system_name(tidy_toll_system_name(raw))


def _toll_tag_from_json(vin: str, row: Mapping[str, Any]) -> TollTag:
    """A v9 toll tag as an unsaved record, its system named as the create schema names it.

    The schema's steps in its order: tidy the whitespace, hold the length,
    then map a spelling people type to the listed name (schemas/toll.py).
    """
    raw_system = _json_text(row, "toll_system")
    if raw_system is None:
        raise _RowError("toll_system is missing")
    _within_length(tidy_toll_system_name(raw_system), "toll_system", 50)
    tag_number = _json_text(row, "tag_number", max_length=50)
    if tag_number is None:
        raise _RowError("tag_number is missing")
    status = _in_vocabulary(_blank_to_none(row.get("status")), "status", _TOLL_TAG_STATUSES)
    return TollTag(
        vin=vin,
        toll_system=_toll_system_name(raw_system),
        tag_number=tag_number,
        status=status or "active",
        notes=_json_text(row, "notes"),
    )


def _toll_tag_key(tag: TollTag | None) -> tuple[str, str] | None:
    """A tag as a transaction's key names it: its listed system and number, None for no tag."""
    return (_toll_system_name(tag.toll_system), tag.tag_number) if tag is not None else None


def _toll_transaction_from_json(
    vin: str, row: Mapping[str, Any], tag_count: int
) -> tuple[TollTransaction, int | None]:
    """A v9 toll as an unsaved record, and the index of its tag in the file's toll_tags."""
    date = _json_row_date(row)
    amount = _json_amount(row)
    _within_api_bounds(TollTransactionCreate, amount=amount)
    location = _json_text(row, "location", max_length=200)
    if location is None:
        raise _RowError("location is missing")
    index = row.get("toll_tag_index")
    if index is not None and (
        isinstance(index, bool) or not isinstance(index, int) or index not in range(tag_count)
    ):
        raise _RowError("toll_tag_index must be the index of a toll tag in this file")
    record = TollTransaction(
        vin=vin, date=date, amount=amount, location=location, notes=_json_text(row, "notes")
    )
    return record, index


def _json_toll_transaction_key(record: TollTransaction) -> list[ColumnElement[bool]]:
    """R5's toll key but the tag, which the caller compares on the loaded rows."""
    return [
        TollTransaction.date == record.date,
        _money_matches(TollTransaction.amount, record.amount),
        TollTransaction.location == record.location,
    ]


def _warranty_from_json(vin: str, row: Mapping[str, Any]) -> WarrantyRecord:
    """A v9 warranty as an unsaved record, its type held to the CHECK's list (R2)."""
    warranty_type = _blank_to_none(row.get("warranty_type"))
    if warranty_type is None:
        raise _RowError("warranty_type is missing")
    warranty_type = _in_vocabulary(warranty_type, "warranty_type", _WARRANTY_TYPES)
    start_date = _json_row_date(row, "start_date")
    mileage_limit_km = _json_decimal(row, "mileage_limit_km")
    _within_api_bounds(WarrantyRecordCreate, mileage_limit_km=mileage_limit_km)
    return WarrantyRecord(
        vin=vin,
        warranty_type=warranty_type,
        provider=_json_text(row, "provider"),
        start_date=start_date,
        end_date=_json_optional_date(row, "end_date"),
        mileage_limit_km=mileage_limit_km,
        coverage_details=_json_text(row, "coverage_details"),
        policy_number=_json_text(row, "policy_number"),
        notes=_json_text(row, "notes"),
    )


def _json_warranty_key(row: Mapping[str, Any], record: WarrantyRecord) -> list[ColumnElement[bool]]:
    """R5's warranty key, each optional part only when the row has it (T-16).

    The mileage limit is NUMERIC(10,2): 36,000 mi is 57936.384 km, which a legacy
    SQLite row may still hold (see `_same_figure`). It exports as 57936.38, so it
    matches within half a cent (T-20).
    """
    key = [
        WarrantyRecord.warranty_type == record.warranty_type,
        WarrantyRecord.start_date == record.start_date,
    ]
    if "provider" in row:
        key.append(_text_matches(WarrantyRecord.provider, record.provider))
    if "end_date" in row:
        key.append(_matches(WarrantyRecord.end_date, record.end_date))
    if "policy_number" in row:
        key.append(_text_matches(WarrantyRecord.policy_number, record.policy_number))
    if "mileage_limit_km" in row:
        key.append(_same_figure(WarrantyRecord.mileage_limit_km, record.mileage_limit_km))
    return key


def _billing_from_json(position: int, bill: Any) -> SpotRentalBilling:
    """One v9 bill as an unsaved record; the caller sets its rental once that has an id.

    Its date isn't held to the stay: editing a rental moves the stay and leaves
    its bills where they were, so a backup can carry that and restores it (C-4).
    A row error names the bill by `position`.
    """
    try:
        if not isinstance(bill, Mapping):
            raise _RowError("must be an object")
        bill = cast(Mapping[str, Any], bill)
        billing_date = _json_row_date(bill, "billing_date")
        monthly_rate = _json_decimal(bill, "monthly_rate")
        electric = _json_decimal(bill, "electric")
        water = _json_decimal(bill, "water")
        waste = _json_decimal(bill, "waste")
        total = _json_decimal(bill, "total")
        _within_api_bounds(
            SpotRentalBillingCreate,
            monthly_rate=monthly_rate,
            electric=electric,
            water=water,
            waste=waste,
            total=total,
        )
        notes = _json_text(bill, "notes", max_length=1000)
    except _RowError as e:
        raise _RowError(f"billing {position}: {e.reason}") from e
    return SpotRentalBilling(
        billing_date=billing_date,
        monthly_rate=monthly_rate,
        electric=electric,
        water=water,
        waste=waste,
        total=total,
        notes=notes,
    )


def _spot_rental_from_json(
    vin: str, row: Mapping[str, Any]
) -> tuple[SpotRental, list[SpotRentalBilling]]:
    """A v9 rental and its bills as unsaved records, the API's rules re-applied (R2).

    No vehicle-type gate and no invented first bill: a backup restores whole,
    with the bills it carries (T-7).
    """
    check_in_date = _json_row_date(row, "check_in_date")
    check_out_date = _json_optional_date(row, "check_out_date")
    nightly_rate = _json_decimal(row, "nightly_rate")
    weekly_rate = _json_decimal(row, "weekly_rate")
    monthly_rate = _json_decimal(row, "monthly_rate")
    electric = _json_decimal(row, "electric")
    water = _json_decimal(row, "water")
    waste = _json_decimal(row, "waste")
    total_cost = _json_decimal(row, "total_cost")
    _within_api_bounds(
        SpotRentalCreate,
        nightly_rate=nightly_rate,
        weekly_rate=weekly_rate,
        monthly_rate=monthly_rate,
        electric=electric,
        water=water,
        waste=waste,
        total_cost=total_cost,
    )
    location_name = _json_text(row, "location_name", max_length=100)
    # An absent key is no bills (T-16); the caller then leaves them out of the key.
    raw_bills = row.get("billings", [])
    if not isinstance(raw_bills, list):
        raise _RowError("billings must be a list")
    bills = [
        _billing_from_json(position, bill)
        for position, bill in enumerate(cast(list[Any], raw_bills))
    ]
    rental = SpotRental(
        vin=vin,
        location_name=location_name,
        location_address=_json_text(row, "location_address"),
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        nightly_rate=nightly_rate,
        weekly_rate=weekly_rate,
        monthly_rate=monthly_rate,
        electric=electric,
        water=water,
        waste=waste,
        total_cost=total_cost,
        amenities=_json_text(row, "amenities"),
        notes=_json_text(row, "notes"),
    )
    return rental, bills


def _json_spot_rental_key(row: Mapping[str, Any], rental: SpotRental) -> list[ColumnElement[bool]]:
    """R5's rental key but the bills, each optional part only when the row has it (T-16)."""
    key = [SpotRental.check_in_date == rental.check_in_date]
    if "location_name" in row:
        key.append(_text_matches(SpotRental.location_name, rental.location_name))
    if "check_out_date" in row:
        key.append(_matches(SpotRental.check_out_date, rental.check_out_date))
    if "total_cost" in row:
        key.append(_money_matches(SpotRental.total_cost, rental.total_cost))
    # C-2: the rental's own rates and utilities, like a bill's amounts.
    for name in _RENTAL_AMOUNTS:
        if name in row:
            key.append(_money_matches(getattr(SpotRental, name), getattr(rental, name)))
    if "location_address" in row:
        key.append(_text_matches(SpotRental.location_address, rental.location_address))
    return key


#: The amounts a v9 export writes on a rental besides its total.
_RENTAL_AMOUNTS = ("nightly_rate", "weekly_rate", "monthly_rate", "electric", "water", "waste")


#: Every amount a v9 export writes on a bill. Two bills with one total can
#: split it differently, and that's another bill (R1-H2).
_BILL_AMOUNTS = ("monthly_rate", "electric", "water", "waste", "total")


def _bill_counts(
    bills: Iterable[SpotRentalBilling], amounts: Sequence[str]
) -> Counter[tuple[Any, ...]]:
    """A rental's bills as counts of their date and `amounts`, each at the cent, a missing one as 0."""
    return Counter(
        (
            bill.billing_date,
            *(_at_scale(getattr(bill, name), _MONEY_STEP) or Decimal(0) for name in amounts),
        )
        for bill in bills
    )
