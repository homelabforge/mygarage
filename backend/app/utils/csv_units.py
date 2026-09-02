"""What a CSV column's unit is called, and which unit its numbers are in.

Issue #152 phase 2b. CSV schema v6 lets a column name its own unit with a
phase-1 vocabulary token (`Odometer (mi)`, `Volume (gal_uk)`), so a file
written by a user whose distance is miles but whose volume is litres still
says exactly what it holds. This module owns that vocabulary for BOTH
directions:

- **Reading** (most of this file): deciding a column's unit from the file
  alone, never from a preference. That is the import path.
- **Spelling** (`spell_header`, and the report header templates at the
  bottom): turning a base name and a token into the header text. Every
  emitter in the app goes through `spell_header` -- the four backup exports
  via `csv_emission.header_for`, the two report CSVs via
  `report_header_row` -- so the writing half and the reading half cannot
  hold two different format strings. `spell_header` is the exact inverse of
  `_split_token` and sits next to it for that reason.

Never a preference (R1)
-----------------------
Nothing here reads a `User`, a `UnitSet`, a `RenderContext`, or the
`imperial_gallon_standard` `Setting`. The unit comes from the file: a header
token, else the `unit_system` marker, else `units_version`, else a narrow
inference over the column names. Resolving the importing account's
preference instead is exactly the defect recorded in
`import_data._row_gallons_to_liters`: importing an old US-gallon backup on a
UK-configured instance multiplied every volume by 4.54609 instead of
3.78541 and wrote the result into canonical storage permanently.

Resolution order (R4), per column, first hit wins
-------------------------------------------------
1. A v6 header token: `Base (token)` where `Base` is an allowlisted base
   name for the quantity and `token` is in that quantity's vocabulary.
   Tokens are case-significant: `L` is not `l`.
2. A historical header whose NAME states its unit outright
   (`Outside Temp (F)`, `OBC L/100km`), or states it up to the gallon
   flavour (`OBC MPG`), which the marker then settles.
3. The file's `unit_system` marker.
4. The file's `units_version`, then the unversioned column-shape inference.

Steps 3 and 4 are the file context: one immutable verdict derived from a
pre-scan of every row, never re-derived per row (R5).

Why steps 2 and 3 are split the way they are
--------------------------------------------
`Mileage`, `Gallons`, `Reading`, `Price Per Liter`, `Price Per Gallon`,
`Price/Gal` and `Price Per Unit` do NOT state their unit here even where the
name looks like it does. Those columns have been marker-driven since v3, and a file whose header and marker disagree (a hand-written sheet built
from a copied metric header row) has always been read the marker's way.
Changing that silently rewrites what an existing file means, which is the
one thing this phase must not do.

`Outside Temp (C)`, `Outside Temp (F)`, `OBC L/100km`, `OBC MPG` and
`OBC Avg Speed (km/h)` have no such history: the importer dropped them
entirely until this task, so there is no behaviour to preserve and the name
is the better evidence. A hand-written sheet with `Outside Temp (F)` and no
marker would otherwise store 68 F as 68 C.

Grammar is an allowlist, not a suffix parser (R6)
-------------------------------------------------
Real v4/v5 fuel headers already carry parentheses that are not units:
`OBC Trip Duration (s)`, `SOC Start (%)`, `SOC End (%)`, `Battery SOH (%)`.
Parsing whatever sits in parentheses and rejecting the unknown would reject
valid historical files. Only the base names an importer declares are
inspected; every other header passes through untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, NoReturn, get_args

from fastapi import HTTPException

from app.constants.units import (
    ConsumptionUnit,
    DistanceUnit,
    SpeedUnit,
    TemperatureUnit,
    VolumeUnit,
)
from app.utils.unit_adapters import ADAPTERS

DISTANCE = "distance"
VOLUME = "volume"
PRICE_PER_VOLUME = "price_per_volume"
TEMPERATURE = "temperature"
CONSUMPTION = "consumption"
SPEED = "speed"

# R7: a recognised token for the WRONG quantity is an error, not a fallback.
# `Odometer (gal_us)` and `Volume (mi)` are both real `ADAPTERS` keys and
# would apply a dimensionally meaningless factor to a canonical column, so
# global adapter membership is not sufficient validation. Derived from the
# `UnitSet` Literals rather than hand-listed, so a new token cannot drift.
# `price_per_volume` is denominated in a VOLUME, hence the shared vocabulary.
QUANTITY_TOKENS: Mapping[str, frozenset[str]] = {
    DISTANCE: frozenset(get_args(DistanceUnit)),
    VOLUME: frozenset(get_args(VolumeUnit)),
    PRICE_PER_VOLUME: frozenset(get_args(VolumeUnit)),
    TEMPERATURE: frozenset(get_args(TemperatureUnit)),
    CONSUMPTION: frozenset(get_args(ConsumptionUnit)),
    SPEED: frozenset(get_args(SpeedUnit)),
}

# The token a metric-canonical file's values are already in.
_CANONICAL_TOKEN: Mapping[str, str] = {
    DISTANCE: "km",
    VOLUME: "L",
    PRICE_PER_VOLUME: "L",
    TEMPERATURE: "c",
    CONSUMPTION: "l_100km",
    SPEED: "kmh",
}

# The token a legacy-imperial file's values are in, as (US, UK). Only the
# gallon-denominated quantities differ between the two flavours; miles,
# Fahrenheit and mph are the same either way.
_IMPERIAL_TOKEN: Mapping[str, tuple[str, str]] = {
    DISTANCE: ("mi", "mi"),
    VOLUME: ("gal_us", "gal_uk"),
    PRICE_PER_VOLUME: ("gal_us", "gal_uk"),
    TEMPERATURE: ("f", "f"),
    CONSUMPTION: ("mpg_us", "mpg_uk"),
    SPEED: ("mph", "mph"),
}

# R8: exactly these, and nothing else. Until this task anything starting
# `unit_system=imperial` was read as imperial while only the exact string
# `imperial_uk` meant UK, so `imperial_ukk` silently imported UK gallons as
# US ones. A typo must fail loudly, not convert quietly.
MARKER_METRIC = "metric"
MARKER_IMPERIAL = "imperial"
MARKER_IMPERIAL_UK = "imperial_uk"
MARKER_CUSTOM = "custom"
VALID_MARKERS: frozenset[str] = frozenset(
    {MARKER_METRIC, MARKER_IMPERIAL, MARKER_IMPERIAL_UK, MARKER_CUSTOM}
)

# The rejected report shapes live at the bottom of this module, next to the
# report header templates they are derived from: see "The report exports".

# R9. The v2 standalone odometer export used a bare `Reading` column holding
# MILES, with no marker and no version column. Stated here as a definition
# rather than left to inference, because nothing in such a file distinguishes
# it from a hand-written metric sheet.
V2_ODOMETER_READING_HEADER = "Reading"


@dataclass(frozen=True)
class LegacyHeader:
    """A pre-v6 header this importer reads, and what its NAME establishes.

    `declared` names the unit outright. `flavoured` names it up to the gallon
    flavour, as `(us_token, uk_token)`, which the file's marker settles. Both
    `None` means the name establishes nothing and the file context decides.
    """

    header: str
    declared: str | None = None
    flavoured: tuple[str, str] | None = None


@dataclass(frozen=True)
class QuantitySpec:
    """One quantity an importer consumes, and the headers it accepts for it.

    `bases` are the v6 tokenised base names: `Odometer` accepts
    `Odometer (km)` and `Odometer (mi)`. `legacy` are exact historical header
    strings, matched before any token parsing so that `Outside Temp (C)` is
    read as the display label it is rather than rejected as the unrecognised
    token `C` (the vocabulary token for Celsius is lowercase `c`).
    """

    quantity: str
    bases: tuple[str, ...]
    legacy: tuple[LegacyHeader, ...] = ()


@dataclass(frozen=True)
class ColumnBinding:
    """The one column carrying a quantity, and the unit its values are in."""

    header: str
    quantity: str
    token: str


# --- the quantity specs each importer declares ------------------------------

# Service, fuel and DEF all spell distance `Odometer (km)` / `Mileage`.
ODOMETER_DISTANCE = QuantitySpec(DISTANCE, ("Odometer",), (LegacyHeader("Mileage"),))

# The standalone odometer pair spells it `Reading (km)` / `Reading`, and also
# accepts `Mileage` (it has since v3).
# A warranty's mileage cap. v3.3.0 is the first release to export it, so there
# is no legacy header to alias: the tokenised spelling is the only one.
MILEAGE_LIMIT_DISTANCE = QuantitySpec(DISTANCE, ("Mileage Limit",), ())

READING_DISTANCE = QuantitySpec(
    DISTANCE, ("Reading",), (LegacyHeader("Reading"), LegacyHeader("Mileage"))
)

FUEL_VOLUME = QuantitySpec(VOLUME, ("Volume",), (LegacyHeader("Liters"), LegacyHeader("Gallons")))

# `Price Per Unit (<volume token>)` is the v6 tokenised spelling for both
# fuel and DEF: the base name is already the unit-neutral one DEF has always
# used, and the parenthetical says which volume the price is per. The
# tokenless `Price Per Unit` keeps its historical marker-driven meaning.
FUEL_PRICE = QuantitySpec(
    PRICE_PER_VOLUME,
    ("Price Per Unit",),
    (
        LegacyHeader("Price Per Liter"),
        LegacyHeader("Price Per Gallon"),
        LegacyHeader("Price/Gal"),
    ),
)
DEF_PRICE = QuantitySpec(PRICE_PER_VOLUME, ("Price Per Unit",), (LegacyHeader("Price Per Unit"),))

FUEL_TEMPERATURE = QuantitySpec(
    TEMPERATURE,
    ("Outside Temp",),
    (
        LegacyHeader("Outside Temp (C)", declared="c"),
        LegacyHeader("Outside Temp (F)", declared="f"),
    ),
)

# `OBC L/100km` becomes `OBC MPG` on imperial export: the BASE name changes,
# not just the parenthetical, so this is an alias group and not a name with a
# suffix. `OBC MPG` does not say which gallon its miles-per is measured
# against, so the marker settles that; `OBC L/100km` needs no help.
FUEL_CONSUMPTION = QuantitySpec(
    CONSUMPTION,
    ("OBC Economy",),
    (
        LegacyHeader("OBC L/100km", declared="l_100km"),
        LegacyHeader("OBC MPG", flavoured=("mpg_us", "mpg_uk")),
    ),
)

# `OBC Avg Speed (mph)` needs no legacy entry: `mph` IS the vocabulary token,
# so it parses as a v6 header and means the same thing either way. `km/h` is
# a display label, not a token (the token is `kmh`), so it needs one.
FUEL_SPEED = QuantitySpec(
    SPEED, ("OBC Avg Speed",), (LegacyHeader("OBC Avg Speed (km/h)", declared="kmh"),)
)


def _reject(detail: str) -> NoReturn:
    """Refuse the whole file, naming the cause. Never guess (R8).

    `NoReturn` so a caller's remaining branches read as unreachable to the
    type checker, the same way a bare `raise` would.
    """
    raise HTTPException(status_code=400, detail=detail)


def volume_factor(token: str) -> Decimal:
    """Litres in one `token`, e.g. `3.78541` for `gal_us`.

    Read off the adapter rather than re-declared, so the price denominator
    can never drift from the volume column's own factor. Valid only because
    every volume adapter is proportional (no offset); `_ensure_volume_token`
    holds that line.

    Public because `app.utils.csv_emission` multiplies a canonical per-litre
    price by this on the way out and this module divides by it on the way in.
    Import and export MUST use the same factor, so there is one definition
    and the exporter imports it rather than owning a second copy.
    """
    _ensure_volume_token(token)
    factor = ADAPTERS[token].to_canonical(Decimal("1"))
    if factor is None:  # pragma: no cover - a volume adapter never returns None for 1
        raise ValueError(f"volume adapter {token!r} has no factor")
    return factor


def _ensure_volume_token(token: str) -> None:
    """Guard `volume_factor` against a non-volume token reaching it."""
    if token not in QUANTITY_TOKENS[VOLUME]:
        raise ValueError(f"{token!r} is not a volume token")


class CsvUnitContext:
    """One immutable per-FILE verdict about units, plus the column bindings.

    Built once by :func:`build_csv_unit_context` from a pre-scan of every row
    (R5). `unit_system` and `units_version` are written into every data row by
    `export.generate_csv_stream`, not once per file, so reading only the first
    row would let a later row disagree and be converted under a context it
    does not belong to.
    """

    def __init__(
        self,
        *,
        marker: str,
        version: str,
        legacy_imperial: bool,
        gallon_flavour: str,
        bindings: Mapping[str, ColumnBinding],
    ) -> None:
        self.marker = marker
        self.version = version
        self.legacy_imperial = legacy_imperial
        self.gallon_flavour = gallon_flavour
        self._bindings = dict(bindings)

    def column(self, quantity: str) -> str | None:
        """The header carrying `quantity` in this file, or None if absent."""
        binding = self._bindings.get(quantity)
        return binding.header if binding is not None else None

    def token(self, quantity: str) -> str | None:
        """The vocabulary token `quantity`'s values are in, or None if absent."""
        binding = self._bindings.get(quantity)
        return binding.token if binding is not None else None

    def to_canonical(self, quantity: str, value: Decimal | None) -> Decimal | None:
        """Convert one cell of `quantity` into canonical metric storage.

        Price is denominator-aware: a price per gallon is a price per litre
        DIVIDED by the litres in a gallon, not multiplied by them.
        """
        if value is None:
            return None
        binding = self._bindings.get(quantity)
        if binding is None:
            return value
        if quantity == PRICE_PER_VOLUME:
            return value / volume_factor(binding.token)
        return ADAPTERS[binding.token].to_canonical(value)


