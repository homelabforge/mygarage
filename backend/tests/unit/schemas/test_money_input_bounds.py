"""Every money input takes the policy bounds, whatever the viewer's currency.

Records carry no currency, so an amount is a bare number and its bound can only
mean "fits the column": 0 to MONEY_MAX for money, 0 to UNIT_PRICE_MAX for a
price per unit. The old caps were dollar-sized, so an ordinary forint fill-up or
a yen nightly rate got a 422.

The walk takes every request body the router accepts, nested models included,
so a new money input fails here until it has a row in `CASES`. Each row then
goes through pydantic at its own maximum, one step past it, and one step below
zero. The importers read the same bounds off the FieldInfo through
`_within_api_bounds`, so the schemas they pass it are held to them too.
"""

import ast
import inspect
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from fastapi import Body, Depends, FastAPI, Query
from fastapi._compat import ModelField
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from starlette.routing import BaseRoute

from app.main import app
from app.routes.import_data import _ImportBoundError, _within_api_bounds
from app.routes.window_sticker import WindowStickerDataUpdate
from app.schemas._money import MONEY_MAX, UNIT_PRICE_MAX
from app.schemas.def_record import DEFRecordCreate, DEFRecordUpdate
from app.schemas.financing import FinancingRecordCreate, FinancingRecordUpdate
from app.schemas.fuel import FuelRecordCreate, FuelRecordUpdate
from app.schemas.insurance import (
    CoverageEntry,
    InsurancePolicyCreate,
    InsurancePolicyRenew,
    InsurancePolicyReplace,
    InsurancePolicyUpdate,
    PolicyVehicleCreate,
    PolicyVehicleUpdate,
    PolicyVehicleUpsert,
)
from app.schemas.maintenance import ReminderCompleteRequest
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceLineItemUpdate,
    ServiceVisitCreate,
    ServiceVisitUpdate,
)
from app.schemas.spot_rental import SpotRentalCreate, SpotRentalUpdate
from app.schemas.spot_rental_billing import SpotRentalBillingCreate, SpotRentalBillingUpdate
from app.schemas.supply import SupplyPurchaseCreate
from app.schemas.tax import TaxRecordCreate, TaxRecordUpdate
from app.schemas.toll import TollTransactionCreate, TollTransactionUpdate
from app.schemas.vehicle import (
    VehicleArchiveRequest,
    VehicleBulkArchiveRequest,
    VehicleCreate,
    VehicleUpdate,
)
from app.services.fuel_ingest import WebhookFuelPayload
from tests._importer_source import importer_modules
from tests.unit.schemas._money_names import MONEY_COLUMN_NAMES, is_money_name
from tests.unit.schemas._schema_walk import unwrap, walk

CENT = Decimal("0.01")
MIL = Decimal("0.001")

#: Unit prices hold a tenth of a cent and ten times fewer whole units.
UNIT_PRICE_FIELDS = frozenset({"price_per_unit"})

VIN = "1HGBH41JXMN109186"
DAY = "2026-01-15"


def _maximum(name: str) -> Decimal:
    """The largest value the field's own column holds."""
    return UNIT_PRICE_MAX if name in UNIT_PRICE_FIELDS else MONEY_MAX


def _step(name: str) -> Decimal:
    """The smallest amount the field's own column tells apart."""
    return MIL if name in UNIT_PRICE_FIELDS else CENT


def _is_money(name: str, info: FieldInfo) -> bool:
    return unwrap(info.annotation)[0] and (is_money_name(name) or name in MONEY_COLUMN_NAMES)


def _money_names(schema: type[BaseModel]) -> tuple[str, ...]:
    return tuple(name for name, info in schema.model_fields.items() if _is_money(name, info))


# ---------------------------------------------------------------------------
# The table: every schema a request can carry money in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """A request schema, a payload it accepts as is, and its money fields."""

    schema: type[BaseModel]
    baseline: dict[str, Any]
    money: tuple[str, ...]
    # What a field needs beside it to validate at all (a coverage slot).
    with_field: dict[str, dict[str, Any]] = field(default_factory=dict)

    def payload(self, name: str, value: Decimal) -> dict[str, Any]:
        return {**self.baseline, **self.with_field.get(name, {}), name: value}


