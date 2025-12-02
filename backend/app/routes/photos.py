"""Vehicle photo management API endpoints."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.photo import VehiclePhoto
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.photo import PhotoUpdate
from app.services.auth import require_auth, get_vehicle_or_403
from app.services.photo_service import PhotoService
from app.services.file_upload_service import FileUploadService, PHOTO_UPLOAD_CONFIG
from app.utils.path_validation import sanitize_filename

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vehicles", tags=["Photos"])

PHOTO_DIR = settings.photos_dir


@router.post("/{vin}/photos", status_code=201)
async def upload_vehicle_photo(
    vin: str,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    set_as_main: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Upload a photo for a vehicle.

    **Args:**
    - **vin**: Vehicle VIN
    - **file**: Image file to upload
    - **caption**: Optional photo caption
    - **set_as_main**: Whether to set this photo as the main photo

    **Returns:**
    - Photo filename and path

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to upload photos for this vehicle
    - **400**: Invalid file type or size
    - **500**: Upload error

    **Security:**
    - Users can only upload photos for their own vehicles
    - Admin users can upload photos for all vehicles
    """
    vin = vin.upper().strip()

    try:
        # Check vehicle ownership
        vehicle = await get_vehicle_or_403(vin, current_user, db)

        # Upload using shared service
        upload_result = await FileUploadService.upload_file(
            file,
            PHOTO_UPLOAD_CONFIG,
            subdirectory=vin
        )

        # Create database record
        relative_photo_path = str(upload_result.file_path.relative_to(settings.photos_dir))
        relative_thumb_path = None
        if upload_result.thumbnail_path:
            relative_thumb_path = str(upload_result.thumbnail_path.relative_to(settings.photos_dir))

        photo_record = VehiclePhoto(
            vin=vin,
            file_path=relative_photo_path,
            thumbnail_path=relative_thumb_path,
            is_main=set_as_main,
            caption=(caption.strip() if caption else None)
        )

        db.add(photo_record)
        await db.flush()

        # Update main photo if requested
        if set_as_main:
            await db.execute(
                update(VehiclePhoto)
                .where(VehiclePhoto.vin == vin, VehiclePhoto.id != photo_record.id)
                .values(is_main=False)
            )
            vehicle.main_photo = relative_photo_path

        await db.commit()
        await db.refresh(photo_record)

        logger.info(f"Uploaded photo for {vin}: {photo_record.file_path}")

        return PhotoService.build_photo_payload(vin, photo_record)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database constraint violation uploading photo for {vin}: {e}")
        raise HTTPException(status_code=409, detail="Photo record already exists")
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database connection error uploading photo for {vin}: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except (OSError, IOError) as e:
        await db.rollback()
        logger.error(f"File system error uploading photo for {vin}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save photo file")