def _normalised_markers(rows: Sequence[Mapping[str, Any]]) -> str:
    """The file's single `unit_system`, rejecting rows that disagree (R5)."""
    seen = {(row.get("unit_system") or "").strip().lower() for row in rows}
    seen.discard("")
    if len(seen) > 1:
        _reject(
            "CSV rows disagree about unit_system: "
            f"{', '.join(sorted(repr(value) for value in seen))}. "
            "One file must be in one unit system."
        )
    marker = next(iter(seen), "")
    if marker and marker not in VALID_MARKERS:
        _reject(
            f"Unrecognised unit_system marker {marker!r}. Expected one of: "
            f"{', '.join(sorted(VALID_MARKERS))}."
        )
    return marker


def _single_version(rows: Sequence[Mapping[str, Any]]) -> str:
    """The file's single `units_version`, rejecting rows that disagree (R5)."""
    seen = {(row.get("units_version") or "").strip() for row in rows}
    seen.discard("")
    if len(seen) > 1:
        _reject(
            "CSV rows disagree about units_version: "
            f"{', '.join(sorted(repr(value) for value in seen))}. "
            "One file must be one schema version."
        )
    return next(iter(seen), "")


def spell_header(base: str, token: str) -> str:
    """The v6 header spelling for `base` in `token`, e.g. `"Odometer (mi)"`.

    The exact inverse of `_split_token`, and deliberately its neighbour: the
    two are a bijective pair and a change to either that is not mirrored in
    the other silently breaks the round trip. Every emitter in the app spells
    a tokened header through this one function -- `csv_emission.header_for`
    for the four backup exports, `report_header_row` for the two reports --
    so there is no second copy of the format string to drift.

    Case-preserving: the token is never lowercased, because `L` (litres) and
    `l` are different vocabulary entries.
    """
    return f"{base} ({token})"


