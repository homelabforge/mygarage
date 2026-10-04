"""Responses carry no bounds on any number, and no rules on any text.

A response validates what the database hands it. A number that inherits an
input bound (`le=100`, `ge=0`) turns a stored value past that bound into a 500
on every read of the record, and of every list it's in. Legacy rows hold such
values, and LiveLink, the webhooks and the importers write some of these columns
without the input schema. A digit rule (`decimal_places`, `max_digits`,
`multiple_of`) refuses a stored value the same way, so it counts as a bound too.
So no model reachable from a route's response may bound a number, money or not,
however deep it sits: list items, nested models, Optional and Annotated
wrappers all count.

The model set comes from the router, not from class names, so a new response
model is covered without registering it. The one way out is a CHECK constraint
that already keeps the column inside the bound (`CHECK_BACKED_BOUNDS`): then no
stored row can break it.

Text is the same trap. A length or pattern rule, or an `EmailStr`, refuses a
stored string past it: SQLite never holds a string to its column's width, and
SSO sign-in, the importers and the sticker OCR write some of these columns
without the input schema. So no response may carry one either.

A response drops a bound by redeclaring the field without it (a twin). A twin
must otherwise match the field it shadows, so the read side can't drift from
the write side's type, default or description.

A validator is the same trap: one on a shared base runs on every response
built from it, so a stored value it refuses 500s the read too. Each one a
response runs has to be read-tolerant, held by a CHECK, or on an input model a
response reuses on purpose. Anything else belongs on the input schemas.

So is a vocabulary. A `Literal` (or an `Enum`) refuses a stored value outside
it, and a vocabulary column with no CHECK can hold one: a restored backup, a
hand edit or a downgrade puts it there. So every response field that reaches a
`Literal` or an `Enum`, computed fields included, reads leniently
(`app.utils.lenient_vocab`), sits behind a read-tolerant validator, a CHECK or
a filter that drops what it doesn't know, or is computed by the app from its
own constants.
"""

import annotationlib
import importlib
import inspect
import re
import typing
from collections.abc import Iterable, Iterator
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, TypeAliasType

from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import (
    BaseModel,
    BeforeValidator,
    EmailStr,
    Field,
    ValidationError,
    computed_field,
    create_model,
)
from pydantic.fields import FieldInfo
from sqlalchemy import CheckConstraint

from app.database import Base
from app.main import app
from app.schemas._money import OptionalMoney
from app.utils.lenient_vocab import LenientVocab, lenient_reader
from tests.unit.schemas._schema_walk import NUMBER_TYPES, unwrap, walk

_BOUND_ATTRS = ("ge", "gt", "le", "lt", "multiple_of", "max_digits", "decimal_places")
_TEXT_ATTRS = ("min_length", "max_length", "pattern")

#: Bounds a CHECK constraint guarantees, so a stored row can't break them: (model, field) -> (table, check).
CHECK_BACKED_BOUNDS: dict[tuple[str, str], tuple[str, str]] = {
    ("ReminderPackItem", "interval_km"): ("reminder_pack_items", "check_pack_item_interval_km"),
    ("ReminderPackItem", "interval_months"): (
        "reminder_pack_items",
        "check_pack_item_interval_months",
    ),
    ("ReminderPackItem", "interval_days"): ("reminder_pack_items", "check_pack_item_interval_days"),
    ("ReminderPackItem", "interval_hours"): (
        "reminder_pack_items",
        "check_pack_item_interval_hours",
    ),
}


def _bounds(metadata: Iterable[Any], attrs: tuple[str, ...] = _BOUND_ATTRS) -> list[str]:
    """Every rule in `attrs` (a bound or digit rule by default) in a metadata
    list, including a nested FieldInfo's own."""
    found = []
    for item in metadata:
        for attr in attrs:
            value = getattr(item, attr, None)
            if value is not None:
                found.append(f"{attr}={value}")
        if isinstance(item, FieldInfo):
            found += _bounds(item.metadata, attrs)
    return found


def _number_fields(model: type[BaseModel]) -> dict[str, list[str]]:
    """Each number field of the model, with the bounds it carries."""
    fields = {}
    for name, info in model.model_fields.items():
        is_number, metadata, _models = unwrap(info.annotation, types=NUMBER_TYPES)
        if is_number:
            fields[name] = _bounds(info.metadata) + _bounds(metadata)
    return fields


def _bounded(models: Iterable[type[BaseModel]]) -> dict[str, dict[str, list[str]]]:
    """Model name -> {number field: its bounds}, for the models that bound one.

    A pair in CHECK_BACKED_BOUNDS is left out, since the database already holds it.
    """
    found = {}
    for model in models:
        bounded = {
            name: b
            for name, b in _number_fields(model).items()
            if b and (model.__name__, name) not in CHECK_BACKED_BOUNDS
        }
        if bounded:
            found[model.__name__] = bounded
    return found


def _response_roots() -> list[Any]:
    """Every response annotation the app declares, from `response_model` and `responses`."""
    roots = []
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute):
            continue
        if route.response_model is not None:
            roots.append(route.response_model)
        for extra in route.responses.values():
            if isinstance(extra, dict) and extra.get("model") is not None:
                roots.append(extra["model"])
    return roots


RESPONSE_MODELS = sorted(walk(_response_roots()), key=lambda m: m.__name__)


