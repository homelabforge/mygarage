"""World Manufacturer Identifier lookups from the bundled ``wmi.json`` (#211).

ISO 3780 gives the first character of a VIN a region and the first two a
country; the first three name the manufacturer. NHTSA's vPIC knows the
manufacturer of a European VIN but rarely the make or the model, its
check digit means nothing outside North America, and its model year
(position 10) is a plant or series character for most European makers.
This table lets the decoder say what it does know and keep quiet about
what it cannot.

The ISO character order for the ranges is A to Z, then 1 to 9, then 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Region codes by first character: Africa, Asia, Europe, North America,
#: Oceania, South America.
Region = str
REGIONS: tuple[str, ...] = ("AF", "AS", "EU", "NA", "OC", "SA")

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "wmi.json"
_ORDER = "ABCDEFGHJKLMNPRSTUVWXYZ1234567890"
_RANK = {ch: index for index, ch in enumerate(_ORDER)}


@dataclass(frozen=True)
class WMIInfo:
    wmi: str
    make: str
    manufacturer: str
    country: str
    #: Whether this maker writes the model year in position 10 outside
    #: North America (every maker does inside it).
    uses_model_year: bool = False


def _rank(code: str) -> tuple[int, ...]:
    return tuple(_RANK.get(ch, -1) for ch in code)


@lru_cache(maxsize=1)
def _table() -> dict[str, Any]:
    with _DATA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def clear_cache() -> None:
    _table.cache_clear()


def _in_range(code: str, start: str, end: str) -> bool:
    return _rank(start) <= _rank(code) <= _rank(end)


#: Countries whose VINs follow the North American rules (check digit, model
#: year in position 10) whatever block their prefix sits in: the SAE has
#: handed newer US makers prefixes under « 7 » (Tesla's 7SA, Rivian's 7G2).
_NORTH_AMERICAN_COUNTRIES = frozenset({"US", "CA", "MX"})


def region_of(vin: str) -> Region | None:
    """The region the VIN's first character names, or None for an unknown one."""
    clean = (vin or "").strip().upper()
    first = clean[:1]
    if first not in _RANK:
        return None
    if country_of(clean) in _NORTH_AMERICAN_COUNTRIES:
        return "NA"
    for entry in _table()["regions"]:
        if _in_range(first, entry["from"], entry["to"]):
            return str(entry["region"])
    return None


def range_country(prefix: str) -> str | None:
    """The country the ISO two-character range names, ignoring the WMI entries."""
    prefix = (prefix or "").strip().upper()[:2]
    if len(prefix) != 2 or any(ch not in _RANK for ch in prefix):
        return None
    for entry in _table()["countries"]:
        if _in_range(prefix, entry["from"], entry["to"]):
            return str(entry["country"])
    return None


def country_of(vin: str) -> str | None:
    """The ISO 3166-1 alpha-2 country of the VIN's maker.

    A WMI entry wins over the two-character range: the ranges are the coarse
    ISO blocks, and a few assignments sit outside their block (Opel's VXK is
    French though VX–V2 is Serbia's block).
    """
    known = lookup(vin)
    if known is not None:
        return known.country
    return range_country((vin or "").strip().upper()[:2])


def lookup(vin: str) -> WMIInfo | None:
    """The manufacturer the VIN's first three characters name, or None."""
    wmi = (vin or "").strip().upper()[:3]
    entry = _table()["wmi"].get(wmi)
    if entry is None:
        return None
    return WMIInfo(
        wmi=wmi,
        make=str(entry["make"]),
        manufacturer=str(entry.get("manufacturer") or entry["make"]),
        country=str(entry["country"]),
        uses_model_year=bool(entry.get("uses_model_year", False)),
    )


def is_north_american(vin: str) -> bool:
    """Whether the check digit and the model year position apply by rule."""
    return region_of(vin) == "NA"


def model_year_applies(vin: str) -> bool:
    """Whether position 10 is a model year: always in North America, and for
    the makers the table flags elsewhere."""
    if is_north_american(vin):
        return True
    info = lookup(vin)
    return info is not None and info.uses_model_year