_FUEL = ("cost", "rebate", "price_per_unit")
_RENTAL = (
    "nightly_rate",
    "weekly_rate",
    "monthly_rate",
    "electric",
    "water",
    "waste",
    "total_cost",
)
_BILLING = ("monthly_rate", "electric", "water", "waste", "total")
_VISIT_FEES = ("tax_amount", "shop_supplies", "misc_fees")
_VEHICLE_PRICES = ("purchase_price", "sold_price")
_MSRP = ("msrp_base", "msrp_options", "msrp_total", "destination_charge")
_POLICY = {"provider": "Acme", "policy_number": "P-1", "start_date": DAY, "end_date": "2026-07-15"}

CASES = [
    Case(
        FuelRecordCreate,
        {"vin": VIN, "date": DAY, "odometer_km": 1000, "liters": 40},
        _FUEL,
    ),
    Case(FuelRecordUpdate, {}, _FUEL),
    Case(WebhookFuelPayload, {"vin": VIN}, ("cost", "price_per_unit")),
    Case(DEFRecordCreate, {"vin": VIN, "date": DAY}, ("cost", "price_per_unit")),
    Case(DEFRecordUpdate, {}, ("cost", "price_per_unit")),
    Case(ServiceLineItemCreate, {"description": "Oil change"}, ("cost",)),
    Case(ServiceLineItemUpdate, {"description": "Oil change"}, ("cost",)),
    Case(ReminderCompleteRequest, {"completed_date": DAY}, ("cost",)),
    Case(
        ServiceVisitCreate,
        {"date": DAY, "line_items": [{"description": "Oil change"}]},
        (*_VISIT_FEES, "total_cost"),
    ),
    Case(ServiceVisitUpdate, {}, ("total_cost", *_VISIT_FEES)),
    Case(SupplyPurchaseCreate, {"date": DAY, "quantity": 1}, ("total_cost",)),
    Case(TaxRecordCreate, {"vin": VIN, "date": DAY, "amount": 0}, ("amount",)),
    Case(TaxRecordUpdate, {}, ("amount",)),
    Case(
        TollTransactionCreate,
        {"vin": VIN, "transaction_date": DAY, "amount": 0, "location": "Plaza"},
        ("amount",),
    ),
    Case(TollTransactionUpdate, {}, ("amount",)),
    Case(
        FinancingRecordCreate,
        {"vin": VIN, "date": DAY, "amount": 0, "category": "loan_payment"},
        ("amount",),
    ),
    Case(FinancingRecordUpdate, {}, ("amount",)),
    Case(SpotRentalCreate, {"check_in_date": DAY}, _RENTAL),
    Case(SpotRentalUpdate, {}, _RENTAL),
    Case(SpotRentalBillingCreate, {"billing_date": DAY}, _BILLING),
    Case(SpotRentalBillingUpdate, {}, _BILLING),
    Case(
        CoverageEntry,
        # Bodily injury has both limits and a premium; collision has the deductible.
        {"coverage_key": "bodily_injury"},
        ("limit_primary", "limit_secondary", "deductible", "premium"),
        with_field={"deductible": {"coverage_key": "collision"}},
    ),
    Case(
        PolicyVehicleCreate,
        {"vin": VIN, "policy_type": "Liability"},
        ("premium_share", "deductible"),
    ),
    Case(PolicyVehicleUpdate, {}, ("premium_share", "deductible")),
    Case(
        PolicyVehicleUpsert,
        {"vin": VIN, "policy_type": "Liability"},
        ("premium_share", "deductible"),
    ),
    Case(InsurancePolicyCreate, _POLICY, ("premium_amount",)),
    Case(InsurancePolicyUpdate, {}, ("premium_amount",)),
    Case(InsurancePolicyRenew, {}, ("premium_amount",)),
    Case(InsurancePolicyReplace, _POLICY, ("premium_amount",)),
    Case(
        VehicleCreate,
        {"vin": VIN, "nickname": "Test", "vehicle_type": "Car"},
        _VEHICLE_PRICES,
    ),
    Case(VehicleUpdate, {}, (*_VEHICLE_PRICES, *_MSRP)),
    Case(VehicleArchiveRequest, {"reason": "Sold"}, ("sale_price",)),
    Case(VehicleBulkArchiveRequest, {"vins": [VIN], "reason": "Sold"}, ("sale_price",)),
    Case(WindowStickerDataUpdate, {}, _MSRP),
]