def _split_token(header: str, bases: tuple[str, ...]) -> tuple[str, str] | None:
    """`("Odometer", "mi")` for `"Odometer (mi)"`, else None.

    Case-preserving throughout: the token is never lowercased, because `L`
    (litres) and `l` are different vocabulary entries.
    """
    if not header.endswith(")"):
        return None
    open_paren = header.rfind(" (")
    if open_paren <= 0:
        return None
    base = header[:open_paren]
    if base not in bases:
        return None
    return base, header[open_paren + 2 : -1]


def _candidate_binding(header: str, spec: QuantitySpec, marker: str) -> ColumnBinding | None:
    """Bind `header` to `spec`'s quantity, or None if it is not one of its columns.

    Legacy exact matches are tried first: `Outside Temp (C)` carries a display
    label, not the lowercase `c` vocabulary token, and must not be rejected as
    an unrecognised token.
    """
    for entry in spec.legacy:
        if entry.header != header:
            continue
        if entry.declared is not None:
            return ColumnBinding(header, spec.quantity, entry.declared)
        if entry.flavoured is not None:
            us_token, uk_token = entry.flavoured
            return ColumnBinding(
                header,
                spec.quantity,
                uk_token if marker == MARKER_IMPERIAL_UK else us_token,
            )
        # The name establishes nothing; the file context decides later.
        return ColumnBinding(header, spec.quantity, "")

    split = _split_token(header, spec.bases)
    if split is None:
        return None
    _, token = split
    allowed = QUANTITY_TOKENS[spec.quantity]
    if token not in allowed:
        if token in ADAPTERS:
            _reject(
                f"CSV column {header!r} declares unit {token!r}, which is not a "
                f"{spec.quantity} unit. Expected one of: {', '.join(sorted(allowed))}."
            )
        _reject(
            f"CSV column {header!r} declares an unrecognised unit {token!r}. "
            f"Expected one of: {', '.join(sorted(allowed))}."
        )
    return ColumnBinding(header, spec.quantity, token)


