"""Opt-in LLM-assisted fuel receipt parsing (draft only, never writes FuelRecord)."""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._types import ScaledNumeric
from app.models.fuel import FuelRecord
from app.services import llm_client
from app.services.settings_service import SettingsService
from app.utils.units import UnitConverter

logger = logging.getLogger(__name__)

OCR_FAILED_DETAIL = "Could not read any text from the image. Paste the receipt text instead."

# What we ask the LLM for: numbers and units exactly as printed. Models are bad
# at unit math, so the server does the converting (D4).
_PROMPT_KEYS = (
    "date",
    "odometer",
    "odometer_unit",
    "volume",
    "volume_unit",
    "kwh",
    "cost",
    "price_per_unit",
    "price_volume_unit",
    "fuel_type_used",
    "notes",
    "station_name",
)

_TEXT_KEYS = ("date", "fuel_type_used", "notes", "station_name")

# Spellings we trust, lowercased. Anything else and the value is null, since a
# guessed unit is worse than an empty field.
_UNIT_ALIASES = {
    "l": "L",
    "liter": "L",
    "liters": "L",
    "litre": "L",
    "litres": "L",
    "gal": "gal",
    "gallon": "gal",
    "gallons": "gal",
    "km": "km",
    "kilometer": "km",
    "kilometers": "km",
    "kilometre": "km",
    "kilometres": "km",
    "mi": "mi",
    "mile": "mi",
    "miles": "mi",
}


def _column_type(name: str) -> ScaledNumeric:
    """The FuelRecord column's type, so the draft rounds to what a save would store."""
    col_type = FuelRecord.__table__.c[name].type
    if not isinstance(col_type, ScaledNumeric):
        raise TypeError(f"FuelRecord.{name} is not a ScaledNumeric column")
    return col_type


_ODOMETER_COL = _column_type("odometer_km")
_LITERS_COL = _column_type("liters")
_PRICE_COL = _column_type("price_per_unit")
_COST_COL = _column_type("cost")
_KWH_COL = _column_type("kwh")

# Plain decimals only. Decimal() also takes "1_000", "1e3" and "NaN", and none
# of those is how a receipt prints a number. Fifteen whole digits is more than
# any column holds, and a million-digit one would overflow the mi/gal maths.
_PLAIN_DECIMAL = re.compile(r"-?[0-9]{1,15}(?:\.[0-9]+)?")


def _number(value: Any) -> Decimal | None:
    """An int, float or plain decimal string as a finite Decimal; anything else is None."""
    # bool is an int subclass, and Decimal(True) is 1. True is not 1 litre.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        number = Decimal(repr(value))
        return number if number.is_finite() else None
    if isinstance(value, str) and _PLAIN_DECIMAL.fullmatch(text := value.strip()):
        return Decimal(text)
    return None


def _unit(value: Any, allowed: tuple[str, ...]) -> str | None:
    """The canonical unit for a printed spelling, if it's one of `allowed`."""
    if not isinstance(value, str):
        return None
    unit = _UNIT_ALIASES.get(value.strip().lower())
    return unit if unit in allowed else None


def _converted(value: Any, unit: Any, allowed: tuple[str, ...]) -> Decimal | None:
    """The value in canonical metric, or None when the number or unit is unusable."""
    number = _number(value)
    canonical_unit = _unit(unit, allowed)
    if number is None or canonical_unit is None:
        return None
    return UnitConverter.to_canonical_decimal(number, canonical_unit)


def _price_per_liter(value: Any, unit: Any) -> Decimal | None:
    """A per-litre or per-US-gallon price as a per-litre price."""
    number = _number(value)
    canonical_unit = _unit(unit, ("L", "gal"))
    if number is None or canonical_unit is None:
        return None
    if canonical_unit == "gal":
        return number / UnitConverter.US_GALLONS_TO_LITERS
    return number