ROWS = [
    pytest.param(case, name, id=f"{case.schema.__name__}.{name}")
    for case in CASES
    for name in case.money
]

#: Fields that took whole cents before and still must: the policy widens their
#: range, not their precision.
KEEP_TWO_PLACES = {
    (schema.__name__, name)
    for schema, names in (
        (FinancingRecordCreate, ("amount",)),
        (FinancingRecordUpdate, ("amount",)),
        (SpotRentalCreate, _RENTAL),
        (SpotRentalUpdate, _RENTAL),
        (CoverageEntry, ("limit_primary", "limit_secondary", "deductible", "premium")),
        (PolicyVehicleCreate, ("premium_share", "deductible")),
        (PolicyVehicleUpdate, ("premium_share", "deductible")),
        (PolicyVehicleUpsert, ("premium_share", "deductible")),
        (InsurancePolicyCreate, ("premium_amount",)),
        (InsurancePolicyUpdate, ("premium_amount",)),
        (InsurancePolicyRenew, ("premium_amount",)),
        (InsurancePolicyReplace, ("premium_amount",)),
    )
    for name in names
}


# ---------------------------------------------------------------------------
# The walk: what the router actually accepts
# ---------------------------------------------------------------------------


def _dependant_params(dependant: Dependant) -> Iterator[ModelField]:
    """The body and query params of a dependant and of every Depends() under it."""
    yield from dependant.body_params
    yield from dependant.query_params
    for sub in dependant.dependencies:
        yield from _dependant_params(sub)


def _request_roots(routes: Sequence[BaseRoute] = app.routes) -> tuple[list[Any], list[str]]:
    """Every body and query annotation, and any money that arrives bare.

    A money parameter outside a model has no row to go in, so it is listed
    on its own for the test to refuse. `routes` is the app's unless a test
    hands it a probe.
    """
    roots: list[Any] = []
    bare: list[str] = []
    for ctx in iter_route_contexts(routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute):
            continue
        for param in _dependant_params(route.dependant):
            roots.append(param.field_info.annotation)
            if _is_money(param.name, param.field_info):
                bare.append(f"{sorted(route.methods)[0]} {ctx.path} {param.name}")
    return roots, bare


REQUEST_ROOTS, BARE_MONEY = _request_roots()
REQUEST_MODELS = sorted(walk(REQUEST_ROOTS), key=lambda m: m.__name__)


def test_the_walk_found_the_request_bodies():
    # A floor on the walk, so a FastAPI change that hides bodies from it can't
    # turn the contract into a pass over nothing.
    names = {model.__name__ for model in REQUEST_MODELS}
    assert len(REQUEST_MODELS) >= 100
    # Reached only through a parent's field, never as a route's own body.
    assert {"CoverageEntry", "PolicyVehicleUpsert", "ServiceLineItemUpdate"} <= names


def test_every_money_input_has_a_row():
    found = {(model.__name__, name) for model in REQUEST_MODELS for name in _money_names(model)}
    listed = {(case.schema.__name__, name) for case in CASES for name in case.money}
    assert found - listed == set(), "a new money input: give it the policy type and a row"
    assert listed - found == set(), "a row the router never accepts: drop it or fix the walk"


def test_no_money_arrives_outside_a_model():
    assert BARE_MONEY == []