def _is_legacy_imperial(marker: str, version: str, bound: Mapping[str, ColumnBinding]) -> bool:
    """Whether a context-driven column's values are imperial (R4 steps 3 and 4).

    Reproduces the pre-v6 rule, lifted from per-row to per-file:

    | input                                    | reading          |
    |------------------------------------------|------------------|
    | marker `imperial` / `imperial_uk`        | legacy imperial  |
    | marker `metric` / `custom`               | metric canonical |
    | `units_version` parses to < 3            | legacy imperial  |
    | `units_version` parses to >= 3           | metric canonical |
    | `units_version` present but unparseable  | legacy imperial  |
    | unversioned bare `Reading`               | legacy imperial  |
    | unversioned `Mileage` or `Gallons` alone | legacy imperial  |
    | anything else                            | metric canonical |

    A BLANK `units_version` counts as absent, not unparseable. A FUTURE
    version reads as metric canonical and is not an error: a newer file's
    unit-bearing columns carry tokens, which never reach this function.
    """
    if marker in (MARKER_IMPERIAL, MARKER_IMPERIAL_UK):
        return True
    if marker in (MARKER_METRIC, MARKER_CUSTOM):
        return False

    if version:
        try:
            # v3 introduced metric-canonical values, so v3 and later are metric.
            return int(version) < 3
        except ValueError:
            # Unparseable: read conservatively rather than trust a value we
            # do not understand.
            return True

    # R9's definition, stated rather than inferred: the v2 standalone odometer
    # export was a bare `Reading` column of miles with no marker and no version.
    distance = bound.get(DISTANCE)
    if distance is not None and distance.header == V2_ODOMETER_READING_HEADER:
        return True

    # Column shape: the imperial names present without their metric siblings.
    headers = {binding.header for binding in bound.values()}
    has_imperial = bool(headers & {"Mileage", "Gallons"})
    has_metric = bool(headers & {"Odometer (km)", "Liters"})
    return has_imperial and not has_metric