def test_the_walk_found_the_responses():
    """A guard: a floor on the walk itself, so a FastAPI change that hides routes
    or nested models from it can't turn the contract into a pass over nothing.

    Mutant: call `_number_fields` with the default MONEY_TYPES, and the number
    count falls to about 361.
    """
    names = {model.__name__ for model in RESPONSE_MODELS}
    assert len(RESPONSE_MODELS) >= 200
    # Reached only through a parent's field, never as a route's own model.
    assert {"PolicyVehicleResponse", "ServiceLineItemResponse", "SupplyUsageResponse"} <= names
    # Reached only through a computed field (UserResponse.resolved_units).
    assert "UnitSet" in names
    numbers = sum(len(_number_fields(model)) for model in RESPONSE_MODELS)
    assert numbers >= 600


def _duplicate_names(models: Iterable[type[BaseModel]]) -> list[str]:
    """Class names more than one of the models goes by."""
    names = [model.__name__ for model in models]
    return sorted({name for name in names if names.count(name) > 1})


def test_response_model_names_are_unique():
    """A guard: the registries below key on the class name, so two response
    models sharing one would shadow each other and a field could go unchecked.

    Mutant: add a probe class named `VehicleResponse` to RESPONSE_MODELS.
    """
    assert _duplicate_names(RESPONSE_MODELS) == []


def test_no_response_bounds_a_number():
    assert _bounded(RESPONSE_MODELS) == {}, (
        "a response inherits an input bound on a number: redeclare the field on "
        "the response without it, or move the bound off the shared base"
    )


def test_a_check_backed_bound_names_a_real_check():
    """A guard: each CHECK_BACKED_BOUNDS entry names a CHECK that exists and is
    about its field, and the field still carries a bound to excuse.

    Mutants: rename a CHECK in `models/reminder_pack.py`, or drop a pair's bound.
    """
    by_name = {model.__name__: model for model in RESPONSE_MODELS}
    for (model_name, field), (table, check) in CHECK_BACKED_BOUNDS.items():
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in Base.metadata.tables[table].constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert check in checks, f"{table} has no CHECK named {check}"
        assert field in checks[check], f"{check} doesn't mention {field}: {checks[check]}"
        assert model_name in by_name, f"{model_name} isn't a response any more"
        assert _number_fields(by_name[model_name]).get(field), (
            f"{model_name}.{field} carries no bound now: drop its CHECK_BACKED_BOUNDS entry"
        )


def test_the_insurance_input_model_is_not_a_response():
    # The responses have their own unbounded twins, so the input models' rules
    # can tighten without reaching a read.
    names = {model.__name__ for model in RESPONSE_MODELS}
    assert "CoverageEntryResponse" in names
    assert "CoverageEntry" not in names
    assert "NamedFieldResponse" in names
    assert "NamedField" not in names


# Text. A length, a pattern or an email check refuses a stored string the same way.


def _mentions(annotation: Any, target: Any) -> bool:
    """Whether `target` sits anywhere in the annotation: inside an Optional, a
    list, an Annotated or a `type` alias."""
    if annotation is target:
        return True
    if isinstance(annotation, TypeAliasType):
        return _mentions(annotation.__value__, target)
    return any(_mentions(arg, target) for arg in typing.get_args(annotation))


def _constrained_text(models: Iterable[type[BaseModel]]) -> dict[str, dict[str, list[str]]]:
    """Model name -> {field: its length, pattern and email rules}, for the
    models that carry one."""
    found = {}
    for model in models:
        constrained = {}
        for name, info in model.model_fields.items():
            rules = _bounds(info.metadata, _TEXT_ATTRS) + _bounds(
                unwrap(info.annotation)[1], _TEXT_ATTRS
            )
            if _mentions(info.annotation, EmailStr):
                rules.append("EmailStr")
            if rules:
                constrained[name] = rules
        if constrained:
            found[model.__name__] = constrained
    return found


def test_no_response_constrains_text():
    reads = [model for model in RESPONSE_MODELS if model.__name__ not in INPUT_MODELS_REUSED]
    assert _constrained_text(reads) == {}, (
        "a response inherits an input rule on text: redeclare the field on the "
        "response without it, or move the rule off the shared base"
    )


# A twin: a response redeclares a field to drop its bound, and copies the rest.

#: Twins that differ from the field they shadow on purpose: (model, field) -> why.
DELIBERATE_TWINS: dict[tuple[str, str], str] = {
    ("AddressBookEntryResponse", "email"): "a plain str: EmailStr refuses a local-domain address",
    ("TopicMapResponse", "role"): "lenient read; the input stays strict",
    ("UserResponse", "email"): "a plain str: EmailStr refuses an SSO email at a local domain",
    ("VehicleResponse", "usage_unit"): "lenient read; the input stays strict",
    ("VehicleResponse", "vehicle_type"): "lenient read; the input stays strict",
}


def _plain(annotation: Any) -> Any:
    """The annotation with its constraints peeled off, at any depth.

    Drops every Annotated layer and `type` alias, so `OptionalMoney` and
    `Decimal | None` come out the same.
    """
    if isinstance(annotation, TypeAliasType):
        return _plain(annotation.__value__)
    if typing.get_origin(annotation) is Annotated:
        return _plain(typing.get_args(annotation)[0])
    args = typing.get_args(annotation)
    if not args:
        return annotation
    return typing.get_origin(annotation), tuple(_plain(arg) for arg in args)


