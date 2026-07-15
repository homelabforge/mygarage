"""Fuel record business logic service layer with L/100km calculation.

Canonical units (since v2.26.2): SI metric. Fuel economy surfaces as
L/100 km (lower is better). Imperial display is done client-side via the
frontend UnitFormatter.
"""

# pyright: reportReturnType=false, reportOptionalOperand=false

import logging
from datetime import date as date_type
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AddressBookEntry
from app.models.fuel import FuelRecord
from app.models.user import User
from app.schemas.fuel import FuelRecordCreate, FuelRecordResponse, FuelRecordUpdate
from app.utils.cache import cached, invalidate_cache_for_vehicle
from app.utils.def_sync import ensure_def_capable, sync_def_from_fuel_record
from app.utils.fuel_station_sync import resolve_fuel_station
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


# Propane-by-weight → liters conversion factor.
# Derived from: gal = lb/4.24 (old imperial formula, 4.24 lb/gal density of propane)
#   L_per_kg = (1/0.45359237) / 4.24 * 3.78541  ≈  1.96850 L/kg
PROPANE_LITERS_PER_KG = Decimal("1.9685")


async def resolve_station_names(
    db: AsyncSession, records: list[FuelRecord]
) -> dict[int, str | None]:
    """Map ``record.id`` -> the station name to display for that record.

    A record either links an address-book entry (FK, freetext nulled by
    ``resolve_fuel_station`` case 1) or carries a one-time-visit freetext name.
    Neither alone is a reliable display value, so callers get the resolved
    name: address-book ``business_name`` first, freetext as fallback.

    Address-book names are fetched in one batched query, so this stays O(1)
    queries regardless of how many records are passed (issue #108).
    """
    station_ids = {r.station_address_book_id for r in records if r.station_address_book_id}
    names: dict[int, str] = {}
    if station_ids:
        result = await db.execute(
            select(AddressBookEntry.id, AddressBookEntry.business_name).where(
                AddressBookEntry.id.in_(station_ids)
            )
        )
        names = dict(result.all())  # type: ignore[arg-type]

    # names has int keys, so a null FK simply misses and falls back to freetext.
    return {r.id: names.get(r.station_address_book_id) or r.station_name_freetext for r in records}


async def build_fuel_response(
    db: AsyncSession, record: FuelRecord, l_per_100km: Decimal | None
) -> FuelRecordResponse:
    """Build the API response for a single fuel record, station name resolved.

    Uses ``db.get`` rather than the batched lookup: on create/update the
    address-book row is already in the session's identity map (the write path
    just loaded or created it), so this usually resolves without any query.
    """
    station_name = record.station_name_freetext
    if record.station_address_book_id:
        entry = await db.get(AddressBookEntry, record.station_address_book_id)
        station_name = (entry.business_name if entry else None) or record.station_name_freetext
    return _fuel_response(record, l_per_100km, station_name)


def _fuel_response(
    record: FuelRecord,
    l_per_100km: Decimal | None,
    station_name: str | None,
) -> FuelRecordResponse:
    """Assemble a response from an ORM row plus its derived fields."""
    record_dict = record.__dict__.copy()
    record_dict["l_per_100km"] = l_per_100km
    record_dict["station_name"] = station_name
    return FuelRecordResponse(**record_dict)


def calculate_l_per_100km(
    current_record: FuelRecord,
    previous_record: FuelRecord | None,
    interval_liters: Decimal | None = None,
) -> Decimal | None:
    """Calculate L/100km for a full-tank fuel record.

    Logic:
    - Only calculate for full tank fill-ups
    - Skip if no previous full tank fill-up
    - Skip if no odometer recorded
    - L/100km = fuel_since_previous_full / (distance_km / 100)

    ``interval_liters`` is the total fuel added since the previous full tank —
    every partial fill-up in between PLUS this full fill-up. This is the
    correct numerator: the distance was covered on all that fuel, not just the
    volume of the final full fill-up. When the caller can't supply it we fall
    back to ``current_record.liters`` alone, which under-reports consumption
    whenever partial fill-ups exist (issue #113); callers on the display and
    average paths always pass it.

    Lower values are better fuel economy.
    """
    # Only calculate for full tank fill-ups
    if not current_record.is_full_tank:
        return None

    # A missed fill-up means the distance since the previous record includes
    # fuel that was never recorded — no valid economy figure exists for this
    # record. It still re-anchors the sequence for the NEXT fill-up.
    if current_record.missed_fillup:
        return None

    # Need odometer_km and liters on current record
    if not current_record.odometer_km or not current_record.liters:
        return None

    # Need a previous record to calculate distance
    if not previous_record or not previous_record.odometer_km:
        return None

    distance_km = current_record.odometer_km - previous_record.odometer_km

    # Sanity check
    if distance_km <= 0 or current_record.liters <= 0:
        return None

    liters = interval_liters if interval_liters is not None else current_record.liters
    if liters <= 0:
        return None

    l_per_100km = (liters / distance_km) * Decimal("100")
    return round(l_per_100km, 2)


