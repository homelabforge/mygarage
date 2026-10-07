"""Canonical maintenance types, and a classifier that never guesses.

A reminder pack, a service line item and a reminder used to share nothing but
words: "Oil Change" on a visit, "Oil & Filter Change" in the pack, and the app
could not tell they were the same maintenance. Every match now goes through a
code from this registry. The code is stored on the line item and the reminder
once, at write time (or by migration 101 for existing rows), and everything
downstream compares codes, never text.

The registry is Python, not a table: no seed rows, no translation rows, and a
pack or a rule may still declare a code this file does not know (a user-defined
pack later, for instance). Such a code is stored verbatim and labelled by the
rule that carries it.

`classify` is deliberately conservative. A description is classified only when
exactly one type claims it; "Rotate and replace tires" claims two and comes
back `None`, as does "Oil pressure sensor replacement", which mentions oil but
is not an oil service. The corpus in `tests/unit/utils/test_maintenance_types.py`
pins both directions.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: A code a pack, a rule or a request may carry: lowercase snake_case, 2..50.
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")


@dataclass(frozen=True)
class MaintenanceType:
    """One canonical maintenance type.

    `include` patterns are tried against the normalised description; the type
    claims it when at least one matches and none of `exclude` does.
    """

    code: str
    label: str
    category: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()


# Word-order-agnostic pair: A anywhere before B, or B anywhere before A.
def _pair(a: str, b: str) -> str:
    return rf"(?:{a}.*{b}|{b}.*{a})"


_TIRE = r"\b(?:tire|tyre|wheel)s?\b"
_REPLACE = r"\b(?:replac\w*|new|mount\w*|purchas\w*|install\w*|fitt?\w*)\b"
_SERVICE_VERB = r"\b(?:fluid|oil|service\w*|flush\w*|change\w*|drain\w*|filter)\b"

REGISTRY: tuple[MaintenanceType, ...] = (
    MaintenanceType(
        "engine_oil_filter",
        "Engine oil and filter",
        "engine",
        include=(
            r"\b(?:engine )?oil (?:and filter )?(?:change\w*|service\w*|replac\w*|drain\w*)\b",
            r"\bchange (?:the )?(?:engine )?oil\b",
            r"\boil (?:and|n) filter\b",
            r"\boil filter\b",
            r"\bsynthetic oil\b",
            r"\blube\b.*\boil\b",
        ),
        exclude=(
            r"\btrans\w*\b",
            r"\bgear\b",
            r"\bdiff(?:erential)?\b",
            r"\btransfer case\b",
            r"\bhydraulic\b",
            r"\bfork\b",
            r"\bfinal drive\b",
            r"\bpower steering\b",
            r"\bbrake\w*\b",
            r"\baxle\b",
            r"\bcompressor\b",
            r"\bsensor\b",
            r"\bswitch\b",
            r"\bpan\b",
            r"\bgasket\b",
            r"\bleak\w*\b",
            r"\bpump\b",
            r"\bcooler\b",
            r"\bline\b",
            r"\bseal\b",
            r"\bcap\b",
            r"\blight\b",
            r"\bpressure\b",
            r"\b(?:two|2) stroke\b",
            r"\binjector\w*\b",
        ),
    ),
    MaintenanceType(
        "air_filter",
        "Engine air filter",
        "filters",
        include=(r"\b(?:engine )?air (?:filter|cleaner)\b", r"\bintake filter\b"),
        exclude=(r"\bcabin\b", r"\bpollen\b", r"\bhvac\b", r"\bmass air\b", r"\bmaf\b"),
    ),
    MaintenanceType(
        "cabin_air_filter",
        "Cabin air filter",
        "filters",
        include=(r"\bcabin (?:air )?filter\b", r"\bpollen filter\b", r"\bhvac filter\b"),
    ),
    MaintenanceType(
        "fuel_filter",
        "Fuel filter",
        "filters",
        include=(r"\bfuel filter\b",),
        exclude=(r"\bpump\b", r"\binjector\w*\b"),
    ),
    MaintenanceType(
        "spark_plugs",
        "Spark plugs",
        "engine",
        include=(r"\bspark ?plugs?\b",),
    ),
    MaintenanceType(
        "drive_belt",
        "Drive belt",
        "engine",
        include=(
            r"\bserpentine\b",
            r"\bdrive belt\b",
            r"\baccessory belt\b",
            r"\bv belt\b",
            r"\bfan belt\b",
            r"\balternator belt\b",
        ),
        exclude=(r"\btensioner\b", r"\bpulley\b", r"\bidler\b"),
    ),
    MaintenanceType(
        "timing_belt",
        "Timing belt or chain",
        "engine",
        include=(r"\btiming (?:belt|chain)\b",),
    ),
    MaintenanceType(
        "battery",
        "Battery",
        "electrical",
        include=(
            _pair(
                r"\bbatter(?:y|ies)\b", r"\b(?:replac\w*|new|chang\w*|install\w*|test\w*|swap\w*)\b"
            ),
            r"^batter(?:y|ies)$",
        ),
        exclude=(
            r"\bkey\b",
            r"\bfob\b",
            r"\bremote\b",
            r"\block\b",
            r"\btpms\b",
            r"\bsmoke\b",
            r"\bdetector\b",
            r"\bclock\b",
            r"\bterminal\w*\b",
            r"\bcable\w*\b",
            r"\bstorage\b",
            r"\bmaintainer\b",
            r"\btender\b",
            r"\bcharg\w*\b",
        ),
    ),
    MaintenanceType(
        "coolant_service",
        "Coolant service",
        "fluids",
        include=(
            r"\bcoolant\b",
            r"\bantifreeze\b",
            r"\bradiator (?:flush|service|drain)\w*\b",
            r"\bcooling system (?:flush|service|drain)\w*\b",
        ),
        exclude=(
            r"\bhose\w*\b",
            r"\bthermostat\b",
            r"\bradiator replac\w*\b",
            r"\bleak\w*\b",
            r"\bwater pump\b",
            r"\bsensor\b",
            r"\bcap\b",
            r"\breservoir\b",
            r"\btank\b",
        ),
    ),
    MaintenanceType(
        "transmission_service",
        "Transmission service",
        "fluids",
        include=(
            _pair(r"\btrans(?:mission)?\b", _SERVICE_VERB),
            r"\batf\b",
            r"\bcvt fluid\b",
        ),
        exclude=(
            r"\breplac\w*\b",
            r"\brebuild\w*\b",
            r"\bmount\w*\b",
            r"\bswap\w*\b",
            r"\bsolenoid\b",
            r"\bsensor\b",
            r"\bcooler\b",
            r"\bline\b",
            r"\bleak\w*\b",
        ),
    ),
    MaintenanceType(
        "differential_service",
        "Differential service",
        "fluids",
        include=(
            _pair(r"\bdiff(?:erential)?\b", _SERVICE_VERB),
            r"\bgear oil\b",
            r"\baxle (?:fluid|oil)\b",
            _pair(r"\bfinal drive\b", _SERVICE_VERB),
        ),
        exclude=(r"\breplac\w*\b", r"\brebuild\w*\b", r"\bleak\w*\b", r"\bseal\b", r"\bbearing\b"),
    ),
    MaintenanceType(
        "transfer_case_service",
        "Transfer case service",
        "fluids",
        include=(r"\btransfer case\b",),
        exclude=(r"\breplac\w*\b", r"\brebuild\w*\b", r"\bleak\w*\b", r"\bseal\b"),
    ),
    MaintenanceType(
        "power_steering_fluid",
        "Power steering fluid",
        "fluids",
        include=(
            _pair(r"\bpower steering\b", r"\b(?:fluid|flush\w*|service\w*|change\w*)\b"),
            r"\bps fluid\b",
        ),
        exclude=(r"\bpump\b", r"\brack\b", r"\bhose\w*\b", r"\bleak\w*\b"),
    ),
    MaintenanceType(
        "brake_fluid",
        "Brake fluid",
        "brakes",
        include=(_pair(r"\bbrake\w*\b", r"\b(?:fluid|flush\w*|bleed\w*)\b"),),
        exclude=(r"\bpads?\b", r"\brotors?\b", r"\bcalipers?\b", r"\bshoes?\b"),
    ),
    MaintenanceType(
        "brake_pads",
        "Brake pads and rotors",
        "brakes",
        include=(
            _pair(
                r"\bbrake\w*\b",
                r"\b(?:pads?|shoes?|rotors?|discs?|calipers?|linings?|drums?)\b",
            ),
        ),
        exclude=(
            r"\bfluid\b",
            r"\bflush\w*\b",
            r"\bbleed\w*\b",
            r"\binspect\w*\b",
            r"\bcheck\w*\b",
        ),
    ),
    MaintenanceType(
        "brake_inspection",
        "Brake inspection",
        "brakes",
        include=(_pair(r"\bbrake\w*\b", r"\b(?:check\w*|inspect\w*)\b"),),
        exclude=(
            r"\bfluid\b",
            r"\bflush\w*\b",
            r"\bbleed\w*\b",
            r"\bpads?\b",
            r"\brotors?\b",
            r"\breplac\w*\b",
        ),
    ),
    MaintenanceType(
        "tire_rotation",
        "Tire rotation",
        "tires",
        include=(_pair(_TIRE, r"\brotat\w*\b"), r"\brotat\w*\b.*\bbalanc\w*\b"),
        exclude=(_REPLACE,),
    ),
    MaintenanceType(
        "tire_replacement",
        "Tire replacement",
        "tires",
        include=(_pair(_TIRE, _REPLACE),),
        exclude=(
            r"\brotat\w*\b",
            r"\bsensor\w*\b",
            r"\bvalve\w*\b",
            r"\bpressure\b",
            r"\brepair\w*\b",
            r"\bplug\w*\b",
            r"\bpatch\w*\b",
            r"\bbearing\w*\b",
        ),
    ),
    MaintenanceType(
        "wheel_alignment",
        "Wheel alignment",
        "tires",
        include=(r"\balign\w*\b",),
        exclude=(
            r"\bheadlight\w*\b",
            r"\bdoor\w*\b",
            r"\btrack\b",
            r"\bski\w*\b",
            r"\bbearing\w*\b",
        ),
    ),
    MaintenanceType(
        "wheel_balance",
        "Wheel balance",
        "tires",
        include=(_pair(_TIRE, r"\bbalanc\w*\b"),),
        exclude=(r"\brotat\w*\b",),
    ),
    MaintenanceType(
        "wiper_blades",
        "Wiper blades",
        "other",
        include=(r"\bwiper\w*\b",),
        exclude=(r"\bmotor\b", r"\bfluid\b", r"\bwasher\b", r"\blinkage\b", r"\barm\w*\b"),
    ),
    MaintenanceType(
        "hvac_service",
        "A/C and heating service",
        "other",
        include=(
            _pair(
                r"\b(?:a ?c|air ?con\w*|hvac|climate)\b",
                r"\b(?:service\w*|recharg\w*|refrigerant|inspect\w*|check\w*|clean\w*|evacuat\w*)\b",
            ),
            r"\brefrigerant\b",
        ),
        exclude=(r"\bfilter\b", r"\bcompressor replac\w*\b"),
    ),
    MaintenanceType(
        "state_inspection",
        "State or safety inspection",
        "inspection",
        include=(
            r"\b(?:state|safety|annual|emissions?|smog|mot|tuv|apk|ct|dekra|dot) "
            r"(?:inspection|test|check)\b",
            r"\binspection sticker\b",
            r"\bregistration inspection\b",
            r"\bvehicle inspection\b",
            # #211 — the periodic roadworthiness test as Europe names it.
            # `normalise` lower-cases but keeps accents, hence the classes.
            r"\b(?:technical|roadworthiness|periodic|periodical) (?:inspection|test)\b",
            r"\bcontr[oô]le technique\b",
            r"\bcontre[- ]?visite\b",
            r"\b(?:ct|t[uü]v|hu|apk|itv|snct|mot)\b",
            r"\bhauptuntersuchung\b",
            r"\brevisione\b",
            r"\b(?:auto)?keuring\b",
        ),
        exclude=(r"\bmulti point\b", r"\bpre purchase\b", r"\bbrake\w*\b", r"\btires?\b"),
    ),
    MaintenanceType(
        "drain_plug_washer",
        "Drain plug washer",
        "engine",
        include=(r"\bdrain plug\b", r"\bcrush washer\b"),
    ),
    # Seasonal and hour-metered items the built-in packs declare.
    MaintenanceType(
        "winterize_engine",
        "Winterize engine and fuel system",
        "seasonal",
        include=(_pair(r"\bwinteri[sz]\w*\b", r"\b(?:engine|fuel)\b"), r"\bfog\w*\b.*\bcylinder"),
    ),
    MaintenanceType(
        "winterize_water_system",
        "Winterize water systems",
        "seasonal",
        include=(_pair(r"\bwinteri[sz]\w*\b", r"\bwater\b"), r"\bdrain\w*\b.*\bwater system"),
    ),
    MaintenanceType(
        "battery_storage",
        "Battery storage check",
        "seasonal",
        include=(_pair(r"\bbatter(?:y|ies)\b", r"\bstorage\b"),),
    ),
    MaintenanceType(
        "spring_recommission",
        "Spring recommission",
        "seasonal",
        include=(r"\brecommission\w*\b", r"\bde ?winteri[sz]\w*\b", r"\bspring commission\w*\b"),
    ),
    MaintenanceType(
        "preseason_fluids_belt",
        "Pre-season fluids and belt",
        "seasonal",
        include=(r"\bpre ?season\b",),
    ),
    MaintenanceType(
        "track_ski_alignment",
        "Track and ski alignment",
        "seasonal",
        include=(_pair(r"\b(?:track|ski)s?\b", r"\balign\w*\b"),),
    ),
)


@dataclass(frozen=True)
class CompiledType:
    """A registry entry with its patterns compiled once, at import."""

    type: MaintenanceType
    include: tuple[re.Pattern[str], ...]
    exclude: tuple[re.Pattern[str], ...]


_BY_CODE: dict[str, MaintenanceType] = {t.code: t for t in REGISTRY}
_COMPILED: tuple[CompiledType, ...] = tuple(
    CompiledType(
        t, tuple(re.compile(p) for p in t.include), tuple(re.compile(p) for p in t.exclude)
    )
    for t in REGISTRY
)
_COMPILED_BY_CODE: dict[str, CompiledType] = {c.type.code: c for c in _COMPILED}

_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalise(description: str) -> str:
    """Lower-case, accents stripped, `&` as `and`, every other punctuation
    run as one space.

    Accents go before the punctuation pass (#211): `[^a-z0-9]` would turn
    « contrôle » into "contr le" and "TÜV" into "t v", and no pattern can
    match a word with a hole in it. "contrôle technique" and "controle
    technique" normalise to the same text.
    """
    decomposed = unicodedata.normalize("NFKD", description)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    text = ascii_text.lower().replace("&", " and ")
    return _NON_WORD.sub(" ", text).strip()


def classify(description: str | None) -> str | None:
    """The one code that claims `description`, or `None`.

    `None` for an empty description, for one no type claims, and for one two
    or more types claim. Ambiguity is never resolved by picking a favourite:
    a wrong code links a service to the wrong rule silently, while `None`
    leaves the line item for the owner to type in the preview.
    """
    if not description:
        return None
    text = normalise(description)
    if not text:
        return None
    matches: list[str] = []
    for compiled in _COMPILED:
        if not any(p.search(text) for p in compiled.include):
            continue
        if any(p.search(text) for p in compiled.exclude):
            continue
        matches.append(compiled.type.code)
        if len(matches) > 1:
            return None
    return matches[0] if matches else None


def resolve_type(explicit: str | None, description: str | None) -> str | None:
    """The type a write stores: the one given, else the classifier's verdict.

    Every place that creates a line item or a reminder from free text goes
    through here, so "explicit wins, classify otherwise" is decided once.
    """
    return explicit or classify(description)


def get_compiled(code: str) -> CompiledType | None:
    """The registry entry with compiled patterns, or `None` for a foreign code."""
    return _COMPILED_BY_CODE.get(code)


def get_type(code: str) -> MaintenanceType | None:
    """The registry entry for `code`, or `None` for a code declared elsewhere."""
    return _BY_CODE.get(code)


def label_for(code: str | None, fallback: str | None = None) -> str | None:
    """A display label: the registry's, else `fallback`, else the code itself."""
    if code is None:
        return fallback
    mtype = _BY_CODE.get(code)
    if mtype is not None:
        return mtype.label
    return fallback or code


def is_valid_code(code: str) -> bool:
    """Whether `code` has the shape a stored maintenance type must have."""
    return bool(CODE_RE.fullmatch(code))


def all_types() -> tuple[MaintenanceType, ...]:
    """Every registry entry, in registry order."""
    return REGISTRY