def _shadowed(model: type[BaseModel]) -> Iterator[tuple[str, FieldInfo, FieldInfo]]:
    """Each field the model redeclares over a base's: its name, its FieldInfo, the base's."""
    own = annotationlib.get_annotations(model, format=annotationlib.Format.FORWARDREF)
    for name in own:
        if name not in model.model_fields:
            continue
        for base in model.__mro__[1:]:
            if issubclass(base, BaseModel) and name in base.model_fields:
                yield name, model.model_fields[name], base.model_fields[name]
                break


def _drift(twin: FieldInfo, shadowed: FieldInfo) -> list[str]:
    """How a twin differs from the field it shadows, bounds aside."""
    drift: list[str] = []
    if _plain(twin.annotation) != _plain(shadowed.annotation):
        drift.append(f"type {twin.annotation} vs {shadowed.annotation}")
    twin_default = (twin.is_required(), twin.default, twin.default_factory)
    shadowed_default = (shadowed.is_required(), shadowed.default, shadowed.default_factory)
    if twin_default != shadowed_default:
        drift.append(f"default {twin_default} vs {shadowed_default}")
    if twin.description != shadowed.description:
        drift.append(f"description {twin.description!r} vs {shadowed.description!r}")
    return drift


def _twins(
    models: Iterable[type[BaseModel]], registry: dict[tuple[str, str], str]
) -> tuple[int, dict[str, list[str]], list[tuple[str, str]]]:
    """Every twin the models hold, checked against the field it shadows.

    Returns how many twins there were, the ones that drift outside `registry`,
    and the registry pairs that don't differ any more (stale entries).
    """
    count = 0
    drift: dict[str, list[str]] = {}
    deliberate: dict[tuple[str, str], list[str]] = {}
    for model in models:
        for name, twin, shadowed in _shadowed(model):
            count += 1
            found = _drift(twin, shadowed)
            if (model.__name__, name) in registry:
                deliberate[(model.__name__, name)] = found
            elif found:
                drift[f"{model.__name__}.{name}"] = found
    stale = [pair for pair in registry if not deliberate.get(pair)]
    return count, drift, stale


def test_a_twin_matches_the_field_it_shadows():
    """A guard: every twin copies its field's type, default and description, and
    only drops the bound. A DELIBERATE_TWINS entry must still differ.

    Mutants: make `_shadowed` yield nothing (the floor fails), or change one
    twin's description (`FuelRecordResponse.cost`, say).
    """
    count, drift, stale = _twins(RESPONSE_MODELS, DELIBERATE_TWINS)
    # 147 today. A floor, so a change in how annotations are read can't turn
    # this into a pass over nothing.
    assert count >= 140
    assert drift == {}, "a twin drifted from the field it shadows: copy it again, bound aside"
    assert stale == [], "these match their field now: drop their DELIBERATE_TWINS entries"


# Validators. One a response runs sees every stored row it reads.

#: Validators a stored row can't trip, and why.
READ_TOLERANT: dict[tuple[str, str], str] = {
    ("AddressBookEntryBase", "empty_str_to_none"): "turns an empty string into None",
    ("DTCDefinitionResponse", "_parse_json_list"): "returns None for anything it can't parse",
    ("FuelRecordBase", "_parse_obc_trip_duration_create"): (
        "an Integer column hands it an int, which passes straight through"
    ),
    ("TollTagBase", "validate_toll_system"): "only rewrites a known spelling, never raises",
    ("TopicMapBase", "canonicalize"): "uppercases, never raises",
    ("UserResponse", "discard_out_of_vocabulary_unit"): "built to drop a bad stored unit",
    ("UserResponse", "discard_out_of_vocabulary_unit_preference"): (
        "built to read a bad stored preference as imperial"
    ),
}
#: Validators a CHECK guarantees: (owner, validator) -> (table, column, (check, ...)).
#: The column is None for a model validator, which spans several.
CHECK_BACKED_VALIDATORS: dict[tuple[str, str], tuple[str, str | None, tuple[str, ...]]] = {
    ("ReminderPackItem", "fill_key_and_check_intervals"): (
        "reminder_pack_items",
        None,
        ("check_pack_item_has_interval", "check_pack_item_distance_or_hours"),
    ),
    ("ServiceLineItemBase", "validate_inspection_result"): (
        "service_line_items",
        "inspection_result",
        ("check_inspection_result",),
    ),
    ("ServiceLineItemBase", "validate_inspection_severity"): (
        "service_line_items",
        "inspection_severity",
        ("check_inspection_severity",),
    ),
    ("ServiceVisitBase", "validate_service_category"): (
        "service_visits",
        "service_category",
        ("check_service_visit_category",),
    ),
    ("TrailerDetailsBase", "validate_brake_type"): (
        "trailer_details",
        "brake_type",
        ("check_brake_type",),
    ),
    ("TrailerDetailsBase", "validate_hitch_type"): (
        "trailer_details",
        "hitch_type",
        ("check_hitch_type",),
    ),
}
#: Input models a response reuses on purpose: model -> why its own rules stay.
INPUT_MODELS_REUSED: dict[str, str] = {
    "ReminderPackItem": (
        "the pack format the apply pipeline consumes, reused as the response. Apply "
        "must fail closed on a bad type, and a saved pack copies its type from a rule "
        "that only validated schemas write"
    ),
}