def compute_full_tank_economy(
    records_asc: list[FuelRecord],
    exclude_hauling: bool = False,
) -> list[tuple[FuelRecord, Decimal]]:
    """L/100km for each full-tank record, computed in a single O(n) pass.

    ``records_asc`` must be every odometer-bearing fill-up for the vehicle,
    ordered by odometer ascending. Consecutive full-tank endpoints tile the
    odometer axis, so a running accumulator collects the liters of every partial
    fill-up since the previous endpoint and folds them — plus the endpoint's own
    fill — into that interval's numerator (issue #113). This is the single
    source of truth for the per-record, vehicle-average, and dashboard surfaces
    so they can't drift apart.

    Endpoint rules:
    - A missed fill-up (amount unknown) is still an endpoint: it anchors the
      next interval but yields no figure of its own (``calculate_l_per_100km``
      returns None for it).
    - When ``exclude_hauling`` is set, a hauling full tank is not an endpoint, so
      its fuel folds into the surrounding interval instead of splitting it.

    Returns ``(record, l_per_100km)`` pairs in odometer order, only for
    endpoints that produced a valid figure.
    """
    results: list[tuple[FuelRecord, Decimal]] = []
    prev_endpoint: FuelRecord | None = None
    liters_since = Decimal(0)  # fuel added strictly after prev_endpoint

    for record in records_asc:
        if record.odometer_km is None:
            continue
        if record.liters is not None:
            liters_since += record.liters

        if not record.is_full_tank or (exclude_hauling and record.is_hauling):
            continue

        # `record` is an endpoint; its own liters are already in `liters_since`.
        value = calculate_l_per_100km(record, prev_endpoint, liters_since)
        if value is not None:
            results.append((record, value))

        prev_endpoint = record
        liters_since = Decimal(0)

    return results


async def sum_liters_since_previous_full(
    db: AsyncSession,
    vin: str,
    previous_full: FuelRecord,
    current_record: FuelRecord,
) -> Decimal | None:
    """SQL sum of liters in the odometer window (prev_full, current].

    Single-record equivalent of the accumulator in
    :func:`compute_full_tank_economy`, for the create/update/get paths where
    loading the whole sequence to score one record would be wasteful. The
    current record must already be persisted so it is counted (issue #113).
    """
    if previous_full.odometer_km is None or current_record.odometer_km is None:
        return None

    result = await db.execute(
        select(func.coalesce(func.sum(FuelRecord.liters), 0))
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.liters.isnot(None))
        .where(FuelRecord.odometer_km > previous_full.odometer_km)
        .where(FuelRecord.odometer_km <= current_record.odometer_km)
    )
    total = result.scalar()
    return Decimal(str(total)) if total is not None else Decimal(0)


async def get_previous_full_tank(
    db: AsyncSession,
    vin: str,
    current_date: date_type,
    current_odometer_km: Decimal | None,
) -> FuelRecord | None:
    """Get the most recent previous full tank fill-up."""
    query = (
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.is_full_tank.is_(True))
        .where(FuelRecord.date < current_date)
    )

    if current_odometer_km:
        query = query.where(FuelRecord.odometer_km < current_odometer_km)

    query = query.order_by(FuelRecord.date.desc()).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


@cached(ttl_seconds=300)  # Cache for 5 minutes
async def calculate_average_l_per_100km(
    db: AsyncSession, vin: str, exclude_hauling: bool = True
) -> Decimal | None:
    """Calculate average L/100km across all full-tank fuel records.

    Args:
        db: Database session
        vin: Vehicle VIN
        exclude_hauling: If True (default), exclude is_hauling=True records
            for more representative daily-driving economy
    """
    # Load ALL fill-ups with an odometer (not just full tanks) so partial
    # fill-ups between two full tanks contribute their volume to the interval
    # (issue #113). Ordered by odometer so the accumulator is monotonic.
    result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.odometer_km.isnot(None))
        .order_by(FuelRecord.odometer_km.asc(), FuelRecord.date.asc())
    )
    all_records = list(result.scalars().all())

    values = [value for _, value in compute_full_tank_economy(all_records, exclude_hauling)]
    if not values:
        return None

    return round(sum(values) / len(values), 2)