def test_the_walk_sees_a_sub_dependency():
    # A Depends() keeps its params on its own dependant, not the route's, so a
    # walk of the route's lists alone would miss money that arrives this way.
    class _ProbeBody(BaseModel):
        cost: Decimal

    def _dep(cost: Decimal = Query(...), body: _ProbeBody = Body(...)) -> None:
        return None

    probe = FastAPI()

    @probe.post("/probe")
    def _probe(_: None = Depends(_dep)) -> None:
        return None

    roots, bare = _request_roots(probe.routes)
    assert "POST /probe cost" in bare
    assert _ProbeBody in set(walk(roots))


def test_each_row_lists_every_money_field_of_its_schema():
    # A schema reached only through the table (none today) still gets all of
    # its money checked, not just the fields someone remembered to list.
    for case in CASES:
        assert set(case.money) == set(_money_names(case.schema)), case.schema.__name__


# ---------------------------------------------------------------------------
# The bounds, per field
# ---------------------------------------------------------------------------


def _field_bounds(info: FieldInfo) -> dict[str, list[Any]]:
    """Every bound on the FieldInfo, read the way `_within_api_bounds` reads it."""
    found: dict[str, list[Any]] = {"ge": [], "gt": [], "le": [], "lt": []}
    for item in info.metadata:
        for attr, values in found.items():
            value = getattr(item, attr, None)
            if value is not None:
                values.append(value)
    return found


@pytest.mark.parametrize(("case", "name"), ROWS)
def test_the_bounds_are_the_policy_type(case: Case, name: str):
    info = case.schema.model_fields[name]
    assert _field_bounds(info) == {"ge": [0], "gt": [], "le": [_maximum(name)], "lt": []}
    # Exactly the constant, not a float that rounds near it.
    assert isinstance(_field_bounds(info)["le"][0], Decimal)
    # Nothing left inside the annotation for the importers to miss.
    assert unwrap(info.annotation)[1] == []


@pytest.mark.parametrize(("case", "name"), ROWS)
def test_whole_cents_stay_where_they_were(case: Case, name: str):
    places = [
        item.decimal_places
        for item in case.schema.model_fields[name].metadata
        if getattr(item, "decimal_places", None) is not None
    ]
    expected = [2] if (case.schema.__name__, name) in KEEP_TWO_PLACES else []
    assert places == expected


