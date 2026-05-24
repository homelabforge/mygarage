"""Truth-table assertions for required-field rules on pydantic input schemas.

What this catches
-----------------
The rc1 fuel form let users save records with neither odometer nor fuel
amount because both fields were ``Optional`` in the pydantic schema.
The form's required-field rule lived in frontend code, not the schema,
so backend tests never failed even when the contract was broken.

This module pins each input schema's required-field set in a declared
truth table. Adding a required field that's not in the table → test
fails. Removing a required field that IS in the table → test fails.
Either change must be deliberate.

What this does NOT catch
------------------------
Cross-field rules (e.g. "either liters OR kwh OR propane_liters must
be present"). Those are encoded as ``model_validator`` on the schema
itself; this test only inspects field-level ``required`` flags. Phase
2.1 lands a model validator for the fuel cross-field rule, with its
own dedicated unit test.

Adding new schemas
------------------
Append a ``RequiredFieldsCase`` to ``REQUIRED_FIELD_CASES``. Set
``expected_required`` to the set of field names that MUST be supplied
when constructing the schema. Pydantic considers a field required when
it has no default and no ``= None`` annotation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from app.schemas.address_book import AddressBookEntryCreate
from app.schemas.def_record import DEFRecordCreate
from app.schemas.fuel import FuelRecordCreate, FuelRecordUpdate
from app.schemas.insurance import InsurancePolicyCreate
from app.schemas.note import NoteCreate
from app.schemas.odometer import OdometerRecordCreate
from app.schemas.service_visit import (
    ReminderCreate,
    ServiceLineItemCreate,
    ServiceVisitCreate,
)
from app.schemas.warranty import WarrantyRecordCreate


@dataclass
class RequiredFieldsCase:
    schema: type[BaseModel]
    expected_required: set[str]


# Truth table — the required-field set for each input schema.
# Phase 4.4 backfills the broader matrix beyond just FuelRecordCreate.
REQUIRED_FIELD_CASES: list[RequiredFieldsCase] = [
    # FuelRecordCreate requires only vin + date at the FIELD level. The
    # cross-field rule (need odometer + at least one fuel-amount unless
    # missed_fillup) lives in a model_validator and is exercised in
    # tests/unit/schemas/test_fuel_schema.py.
    RequiredFieldsCase(
        schema=FuelRecordCreate,
        expected_required={"vin", "date"},
    ),
    # FuelRecordUpdate is a partial update — nothing is required.
    RequiredFieldsCase(
        schema=FuelRecordUpdate,
        expected_required=set(),
    ),
    RequiredFieldsCase(
        schema=ServiceVisitCreate,
        expected_required={"date", "line_items"},
    ),
    RequiredFieldsCase(
        schema=ServiceLineItemCreate,
        expected_required={"description"},
    ),
    RequiredFieldsCase(
        schema=ReminderCreate,
        expected_required={"reminder_type", "title"},
    ),
    RequiredFieldsCase(
        schema=InsurancePolicyCreate,
        expected_required={
            "end_date",
            "policy_number",
            "policy_type",
            "provider",
            "start_date",
        },
    ),
    RequiredFieldsCase(
        schema=WarrantyRecordCreate,
        expected_required={"start_date", "warranty_type"},
    ),
    RequiredFieldsCase(
        schema=AddressBookEntryCreate,
        expected_required={"business_name"},
    ),
    RequiredFieldsCase(
        schema=OdometerRecordCreate,
        expected_required={"date", "odometer_km", "vin"},
    ),
    RequiredFieldsCase(
        schema=NoteCreate,
        expected_required={"content", "date", "vin"},
    ),
    RequiredFieldsCase(
        schema=DEFRecordCreate,
        expected_required={"date", "vin"},
    ),
]


def _required_fields(schema: type[BaseModel]) -> set[str]:
    """Return the set of field names that MUST be supplied when creating
    an instance of the schema."""
    return {name for name, field in schema.model_fields.items() if field.is_required()}


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    REQUIRED_FIELD_CASES,
    ids=lambda c: c.schema.__name__,
)
def test_schema_required_fields(case: RequiredFieldsCase):
    """Required-field set must match the declared truth table."""
    actual = _required_fields(case.schema)
    expected = case.expected_required

    extra = actual - expected
    missing = expected - actual

    assert not extra, (
        f"{case.schema.__name__} requires fields not in the truth table: "
        f"{sorted(extra)}. If intentional, add them to expected_required."
    )
    assert not missing, (
        f"{case.schema.__name__} no longer requires fields the truth table claims: "
        f"{sorted(missing)}. If intentional, remove from expected_required."
    )


@pytest.mark.unit
def test_required_field_truth_table_lists_only_real_fields():
    """Catches typos in expected_required after a field rename."""
    for case in REQUIRED_FIELD_CASES:
        all_fields: set[str] = set(case.schema.model_fields.keys())
        bogus = case.expected_required - all_fields
        assert not bogus, (
            f"{case.schema.__name__}.expected_required contains names that "
            f"are not declared on the schema: {sorted(bogus)}"
        )
