"""Fuel and DEF rows from a JSON backup, and the fuel helpers the CSV route shares."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Callable, Mapping
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.fuel import (
    PAYMENT_METHOD_VALUES,
    TRIP_TYPE_VALUES,
    FuelTypeEnum,
    normalize_fuel_type,
)
from app.models import (
    AddressBookEntry,
    DEFRecord,
    FuelRecord,
)
from app.models.user import User
from app.routes.import_data._common import (
    _blank_to_none,
    _in_vocabulary,
    _is_blank,
    _json_decimal,
    _json_int,
    _json_text,
    _RowError,
    _within_api_bounds,
    parse_decimal,
)
from app.routes.import_data._matching import (
    _COLUMN_SCALE,
    _at_scale,
    _converted_value_matches,
    _matches,
    _money_matches,
    _odometer_matches,
    _or_blank_zero,
    _same_figure,
    _text_matches,
)
from app.schemas.def_record import DEFRecordCreate
from app.schemas.fuel import (
    CHARGE_LEVEL_VALUES,
    CHARGE_LOCATION_VALUES,
    PRICE_BASIS_VALUES,
    FuelRecordCreate,
    _parse_obc_trip_duration,
    _validate_diesel_grade,
    _validate_octane,
)
from app.utils.csv_units import MASS, PRICE_PER_VOLUME, CsvUnitContext
from app.utils.odometer_tolerance import LITRE_STEP

logger = logging.getLogger(__name__)


def _coerce_octane(value: object) -> int | None:
    """A backup's octane as an int, or a ValueError for a fractional one.

    JSON numbers arrive as int or float; a float only passes when it is
    integral, because int() would otherwise store 91.9 as 91 and let 150.9
    sneak under the 150 bound the API enforces (codex code review R1-M1).
    Strings raise in int() and fail the row like any other bad field.
    """
    if value is None:
        return None
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"octane must be a whole number, got {value!r}")
    return int(value)  # type: ignore[arg-type]


def _derive_price_basis(
    price_per_unit: Decimal | None,
    *,
    liters: Decimal | None = None,
    propane_liters: Decimal | None = None,
    kwh: Decimal | None = None,
) -> str | None:
    """Which denominator `price_per_unit` is measured against.

    Mirrors migration 053's rule verbatim, on the post-053 metric columns.
    Imports previously left this NULL, and the frontend's `priceToDisplay`
    converts a stored price to the user's units ONLY when the basis says
    `per_volume` — so on an imperial account every imported fill-up showed
    the canonical per-litre figure under a "Price/Gal" heading. $2.50/gal
    was stored correctly as $0.660/L and then rendered as "0.66" (#128).

    Returns None when there is no price, since there is then nothing to
    interpret — a basis on a priceless row would be noise.
    """
    if price_per_unit is None:
        return None
    if kwh is not None and liters is None and propane_liters is None:
        return "per_kwh"
    if liters is not None or propane_liters is not None:
        return "per_volume"
    return None


def _csv_fuel_price(
    units: CsvUnitContext,
    row: Mapping[str, Any],
    *,
    liters: Decimal | None,
    propane_liters: Decimal | None,
    kwh: Decimal | None,
) -> tuple[Decimal | None, str | None]:
    """A fuel CSV row's canonical price and its basis (K9, S11).

    The Price Basis column says what the price is per; a file without one
    derives it like the migration did, so an old file reads exactly as before.
    A per_weight price takes its pound or kilo from the Tank Size header, the
    only place it's written, so without that column the row is refused.
    """
    header = units.column(PRICE_PER_VOLUME)
    raw = parse_decimal(row.get(header) or "") if header is not None else None
    basis = _in_vocabulary(
        _blank_to_none((row.get("Price Basis") or "").strip()), "price_basis", PRICE_BASIS_VALUES
    ) or _derive_price_basis(raw, liters=liters, propane_liters=propane_liters, kwh=kwh)
    if raw is not None and basis == "per_weight" and units.column(MASS) is None:
        raise _RowError("a per_weight price needs the Tank Size column to say what weight it's per")
    price = units.price_to_canonical(raw, basis)
    # R7: a converted price is rounded to the column's scale, like `_canonical_cell` does.
    if units.price_converts(basis):
        price = _at_scale(price, _COLUMN_SCALE[PRICE_PER_VOLUME])
    return price, basis


def _local_datetime(raw: Any, key: str) -> datetime | None:
    """A fill-up's naive local time. The export never writes a zone; one given is dropped."""
    if _is_blank(raw):
        return None
    if not isinstance(raw, str):
        raise _RowError(f"{key} is not a valid date and time")
    try:
        return datetime.fromisoformat(raw.strip()).replace(tzinfo=None)
    except ValueError as e:
        raise _RowError(f"{key} is not a valid date and time") from e


def _trip_seconds(raw: Any, key: str) -> int | None:
    """The trip duration in seconds, read the way the API reads it."""
    try:
        return _parse_obc_trip_duration(raw)
    except ValueError as e:
        raise _RowError(f"{key} must be whole seconds, HH:MM or HH:MM:SS") from e


#: The warnings for a link this instance can't confirm (R6), added once the row is written.
_STATION_KEPT_AS_TEXT = "station not in this address book, kept as text"
_DRIVER_KEPT_AS_TEXT = "driver not on this instance, kept as text"


async def _portable_station(
    db: AsyncSession, station_id: int | None, name: str | None
) -> tuple[int | None, str | None, bool]:
    """The station id and text to store, and whether a link was dropped (R6).

    The id stays only when this address book holds it under the same name (the
    export writes the resolved name), so a file from another instance never
    links someone else's entry. Otherwise the name is kept as text.
    """
    text = (name or "").strip()[:150] or None
    if station_id is None:
        return None, text, False
    entry = await db.get(AddressBookEntry, station_id)
    if (
        entry is not None
        and text
        and (entry.business_name or "").strip().casefold() == text.casefold()
    ):
        return station_id, None, False
    return None, text, True


async def _portable_driver(
    db: AsyncSession, driver_id: int | None, username: str | None, freetext: str | None
) -> tuple[int | None, str | None, bool]:
    """The driver id and text to store, and whether a link was dropped (R6).

    The id stays only when it is a user here with the exported username. The
    API checks nothing more for a driver (T-5).
    """
    if driver_id is None:
        return None, ((freetext or "").strip()[:100] or None), False
    user = await db.get(User, driver_id)
    if user is not None and username and user.username.casefold() == username.strip().casefold():
        return driver_id, freetext, False
    return None, ((freetext or username or "").strip()[:100] or None), True


#: Who writes a DEF row: a purchase (the column default, models/def_record.py:44-46)
#: or the fuel form's fill-level sync (utils/def_sync.py:72). No CHECK backs it.
_DEF_ENTRY_TYPES = ("purchase", "auto_fuel_sync")


def _fuel_record_from_json(
    vin: str,
    date: date_type,
    row: Mapping[str, Any],
    *,
    idx: int,
    odometer_km: Decimal | None,
    liters: Decimal | None,
    price_per_unit: Decimal | None,
) -> FuelRecord:
    """A JSON fuel row as an unsaved record, the API's rules re-applied (R2).

    `odometer_km`, `liters` and `price_per_unit` arrive converted from a legacy
    file. The station and driver links are left for the caller to set once this
    instance has confirmed them (R6).
    """
    filled_at = _local_datetime(row.get("filled_at"), "filled_at")
    engine_hours = _json_decimal(row, "engine_hours")
    propane_liters = _json_decimal(row, "propane_liters")
    tank_size_kg = _json_decimal(row, "tank_size_kg")
    tank_quantity = _json_int(row, "tank_quantity")
    kwh = _json_decimal(row, "kwh")
    soc_start_pct = _json_decimal(row, "soc_start_pct")
    soc_end_pct = _json_decimal(row, "soc_end_pct")
    battery_soh_pct = _json_decimal(row, "battery_soh_pct")
    cost = _json_decimal(row, "cost")
    rebate = _json_decimal(row, "rebate")
    outside_temp_c = _json_decimal(row, "outside_temp_c")
    obc_l_per_100km = _json_decimal(row, "obc_l_per_100km")
    obc_avg_speed_kmh = _json_decimal(row, "obc_avg_speed_kmh")
    obc_trip_duration_s = _trip_seconds(row.get("obc_trip_duration_s"), "obc_trip_duration_s")
    _within_api_bounds(
        FuelRecordCreate,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        liters=liters,
        propane_liters=propane_liters,
        tank_size_kg=tank_size_kg,
        tank_quantity=tank_quantity,
        kwh=kwh,
        soc_start_pct=soc_start_pct,
        soc_end_pct=soc_end_pct,
        battery_soh_pct=battery_soh_pct,
        cost=cost,
        rebate=rebate,
        price_per_unit=price_per_unit,
        outside_temp_c=outside_temp_c,
        obc_l_per_100km=obc_l_per_100km,
        obc_avg_speed_kmh=obc_avg_speed_kmh,
        obc_trip_duration_s=obc_trip_duration_s,
    )
    price_basis = _in_vocabulary(
        _blank_to_none(row.get("price_basis")), "price_basis", PRICE_BASIS_VALUES
    ) or _derive_price_basis(price_per_unit, liters=liters, propane_liters=propane_liters, kwh=kwh)

    # The export has always written fuel_type_used and is_hauling but the
    # importer silently dropped both, so a restored backup lost them. Same
    # locale-tolerant normalization as the CSV path.
    raw_fuel_type = (row.get("fuel_type_used") or "").strip() or None
    normalized_fuel_type = normalize_fuel_type(raw_fuel_type)
    if raw_fuel_type and normalized_fuel_type is None:
        logger.warning(
            "Fuel import record %s: unrecognized fuel type %r → 'other'",
            idx,
            raw_fuel_type,
        )
        normalized_fuel_type = FuelTypeEnum.OTHER

    return FuelRecord(
        vin=vin,
        date=date,
        filled_at=filled_at,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        liters=liters,
        propane_liters=propane_liters,
        tank_size_kg=tank_size_kg,
        tank_quantity=tank_quantity,
        kwh=kwh,
        soc_start_pct=soc_start_pct,
        soc_end_pct=soc_end_pct,
        charge_level=_in_vocabulary(
            _blank_to_none(row.get("charge_level")), "charge_level", CHARGE_LEVEL_VALUES
        ),
        charge_location=_in_vocabulary(
            _blank_to_none(row.get("charge_location")), "charge_location", CHARGE_LOCATION_VALUES
        ),
        battery_soh_pct=battery_soh_pct,
        cost=cost,
        rebate=rebate,
        price_per_unit=price_per_unit,
        price_basis=price_basis,
        fuel_type_used=normalized_fuel_type.value if normalized_fuel_type is not None else None,
        # #164: direct ORM construction bypasses Pydantic, so the shared
        # validators run here per row (R1-M2). _coerce_octane rejects a
        # fractional value instead of silently truncating it the way a bare
        # int() would (91.9 -> 91; codex review R1-M1).
        octane=_validate_octane(_coerce_octane(row.get("octane"))),
        diesel_grade=_validate_diesel_grade(row.get("diesel_grade")),
        is_full_tank=row.get("is_full_tank", True),
        missed_fillup=row.get("missed_fillup", False),
        is_hauling=row.get("is_hauling", False),
        notes=row.get("notes"),
        payment_method=_in_vocabulary(
            _blank_to_none(row.get("payment_method")), "payment_method", PAYMENT_METHOD_VALUES
        ),
        trip_type=_in_vocabulary(
            _blank_to_none(row.get("trip_type")), "trip_type", TRIP_TYPE_VALUES
        ),
        outside_temp_c=outside_temp_c,
        obc_l_per_100km=obc_l_per_100km,
        obc_avg_speed_kmh=obc_avg_speed_kmh,
        obc_trip_duration_s=obc_trip_duration_s,
    )


def _json_fuel_key(
    row: Mapping[str, Any],
    record: FuelRecord,
    *,
    converted: bool,
    last_id: int,
    zero_was_null: bool,
) -> list[ColumnElement[bool]]:
    """R5's fuel key: date and odometer always, the rest only when the row has the key (T-16).

    A v9 row carries every key, so an hours-only or propane fill-up with no
    odometer is told apart by its quantities (R1-H1). A v<=8 file wrote 0 L
    as null, so there its null also matches a stored 0 (`zero_was_null`).
    """
    key = [
        FuelRecord.date == record.date,
        _odometer_matches(
            FuelRecord, record.odometer_km, converted=converted, last_id_before_import=last_id
        ),
    ]
    if "filled_at" in row:
        key.append(_matches(FuelRecord.filled_at, record.filled_at))
    if "liters" in row or "gallons" in row:
        key.append(
            _or_blank_zero(
                _converted_value_matches(
                    FuelRecord.liters,
                    record.liters,
                    LITRE_STEP,
                    converted=converted,
                    stored_before_import=FuelRecord.id <= last_id,
                ),
                FuelRecord.liters,
                record.liters,
                zero_was_blank=zero_was_null,
            )
        )
    # NUMERIC(8,3) and (9,3).
    if "kwh" in row:
        key.append(_same_figure(FuelRecord.kwh, record.kwh))
    if "propane_liters" in row:
        key.append(_same_figure(FuelRecord.propane_liters, record.propane_liters))
    if "cost" in row:
        key.append(_money_matches(FuelRecord.cost, record.cost))
    # C-1, C-5: the rest of what tells two fill-ups apart. A propane exchange
    # has no odometer or litres, so the tanks and hours carry it. Flags, payment,
    # trip type, trip computer, temperature and charge details stay out on purpose:
    # they describe the same fill-up, and an edit to one shouldn't re-import it.
    # Price basis, station and driver are derived or rewritten on import.
    for name in ("engine_hours", "tank_size_kg", "soc_start_pct", "soc_end_pct"):
        if name in row:
            key.append(_same_figure(getattr(FuelRecord, name), getattr(record, name)))
    if "tank_quantity" in row:
        key.append(_matches(FuelRecord.tank_quantity, record.tank_quantity))
    if "rebate" in row:
        key.append(_money_matches(FuelRecord.rebate, record.rebate))
    # A legacy unit price was converted from per gallon, at a scale that moved
    # since, so only a canonical one is compared.
    if "price_per_unit" in row and not converted:
        key.append(_same_figure(FuelRecord.price_per_unit, record.price_per_unit))
    if "octane" in row:
        key.append(_matches(FuelRecord.octane, record.octane))
    if "diesel_grade" in row:
        key.append(_matches(FuelRecord.diesel_grade, record.diesel_grade))
    return key


def _canonical_fuel_type(raw: str | None) -> str | None:
    """A fuel type as the import stores it: the listed value, 'other' for an unknown word."""
    if raw is None or not raw.strip():
        return None
    normalized = normalize_fuel_type(raw)
    return (normalized or FuelTypeEnum.OTHER).value


def _same_fuel_type(row: Mapping[str, Any], record: FuelRecord) -> Callable[[Any], bool] | None:
    """The fuel type compared on the loaded row, so an old 'Gasoline' still reads as gasoline (T-16)."""
    if "fuel_type_used" not in row:
        return None
    return lambda stored: _canonical_fuel_type(stored.fuel_type_used) == record.fuel_type_used


def _def_record_from_json(
    vin: str,
    date: date_type,
    row: Mapping[str, Any],
    *,
    odometer_km: Decimal | None,
    liters: Decimal | None,
    price_per_unit: Decimal | None,
) -> DEFRecord:
    """A JSON DEF row as an unsaved record, the API's rules re-applied (R2).

    No price_basis: DEF is volume-only, has no such column, and the UI passes
    'per_volume' as a literal when displaying it. No origin_fuel_record_id
    either: the fill-up it named is on the instance that wrote the file.
    """
    cost = _json_decimal(row, "cost")
    fill_level = _json_decimal(row, "fill_level")
    _within_api_bounds(
        DEFRecordCreate,
        odometer_km=odometer_km,
        liters=liters,
        price_per_unit=price_per_unit,
        cost=cost,
        fill_level=fill_level,
    )
    return DEFRecord(
        vin=vin,
        date=date,
        odometer_km=odometer_km,
        liters=liters,
        price_per_unit=price_per_unit,
        cost=cost,
        fill_level=fill_level,
        source=_json_text(row, "source"),
        brand=_json_text(row, "brand"),
        notes=_json_text(row, "notes"),
        entry_type=_in_vocabulary(
            _blank_to_none(row.get("entry_type")), "entry_type", _DEF_ENTRY_TYPES
        )
        or "purchase",
    )


def _json_def_key(
    row: Mapping[str, Any],
    record: DEFRecord,
    *,
    converted: bool,
    last_id: int,
    zero_was_null: bool,
) -> list[ColumnElement[bool]]:
    """R5's DEF key: date and odometer always, the rest only when the row has the key (T-16).

    A v<=8 file wrote 0 L and a 0.00 fill level as null, so there its null also
    matches a stored 0 (`zero_was_null`).
    """
    key = [
        DEFRecord.date == record.date,
        _odometer_matches(
            DEFRecord, record.odometer_km, converted=converted, last_id_before_import=last_id
        ),
    ]
    if "liters" in row or "gallons" in row:
        key.append(
            _or_blank_zero(
                _converted_value_matches(
                    DEFRecord.liters,
                    record.liters,
                    LITRE_STEP,
                    converted=converted,
                    stored_before_import=DEFRecord.id <= last_id,
                ),
                DEFRecord.liters,
                record.liters,
                zero_was_blank=zero_was_null,
            )
        )
    if "cost" in row:
        key.append(_money_matches(DEFRecord.cost, record.cost))
    # NUMERIC(3,2).
    if "fill_level" in row:
        key.append(
            _or_blank_zero(
                _same_figure(DEFRecord.fill_level, record.fill_level),
                DEFRecord.fill_level,
                record.fill_level,
                zero_was_blank=zero_was_null,
            )
        )
    if "entry_type" in row:
        key.append(DEFRecord.entry_type == record.entry_type)
    # C-5: the unit price (a canonical one, as fuel), and where and which brand.
    if "price_per_unit" in row and not converted:
        key.append(_same_figure(DEFRecord.price_per_unit, record.price_per_unit))
    if "source" in row:
        key.append(_text_matches(DEFRecord.source, record.source))
    if "brand" in row:
        key.append(_text_matches(DEFRecord.brand, record.brand))
    return key