def _refusal(case: Case, name: str, value: Decimal) -> list[tuple[tuple[Any, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        case.schema.model_validate(case.payload(name, value))
    return [(error["loc"], error["type"]) for error in caught.value.errors()]


@pytest.mark.parametrize(("case", "name"), ROWS)
def test_each_field_takes_its_own_maximum(case: Case, name: str):
    top, step = _maximum(name), _step(name)
    assert getattr(case.schema.model_validate(case.payload(name, top)), name) == top
    assert getattr(case.schema.model_validate(case.payload(name, Decimal(0))), name) == 0
    # One error each, on the field, for the bound: the baseline is clean.
    assert _refusal(case, name, top + step) == [((name,), "less_than_equal")]
    assert _refusal(case, name, -step) == [((name,), "greater_than_equal")]


# ---------------------------------------------------------------------------
# Everyday forint amounts, the kind the dollar-sized caps got wrong
# ---------------------------------------------------------------------------


def test_a_forint_financing_payment_is_accepted():
    for schema, baseline in (
        (FinancingRecordCreate, {"vin": VIN, "date": DAY, "category": "loan_payment"}),
        (FinancingRecordUpdate, {}),
    ):
        record = schema.model_validate({**baseline, "amount": "335000.00"})
        assert getattr(record, "amount") == Decimal("335000.00")


def test_a_forint_fill_up_is_accepted():
    for schema, baseline in (
        (FuelRecordCreate, {"vin": VIN, "date": DAY, "odometer_km": 1000, "liters": 400}),
        (FuelRecordUpdate, {}),
        (WebhookFuelPayload, {"vin": VIN}),
    ):
        record = schema.model_validate({**baseline, "cost": "248000", "price_per_unit": "620"})
        assert getattr(record, "cost") == Decimal(248000)


def test_a_forint_price_per_tank_is_accepted():
    # A propane bottle refill: priced per tank, with no odometer.
    record = FuelRecordCreate.model_validate(
        {
            "vin": VIN,
            "date": DAY,
            "tank_size_kg": "11.5",
            "tank_quantity": 1,
            "price_basis": "per_tank",
            "price_per_unit": "12000",
            "cost": "12000",
        }
    )
    assert record.price_per_unit == Decimal(12000)
    for schema, baseline in ((FuelRecordUpdate, {}), (WebhookFuelPayload, {"vin": VIN})):
        other = schema.model_validate({**baseline, "price_per_unit": "12000"})
        assert getattr(other, "price_per_unit") == Decimal(12000)


# ---------------------------------------------------------------------------
# The importers: `_within_api_bounds` reads the same bounds
# ---------------------------------------------------------------------------


def _importer_calls() -> tuple[dict[str, set[str]], dict[str, type[BaseModel]], int]:
    """Schema name -> the fields the importers pass `_within_api_bounds` for it.

    Read from the source, so a new importer call is covered the day it lands.
    Every importer module is read, and each schema is looked up in the module
    that passes it. Also returns how many calls the walk saw.
    """
    calls: dict[str, set[str]] = {}
    schemas: dict[str, type[BaseModel]] = {}
    seen = 0
    for module in importer_modules():
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "_within_api_bounds"
            ):
                continue
            schema = node.args[0]
            assert isinstance(schema, ast.Name), ast.unparse(node)
            calls.setdefault(schema.id, set()).update(kw.arg for kw in node.keywords if kw.arg)
            schemas[schema.id] = getattr(module, schema.id)
            seen += 1
    return calls, schemas, seen


IMPORTER_CALLS, IMPORTER_SCHEMAS, IMPORTER_CALL_COUNT = _importer_calls()
IMPORTER_ROWS = [
    pytest.param(schema, name, id=f"{schema.__name__}.{name}")
    for schema in sorted(IMPORTER_SCHEMAS.values(), key=lambda s: s.__name__)
    for name in _money_names(schema)
]


def test_the_walk_sees_every_importer_call():
    # 30 is the count on 32b15b50, so a walk that drops a module comes up short.
    assert IMPORTER_CALL_COUNT >= 30


def test_the_importers_check_the_money_they_import():
    passed = {
        (schema, name)
        for schema, names in IMPORTER_CALLS.items()
        for name in names
        if _is_money(name, IMPORTER_SCHEMAS[schema].model_fields[name])
    }
    # A floor, so an AST change that finds no calls can't pass over nothing.
    assert {
        ("FuelRecordCreate", "cost"),
        ("FuelRecordCreate", "rebate"),
        ("FuelRecordCreate", "price_per_unit"),
        ("DEFRecordCreate", "cost"),
        ("DEFRecordCreate", "price_per_unit"),
        ("ServiceLineItemCreate", "cost"),
        ("TaxRecordCreate", "amount"),
        # The insurance importers (B4): a vehicle's share and deductible, and
        # each coverage's amounts.
        ("PolicyVehicleCreate", "premium_share"),
        ("PolicyVehicleCreate", "deductible"),
        ("CoverageEntry", "limit_primary"),
        ("CoverageEntry", "limit_secondary"),
        ("CoverageEntry", "deductible"),
        ("CoverageEntry", "premium"),
    } <= passed


@pytest.mark.parametrize(("schema", "name"), IMPORTER_ROWS)
def test_an_importer_schema_carries_the_policy_maximum(schema: type[BaseModel], name: str):
    bounds = _field_bounds(schema.model_fields[name])
    assert bounds["le"] == [_maximum(name)]
    assert bounds["ge"] == [0]


@pytest.mark.parametrize(("schema", "name"), IMPORTER_ROWS)
def test_an_import_past_the_maximum_fails_its_row(schema: type[BaseModel], name: str):
    top, step = _maximum(name), _step(name)
    _within_api_bounds(schema, **{name: top})
    with pytest.raises(_ImportBoundError, match=f"{name} must be at most {top},"):
        _within_api_bounds(schema, **{name: top + step})
    with pytest.raises(_ImportBoundError, match=f"{name} must be at least 0,"):
        _within_api_bounds(schema, **{name: -step})