def _owner(model: type[BaseModel], name: str) -> str:
    """The class in the model's MRO that declares the validator."""
    return next(cls.__name__ for cls in model.__mro__ if name in cls.__dict__)


def _validators(model: type[BaseModel]) -> dict[tuple[str, str], tuple[str, ...]]:
    """Each validator the model runs, keyed (owner, name), with the fields it
    checks. A model validator checks none by name."""
    decorators = model.__pydantic_decorators__
    found = {
        (_owner(model, name), name): decorator.info.fields
        for name, decorator in decorators.field_validators.items()
    }
    for name in decorators.model_validators:
        found[(_owner(model, name), name)] = ()
    return found


def test_every_response_validator_is_accounted_for():
    unaccounted = sorted(
        f"{model.__name__}: {owner}.{name}"
        for model in RESPONSE_MODELS
        if model.__name__ not in INPUT_MODELS_REUSED
        for owner, name in _validators(model)
        if (owner, name) not in READ_TOLERANT and (owner, name) not in CHECK_BACKED_VALIDATORS
    )
    assert unaccounted == [], (
        "a stored row can trip these and 500 the read: move them to the input "
        "schemas, or register why no stored row can"
    )


def test_a_check_backed_validator_names_real_checks():
    """A guard: each CHECK_BACKED_VALIDATORS entry names CHECKs that exist on its
    table, about the column its validator checks.

    Mutants: rename `check_hitch_type` in `models/vehicle.py`, or give the
    ReminderPackItem entry the column `interval_km`.
    """
    seen = {key: fields for model in RESPONSE_MODELS for key, fields in _validators(model).items()}
    for (owner, name), (table, column, names) in CHECK_BACKED_VALIDATORS.items():
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in Base.metadata.tables[table].constraints
            if isinstance(constraint, CheckConstraint)
        }
        for check in names:
            assert check in checks, f"{table} has no CHECK named {check}"
            if column is not None:
                assert column in checks[check], f"{check} doesn't mention {column}"
        assert column is None or column in seen.get((owner, name), ()), (
            f"{owner}.{name} doesn't check {column}"
        )


def test_no_stale_validator_entries():
    """A guard: every registry entry still names a validator a response runs,
    and every reused input model is still a response with validators of its own.

    Mutants: add a READ_TOLERANT entry for a validator that doesn't exist, or
    an INPUT_MODELS_REUSED entry for a model that isn't a response.
    """
    seen = {key for model in RESPONSE_MODELS for key in _validators(model)}
    validated = {model.__name__ for model in RESPONSE_MODELS if _validators(model)}
    stale = [
        f"{owner}.{name}"
        for owner, name in (*READ_TOLERANT, *CHECK_BACKED_VALIDATORS)
        if (owner, name) not in seen
    ]
    stale += [model for model in INPUT_MODELS_REUSED if model not in validated]
    assert stale == [], "no response runs these now: drop their entries"


# Vocabularies. A Literal refuses a stored value outside it, the same way a bound does.

