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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

GAL_TO_L = Decimal("3.785411784")
MI_TO_KM = Decimal("1.609344")


def _dec(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    if not text or text.lower() in {"null", "none", "-"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation, ValueError:
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
    if "data" in headers and "odômetro" in headers or "odometro" in headers:
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


def parse_fuelio(csv_data: str) -> list[dict[str, Any]]:
    """Parse Fuelio CSV export.

    Common columns: Date, Odometer, Fuel Type, Volume(l)/Gallons, Price,
    Total cost, Full tank, Notes. Fuelio may export imperial or metric
    depending on app settings — we sniff volume column name.
    """
    records: list[dict[str, Any]] = []
    for row in _rows(csv_data):
        # Skip Fuelio header junk / vehicle info rows
        date_val = _parse_date(row.get("Date") or row.get("date") or row.get("Data"))
        if not date_val:
            continue

        odo_raw = _dec(row.get("Odometer") or row.get("odometer") or row.get("Mileage"))
        volume_l = _dec(row.get("Volume(l)") or row.get("Volume (l)") or row.get("Liters"))
        gallons = _dec(row.get("Gallons") or row.get("Volume(gal)"))
        cost = _dec(row.get("Total cost") or row.get("Total Cost") or row.get("Cost"))
        price = _dec(row.get("Price") or row.get("Price/L") or row.get("Price/Gal"))
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
            kwh = liters or _dec(row.get("kWh") or row.get("Energy"))
            liters = None
            price_basis = "per_kwh"

        # Odometer: Fuelio often stores user units; assume km unless Miles column
        odometer_km = odo_raw
        if row.get("Miles") and not row.get("Odometer"):
            odometer_km = (_dec(row.get("Miles")) or Decimal(0)) * MI_TO_KM

        records.append(
            {
                "date": date_val,
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


def parse_drivvo(csv_data: str) -> list[dict[str, Any]]:
    """Parse Drivvo CSV export (EN or PT headers)."""
    records: list[dict[str, Any]] = []
    for row in _rows(csv_data):
        date_val = _parse_date(row.get("Date") or row.get("Data") or row.get("date"))
        if not date_val:
            continue

        odo = _dec(
            row.get("Odometer (km)")
            or row.get("Odometer")
            or row.get("Odômetro")
            or row.get("Odometro")
        )
        # Drivvo may export miles
        if odo is None:
            miles = _dec(row.get("Odometer (mi)") or row.get("Mileage"))
            odo = miles * MI_TO_KM if miles is not None else None

        liters = _dec(
            row.get("Quantity (liters)")
            or row.get("Liters")
            or row.get("Quantidade (litros)")
            or row.get("Volume")
        )
        gallons = _dec(row.get("Quantity (gallons)") or row.get("Gallons"))
        price = _dec(
            row.get("Price/liter")
            or row.get("Price per liter")
            or row.get("Preço/litro")
            or row.get("Price")
        )
        cost = _dec(
            row.get("Total cost") or row.get("Total") or row.get("Custo total") or row.get("Cost")
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
            kwh = liters or _dec(row.get("kWh") or row.get("Energy"))
            liters = None
            price_basis = "per_kwh"

        records.append(
            {
                "date": date_val,
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


def parse_tesla(csv_data: str) -> list[dict[str, Any]]:
    """Parse Tesla charge history CSV (or ABRP-style charge exports).

    Typical columns: Charge Start Date, Charge End Date, Energy Added (kWh),
    Odometer, Cost, Charge Type, Starting SOC, Ending SOC.
    """
    records: list[dict[str, Any]] = []
    for row in _rows(csv_data):
        date_val = _parse_date(
            row.get("Charge End Date")
            or row.get("Charge Start Date")
            or row.get("Date")
            or row.get("End Date")
        )
        if not date_val:
            continue

        kwh = _dec(
            row.get("Energy Added (kWh)")
            or row.get("Energy Added")
            or row.get("kWh")
            or row.get("Energy (kWh)")
        )
        odo = _dec(row.get("Odometer") or row.get("Odometer (km)") or row.get("Mileage"))
        if odo is not None and (
            "mi" in (row.get("Odometer Unit") or "").lower() or row.get("Odometer (mi)")
        ):
            odo = odo * MI_TO_KM
            if row.get("Odometer (mi)"):
                odo = _dec(row.get("Odometer (mi)"))
                odo = odo * MI_TO_KM if odo is not None else None

        cost = _dec(row.get("Cost") or row.get("Total Cost") or row.get("Fee"))
        price = _dec(row.get("Price/kWh") or row.get("Rate") or row.get("Cost per kWh"))
        soc_start = _dec(
            row.get("Starting SOC")
            or row.get("Start SOC")
            or row.get("SOC Start")
            or row.get("soc_start")
        )
        soc_end = _dec(
            row.get("Ending SOC") or row.get("End SOC") or row.get("SOC End") or row.get("soc_end")
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