class FuelRecordService:
    """Service for managing fuel record business logic with L/100km calculations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _economy_for(self, vin: str, record: FuelRecord) -> Decimal | None:
        """L/100km for a single just-written/read full-tank record.

        Finds the previous full tank and sums the partial fill-ups since it
        (issue #113) via a bounded SQL query rather than loading the whole
        sequence. Returns None for partial fill-ups and un-anchorable records.
        """
        if not record.is_full_tank:
            return None
        prev_record = await get_previous_full_tank(self.db, vin, record.date, record.odometer_km)
        interval_liters = (
            await sum_liters_since_previous_full(self.db, vin, prev_record, record)
            if prev_record
            else None
        )
        return calculate_l_per_100km(record, prev_record, interval_liters)

    async def list_fuel_records(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
        include_hauling: bool = False,
    ) -> tuple[list[FuelRecordResponse], int, Decimal | None]:
        """List fuel records with per-record L/100km + vehicle-wide average."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .order_by(FuelRecord.date.desc())
                .offset(skip)
                .limit(limit)
            )
            records = result.scalars().all()

            # Per-record economy for every full tank, computed once over the
            # whole ordered sequence so partial fill-ups fold into the next full
            # tank (issue #113). Hauling tanks stay as endpoints here — the
            # per-record display shows a figure for each full fill-up.
            all_asc_result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .where(FuelRecord.odometer_km.isnot(None))
                .order_by(FuelRecord.odometer_km.asc(), FuelRecord.date.asc())
            )
            all_asc = list(all_asc_result.scalars().all())
            economy_by_id = {r.id: value for r, value in compute_full_tank_economy(all_asc)}

            station_names = await resolve_station_names(self.db, list(records))
            responses = [
                _fuel_response(record, economy_by_id.get(record.id), station_names.get(record.id))
                for record in records
            ]

            count_result = await self.db.execute(
                select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
            )
            total = count_result.scalar()

            avg_value = await calculate_average_l_per_100km(
                self.db, vin, exclude_hauling=not include_hauling
            )

            return responses, total, avg_value

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing fuel records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_fuel_record(
        self, vin: str, record_id: int, current_user: User
    ) -> tuple[FuelRecord, Decimal | None]:
        """Get a specific fuel record with L/100km."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

        value = await self._economy_for(vin, record)

        return record, value

    async def create_fuel_record(
        self, vin: str, record_data: FuelRecordCreate, current_user: User
    ) -> tuple[FuelRecord, Decimal | None]:
        """Create a new fuel record with L/100km calc.

        Uses a single outer transaction (since v2.27.0) so station create,
        usage_count bump, fuel-record insert, odometer sync, and DEF sync
        either all succeed or all roll back together.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            record_dict = record_data.model_dump()
            record_dict["vin"] = vin

            # Pop DEF fill level before creating FuelRecord (not a fuel table column)
            def_fill_level = record_dict.pop("def_fill_level", None)
            # Gate BEFORE any DB insert/mutation so a rejected request leaves
            # no fuel record row behind (the bypass surface this closes).
            if def_fill_level is not None:
                ensure_def_capable(vehicle)
            # Pop the one_time_visit form-only flag — not a column on fuel_records
            one_time_visit = bool(record_dict.pop("one_time_visit", False))
            station_id_in = record_dict.pop("station_address_book_id", None)
            station_name_in = record_dict.pop("station_name_freetext", None)

            # Mirror filled_at into date when only filled_at was provided.
            if record_dict.get("filled_at") is not None and record_dict.get("date") is None:
                record_dict["date"] = record_dict["filled_at"].date()

            # Compatibility: keep legacy fuel_type populated when a client
            # sends only fuel_type_used (and vice versa) for one release.
            # The legacy → fuel_type_used direction only mirrors when the
            # legacy value happens to be on the canonical enum vocabulary;
            # otherwise we leave fuel_type_used null rather than poisoning
            # the new column with pre-migration free-text.
            ft_legacy = record_dict.get("fuel_type")
            ft_used = record_dict.get("fuel_type_used")
            if ft_used and not ft_legacy:
                record_dict["fuel_type"] = ft_used
            elif ft_legacy and not ft_used:
                from app.constants.fuel import FUEL_TYPE_VALUES as _FT

                if ft_legacy in _FT:
                    record_dict["fuel_type_used"] = ft_legacy

            # Auto-calculate propane_liters if tank-by-weight data provided
            if (
                record_dict.get("tank_size_kg") is not None
                and record_dict.get("tank_quantity") is not None
                and record_dict.get("propane_liters") is None
            ):
                tank_kg = Decimal(str(record_dict["tank_size_kg"]))
                qty = Decimal(str(record_dict["tank_quantity"]))
                calculated = tank_kg * PROPANE_LITERS_PER_KG * qty
                record_dict["propane_liters"] = calculated.quantize(Decimal("0.001"))

            # ---- Single outer transaction begins ----
            # 1. Resolve station inputs (may create an address_book row).
            station_id, station_freetext = await resolve_fuel_station(
                self.db,
                station_address_book_id=station_id_in,
                station_name_freetext=station_name_in,
                one_time_visit=one_time_visit,
            )
            record_dict["station_address_book_id"] = station_id
            record_dict["station_name_freetext"] = station_freetext

            # 2. Insert fuel record.
            record = FuelRecord(**record_dict)
            self.db.add(record)
            await self.db.flush()  # populate record.id without committing

            # 3. Odometer sync (no internal commit).
            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="fuel",
                        source_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    # Log but do NOT swallow — let the outer transaction roll
                    # back so we don't end up with a stranded fuel record
                    # that's missing its odometer entry.
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record (rolling back): %s",
                        sanitize_for_log(e),
                    )
                    raise

            # 4. DEF sync (no internal commit).
            if def_fill_level is not None:
                try:
                    await sync_def_from_fuel_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        fill_level=def_fill_level,
                        fuel_record_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync DEF for fuel record (rolling back): %s",
                        sanitize_for_log(e),
                    )
                    raise

            # 5. Single commit closes the outer transaction.
            await self.db.commit()
            await self.db.refresh(record)

            value = await self._economy_for(vin, record)

            logger.info(
                "Created fuel record %s for %s (L/100km: %s)",
                record.id,
                sanitize_for_log(vin),
                value,
            )

            await invalidate_cache_for_vehicle(vin)

            return record, value

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid fuel record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_fuel_record(
        self,
        vin: str,
        record_id: int,
        record_data: FuelRecordUpdate,
        current_user: User,
    ) -> tuple[FuelRecord, Decimal | None]:
        """Update a fuel record; recompute L/100km."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            update_data = record_data.model_dump(exclude_unset=True)
            def_fill_level = update_data.pop("def_fill_level", None)
            def_fill_level_was_sent = "def_fill_level" in record_data.model_fields_set
            # Gate BEFORE any field mutation so a rejected request leaves the
            # existing fuel record untouched.
            if def_fill_level_was_sent and def_fill_level is not None:
                ensure_def_capable(vehicle)

            # Mirror filled_at into date when only filled_at was sent.
            if (
                "filled_at" in record_data.model_fields_set
                and update_data.get("filled_at") is not None
                and "date" not in record_data.model_fields_set
            ):
                update_data["date"] = update_data["filled_at"].date()

            # Compatibility mirroring between legacy fuel_type and fuel_type_used.
            # Legacy → fuel_type_used only mirrors values already on the enum
            # vocabulary so we don't poison the new column with pre-migration
            # free-text strings.
            ft_legacy_sent = "fuel_type" in record_data.model_fields_set
            ft_used_sent = "fuel_type_used" in record_data.model_fields_set
            if ft_used_sent and not ft_legacy_sent:
                update_data["fuel_type"] = update_data.get("fuel_type_used")
            elif ft_legacy_sent and not ft_used_sent:
                from app.constants.fuel import FUEL_TYPE_VALUES as _FT

                legacy_val = update_data.get("fuel_type")
                if legacy_val is None or legacy_val in _FT:
                    update_data["fuel_type_used"] = legacy_val

            # Auto-calculate propane_liters if tank-by-weight data provided/updated
            if (
                update_data.get("tank_size_kg") is not None
                and update_data.get("tank_quantity") is not None
                and update_data.get("propane_liters") is None
            ):
                tank_size = update_data.get("tank_size_kg", record.tank_size_kg)
                tank_qty = update_data.get("tank_quantity", record.tank_quantity)
                if tank_size is not None and tank_qty is not None:
                    calculated = (
                        Decimal(str(tank_size)) * PROPANE_LITERS_PER_KG * Decimal(str(tank_qty))
                    )
                    update_data["propane_liters"] = calculated.quantize(Decimal("0.001"))

            # Station inputs go through the same resolver as create, so an edit
            # can re-point or promote a station instead of raw-writing the
            # columns (issue #108).
            one_time_visit = update_data.pop("one_time_visit", None)
            if {"station_address_book_id", "station_name_freetext"} & record_data.model_fields_set:
                # Default each omitted field from the record: under
                # exclude_unset an absent key carries no intent, and reading it
                # as None would let a caller that sends one station field wipe
                # the other. Same pattern as the propane block above.
                new_id = update_data.get("station_address_book_id", record.station_address_book_id)
                new_text = (
                    update_data.get("station_name_freetext", record.station_name_freetext) or None
                )
                # Resolve only on a real change: the form posts these fields on
                # every save and the resolver bumps usage_count, which counts
                # fill-ups, not saves.
                if (new_id, new_text) != (
                    record.station_address_book_id,
                    record.station_name_freetext,
                ):
                    station_id, station_freetext = await resolve_fuel_station(
                        self.db,
                        station_address_book_id=new_id,
                        station_name_freetext=new_text,
                        # A record with freetext and no FK IS a one-time visit;
                        # default to preserving that so editing such a station
                        # doesn't promote a stop the user kept out of the book.
                        one_time_visit=(
                            bool(one_time_visit)
                            if one_time_visit is not None
                            else record.station_address_book_id is None
                            and record.station_name_freetext is not None
                        ),
                    )
                    update_data["station_address_book_id"] = station_id
                    update_data["station_name_freetext"] = station_freetext

            for field, value in update_data.items():
                setattr(record, field, value)

            # ---- Single outer transaction begins ----
            await self.db.flush()  # apply field changes inside the same tx

            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="fuel",
                        source_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record %s (rolling back): %s",
                        record_id,
                        sanitize_for_log(e),
                    )
                    raise

            if def_fill_level_was_sent:
                try:
                    if def_fill_level is not None:
                        await sync_def_from_fuel_record(
                            db=self.db,
                            vin=vin,
                            date=record.date,
                            odometer_km=record.odometer_km,
                            fill_level=def_fill_level,
                            fuel_record_id=record.id,
                            commit=False,
                        )
                    else:
                        from app.models.def_record import DEFRecord

                        await self.db.execute(
                            delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
                        )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync DEF for fuel record %s (rolling back): %s",
                        record_id,
                        sanitize_for_log(e),
                    )
                    raise

            await self.db.commit()
            await self.db.refresh(record)

            value = await self._economy_for(vin, record)

            logger.info("Updated fuel record %s for %s", record_id, sanitize_for_log(vin))

            await invalidate_cache_for_vehicle(vin)

            return record, value

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_fuel_record(self, vin: str, record_id: int, current_user: User) -> None:
        """Delete a fuel record and any linked DEF auto-synced record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            from app.models.def_record import DEFRecord
            from app.models.odometer import OdometerRecord

            await self.db.execute(
                delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
            )
            # Clean up the synced odometer row. PG enforces this via the FK
            # ``fk_odometer_records_fuel_record`` (ON DELETE CASCADE) added
            # in migration 055, but SQLite doesn't enforce FKs without
            # PRAGMA foreign_keys=ON, so we sweep at the service layer too.
            # Issuing the delete on both engines is harmless (idempotent
            # on PG since the row is already gone by the time the cascade
            # fires below) and keeps a single code path.
            await self.db.execute(
                delete(OdometerRecord).where(OdometerRecord.fuel_record_id == record_id)
            )
            await self.db.execute(
                delete(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            await self.db.commit()

            logger.info("Deleted fuel record %s for %s", record_id, sanitize_for_log(vin))

            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")


# Back-compat aliases for v1 widget endpoints (kept until v3.2.0).
calculate_mpg = calculate_l_per_100km
calculate_average_mpg = calculate_average_l_per_100km