#: Vocabulary fields a CHECK keeps inside the vocabulary: (model, field) -> (table, check).
#: The table is where the value is stored, which isn't always the response's own.
CHECK_BACKED_VOCAB: dict[tuple[str, str], tuple[str, str]] = {
    ("FinancingRecordResponse", "category"): (
        "financing_records",
        "check_financing_records_category",
    ),
    ("ServiceLineItemResponse", "inspection_result"): (
        "service_line_items",
        "check_inspection_result",
    ),
    ("ServiceLineItemResponse", "inspection_severity"): (
        "service_line_items",
        "check_inspection_severity",
    ),
    ("ServiceVisitResponse", "service_category"): (
        "service_visits",
        "check_service_visit_category",
    ),
    ("SupplyResponse", "unit_type"): ("supplies", "check_supply_unit_type"),
    # The usage's own row has no unit type: it reads the joined supply's.
    ("SupplyUsageResponse", "unit_type"): ("supplies", "check_supply_unit_type"),
    ("TaxRecordResponse", "tax_type"): ("tax_records", "check_tax_type"),
}
#: Vocabulary fields the app works out rather than reads: (model, field) ->
#: (the producer's dotted path, why every branch lands in the vocabulary).
COMPUTED_VOCAB: dict[tuple[str, str], tuple[str, str]] = {
    ("AnchorProposal", "origin"): (
        "app.services.maintenance_service._plan_item",
        "every branch sets a constant",
    ),
    ("AnomalyAlert", "severity"): (
        "app.routes.analytics.build_anomalies_from_monthly_df",
        "a ternary of two constants",
    ),
    ("AssistantCitation", "source"): (
        "app.services.garage_assistant_service._coerce_citations",
        "drops a source outside `allowed`, which is the Literal's values",
    ),
    ("CalendarEvent", "type"): (
        "app.routes.calendar.get_calendar_events",
        "a constant per kind of event",
    ),
    ("CalendarEvent", "urgency"): (
        "app.routes.calendar.get_calendar_events",
        "constants on every branch, its own and calculate_urgency's",
    ),
    ("CalendarEvent", "category"): (
        "app.routes.calendar.get_calendar_events",
        "a constant per kind of event",
    ),
    ("DeviceReading", "format"): (
        "app.routes.livelink_admin.get_device_readings",
        "the code preset's typed format, else 'value'",
    ),
    ("DeviceReading", "alert_lines"): (
        "app.routes.livelink_admin.get_device_readings",
        "the code preset's typed alert lines, else none",
    ),
    ("FuelEfficiencyAlert", "code"): (
        "app.routes.analytics.build_fuel_alerts",
        "a constant per alert",
    ),
    ("FuelEfficiencyAlert", "severity"): (
        "app.routes.analytics.build_fuel_alerts",
        "constants on every branch",
    ),
    ("InboxItem", "kind"): (
        "app.routes.notifications.notification_inbox",
        "a ternary of two constants",
    ),
    ("InboxItem", "severity"): (
        "app.routes.notifications.notification_inbox",
        "a ternary of two constants",
    ),
    ("InsurancePolicyResponse", "status"): (
        "app.services.insurance_service.policy_status",
        "every branch returns a constant",
    ),
    ("LiveSensorReading", "format"): (
        "app.services.livelink_sources.presets.sensors._live_reading",
        "the code preset's typed format, else the default",
    ),
    ("PackItemPlan", "rule_action"): (
        "app.services.maintenance_service._plan_item",
        "every branch sets a constant",
    ),
    ("PolicyHistoryEntry", "status"): (
        "app.services.insurance_service.InsuranceService.history",
        "copies the computed InsurancePolicyResponse.status",
    ),
    ("ReminderResponse", "due_status"): (
        "app.services.reminder_service.reminder_due_status",
        "every branch returns a constant",
    ),
    ("ReminderResponse", "progress_basis"): (
        "app.services.reminder_service.leading_progress",
        "returns a key of _BASIS_ORDER, which holds the Literal's values",
    ),
    ("SearchHit", "type"): (
        "app.routes.search.global_search",
        "a constant per kind of hit",
    ),
    ("SupplyLedgerEntry", "entry_type"): (
        "app.services.supply_service.SupplyService.get_supply_history",
        "a constant per kind of entry",
    ),
    ("TelegramFuelStatus", "state"): (
        "app.services.telegram_poller.TelegramPoller._set_state",
        "in-memory state that only _set_state and _fail write, from constants",
    ),
    ("TelegramFuelStatus", "error_code"): (
        "app.services.telegram_poller.TelegramPoller._fail",
        "every caller passes a constant",
    ),
    ("TelemetryLatestValue", "alert_band"): (
        "app.services.livelink_alerts.alert_band",
        "every branch returns a constant",
    ),
    **{
        ("UnitSet", quantity): (
            "app.utils.unit_resolution.resolve_units",
            "UserResponse.resolved_units: a preset's value, or an override it "
            "checked against the vocabulary first",
        )
        for quantity in (
            "distance",
            "speed",
            "length",
            "volume",
            "consumption",
            "pressure",
            "temperature",
            "mass",
            "torque",
            "tread",
            "secondary_gallon",
        )
    },
}
#: Vocabulary fields whose one builder drops a stored value outside the
#: vocabulary before validating it: (model, field) -> (the filter, why).
FILTERED_VOCAB: dict[tuple[str, str], tuple[str, str]] = {
    ("CoverageEntryResponse", "coverage_key"): (
        "app.services.insurance_service._coverage_responses",
        "drops and logs a key outside the catalogue, and the catalogue is the Literal "
        "(test_the_literal_matches_the_catalogue)",
    ),
}
#: Names a stored vocabulary column goes by on a response.
VOCABULARY_NAMESAKES = ("vehicle_type", "usage_unit", "ecu_status", "device_status", "anchor_kind")
#: Namesakes that carry something else: (model, field) -> what they carry.
FREE_TEXT_NAMESAKES: dict[tuple[str, str], str] = {
    ("ExternalVehicleResponse", "vehicle_type"): (
        "external_vehicles.vehicle_type: free text about someone else's vehicle"
    ),
    ("VINDecodeResponse", "vehicle_type"): "NHTSA's own text from a VIN decode, never stored",
}

#: Sits outside every vocabulary, for reading a lenient field back.
_OUT_OF_VOCABULARY = "<not in any vocabulary>"


def _resolve(path: str) -> Any:
    """What a dotted path names, a module's function or a class's method, or None."""
    parts = path.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            target: Any = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        for name in parts[split:]:
            target = getattr(target, name, None)
        return target
    return None


def _vocabulary(annotation: Any) -> frozenset[object]:
    """Every Literal value or Enum member value an annotation can hold, at any
    depth: inside an Optional, a list, an Annotated or a `type` alias. Empty if
    it holds none."""
    if isinstance(annotation, TypeAliasType):
        return _vocabulary(annotation.__value__)
    if typing.get_origin(annotation) is Literal:
        return frozenset(typing.get_args(annotation))
    # An Enum (StrEnum too) refuses a stored value outside its members just
    # like a Literal. None is on a response today; this is for the next one.
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return frozenset(member.value for member in annotation)
    return frozenset().union(*(_vocabulary(arg) for arg in typing.get_args(annotation)))


def _annotations(model: type[BaseModel]) -> Iterator[tuple[str, Any, FieldInfo | None]]:
    """Each field's name, annotation and FieldInfo, computed fields included.

    A computed field gets no FieldInfo: it's never validated, so nothing can
    make it lenient.
    """
    for name, info in model.model_fields.items():
        yield name, info.annotation, info
    for name, computed in model.model_computed_fields.items():
        yield name, computed.return_type, None