def build_csv_unit_context(
    fieldnames: Sequence[str] | None,
    rows: Sequence[Mapping[str, Any]],
    specs: Sequence[QuantitySpec],
) -> CsvUnitContext:
    """Derive one immutable unit context for a whole uploaded CSV.

    Runs before any ORM write. Raises `HTTPException(400)` naming the cause
    for every rejection rule in R8: an unrecognised header token, a
    recognised token for the wrong quantity, an unrecognised marker, marker
    `custom` with a tokenless unit column, two candidate columns for one
    quantity, a duplicated unit column, rows that disagree about
    `unit_system` or `units_version`, the irreducibly ambiguous unversioned
    service-history report, and either of the two v6 report exports.
    """
    headers = list(fieldnames or [])
    rejection = REJECTED_HEADER_TUPLES.get(tuple(headers))
    if rejection is not None:
        _reject(rejection)

    marker = _normalised_markers(rows)
    version = _single_version(rows)

    bound: dict[str, ColumnBinding] = {}
    for spec in specs:
        matches: list[ColumnBinding] = []
        for header in headers:
            binding = _candidate_binding(header, spec, marker)
            if binding is not None:
                matches.append(binding)
        if not matches:
            continue
        distinct = sorted({binding.header for binding in matches})
        if len(distinct) > 1:
            _reject(
                f"CSV has more than one {spec.quantity} column: "
                f"{', '.join(repr(name) for name in distinct)}. "
                "Keep exactly one and re-import."
            )
        if len(matches) > 1:
            _reject(
                f"CSV has a duplicate {distinct[0]!r} column. Remove the duplicate and re-import."
            )
        bound[spec.quantity] = matches[0]

    if marker == MARKER_CUSTOM:
        for binding in bound.values():
            if not binding.token:
                _reject(
                    f"unit_system 'custom' says the units are in the headers, but "
                    f"column {binding.header!r} carries no unit token."
                )

    legacy_imperial = _is_legacy_imperial(marker, version, bound)
    gallon_flavour = "uk" if marker == MARKER_IMPERIAL_UK else "us"

    resolved: dict[str, ColumnBinding] = {}
    for quantity, binding in bound.items():
        if binding.token:
            resolved[quantity] = binding
            continue
        if legacy_imperial:
            us_token, uk_token = _IMPERIAL_TOKEN[quantity]
            token = uk_token if gallon_flavour == "uk" else us_token
        else:
            token = _CANONICAL_TOKEN[quantity]
        resolved[quantity] = ColumnBinding(binding.header, quantity, token)

    return CsvUnitContext(
        marker=marker,
        version=version,
        legacy_imperial=legacy_imperial,
        gallon_flavour=gallon_flavour,
        bindings=resolved,
    )


