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

    Known limitation: concurrent creates with only case/whitespace differences
    could produce duplicate vendors. Acceptable for single-user homelab use.
    """
    if not business_name or not business_name.strip():
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
        logger.exception("Failed to sync address book entry %r to vendors", name)
        # SAVEPOINT was rolled back; parent transaction (address book write) unaffected


@router.get("", response_model=AddressBookListResponse)
async def list_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    search: str | None = Query(None, description="Search by name, business name, or city"),
    category: str | None = Query(None, description="Filter by category"),
    current_user: User | None = Depends(require_auth),
) -> AddressBookListResponse:
    """List all address book entries with optional search and filtering."""
    query = select(AddressBookEntry)

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

    # Order by business_name, then name (handles NULL names)
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

    # Update fields
    if update_data.name is not None:
        entry.name = update_data.name
    if update_data.business_name is not None:
        entry.business_name = update_data.business_name
    if update_data.address is not None:
        entry.address = update_data.address
    if update_data.city is not None:
        entry.city = update_data.city
    if update_data.state is not None:
        entry.state = update_data.state
    if update_data.zip_code is not None:
        entry.zip_code = update_data.zip_code
    if update_data.phone is not None:
        entry.phone = update_data.phone
    if update_data.email is not None:
        entry.email = update_data.email
    if update_data.website is not None:
        entry.website = update_data.website
    if update_data.category is not None:
        entry.category = update_data.category
    if update_data.notes is not None:
        entry.notes = update_data.notes

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