def _vocabulary_fields(
    models: Iterable[type[BaseModel]],
) -> dict[tuple[str, str], tuple[frozenset[object], FieldInfo | None]]:
    """(model, field) -> (its vocabulary, its FieldInfo), for every field that reaches a Literal."""
    return {
        (model.__name__, name): (vocabulary, info)
        for model in models
        for name, annotation, info in _annotations(model)
        if (vocabulary := _vocabulary(annotation))
    }


def _reads_leniently(info: FieldInfo) -> bool:
    """Whether the field carries `LenientVocab` and keeps its promise.

    The marker alone proves nothing, so a bad value and None go through the
    field's own type and validators, and both have to come back as the
    marker's fallback.
    """
    metadata = [*info.metadata, *unwrap(info.annotation)[1]]
    marker = next((item for item in metadata if isinstance(item, LenientVocab)), None)
    if marker is None:
        return False
    annotation = Annotated[info.annotation, *info.metadata] if info.metadata else info.annotation
    read_back = create_model("_ReadBack", value=(annotation, ...))
    try:
        return all(
            read_back.model_validate({"value": value}).value == marker.fallback
            for value in (_OUT_OF_VOCABULARY, None)
        )
    except ValidationError:
        return False


def _tolerated(model: type[BaseModel]) -> set[str]:
    """Fields a READ_TOLERANT validator sees before their Literal does.

    An after-validator only runs once the Literal has passed the value, so it
    can't rescue a bad one.
    """
    return {
        field
        for name, decorator in model.__pydantic_decorators__.field_validators.items()
        if (_owner(model, name), name) in READ_TOLERANT and decorator.info.mode != "after"
        for field in decorator.info.fields
    }


def _unaccounted_vocabulary(models: Iterable[type[BaseModel]]) -> list[str]:
    """Each vocabulary field a stored value can push outside its vocabulary."""
    registered = CHECK_BACKED_VOCAB.keys() | COMPUTED_VOCAB.keys() | FILTERED_VOCAB.keys()
    unaccounted = []
    for model in models:
        tolerated = _tolerated(model)
        for (_model, name), (_values, info) in _vocabulary_fields([model]).items():
            if (model.__name__, name) in registered or name in tolerated:
                continue
            if info is not None and _reads_leniently(info):
                continue
            unaccounted.append(f"{model.__name__}.{name}")
    return sorted(unaccounted)


def _namesakes(models: Iterable[type[BaseModel]]) -> dict[tuple[str, str], bool]:
    """(model, field) -> whether it reaches a Literal, for each field named like a
    stored vocabulary column."""
    return {
        (model.__name__, name): bool(_vocabulary(annotation))
        for model in models
        for name, annotation, _info in _annotations(model)
        if name in VOCABULARY_NAMESAKES
    }


def test_every_vocabulary_field_is_accounted_for():
    assert _unaccounted_vocabulary(RESPONSE_MODELS) == [], (
        "a stored value outside these vocabularies 500s the read: make the field "
        "lenient (app.utils.lenient_vocab), or register the CHECK, the filter or "
        "the computation that keeps it inside"
    )


def test_vocabulary_namesakes_reach_a_literal():
    free_text = sorted(
        f"{model}.{field}"
        for (model, field), reaches in _namesakes(RESPONSE_MODELS).items()
        if not reaches and (model, field) not in FREE_TEXT_NAMESAKES
    )
    assert free_text == [], (
        "these copy a stored vocabulary column as plain text, so a bad value goes "
        "to the UI as is: type them with the vocabulary's lenient alias, or "
        "register what else they carry"
    )


def test_a_check_backed_vocabulary_names_a_real_check():
    """A guard: each CHECK_BACKED_VOCAB entry names a CHECK on its table that is
    about the field and allows nothing the field's Literal refuses.

    Mutants: rename `check_supply_unit_type` in `models/supply.py`, or add a
    value to its IN list.
    """
    fields = _vocabulary_fields(RESPONSE_MODELS)
    for (model_name, field), (table, check) in CHECK_BACKED_VOCAB.items():
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in Base.metadata.tables[table].constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert check in checks, f"{table} has no CHECK named {check}"
        assert field in checks[check], f"{check} doesn't mention {field}: {checks[check]}"
        assert (model_name, field) in fields, f"{model_name}.{field} isn't a vocabulary field"
        allowed = set(re.findall(r"'([^']*)'", checks[check]))
        refused = allowed - fields[(model_name, field)][0]
        assert allowed and not refused, f"{check} lets in {sorted(refused)}, which {field} refuses"


def test_a_filtered_vocabulary_names_a_real_filter():
    """A guard: each FILTERED_VOCAB entry names a function that exists and
    builds that response from that field.

    Mutant: rename `_coverage_responses` in `services/insurance_service.py`.
    """
    for (model_name, field), (path, _why) in FILTERED_VOCAB.items():
        function = _resolve(path)
        assert callable(function), f"{path} doesn't exist"
        source = inspect.getsource(function)
        assert model_name in source and field in source, (
            f"{path} doesn't build {model_name} from {field}"
        )


def test_a_computed_vocabulary_names_a_real_producer():
    """A guard: each COMPUTED_VOCAB entry names a function or method that exists.

    Mutant: point the SearchHit entry at `app.routes.search.find_hits`.
    """
    missing = sorted(
        f"{model}.{field}: {path}"
        for (model, field), (path, _why) in COMPUTED_VOCAB.items()
        if not callable(_resolve(path))
    )
    assert missing == [], "these producers are gone: point the entries at what computes them now"


