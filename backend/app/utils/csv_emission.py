"""Which unit a CSV column's numbers go OUT in, and how many decimals.

Issue #152 phase 2b. The emitting half of the pair whose reading half is
`app.utils.csv_units`. Schema v6 lets a column name its own unit with a
phase-1 vocabulary token, so an account whose distance is miles but whose
volume is litres exports a file that says exactly what it holds, and the
importer never has to consult a preference to read it back (R1).

The two halves must agree exactly, and nothing structural forces them to,
because task 2 shipped the reader before this shipped the writer. Three
things keep them together:

- the base names below are the same strings `csv_units`' `QuantitySpec.bases`
  accepts, pinned by `tests/unit/utils/test_csv_emission.py`, which drives
  every header this module can emit back through `build_csv_unit_context`;
- the price denominator is `csv_units.volume_factor`, the importer's own
  function, so the two can never drift;
- an end-to-end round trip through both halves is asserted in
  `tests/integration/routes/test_export_csv_v6_units.py`.

Header tokens, never display labels (R2)
----------------------------------------
`gal_us` and `gal_uk` both render as the label `gal`, and `mpg_us`/`mpg_uk`
both as `MPG` (`unit_adapters.py`), so a labelled header cannot identify its
own unit. The phase-1 vocabulary tokens are unique by construction and are
direct keys into `ADAPTERS`. Tokens are case-significant: `L` is not `l`, and
the Celsius token is lowercase `c` even though v5 emitted the display label
`(C)`.

The marker (D-precedence)
-------------------------
v6 emits `metric | imperial | custom` and never `imperial_uk` again: the
gallon flavour now travels in the header token. `imperial_uk` stays
ACCEPTED on import forever, because v2 through v5 files carry it.

The marker is decided by the RESOLVED unit set and nothing else. Reading
`user.unit_preference` instead gets the four obvious cases right and both
interesting ones wrong: a `custom` account whose eleven columns spell out the
metric preset is `metric`, and a `metric` account with one override is
`custom`.

Numeric cells only (R10)
------------------------
`adapter.format()` adds a thousands separator and a unit label, both of which
turn a numeric CSV cell into text a spreadsheet will not sum. Cells go
through `to_display` (or, for price, `volume_factor`) and are then quantized
directly.

Rounding is ROUND_HALF_UP everywhere in this module. Python's default for
`Decimal` is ROUND_HALF_EVEN, which would render a cell sitting exactly on a
half-step differently depending on the digit before it.

Per-column decimal places
-------------------------
Adapter presentation precision is NOT CSV precision: the distance adapters
declare zero decimals, which would round an odometer to the nearest
kilometre. The table below is derived from what each column's stored
`Numeric(p, s)` scale carries, under two rules:

1. A metric cell reproduces the stored scale exactly, so the file is a
   faithful copy of canonical storage.
2. A non-metric cell carries at least as much information as the metric one.
   Where the typed unit is LARGER than the canonical unit, equal decimals
   would be coarser, so it gains places.

| column       | canonical scale | token    | dp | why                          |
|--------------|-----------------|----------|----|------------------------------|
| odometer     | NUMERIC(10,2)   | km       | 2  | the stored scale             |
|              |                 | mi       | 3  | 0.01 mi = 16.1 m > 10 m      |
| volume       | NUMERIC(9,3)    | L        | 3  | the stored scale             |
|              |                 | gal_us   | 4  | 0.001 gal = 3.79 mL > 1 mL   |
|              |                 | gal_uk   | 4  | 0.001 gal = 4.55 mL > 1 mL   |
| price/volume | NUMERIC(13,4)   | L        | 4  | the stored scale             |
|              |                 | gal_us   | 4  | a gallon price is 3.79x the  |
|              |                 | gal_uk   | 4  | litre price, so 4 dp is FINER|
| temperature  | NUMERIC(5,2)    | c        | 2  | the stored scale             |
|              |                 | f        | 2  | 0.01 F = 0.0056 C, finer     |
| consumption  | NUMERIC(7,4)    | l_100km  | 4  | the stored scale             |
|              |                 | km_l     | 6  | reciprocal, see below        |
|              |                 | mpg_us   | 5  | reciprocal, see below        |
|              |                 | mpg_uk   | 5  | reciprocal, see below        |
| speed        | NUMERIC(5,1)    | kmh      | 1  | the stored scale             |
|              |                 | mph      | 2  | 0.1 mph = 0.16 km/h > 0.1    |
| propane vol  | NUMERIC(9,3)    | L        | 3  | as volume                    |
|              |                 | gal_us   | 4  | as volume                    |
|              |                 | gal_uk   | 4  | as volume                    |
| tank size    | NUMERIC(7,3)    | kg       | 3  | the stored scale             |
|              |                 | lb       | 3  | 0.001 lb = 0.45 g, finer     |
| price/mass   | NUMERIC(13,4)   | kg       | 4  | the stored scale             |
|              |                 | lb       | 5  | a pound price is 0.4536x the |
|              |                 |          |    | kilo price; 4 dp is coarser  |

The three reciprocal consumption tokens have no fixed resolution: one step of
MPG is worth more L/100km the thirstier the vehicle. Five decimals carries
the stored 0.0001 L/100km down to 4.9 US MPG and 5.3 UK MPG, below which no
road vehicle goes; one decimal (what v5 emitted) already loses it at 50 MPG.
`km_l` takes six. Its steps are coarser for the same consumption (one km/L
spans more L/100km than one MPG does), so five would carry the stored 0.0001
L/100km only down to 3.16 km/L (31.6 L/100km), which an RV or a loaded truck
goes below. Six carry it to 1 km/L (100 L/100km). (At the old NUMERIC(5,2)
three were enough; the column gained two places, so these did too.)

Price, temperature and consumption all widened so a value typed in the UI
comes back as typed, and the CSV follows. A UK 6.000/gal is stored as
1.3198/L; the litre cell now carries all four places, so a re-import stores
1.3198 again. At 3 places that cell went out as 1.320 and came back 6.001/gal.

A fuel price is written by its basis (K9). A per_weight one is per the mass
unit, at the price/mass places above; a per_kwh or per_tank one has no unit
in its denominator, so it goes out as stored, at 4 places, whatever the
file's units.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.utils.csv_units import (
    CONSUMPTION,
    DISTANCE,
    MASS,
    PRICE_PER_VOLUME,
    PROPANE_VOLUME,
    SPEED,
    TEMPERATURE,
    VOLUME,
    mass_factor,
    spell_header,
    volume_factor,
)
from app.utils.unit_adapters import ADAPTERS

MARKER_METRIC = "metric"
MARKER_IMPERIAL = "imperial"
MARKER_CUSTOM = "custom"


@dataclass(frozen=True)
class EmittedColumn:
    """One unit-bearing export column: where its token comes from, and how it
    is spelled and rounded in every unit it can be written in.

    `field` is the `UnitSet` field supplying the token. Price is denominated
    in a volume, so it reads `volume` rather than a field of its own.
    `decimals` doubles as the column's vocabulary: a token missing from it is
    a token this column cannot emit.
    """

    quantity: str
    field: str
    base: str
    decimals: Mapping[str, int]


_DISTANCE_DECIMALS: Mapping[str, int] = {"km": 2, "mi": 3}
_VOLUME_DECIMALS: Mapping[str, int] = {"L": 3, "gal_us": 4, "gal_uk": 4}
_PRICE_DECIMALS: Mapping[str, int] = {"L": 4, "gal_us": 4, "gal_uk": 4}
_TEMPERATURE_DECIMALS: Mapping[str, int] = {"c": 2, "f": 2}
_CONSUMPTION_DECIMALS: Mapping[str, int] = {
    "l_100km": 4,
    "km_l": 6,
    "mpg_us": 5,
    "mpg_uk": 5,
}
_SPEED_DECIMALS: Mapping[str, int] = {"kmh": 1, "mph": 2}
_MASS_DECIMALS: Mapping[str, int] = {"kg": 3, "lb": 3}
# Five for a pound: at four, 2.2047/kg goes out as 1.0000/lb and comes back
# 2.2046. Five carry it home.
_PRICE_PER_MASS_DECIMALS: Mapping[str, int] = {"kg": 4, "lb": 5}
#: per_kwh and per_tank prices go out as stored.
_UNITLESS_PRICE_DECIMALS = 4

# Keyed by the CANONICAL header name the four export routes declare, which is
# also the metric spelling v3 through v5 emitted. A header not in this map is
# dimensionless and passes through untouched (R6: an allowlist, not a suffix
# parser -- `SOC Start (%)` and `OBC Trip Duration (s)` are real v4 headers
# whose parentheses hold no unit token).
# Named separately from the map below because `routes/reports.py` needs these
# two by name: the report CSVs build their rows by hand rather than through
# `apply_unit_set`, but their odometer and volume cells are the SAME columns
# the backup exports write, so they resolve their token and their decimal
# places from these definitions rather than from a second copy.
ODOMETER_COLUMN = EmittedColumn(DISTANCE, "distance", "Odometer", _DISTANCE_DECIMALS)
VOLUME_COLUMN = EmittedColumn(VOLUME, "volume", "Volume", _VOLUME_DECIMALS)
_FUEL_PRICE_COLUMN = EmittedColumn(PRICE_PER_VOLUME, "volume", "Price Per Unit", _PRICE_DECIMALS)

EMITTED_COLUMNS: Mapping[str, EmittedColumn] = {
    "Odometer (km)": ODOMETER_COLUMN,
    "Reading (km)": EmittedColumn(DISTANCE, "distance", "Reading", _DISTANCE_DECIMALS),
    # A warranty's mileage cap. Added in v3.3.0: the column is unit-bearing and
    # had never been exported at all, so there is no legacy spelling to alias.
    "Mileage Limit (km)": EmittedColumn(DISTANCE, "distance", "Mileage Limit", _DISTANCE_DECIMALS),
    "Liters": VOLUME_COLUMN,
    "Price Per Liter": _FUEL_PRICE_COLUMN,
    # DEF's price column has always been called `Price Per Unit`; v6 adds the
    # volume token to it and the two pairs then share one spelling.
    "Price Per Unit": EmittedColumn(PRICE_PER_VOLUME, "volume", "Price Per Unit", _PRICE_DECIMALS),
    "Outside Temp (C)": EmittedColumn(
        TEMPERATURE, "temperature", "Outside Temp", _TEMPERATURE_DECIMALS
    ),
    # v5 changed the BASE name on imperial export (`OBC L/100km` -> `OBC MPG`),
    # so this is an alias group rather than a name with a swappable suffix.
    # v6 has one base name and four tokens.
    "OBC L/100km": EmittedColumn(CONSUMPTION, "consumption", "OBC Economy", _CONSUMPTION_DECIMALS),
    "OBC Avg Speed (km/h)": EmittedColumn(SPEED, "speed", "OBC Avg Speed", _SPEED_DECIMALS),
    # Batch 3b's fuel columns (B3-3). Propane is a volume, so it follows the
    # account's volume unit; tank size follows its mass unit.
    "Propane Volume (L)": EmittedColumn(
        PROPANE_VOLUME, "volume", "Propane Volume", _VOLUME_DECIMALS
    ),
    "Tank Size (kg)": EmittedColumn(MASS, "mass", "Tank Size", _MASS_DECIMALS),
}


@dataclass(frozen=True)
class BasisPrice:
    """A fuel price cell and the basis its denominator is in (K9).

    The fuel export hands this to `apply_unit_set` in place of a bare price, so
    a per-kg or per-kWh price isn't scaled as if it were per litre.
    """

    value: Decimal | None
    basis: str | None


def marker_for(units: UnitSet) -> str:
    """The `unit_system` marker for a resolved unit set.

    `metric` and `imperial` mean the file is exactly that preset; `custom`
    means the units live in the headers and nowhere else. Never
    `imperial_uk`: a UK-gallon export now says `custom` and carries
    `Volume (gal_uk)`.
    """
    if units == METRIC_PRESET:
        return MARKER_METRIC
    if units == IMPERIAL_PRESET:
        return MARKER_IMPERIAL
    return MARKER_CUSTOM


def token_for(column: EmittedColumn, units: UnitSet) -> str:
    """The vocabulary token `column` is emitted in under `units`."""
    token = getattr(units, column.field)
    if token not in column.decimals:
        raise ValueError(f"{column.base!r} cannot be emitted in {token!r}")
    return str(token)


def header_for(column: EmittedColumn, token: str) -> str:
    """The v6 header for `column` in `token`, e.g. `Volume (gal_uk)`.

    Delegates the spelling to `csv_units.spell_header`, the inverse of the
    importer's own `_split_token`, so the two halves of the round trip cannot
    hold two different format strings. The two report exports spell their
    headers through the same function.
    """
    return spell_header(column.base, token)


def _as_decimal(value: Any) -> Decimal | None:
    """One raw cell as a `Decimal`, with blank and `None` meaning "no value".

    The export routes pass the ORM's own `Decimal` straight through, so this
    is normally the identity. It also absorbs `""`, which is how those routes
    have always spelled an absent number.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantized(value: Decimal, decimals: int) -> str:
    """`value` at `decimals` places, half up, as a plain numeric cell."""
    return format(value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP), "f")