# --- The report exports, and why they are not importable --------------------
#
# `routes/reports.py` emits two CSVs that are printable summaries rather than
# backups. Both are rejected on import, and both spell their unit-bearing
# columns with the same v6 vocabulary tokens the backup exports use.
#
# The templates below are the ONE source for those header rows: `reports.py`
# emits from them via `report_header_row`, and `REJECTED_HEADER_TUPLES` is
# derived from them by `_report_header_variants`. Renaming a report column
# therefore updates the guard by construction, instead of leaving a
# hand-maintained literal to fall out of step with the emitter.


@dataclass(frozen=True)
class ReportColumn:
    """One report header cell whose spelling depends on the reader's units.

    Built from the importer's own `QuantitySpec` rather than from a loose
    string, so the base name a report emits is by construction a base name
    this module already accepts. `bases` is unpacked as a one-tuple, which
    fails loudly if a spec ever grows a second base and this code has to
    choose between them.
    """

    spec: QuantitySpec

    @property
    def base(self) -> str:
        """The single base name the report spells this quantity with."""
        (base,) = self.spec.bases
        return base

    @property
    def quantity(self) -> str:
        """The quantity this cell carries, keying `QUANTITY_TOKENS`."""
        return self.spec.quantity


# A header row where a plain `str` is a fixed column name and a `ReportColumn`
# is one whose spelling depends on the reader's resolved units.
ReportHeaderTemplate = tuple[str | ReportColumn, ...]

