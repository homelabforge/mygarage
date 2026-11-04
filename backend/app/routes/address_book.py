"""Address book routes for MyGarage API."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AddressBookEntry
from app.models.user import User
from app.models.vendor import Vendor
from app.schemas.address_book import (
    AddressBookEntryCreate,
    AddressBookEntryResponse,
    AddressBookEntryUpdate,
    AddressBookListResponse,
)
from app.services.auth import require_auth
from app.utils.gas_station import GAS_STATION_POI, gas_station_clause, is_gas_station
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/address-book", tags=["address-book"])


async def _sync_to_vendor(
    db: AsyncSession, business_name: str | None, entry: AddressBookEntry
) -> None:
    """Silently create a matching vendor when an address book entry has a business name.

    Uses a nested transaction (SAVEPOINT) so any failure here cannot poison
    the parent address-book write. Checks case-insensitively to prevent duplicates.
    Updates to existing vendor fields are intentionally not performed here —
    a vendor may already be linked to service visits.

    Skipped for gas stations (either field, see ``app.utils.gas_station``):
    they are not vendors in MyGarage's domain model and would pollute the
    vendors table.

    Known limitation: concurrent creates with only case/whitespace differences
    could produce duplicate vendors. Acceptable for single-user homelab use.
    """
    if not business_name or not business_name.strip():
        return
    # Gas stations never sync to vendors, however the entry was made. This
    # only checked poi_category, so every station added on the Address Book
    # page landed in vendors too (#194).
    if is_gas_station(entry):
        return
    name = business_name.strip()[:100]  # Enforce vendors.name VARCHAR(100) limit
    try:
        async with db.begin_nested():  # SAVEPOINT
            result = await db.execute(select(Vendor).where(func.lower(Vendor.name) == name.lower()))
            if result.scalar_one_or_none() is not None:
                return  # Vendor already exists (case-insensitive match)
            vendor = Vendor(
                name=name,
                address=entry.address,
                city=entry.city,
                state=entry.state,
                zip_code=entry.zip_code,
                phone=entry.phone,
            )
            db.add(vendor)
            await (
                db.flush()
            )  # Force INSERT inside the savepoint boundary — critical for rollback isolation
            # SAVEPOINT releases here
    except Exception:
        logger.exception("Failed to sync address book entry %r to vendors", sanitize_for_log(name))
        # SAVEPOINT was rolled back; parent transaction (address book write) unaffected


@router.get("", response_model=AddressBookListResponse)
async def list_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None, description="Search by name, business name, or city"),
    category: str | None = Query(None, description="Filter by category"),
    poi_category: str | None = Query(
        None,
        description=(
            "Filter by POI category (e.g. 'gas_station' for the Gas Stations "
            "filter view). Combine with `search` for autocomplete."
        ),
    ),
    current_user: User | None = Depends(require_auth),
) -> AddressBookListResponse:
    """List all address book entries with optional search and filtering."""
    query = select(AddressBookEntry)

    # The fill-up's station picker asks for gas_station, and a station saved on
    # the Address Book page only has the category, so ask both fields (#194).
    poi_filter = (
        gas_station_clause()
        if poi_category == GAS_STATION_POI
        else AddressBookEntry.poi_category == poi_category
    )

    # Apply search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                AddressBookEntry.name.ilike(search_pattern),
                AddressBookEntry.business_name.ilike(search_pattern),
                AddressBookEntry.city.ilike(search_pattern),
            )
        )

    # Apply category filter
    if category:
        query = query.where(AddressBookEntry.category == category)
    if poi_category:
        query = query.where(poi_filter)

    # When filtering to fuel stations, rank by usage so frequently-visited
    # stations float to the top of autocomplete suggestions.
    if poi_category == GAS_STATION_POI:
        query = query.order_by(
            AddressBookEntry.usage_count.desc(),
            AddressBookEntry.last_used.desc().nullslast(),
            AddressBookEntry.business_name,
        )
    else:
        query = query.order_by(AddressBookEntry.business_name, AddressBookEntry.name)

    result = await db.execute(query)
    entries = result.scalars().all()

    # Get total count
    count_query = select(func.count()).select_from(AddressBookEntry)
    if search:
        search_pattern = f"%{search}%"
        count_query = count_query.where(
            or_(
                AddressBookEntry.name.ilike(search_pattern),
                AddressBookEntry.business_name.ilike(search_pattern),
                AddressBookEntry.city.ilike(search_pattern),
            )
        )
    if category:
        count_query = count_query.where(AddressBookEntry.category == category)
    if poi_category:
        count_query = count_query.where(poi_filter)

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    return AddressBookListResponse(
        entries=[AddressBookEntryResponse.model_validate(e) for e in entries],
        total=total,
    )


@router.post("", response_model=AddressBookEntryResponse, status_code=201)
async def create_entry(
    db: Annotated[AsyncSession, Depends(get_db)],
    entry_data: AddressBookEntryCreate,
    current_user: User | None = Depends(require_auth),
) -> AddressBookEntryResponse:
    """Create a new address book entry."""
    entry = AddressBookEntry(
        name=entry_data.name,
        business_name=entry_data.business_name,
        address=entry_data.address,
        city=entry_data.city,
        state=entry_data.state,
        zip_code=entry_data.zip_code,
        phone=entry_data.phone,
        email=entry_data.email,
        website=entry_data.website,
        category=entry_data.category,
        notes=entry_data.notes,
        poi_category=entry_data.poi_category,
        poi_metadata=entry_data.poi_metadata,
        latitude=entry_data.latitude,
        longitude=entry_data.longitude,
        source=entry_data.source or "manual",
        external_id=entry_data.external_id,
        rating=entry_data.rating,
        user_rating=entry_data.user_rating,
    )

    db.add(entry)
    try:
        await _sync_to_vendor(db, entry_data.business_name, entry)
    except Exception:
        logger.exception("Unexpected vendor sync error during address book create, continuing")
    await db.commit()
    await db.refresh(entry)

    return AddressBookEntryResponse.model_validate(entry)


@router.get("/{entry_id}", response_model=AddressBookEntryResponse)
async def get_entry(
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> AddressBookEntryResponse:
    """Get a specific address book entry."""
    result = await db.execute(select(AddressBookEntry).where(AddressBookEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Address book entry not found")

    return AddressBookEntryResponse.model_validate(entry)


@router.put("/{entry_id}", response_model=AddressBookEntryResponse)
async def update_entry(
    entry_id: int,
    update_data: AddressBookEntryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> AddressBookEntryResponse:
    """Update an address book entry."""
    # Get entry
    result = await db.execute(select(AddressBookEntry).where(AddressBookEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Address book entry not found")

    # An omitted field keeps its value and an explicit null clears it. Every
    # field used to be `if x is not None`, and email/website turn '' into None
    # first, so a cleared email or website said saved and stayed.
    changes = update_data.model_dump(exclude_unset=True)
    changes.pop("poi_category", None)
    for field, value in changes.items():
        setattr(entry, field, value)

    # An omitted poi_category keeps the stored one, and an explicit one is
    # honoured (model_fields_set), so a null clears it. The Address Book page
    # sends null only when it re-files a gas station under another chip; other
    # callers can send any value. Guard: a gas or clear value never overwrites a
    # non-gas POI tag (auto_shop/rv_shop/ev_charging/propane), so a stale client
    # snapshot can't wipe one (#108). A non-gas value always applies.
    if "poi_category" in update_data.model_fields_set:
        incoming = update_data.poi_category
        _gas_or_clear = {None, "", "gas_station"}
        if incoming in _gas_or_clear and entry.poi_category not in _gas_or_clear:
            pass  # protect the existing non-gas tag
        else:
            entry.poi_category = incoming or None  # normalize empty string to NULL

    try:
        await _sync_to_vendor(db, entry.business_name, entry)
    except Exception:
        logger.exception("Unexpected vendor sync error during address book update, continuing")
    await db.commit()
    await db.refresh(entry)

    return AddressBookEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete an address book entry."""
    # Verify entry exists
    result = await db.execute(select(AddressBookEntry).where(AddressBookEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Address book entry not found")

    await db.delete(entry)
    await db.commit()