def cell_for(column: EmittedColumn, token: str, value: Decimal | None) -> str:
    """One canonical value as the numeric cell `column` writes in `token`.

    Returns `""` for an absent value, and for a reciprocal adapter's
    undefined zero (0 L/100km has no MPG). Never returns a grouped or
    labelled number: this is a CSV cell, not a rendering.
    """
    if value is None:
        return ""
    decimals = column.decimals[token]
    if column.quantity == PRICE_PER_VOLUME:
        # Denominator-aware: a price PER GALLON is a price per litre
        # MULTIPLIED by the litres in a gallon. Scaling it the way the volume
        # column scales (dividing) is off by the square of the factor.
        display: Decimal | None = value * volume_factor(token)
    else:
        display = ADAPTERS[token].to_display(value)
    if display is None:
        return ""
    return _quantized(display, decimals)


def price_cell(price: BasisPrice, volume_token: str, units: UnitSet) -> str:
    """One fuel price as the cell it's written as, read by its basis.

    The header still says the volume token (K9 accepts that); the Price Basis
    column next to it says what the number is per. A per_weight price is
    per the account's mass unit, which the Tank Size header spells out.
    """
    if price.value is None:
        return ""
    if price.basis == "per_weight":
        return _quantized(
            price.value * mass_factor(units.mass), _PRICE_PER_MASS_DECIMALS[units.mass]
        )
    if price.basis in ("per_kwh", "per_tank"):
        return _quantized(price.value, _UNITLESS_PRICE_DECIMALS)
    return cell_for(_FUEL_PRICE_COLUMN, volume_token, price.value)