def _stored(col: ScaledNumeric, value: Decimal | None) -> Decimal | None:
    """The value as the column would store it, or None if it won't fit.

    rounded() hands back a number too long to round untouched, and that one
    fails the width check too.
    """
    if value is None:
        return None
    rounded: Decimal = col.rounded(value)
    if rounded.adjusted() >= col.precision - col.scale:
        return None
    return rounded


def _positive(value: Decimal | None) -> Decimal | None:
    """Null for zero or below. A receipt never prints a zero odometer, volume or price."""
    return value if value is not None and value > 0 else None


def _non_negative(value: Decimal | None) -> Decimal | None:
    """Null below zero. Zero stays, since a free charge is a real receipt."""
    if value is None or value < 0:
        return None
    # "-0.00" passes the check above, and a free charge isn't negative.
    return value.copy_abs() if value.is_zero() else value


def _build_draft(raw: dict[str, Any]) -> dict[str, Any]:
    """Turn the LLM's as-printed reply into the canonical draft."""
    odometer = _converted(raw.get("odometer"), raw.get("odometer_unit"), ("km", "mi"))
    liters = _converted(raw.get("volume"), raw.get("volume_unit"), ("L", "gal"))
    price = _price_per_liter(raw.get("price_per_unit"), raw.get("price_volume_unit"))
    # A number where text belongs used to fail the response model with a 500.
    draft: dict[str, Any] = {
        key: value if isinstance(value := raw.get(key), str) else None for key in _TEXT_KEYS
    }
    draft.update(
        odometer_km=_positive(_stored(_ODOMETER_COL, odometer)),
        liters=_positive(_stored(_LITERS_COL, liters)),
        price_per_unit=_positive(_stored(_PRICE_COL, price)),
        kwh=_stored(_KWH_COL, _non_negative(_number(raw.get("kwh")))),
        cost=_stored(_COST_COL, _non_negative(_number(raw.get("cost")))),
    )
    return draft


async def parse_receipt_draft(
    db: AsyncSession,
    *,
    text: str | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Return ``{"draft": {...}, "source": "llm"}``. Raises 403 when disabled."""
    if not await SettingsService.get_bool(db, "llm_receipt_parse_enabled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="LLM receipt parsing is disabled",
        )

    receipt_text = (text or "").strip()
    if not receipt_text and file_bytes:
        from app.services.document_ocr import DocumentOCRService

        ocr = DocumentOCRService()
        name = (filename or "").lower()
        is_pdf = name.endswith(".pdf") or (content_type or "").endswith("pdf")
        try:
            receipt_text = (
                await ocr.extract_text_from_bytes(file_bytes, is_pdf=is_pdf) or ""
            ).strip()
        except Exception as exc:  # noqa: BLE001 - OCR backends raise broadly
            # Deliberately NOT falling through with a placeholder. That spent a
            # 60s LLM call on text we never had, then returned an all-null draft
            # indistinguishable from a genuinely blank receipt.
            logger.info("Receipt OCR failed (%s)", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=OCR_FAILED_DETAIL,
            ) from exc

    if not receipt_text:
        # document_ocr swallows a missing OCR dependency and returns "", so a
        # user who did upload an image would otherwise be told to provide one.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OCR_FAILED_DETAIL if file_bytes else "Provide text or an image file",
        )

    system = (
        "You extract vehicle fuel/charge receipt fields. "
        "Reply with ONLY a JSON object using keys: "
        + ", ".join(_PROMPT_KEYS)
        + ". Give every number exactly as printed and never convert units. "
        "odometer_unit is km or mi, volume_unit is L or gal, and price_volume_unit "
        "is the unit price_per_unit is per (L or gal). Gallons are US gallons. "
        "Use null for anything the receipt doesn't say, including a unit."
    )
    content = await llm_client.chat_completion(
        db,
        system=system,
        user=f"Receipt text:\n{receipt_text[:8000]}",
        temperature=0,
    )
    raw = llm_client.extract_json_object(str(content))
    return {"draft": _build_draft(raw), "source": "llm"}
