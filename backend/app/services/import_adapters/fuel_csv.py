"""Third-party fuel CSV adapters (Fuelio, Drivvo, Tesla).

Each adapter yields normalized dicts ready for FuelRecord construction:
  date, odometer_km, liters, kwh, cost, price_per_unit, price_basis,
  is_full_tank, notes, fuel_type_used, soc_start_pct, soc_end_pct, ...
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

GAL_TO_L = Decimal("3.785411784")
MI_TO_KM = Decimal("1.609344")


@dataclass(frozen=True)
class ParseOptions:
    """Caller-declared interpretation of an ambiguous third-party export.

    Neither Fuelio, Drivvo, nor Tesla stamps units or locale into a bare
    "Odometer" or "Price" column, so guessing corrupts data silently: a US
    export read as km understates distance by 38 percent, and a European
    "35,2" read as dot-decimal becomes 352. The caller declares intent and an
    unambiguous header (an explicit "(mi)" or "Gallons") still wins.
    """

    odometer_unit: str = "km"
    decimal_separator: str = "dot"


def _dec(raw: str | None, sep: str = "dot") -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "-"}:
        return None
    if sep == "comma":
        # "1.234,5" -> "1234.5": dots are thousands separators here.
        text = text.replace(".", "").replace(",", ".")
    else:
        # "1,234.5" -> "1234.5": commas are thousands separators here.
        text = text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation, ValueError:
        return None


def _odometer_km(
    row: dict[str, str],
    opts: ParseOptions,
    *,
    km_keys: tuple[str, ...],
    mi_keys: tuple[str, ...],
    ambiguous_keys: tuple[str, ...],
) -> Decimal | None:
    """Resolve an odometer cell to km.

    An explicit unit in the header always wins. A bare column falls back to the
    caller's declared unit, never to a guess.
    """
    sep = opts.decimal_separator
    for key in mi_keys:
        if row.get(key):
            value = _dec(row.get(key), sep)
            return value * MI_TO_KM if value is not None else None
    for key in km_keys:
        if row.get(key):
            return _dec(row.get(key), sep)
    for key in ambiguous_keys:
        if row.get(key):
            value = _dec(row.get(key), sep)
            if value is None:
                return None
            return value * MI_TO_KM if opts.odometer_unit == "mi" else value
    return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d %b %Y",
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(text[: len(fmt) + 8], fmt).date()
        except ValueError:
            continue
    # ISO date prefix
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(raw: str | None) -> datetime | None:
    """Full timestamp when the cell carries a time, else None.

    Charge exports routinely record several sessions on one day, and the time is
    the only thing that distinguishes them. _parse_date truncates it away, which
    made two same-day sessions look identical and forced duplicate detection to
    compare mutable metadata (cost, notes) instead of the event itself.
    """
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text[: len(fmt) + 8], fmt)
        except ValueError:
            continue
    return None


def _rows(csv_data: str) -> Iterator[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_data))
    for row in reader:
        yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def detect_format(csv_data: str) -> str | None:
    """Best-effort format sniff from header names."""
    reader = csv.DictReader(io.StringIO(csv_data))
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    if {"fuel type", "volume(l)", "odometer"}.issubset(headers) or "fuelio" in " ".join(headers):
        return "fuelio"
    if "data" in headers and ("odômetro" in headers or "odometro" in headers):
        return "drivvo"
    if {"odometer (km)", "quantity (liters)"}.issubset(headers) or "drivvo" in " ".join(headers):
        return "drivvo"
    if {"charge start date", "charge end date"}.issubset(headers) or "energy added" in " ".join(
        headers
    ):
        return "tesla"
    if "odometer" in headers and ("gallons" in headers or "volume" in headers):
        return "fuelio"
    return None


def parse_fuelio(csv_data: str, opts: ParseOptions | None = None) -> list[dict[str, Any]]:
    """Parse Fuelio CSV export.

    Common columns: Date, Odometer, Fuel Type, Volume(l)/Gallons, Price,
    Total cost, Full tank, Notes. Fuelio may export imperial or metric
    depending on app settings — we sniff volume column name.
    """
    opts = opts or ParseOptions()
    sep = opts.decimal_separator
    records: list[dict[str, Any]] = []
    for row in _rows(csv_data):
        # Skip Fuelio header junk / vehicle info rows
        raw_when = row.get("Date") or row.get("date") or row.get("Data")
        date_val = _parse_date(raw_when)
        if not date_val:
            continue
        filled_at = _parse_datetime(raw_when)

        odometer_km = _odometer_km(
            row,
            opts,
            km_keys=("Odometer (km)",),
            mi_keys=("Miles", "Odometer (mi)"),
            ambiguous_keys=("Odometer", "odometer", "Mileage"),
        )
        volume_l = _dec(row.get("Volume(l)") or row.get("Volume (l)") or row.get("Liters"), sep)
        gallons = _dec(row.get("Gallons") or row.get("Volume(gal)"), sep)
        cost = _dec(row.get("Total cost") or row.get("Total Cost") or row.get("Cost"), sep)
        price = _dec(row.get("Price") or row.get("Price/L") or row.get("Price/Gal"), sep)
        full = (row.get("Full tank") or row.get("Full Tank") or "1").lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        notes = row.get("Notes") or row.get("Note") or None
        fuel_type = (row.get("Fuel Type") or row.get("Fuel type") or "").lower()

        liters = volume_l
        price_basis = "per_volume"
        kwh = None
        if liters is None and gallons is not None:
            liters = gallons * GAL_TO_L
            if price is not None:
                price = price / GAL_TO_L
        if "electr" in fuel_type or "kwh" in fuel_type:
            kwh = liters or _dec(row.get("kWh") or row.get("Energy"), sep)
            liters = None
            price_basis = "per_kwh"

        records.append(
            {
                "date": date_val,
                "filled_at": filled_at,
                "odometer_km": odometer_km,
                "liters": liters,
                "kwh": kwh,
                "cost": cost,
                "price_per_unit": price,
                "price_basis": price_basis,
                "is_full_tank": full,
                "notes": notes,
                "fuel_type_used": "electric" if kwh is not None else None,
            }
        )
    return records


def parse_drivvo(csv_data: str, opts: ParseOptions | None = None) -> list[dict[str, Any]]:
    """Parse Drivvo CSV export (EN or PT headers)."""
    opts = opts or ParseOptions()
    sep = opts.decimal_separator
    records: list[dict[str, Any]] = []
    for row in _rows(csv_data):
        raw_when = row.get("Date") or row.get("Data") or row.get("date")
        date_val = _parse_date(raw_when)
        if not date_val:
            continue
        filled_at = _parse_datetime(raw_when)

        odo = _odometer_km(
            row,
            opts,
            km_keys=("Odometer (km)",),
            mi_keys=("Odometer (mi)", "Mileage"),
            ambiguous_keys=("Odometer", "Odômetro", "Odometro"),
        )

        liters = _dec(
            row.get("Quantity (liters)")
            or row.get("Liters")
            or row.get("Quantidade (litros)")
            or row.get("Volume"),
            sep,
        )
        gallons = _dec(row.get("Quantity (gallons)") or row.get("Gallons"), sep)
        price = _dec(
            row.get("Price/liter")
            or row.get("Price per liter")
            or row.get("Preço/litro")
            or row.get("Price"),
            sep,
        )
        cost = _dec(
            row.get("Total cost") or row.get("Total") or row.get("Custo total") or row.get("Cost"),
            sep,
        )
        full = (row.get("Full tank") or row.get("Tanque cheio") or "yes").lower() in {
            "1",
            "true",
            "yes",
            "y",
            "sim",
        }
        notes = row.get("Notes") or row.get("Observações") or row.get("Note") or None
        fuel_type = (
            row.get("Fuel type") or row.get("Tipo de combustível") or row.get("Type") or ""
        ).lower()

        price_basis = "per_volume"
        kwh = None
        if liters is None and gallons is not None:
            liters = gallons * GAL_TO_L
            if price is not None:
                price = price / GAL_TO_L
        if "electr" in fuel_type or "elétr" in fuel_type or "eletr" in fuel_type:
            kwh = liters or _dec(row.get("kWh") or row.get("Energy"), sep)
            liters = None
            price_basis = "per_kwh"

        records.append(
            {
                "date": date_val,
                "filled_at": filled_at,
                "odometer_km": odo,
                "liters": liters,
                "kwh": kwh,
                "cost": cost,
                "price_per_unit": price,
                "price_basis": price_basis,
                "is_full_tank": full,
                "notes": notes,
                "fuel_type_used": "electric" if kwh is not None else None,
            }
        )
    return records


def parse_tesla(csv_data: str, opts: ParseOptions | None = None) -> list[dict[str, Any]]:
    """Parse Tesla charge history CSV (or ABRP-style charge exports).

    Typical columns: Charge Start Date, Charge End Date, Energy Added (kWh),
    Odometer, Cost, Charge Type, Starting SOC, Ending SOC.
    """
    opts = opts or ParseOptions()
    sep = opts.decimal_separator
    records: list[dict[str, Any]] = []
    for row in _rows(csv_data):
        raw_when = (
            row.get("Charge End Date")
            or row.get("Charge Start Date")
            or row.get("Date")
            or row.get("End Date")
        )
        date_val = _parse_date(raw_when)
        if not date_val:
            continue
        # Charge exports routinely hold several sessions per day; the time is
        # what tells them apart.
        filled_at = _parse_datetime(raw_when)

        kwh = _dec(
            row.get("Energy Added (kWh)")
            or row.get("Energy Added")
            or row.get("kWh")
            or row.get("Energy (kWh)"),
            sep,
        )
        odo = _odometer_km(
            row,
            opts,
            km_keys=("Odometer (km)",),
            mi_keys=("Odometer (mi)",),
            ambiguous_keys=("Odometer", "Mileage"),
        )
        # An explicit unit column beats the declared default, but only when the
        # value came from an ambiguous header.
        if (
            odo is not None
            and "mi" in (row.get("Odometer Unit") or "").lower()
            and not row.get("Odometer (km)")
            and not row.get("Odometer (mi)")
            and opts.odometer_unit != "mi"
        ):
            odo = (_dec(row.get("Odometer") or row.get("Mileage"), sep) or Decimal(0)) * MI_TO_KM

        cost = _dec(row.get("Cost") or row.get("Total Cost") or row.get("Fee"), sep)
        price = _dec(row.get("Price/kWh") or row.get("Rate") or row.get("Cost per kWh"), sep)
        soc_start = _dec(
            row.get("Starting SOC")
            or row.get("Start SOC")
            or row.get("SOC Start")
            or row.get("soc_start"),
            sep,
        )
        soc_end = _dec(
            row.get("Ending SOC") or row.get("End SOC") or row.get("SOC End") or row.get("soc_end"),
            sep,
        )
        charge_type = (
            row.get("Charge Type") or row.get("Charger") or row.get("Level") or ""
        ).upper()
        charge_level = None
        if "DC" in charge_type or "SUPER" in charge_type or "DCFC" in charge_type:
            charge_level = "DCFC"
        elif "L2" in charge_type or "LEVEL 2" in charge_type or "AC" in charge_type:
            charge_level = "L2"
        elif "L1" in charge_type or "LEVEL 1" in charge_type:
            charge_level = "L1"

        location_raw = (row.get("Location") or row.get("Site") or "").lower()
        charge_location = None
        if "home" in location_raw:
            charge_location = "home"
        elif location_raw:
            charge_location = "public"

        notes = row.get("Notes") or row.get("Description") or None

        records.append(
            {
                "date": date_val,
                "filled_at": filled_at,
                "odometer_km": odo,
                "liters": None,
                "kwh": kwh,
                "cost": cost,
                "price_per_unit": price,
                "price_basis": "per_kwh",
                "is_full_tank": False,
                "notes": notes,
                "fuel_type_used": "electric",
                "soc_start_pct": soc_start,
                "soc_end_pct": soc_end,
                "charge_level": charge_level,
                "charge_location": charge_location,
            }
        )
    return records


PARSERS = {
    "fuelio": parse_fuelio,
    "drivvo": parse_drivvo,
    "tesla": parse_tesla,
}