# `reports.download_service_history_csv`. The distance column was called
# `Mileage` until v6; T5-R5 renames it to `Odometer (<token>)` so that one
# base name spells distance across every CSV the app emits, and `Mileage`
# survives only as a legacy alias the importer reads (`ODOMETER_DISTANCE`).
SERVICE_HISTORY_REPORT_HEADERS: ReportHeaderTemplate = (
    "Date",
    ReportColumn(ODOMETER_DISTANCE),
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
)

# `reports.download_all_records_csv`. `Volume (<token>)` is new in v6 and is
# APPENDED rather than inserted: under metric the seven pre-v6 columns keep
# their exact spellings and positions, so a spreadsheet reading columns 0..6
# is unaffected, and the two row-type-specific columns (`Vendor`, which only
# service rows fill, and `Volume`, which only fuel rows fill) end up adjacent
# at the end instead of splitting the free-text block around `Description`.
ALL_RECORDS_REPORT_HEADERS: ReportHeaderTemplate = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    ReportColumn(ODOMETER_DISTANCE),
    "Vendor",
    ReportColumn(FUEL_VOLUME),
)


def report_header_row(template: ReportHeaderTemplate, tokens: Mapping[str, str]) -> list[str]:
    """`template` spelled out for a reader whose units are `tokens`.

    `tokens` maps a quantity constant (`DISTANCE`, `VOLUME`) to the
    vocabulary token that quantity is emitted in. A template cell whose
    quantity is missing from `tokens` raises `KeyError` rather than falling
    back to canonical, because a silently-metric column in an imperial file
    is the exact defect this phase exists to remove.
    """
    return [
        cell if isinstance(cell, str) else spell_header(cell.base, tokens[cell.quantity])
        for cell in template
    ]


def _report_header_variants(template: ReportHeaderTemplate) -> set[tuple[str, ...]]:
    """Every header row `template` can be emitted as, over all unit sets.

    The cross product of each `ReportColumn`'s full quantity vocabulary, so
    the guard covers an imperial reader's export as well as a metric one's.
    Both quantities are small (two distance tokens, three volume tokens), so
    the all-records template expands to six rows and the service-history one
    to two.
    """
    rows: list[tuple[str, ...]] = [()]
    for cell in template:
        if isinstance(cell, str):
            rows = [row + (cell,) for row in rows]
            continue
        rows = [
            row + (spell_header(cell.base, token),)
            for row in rows
            for token in sorted(QUANTITY_TOKENS[cell.quantity])
        ]
    return set(rows)


# --- Which report shapes are refused on import, and why ---------------------
#
# A report CSV is never importable, in ANY era. `routes/reports.py` writes
# printable summaries, not backups: both endpoints flatten each service visit
# into one row per line item and carry columns the service importer does not
# consume, and `download_all_records_csv` additionally interleaves fuel rows
# into what that importer reads as a service file.
#
# That flat rule REPLACES a narrower one that refused only the shapes whose
# UNITS were ambiguous. The narrower rule left the worst case wide open:
# importing a pre-v6 all-records report returned HTTP 200 and created one
# service visit per fuel fill-up, each stamped `service_category='Maintenance'`
# because the importer ignores the report's `Type` column and coerces the
# unknown category. Those rows are indistinguishable from real maintenance in
# the UI and in every cost aggregate. Ambiguity was the wrong criterion; a
# report is simply not a backup, and the shape a user is most likely to
# re-import is one they exported before the guard existed.
#
# ★ The historical literals below are NOT redundant with the derived tuples
# and must NOT be deleted as such. The emitters that wrote them no longer
# exist, so nothing can derive them; deleting one silently un-rejects every
# file that era produced.
#
# Matching is by exact ORDERED header tuple, never by column membership. The
# v2 PRIMARY service export carries the same seven names as the seven-column
# report in a different order (`3fc799c`, one day after `2d46bae`), and the v2
# INITIAL service export carries eight names overlapping the eight-column
# report's, again in a different order and with `Vendor Location` where the
# report has `Vendor Phone`. Membership matching would break the first of
# those backup restores outright.

