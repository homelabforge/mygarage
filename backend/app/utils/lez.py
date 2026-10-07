"""Euro class and low-emission-zone class, computed from what the vehicle says (#211).

Pure functions, no database. The Crit'Air grid is the French one for cars
and light vans (arrêté du 21 juin 2016, consolidated); heavy vehicles,
buses and L-category vehicles have their own grids and come back as
"unclassified" here (`None`), which the UI says plainly. Every result is
indicative: the official site decides, and a person can set the class by
hand on the vehicle (`lez_class`), which the compliance view prefers.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

#: Fuel types (app.constants.fuel.FuelTypeEnum values) grouped by how a
#: low-emission scheme sees them.
_ELECTRIC = frozenset({"electric", "hydrogen"})
_GAS = frozenset({"cng", "propane_lpg"})
_PLUGIN = frozenset({"plugin_hybrid"})
_PETROL = frozenset({"gasoline", "e85", "hybrid"})
_DIESEL = frozenset({"diesel"})

#: Vehicle types the car/light-van grid applies to; the others (Motorcycle,
#: ATV, Boat, Trailer…) are not classified here.
CAR_LIKE_TYPES = frozenset({"Car", "SUV", "Truck", "Electric", "Hybrid", "RV"})

#: First day every new registration had to meet the class (passenger cars).
EURO_CLASS_FROM: tuple[tuple[date, int], ...] = (
    (date(2015, 9, 1), 6),
    (date(2011, 1, 1), 5),
    (date(2006, 1, 1), 4),
    (date(2001, 1, 1), 3),
    (date(1997, 1, 1), 2),
    (date(1993, 1, 1), 1),
)

LezBasis = Literal["override", "euro_class", "first_registration", "fuel"]

_EURO_RE = re.compile(r"euro\s*-?\s*([1-6])", re.IGNORECASE)
_LEADING_DIGIT_RE = re.compile(r"^\s*([1-6])(?![0-9])")


def euro_class_number(text: str | None) -> int | None:
    """The Euro class a V.9 text names: « Euro 6d-TEMP » → 6,
    « 715/2007*692/2008EURO5 » → 5, « 6d » → 6, anything else → None."""
    if not text:
        return None
    match = _EURO_RE.search(text) or _LEADING_DIGIT_RE.match(text)
    return int(match.group(1)) if match else None


def estimated_euro_class(first_registration: date | None) -> int | None:
    """The Euro class a car first registered on that day had to meet, at least.

    An estimate: a model may have been approved to a newer class before the
    date it became mandatory. None before Euro 1 (1993) or without a date.
    """
    if first_registration is None:
        return None
    for since, euro in EURO_CLASS_FROM:
        if first_registration >= since:
            return euro
    return None


def _engine_kind(
    fuel_type: str | None, fuel_type_secondary: str | None, vehicle_type: str | None
) -> str | None:
    """'electric', 'gas', 'plugin', 'petrol', 'diesel' or None.

    A hybrid is its combustion engine; `hybrid` alone is petrol (the common
    case) unless the secondary fuel says diesel. A vehicle typed Electric
    with no fuel on record is electric.
    """
    fuels = {f for f in (fuel_type, fuel_type_secondary) if f}
    if fuels & _ELECTRIC and not (fuels & (_PETROL | _DIESEL)):
        return "electric"
    if fuels & _PLUGIN:
        return "plugin"
    if fuels & _GAS:
        return "gas"
    if fuel_type in _DIESEL or (fuel_type == "hybrid" and fuel_type_secondary in _DIESEL):
        return "diesel"
    if fuels & _PETROL:
        return "petrol"
    if not fuels and vehicle_type == "Electric":
        return "electric"
    return None


def critair_class(
    *,
    fuel_type: str | None,
    fuel_type_secondary: str | None,
    vehicle_type: str | None,
    euro_class: int | None,
    first_registration: date | None,
) -> tuple[str | None, LezBasis | None]:
    """The Crit'Air class of a car or light van, and what it rests on.

    0: electric and hydrogen. 1: gas, plug-in hybrid, petrol Euro 5/6.
    2: petrol Euro 4, diesel Euro 5/6. 3: petrol Euro 2/3, diesel Euro 4.
    4: diesel Euro 3. 5: diesel Euro 2. Earlier vehicles are not classified.
    The Euro class given wins; without one, the class is estimated from the
    first registration date and the basis says so.
    """
    if vehicle_type not in CAR_LIKE_TYPES:
        return None, None
    kind = _engine_kind(fuel_type, fuel_type_secondary, vehicle_type)
    if kind == "electric":
        return "0", "fuel"
    if kind in ("gas", "plugin"):
        return "1", "fuel"
    if kind not in ("petrol", "diesel"):
        return None, None

    basis: LezBasis = "euro_class"
    euro = euro_class
    if euro is None:
        euro = estimated_euro_class(first_registration)
        basis = "first_registration"
    if euro is None:
        return None, None

    if kind == "petrol":
        grid = {6: "1", 5: "1", 4: "2", 3: "3", 2: "3"}
    else:
        grid = {6: "2", 5: "2", 4: "3", 3: "4", 2: "5"}
    value = grid.get(euro)
    return (value, basis) if value is not None else (None, basis)