def test_no_stale_vocabulary_entries():
    """A guard: every registry entry still names a vocabulary field on a
    response, one that doesn't read leniently already.

    Mutants: add a COMPUTED_VOCAB entry for a field no response has, or make a
    registered field lenient.
    """
    fields = _vocabulary_fields(RESPONSE_MODELS)
    # 65 today. A floor, so a detector gone blind can't pass the vocabulary
    # accounting over nothing.
    assert len(fields) >= 65
    stale = []
    for key in (*CHECK_BACKED_VOCAB, *COMPUTED_VOCAB, *FILTERED_VOCAB):
        info = fields[key][1] if key in fields else None
        if key not in fields or (info is not None and _reads_leniently(info)):
            stale.append(".".join(key))
    assert stale == [], "these name no strict vocabulary field now: drop their entries"


def test_no_stale_namesake_entries():
    """A guard: every FREE_TEXT_NAMESAKES entry is still a namesake on a
    response, and still free text.

    Mutant: register `VehicleResponse.vehicle_type`, which reaches a Literal.
    """
    namesakes = _namesakes(RESPONSE_MODELS)
    stale = [
        f"{model}.{field}"
        for model, field in FREE_TEXT_NAMESAKES
        if namesakes.get((model, field), True)
    ]
    assert stale == [], "these reach a Literal now, or are gone: drop their entries"


# The detector itself, on one field per way a bound can be written.

type _BoundedAlias = Annotated[Decimal, Field(ge=0)]
type _BoundedCount = Annotated[int, Field(ge=1)]


class _Nested(BaseModel):
    cost: Decimal | None = Field(None, ge=0)


class _Probe(BaseModel):
    amount: Decimal | None = Field(None, le=100)
    cost: Annotated[Decimal, Field(ge=0)] | None = None
    premium: OptionalMoney = None
    deductible: _BoundedAlias | None = None
    price: float = Field(0, gt=0)
    rate: Decimal | None = Field(None, decimal_places=2)
    fee: Decimal | None = Field(None, max_digits=12)
    charge: Decimal | None = Field(None, multiple_of=Decimal("0.01"))
    # A number with no bound stays out. A measurement and a count aren't money,
    # but their bounds 500 a read all the same.
    total_cost: Decimal | None = None
    odometer_km: Decimal | None = Field(None, ge=0)
    total: int = Field(0, ge=0)
    count: int | None = Field(None, ge=0)
    aliased: _BoundedCount | None = None
    items: list[_Nested] = []


def test_the_detector_sees_every_form():
    # On the FieldInfo, inside the Optional, through the shared alias, inside a
    # PEP 695 alias, on a float, each digit rule, an int bare, Optional and
    # aliased, and one model down through a list.
    assert _bounded(walk([_Probe])) == {
        "_Probe": {
            "amount": ["le=100"],
            "cost": ["ge=0"],
            "premium": ["ge=0", "le=9999999999.99"],
            "deductible": ["ge=0"],
            "price": ["gt=0"],
            "rate": ["decimal_places=2"],
            "fee": ["max_digits=12"],
            "charge": ["multiple_of=0.01"],
            "odometer_km": ["ge=0"],
            "total": ["ge=0"],
            "count": ["ge=0"],
            "aliased": ["ge=1"],
        },
        "_Nested": {"cost": ["ge=0"]},
    }