# `download_service_history_csv`, `2d46bae`..v6. Seven columns. This is the
# one shape that is ALSO unit-ambiguous: its `Mileage` header survived the
# 2026-04-25 metric migration unchanged, so a miles file and a kilometres file
# are byte-identical. It keeps its own message for that reason.
_HISTORICAL_SERVICE_HISTORY_REPORT = (
    "Date",
    "Mileage",
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
)

# `download_service_history_csv`, `ad13de6`..`2d46bae` (23 tagged releases).
# Eight columns. Retired before the metric migration, so its values can only
# be miles and it is NOT ambiguous -- it is refused for being a report.
_HISTORICAL_SERVICE_HISTORY_REPORT_V2 = (
    "Date",
    "Mileage",
    "Service Type",
    "Description",
    "Cost",
    "Vendor Name",
    "Vendor Phone",
    "Notes",
)

# `download_all_records_csv`, `ad13de6`..`6f04e53`, and `6f04e53`..v6. The
# distance column was renamed in the same commit that made its values
# canonical, so neither era is ambiguous. Both are refused for being reports,
# and this pair is where the fuel-row corruption actually happened.
_HISTORICAL_ALL_RECORDS_REPORT_V2 = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Mileage",
    "Vendor",
)
_HISTORICAL_ALL_RECORDS_REPORT_V3 = (
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (km)",
    "Vendor",
)

# Each message claims only what the header tuple establishes. A header row is
# evidence that a file MATCHES a report export, not proof of where it came
# from: these seven or eight names in this order are also a plausible
# hand-authored sheet, and telling such a user their file "is" a report export
# would assert a provenance nothing in the file supports.
REJECTED_REPORT_DETAIL = (
    "This header row matches the unversioned service-history report export. "
    "Its 'Mileage' column is miles in older files and kilometres in newer ones, "
    "with nothing in the file to tell them apart, so importing it could "
    "silently store the wrong distance. Re-export the vehicle from "
    "Export > Service records instead, which carries a units marker."
)
_SERVICE_HISTORY_REPORT_DETAIL = (
    "This header row matches the service-history report export, which is a "
    "printable summary rather than a backup: it flattens each service visit "
    "into one row per line item and carries columns the importer does not "
    "consume, so importing it would create malformed records. Re-export the "
    "vehicle from Export > Service records instead."
)
_ALL_RECORDS_REPORT_DETAIL = (
    "This header row matches the all-records report export, which is a "
    "printable summary rather than a backup: it interleaves fuel rows with "
    "service rows in one file, so importing it would create a service visit "
    "out of every fill-up. Re-export the vehicle from Export instead, one "
    "record type at a time."
)

# A read-only view rather than a bare dict: an annotation is documentation,
# not enforcement, and the object this replaced was a frozenset that an
# importer could not mutate at all.
REJECTED_HEADER_TUPLES: Mapping[tuple[str, ...], str] = MappingProxyType(
    {
        _HISTORICAL_SERVICE_HISTORY_REPORT: REJECTED_REPORT_DETAIL,
        _HISTORICAL_SERVICE_HISTORY_REPORT_V2: _SERVICE_HISTORY_REPORT_DETAIL,
        _HISTORICAL_ALL_RECORDS_REPORT_V2: _ALL_RECORDS_REPORT_DETAIL,
        _HISTORICAL_ALL_RECORDS_REPORT_V3: _ALL_RECORDS_REPORT_DETAIL,
        **{
            headers: _SERVICE_HISTORY_REPORT_DETAIL
            for headers in _report_header_variants(SERVICE_HISTORY_REPORT_HEADERS)
        },
        **{
            headers: _ALL_RECORDS_REPORT_DETAIL
            for headers in _report_header_variants(ALL_RECORDS_REPORT_HEADERS)
        },
    }
)
