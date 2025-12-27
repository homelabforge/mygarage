"""Note routes for MyGarage API."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Note, Vehicle
from app.models.user import User
from app.schemas.note import (
    NoteCreate,
    NoteListResponse,
    NoteResponse,
    NoteUpdate,
)
from app.services.auth import require_auth

router = APIRouter(prefix="/api/vehicles", tags=["notes"])


@router.get("/{vin}/notes", response_model=NoteListResponse)
async def list_notes(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> NoteListResponse:
    """List all notes for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get notes sorted by date descending (newest first)
    result = await db.execute(
        select(Note).where(Note.vin == vin).order_by(Note.date.desc())
    )
    notes = result.scalars().all()

    return NoteListResponse(
        notes=[NoteResponse.model_validate(note) for note in notes],
        total=len(notes),
    )


@router.post("/{vin}/notes", response_model=NoteResponse, status_code=201)
async def create_note(
    vin: str,
    note_data: NoteCreate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> NoteResponse:
    """Create a new note for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create note
    note = Note(
        vin=vin,
        date=note_data.date,
        title=note_data.title,
        content=note_data.content,
    )

    db.add(note)
    await db.commit()
    await db.refresh(note)

    return NoteResponse.model_validate(note)


@router.get("/{vin}/notes/{note_id}", response_model=NoteResponse)
async def get_note(
    vin: str,
    note_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> NoteResponse:
    """Get a specific note."""
    result = await db.execute(select(Note).where(Note.id == note_id, Note.vin == vin))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    return NoteResponse.model_validate(note)


@router.put("/{vin}/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    vin: str,
    note_id: int,
    update_data: NoteUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> NoteResponse:
    """Update a note."""
    # Get note
    result = await db.execute(select(Note).where(Note.id == note_id, Note.vin == vin))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Update fields
    if update_data.date is not None:
        note.date = update_data.date
    if update_data.title is not None:
        note.title = update_data.title
    if update_data.content is not None:
        note.content = update_data.content

    await db.commit()
    await db.refresh(note)

    return NoteResponse.model_validate(note)


@router.delete("/{vin}/notes/{note_id}", status_code=204)
async def delete_note(
    vin: str,
    note_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> None:
    """Delete a note."""
    # Get note
    result = await db.execute(select(Note).where(Note.id == note_id, Note.vin == vin))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    await db.delete(note)
    await db.commit()