@router.get("/{vin}/photos/{filename}")
async def get_vehicle_photo(
    vin: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Get a vehicle photo by filename.

    **Security:**
    - Users can only view photos for their own vehicles
    - Admin users can view photos for all vehicles
    """
    vin = vin.upper().strip()

    safe_filename = sanitize_filename(filename)

    # Check vehicle ownership
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Get photo path
    file_path = PHOTO_DIR / vin / safe_filename

    # Validate file type before serving
    if not file_path.suffix.lower() in settings.allowed_photo_extensions:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Photo not found")

    return FileResponse(file_path)


@router.get("/{vin}/photos/thumbnails/{filename}")
async def get_vehicle_thumbnail(
    vin: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Serve a thumbnail for a photo.

    **Security:**
    - Users can only view thumbnails for their own vehicles
    - Admin users can view thumbnails for all vehicles
    """
    vin = vin.upper().strip()
    safe_filename = sanitize_filename(filename)

    # Check vehicle ownership
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    thumb_path = PHOTO_DIR / vin / "thumbnails" / safe_filename
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return FileResponse(thumb_path)


@router.get("/{vin}/photos")
async def list_vehicle_photos(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    List all photos for a vehicle.

    **Security:**
    - Users can only list photos for their own vehicles
    - Admin users can list photos for all vehicles
    """
    vin = vin.upper().strip()

    # Check vehicle ownership
    vehicle = await get_vehicle_or_403(vin, current_user, db)

    # Note: Legacy photo hydration now runs via migration 014_hydrate_legacy_photos.py
    # No need to hydrate on every request

    result = await db.execute(
        select(VehiclePhoto)
        .where(VehiclePhoto.vin == vin)
        .order_by(VehiclePhoto.is_main.desc(), VehiclePhoto.uploaded_at.desc())
    )
    photo_rows = result.scalars().all()

    photos = [PhotoService.build_photo_payload(vin, photo) for photo in photo_rows]

    return {"photos": photos, "total": len(photos)}


@router.delete("/{vin}/photos/{filename}", status_code=204)
async def delete_vehicle_photo(
    vin: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Delete a vehicle photo.

    **Security:**
    - Users can only delete photos for their own vehicles
    - Admin users can delete photos for all vehicles
    """
    vin = vin.upper().strip()

    safe_filename = sanitize_filename(filename)

    try:
        # Check vehicle ownership
        vehicle = await get_vehicle_or_403(vin, current_user, db)

        result = await db.execute(
            select(VehiclePhoto).where(
                VehiclePhoto.vin == vin,
                VehiclePhoto.file_path == f"{vin}/{safe_filename}"
            )
        )
        photo_record = result.scalar_one_or_none()

        photo_relative = Path(photo_record.file_path) if photo_record else Path(vin) / safe_filename
        file_path = PHOTO_DIR / photo_relative

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Photo not found")

        # If this is the main photo, clear it (metadata may be missing for legacy uploads)
        relative_string = str(photo_relative)
        if vehicle.main_photo == relative_string or (photo_record and photo_record.is_main):
            vehicle.main_photo = None

        # Delete file
        file_path.unlink()

        if photo_record:
            if photo_record.thumbnail_path:
                thumb_path = PHOTO_DIR / photo_record.thumbnail_path
                if thumb_path.exists():
                    thumb_path.unlink()

            await db.execute(
                delete(VehiclePhoto).where(VehiclePhoto.id == photo_record.id)
            )
        await db.commit()

        logger.info(f"Deleted photo for {vin}: {filename}")

        return None

    except HTTPException:
        raise
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database connection error deleting photo for {vin}: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
    except (OSError, IOError) as e:
        await db.rollback()
        logger.error(f"File system error deleting photo for {vin}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete photo file")


@router.put("/{vin}/photos/main")
async def set_main_photo(
    vin: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Set the main photo for a vehicle.

    **Security:**
    - Users can only set main photo for their own vehicles
    - Admin users can set main photo for all vehicles
    """
    vin = vin.upper().strip()

    safe_filename = sanitize_filename(filename)

    try:
        # Check vehicle ownership
        vehicle = await get_vehicle_or_403(vin, current_user, db)

        # Check if photo exists
        file_path = PHOTO_DIR / vin / safe_filename

        # Validate file type
        if not file_path.suffix.lower() in settings.allowed_photo_extensions:
            raise HTTPException(status_code=400, detail="Invalid file type")

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Photo not found")

        relative_path = str(file_path.relative_to(PHOTO_DIR).parent / safe_filename)

        result = await db.execute(
            select(VehiclePhoto).where(
                VehiclePhoto.vin == vin,
                VehiclePhoto.file_path == relative_path
            )
        )
        photo_record = result.scalar_one_or_none()

        if photo_record is None:
            photo_record = VehiclePhoto(
                vin=vin,
                file_path=relative_path,
                is_main=True,
                caption=None
            )
            db.add(photo_record)
            await db.flush()
        else:
            photo_record.is_main = True

        await db.execute(
            update(VehiclePhoto)
            .where(VehiclePhoto.vin == vin, VehiclePhoto.id != photo_record.id)
            .values(is_main=False)
        )

        # Set main photo
        vehicle.main_photo = relative_path
        await db.commit()
        await db.refresh(vehicle)

        logger.info(f"Set main photo for {vin}: {safe_filename}")

        # Import VehicleResponse here to avoid circular dependency
        from app.schemas.vehicle import VehicleResponse
        return VehicleResponse.model_validate(vehicle)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database constraint violation setting main photo for {vin}: {e}")
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database connection error setting main photo for {vin}: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.patch("/{vin}/photos/{photo_id}")
async def update_vehicle_photo_metadata(
    vin: str,
    photo_id: int,
    photo_update: PhotoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Update caption or main flag for an existing photo.

    **Security:**
    - Users can only update photos for their own vehicles
    - Admin users can update photos for all vehicles
    """
    vin = vin.upper().strip()

    try:
        # Check vehicle ownership
        vehicle = await get_vehicle_or_403(vin, current_user, db)

        result = await db.execute(
            select(VehiclePhoto).where(VehiclePhoto.id == photo_id, VehiclePhoto.vin == vin)
        )
        photo = result.scalar_one_or_none()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        if photo_update.caption is not None:
            new_caption = photo_update.caption.strip() if photo_update.caption else None
            photo.caption = new_caption or None

        if photo_update.is_main:
            await db.execute(
                update(VehiclePhoto)
                .where(VehiclePhoto.vin == vin, VehiclePhoto.id != photo.id)
                .values(is_main=False)
            )
            photo.is_main = True
            vehicle.main_photo = photo.file_path

        await db.commit()
        await db.refresh(photo)
        return PhotoService.build_photo_payload(vin, photo)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Database constraint violation updating photo metadata for {vin}: {e}")
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error(f"Database connection error updating photo metadata for {vin}: {e}")
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")
