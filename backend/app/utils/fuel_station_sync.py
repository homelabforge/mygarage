"""Helper for resolving / creating fuel-station address-book entries.

Used by the fuel-record save flow to translate a free-text station name (or
existing address-book id) plus the form's "one-time visit" toggle into a
final `(station_address_book_id, station_name_freetext)` tuple, while
optionally creating the address-book row inside the caller's transaction.

`gas_station` POI entries deliberately bypass the vendor sync path — see
routes/address_book.py::_sync_to_vendor for the defense-in-depth guard.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AddressBookEntry


async def resolve_fuel_station(
    db: AsyncSession,
    *,
    station_address_book_id: int | None,
    station_name_freetext: str | None,
    one_time_visit: bool,
) -> tuple[int | None, str | None]:
    """Resolve fuel-station inputs into final FK + freetext columns.

    Behavior matrix:
      1. station_address_book_id is set → use that FK; freetext stays None.
         Bumps usage_count + last_used on the existing entry.
      2. station_name_freetext is set + one_time_visit=True →
         freetext stored as-is; no FK; no address_book row created.
      3. station_name_freetext is set + one_time_visit=False →
         create new gas_station address_book entry, set FK, freetext stays None.
      4. Both inputs are None/blank → both outputs None.

    Caller manages the outer transaction. We only `flush()` to ensure new
    rows have ids visible inside the transaction.
    """
    # Case 1: explicit address-book pick
    if station_address_book_id is not None:
        entry = await db.get(AddressBookEntry, station_address_book_id)
        if entry is None:
            # Caller passed a stale id — fall back to freetext if any
            if station_name_freetext and station_name_freetext.strip():
                return None, station_name_freetext.strip()[:150]
            return None, None
        entry.usage_count = (entry.usage_count or 0) + 1
        entry.last_used = datetime.now()
        await db.flush()
        return entry.id, None

    # Cases 2/3/4 — depend on freetext presence
    name = (station_name_freetext or "").strip()
    if not name:
        return None, None

    # Case 2: one-time visit
    if one_time_visit:
        return None, name[:150]

    # Case 3: promote to address book.
    # Look for an existing gas_station entry with the same business_name
    # (case-insensitive) before creating, to keep the autocomplete dataset
    # tidy under casual-typing concurrency.
    from sqlalchemy import func

    result = await db.execute(
        select(AddressBookEntry)
        .where(AddressBookEntry.poi_category == "gas_station")
        .where(func.lower(AddressBookEntry.business_name) == name.lower())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.usage_count = (existing.usage_count or 0) + 1
        existing.last_used = datetime.now()
        await db.flush()
        return existing.id, None

    new_entry = AddressBookEntry(
        business_name=name[:150],
        poi_category="gas_station",
        source="manual",
        usage_count=1,
        last_used=datetime.now(),
    )
    db.add(new_entry)
    await db.flush()
    return new_entry.id, None