def apply_unit_set(
    headers: Sequence[str], rows: Sequence[Sequence[Any]], units: UnitSet
) -> tuple[list[str], list[list[Any]]]:
    """Rewrite a canonical-metric table into `units`, headers and cells alike.

    Storage is metric-canonical, so every export used to be metric whatever
    the account read in, which is unusable for someone migrating years of
    imperial history into another program (#128). Columns with no unit
    (dates, notes, engine hours, costs, percentages) pass through untouched,
    including their existing formatting.
    """
    out_headers: list[str] = []
    columns: list[tuple[EmittedColumn, str] | None] = []
    for header in headers:
        column = EMITTED_COLUMNS.get(header)
        if column is None:
            out_headers.append(header)
            columns.append(None)
            continue
        token = token_for(column, units)
        out_headers.append(header_for(column, token))
        columns.append((column, token))

    out_rows = [
        [_unit_cell(value, bound, units) for value, bound in zip(row, columns, strict=True)]
        for row in rows
    ]
    return out_headers, out_rows


def _unit_cell(value: Any, bound: tuple[EmittedColumn, str] | None, units: UnitSet) -> Any:
    """One cell of `apply_unit_set`: untouched, a price read by its basis, or converted."""
    if bound is None:
        return value
    if isinstance(value, BasisPrice):
        return price_cell(value, bound[1], units)
    return cell_for(bound[0], bound[1], _as_decimal(value))
