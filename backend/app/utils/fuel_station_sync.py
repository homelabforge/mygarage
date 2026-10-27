"""Helper for resolving / creating fuel-station address-book entries.

Used by the fuel-record save flow to translate a free-text station name (or
existing address-book id) plus the form's "one-time visit" toggle into a
final `(station_address_book_id, station_name_freetext)` tuple, while
optionally creating the address-book row inside the caller's transaction.

What counts as a gas station is ``app.utils.gas_station``: the lookup asks
``gas_station_clause()``, so a station saved on the Address Book page (category
"Gas Station", no poi_category) is found instead of copied (#194). Gas stations
never sync to vendors; see routes/address_book.py::_sync_to_vendor.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AddressBookEntry
from app.utils.datetime_utils import utc_now
from app.utils.gas_station import GAS_STATION_POI, gas_station_clause


async def resolve_fuel_station(
    db: AsyncSession,
    *,
    station_address_book_id: int | None,
    station_name_freetext: str | None,
    one_time_visit: bool,
) -> tuple[int | None, str | None]:
    """Resolve fuel-station inputs into final FK + freetext columns.

    Behavior matrix:
      1. station_address_book_id is set AND the caller typed nothing (or typed
         that entry's own name) → use that FK; freetext stays None. Bumps
         usage_count + last_used on the existing entry. A typed name that
         DIFFERS from the entry is a re-point and falls through to 2/3.
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
        typed = (station_name_freetext or "").strip()
        # Honor the pick when the caller typed nothing, or typed this entry's
        # own name. A DIFFERENT name means they retyped over the linked station
        # — that is a re-point, so fall through and resolve the typed name.
        # Letting the FK win here is what silently discarded the user's text
        # and made a station look unsaveable (issue #108); arbitrating in the
        # resolver fixes it for every caller, not just the one form that
        # remembers to null the FK first.
        if not typed or typed.casefold() == (entry.business_name or "").casefold():
            entry.usage_count = (entry.usage_count or 0) + 1
            entry.last_used = utc_now()
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
    # Look for an existing gas station with the same business_name
    # (case-insensitive) before creating, to keep the autocomplete dataset
    # tidy under casual-typing concurrency.
    # Users who hit #194 have a manual entry and a poi_category twin of the same
    # name, so prefer the twin, then the most used. IS TRUE, not the bare
    # compare: that's NULL for a manual row and PostgreSQL sorts NULL first.
    result = await db.execute(
        select(AddressBookEntry)
        .where(gas_station_clause())
        .where(func.lower(AddressBookEntry.business_name) == name.lower())
        .order_by(
            (AddressBookEntry.poi_category == GAS_STATION_POI).is_(True).desc(),
            AddressBookEntry.usage_count.desc(),
            AddressBookEntry.id,
        )
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.usage_count = (existing.usage_count or 0) + 1
        existing.last_used = utc_now()
        await db.flush()
        return existing.id, None

    new_entry = AddressBookEntry(
        business_name=name[:150],
        poi_category=GAS_STATION_POI,
        source="manual",
        usage_count=1,
        last_used=utc_now(),
    )
    db.add(new_entry)
    await db.flush()
    return new_entry.id, None