class _TextProbe(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: Annotated[str, Field(max_length=30)] | None = None
    code: str | None = Field(None, pattern=r"^[A-Z]+$")
    email: EmailStr
    backup_email: EmailStr | None = None
    # No rule, so they stay out.
    notes: str | None = None
    kind: Literal["shop", "dealer"] = "shop"


def test_the_text_detector_sees_every_form():
    """A guard: true the day it lands, next to its RED (test_no_response_constrains_text).

    Mutants: drop "pattern" from _TEXT_ATTRS, or stop looking for EmailStr in
    `_constrained_text`.
    """
    assert _constrained_text([_TextProbe]) == {
        "_TextProbe": {
            "name": ["min_length=1", "max_length=100"],
            "color": ["max_length=30"],
            "code": ["pattern=^[A-Z]+$"],
            "email": ["EmailStr"],
            "backup_email": ["EmailStr"],
        }
    }


# The twin check itself, on local classes and a local registry.


class _TwinBase(BaseModel):
    same: Decimal | None = Field(None, ge=0, description="Kept")
    money: OptionalMoney = Field(None, description="Paid")
    counted: _BoundedCount | None = None
    described: Decimal | None = Field(None, ge=0, description="Original")
    defaulted: Decimal | None = Field(None, ge=0)
    required: Decimal = Field(..., ge=0)
    typed: Decimal | None = Field(None, ge=0)
    registered: int | None = Field(None, ge=0, description="Bounded")
    settled: int | None = Field(None, ge=0)


class _TwinProbe(_TwinBase):
    # Bounds dropped and nothing else, through a plain field, the shared money
    # alias and a PEP 695 alias.
    same: Decimal | None = Field(None, description="Kept")
    money: Decimal | None = Field(None, description="Paid")
    counted: int | None = None
    # One drift each.
    described: Decimal | None = Field(None, description="Changed")
    defaulted: Decimal | None = Decimal(0)
    required: Decimal = Decimal(0)
    typed: float | None = None
    # Registered: one still differs, one matches now and so is stale.
    registered: int | None = None
    settled: int | None = None


_PROBE_TWINS: dict[tuple[str, str], str] = {
    ("_TwinProbe", "registered"): "drops its description on purpose",
    ("_TwinProbe", "settled"): "used to differ",
}


def test_the_twin_check_sees_each_drift():
    """A guard: true today. Each kind of drift is flagged for its own reason, a
    registered pair that still differs passes, and one that matches is stale.

    Mutant: drop the description comparison from `_drift`.
    """
    count, drift, stale = _twins([_TwinProbe], _PROBE_TWINS)
    assert count == 9
    assert {name: [d.split()[0] for d in found] for name, found in drift.items()} == {
        "_TwinProbe.described": ["description"],
        "_TwinProbe.defaulted": ["default"],
        "_TwinProbe.required": ["default"],
        "_TwinProbe.typed": ["type"],
    }
    assert stale == [("_TwinProbe", "settled")]


# The vocabulary detector itself, on one field per way a vocabulary can be written.

type _PepVocab = Literal["x", "y"]
_ModuleVocab = Literal["x", "y"]


class _VocabNested(BaseModel):
    kind: Literal["a", "b"] = "a"


class _VocabResolved(BaseModel):
    """Reached only through a computed field, the way `UnitSet` is."""

    unit: _ModuleVocab = "x"


class _VocabBase(BaseModel):
    inherited: _ModuleVocab = "x"


class _ProbeEnum(Enum):
    """Pydantic refuses a value outside its members the same way a Literal does."""

    A = "a"
    B = "b"


class _ProbeStrEnum(StrEnum):
    A = "a"
    B = "b"


class _VocabProbe(_VocabBase):
    bare: Literal["a", "b"] = "a"
    aliased: _ModuleVocab = "x"
    pep695: _PepVocab = "x"
    annotated: Annotated[_ModuleVocab, "tagged"] | None = None
    optional: _ModuleVocab | None = None
    listed: list[Literal["a", "b"]] = []
    nested: list[_VocabNested] = []
    enumerated: _ProbeEnum = _ProbeEnum.A
    str_enumerated: _ProbeStrEnum | None = None
    # No vocabulary, so they stay out.
    text: str = ""
    count: int = 0

    @computed_field
    @property
    def resolved(self) -> _VocabResolved:
        return _VocabResolved()

    @computed_field
    @property
    def derived(self) -> Literal["a", "b"]:
        return "a"


def test_the_vocabulary_detector_sees_every_form():
    """A guard: bare, through a module alias and a PEP 695 alias, inside an
    Annotated, an Optional and a list, inherited from a base, one model down,
    a model behind a computed field, a computed field that is the Literal, and
    an Enum or StrEnum (its vocabulary is its members' values).

    Mutants: drop the computed-field loop from `_schema_walk.walk`, drop the
    `TypeAliasType` unwrap from `_vocabulary`, drop the Enum branch from
    `_vocabulary`, or skip computed fields in `_annotations` (the walk still
    follows their models).
    """
    fields = _vocabulary_fields(walk([_VocabProbe]))
    assert set(fields) == {
        ("_VocabProbe", "inherited"),
        ("_VocabProbe", "bare"),
        ("_VocabProbe", "aliased"),
        ("_VocabProbe", "pep695"),
        ("_VocabProbe", "annotated"),
        ("_VocabProbe", "optional"),
        ("_VocabProbe", "listed"),
        ("_VocabProbe", "enumerated"),
        ("_VocabProbe", "str_enumerated"),
        ("_VocabProbe", "derived"),
        ("_VocabNested", "kind"),
        ("_VocabResolved", "unit"),
    }
    # Values, not members: a CHECK's IN list holds the stored strings.
    assert fields[("_VocabProbe", "enumerated")][0] == {"a", "b"}


def _lenient_probe() -> type[BaseModel]:
    """One lenient field per shape, and three that only look it.

    Built when called, so a missing reader fails its test and not the module.
    """
    lenient = Annotated[
        _ModuleVocab | None, BeforeValidator(lenient_reader(_ModuleVocab)), LenientVocab(None)
    ]

    class _LenientProbe(BaseModel):
        nullable: lenient = None
        nested: lenient | None = None
        required: Annotated[
            _ModuleVocab,
            BeforeValidator(lenient_reader(_ModuleVocab, fallback="x")),
            LenientVocab("x"),
        ] = "x"
        # The marker, and nothing that reads a bad value.
        marker_only: Annotated[_ModuleVocab | None, LenientVocab(None)] = None
        # Reads a bad value as None, where its marker promises "x".
        wrong_fallback: Annotated[
            _ModuleVocab, BeforeValidator(lenient_reader(_ModuleVocab)), LenientVocab("x")
        ] = "x"
        strict: _ModuleVocab = "x"

    return _LenientProbe


def test_only_a_field_that_reads_leniently_counts_as_lenient():
    """A guard: true the day the reader lands. A field counts as lenient when a
    bad value really reads as its marker's fallback, not because it has one.

    Mutant: return True from `_reads_leniently` as soon as it finds the marker.
    """
    assert _unaccounted_vocabulary([_lenient_probe()]) == [
        "_LenientProbe.marker_only",
        "_LenientProbe.strict",
        "_LenientProbe.wrong_fallback",
    ]
