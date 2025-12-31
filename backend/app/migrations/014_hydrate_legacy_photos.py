"""Hydrate VehiclePhoto entries for existing filesystem photos (one-time migration)."""

import os
import logging
from pathlib import Path
from typing import Optional
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (512, 512)


def _generate_thumbnail_for_existing(file_path: Path, photo_dir: Path) -> Optional[str]:
    """Create a thumbnail for an existing image file."""
    try:
        image = Image.open(file_path)
        image = ImageOps.exif_transpose(image)
    except UnidentifiedImageError:
        logger.warning("Failed to open image for thumbnail generation: %s", file_path)
        return None

    thumb = image.copy()  # type: ignore[union-attr]
    thumb.thumbnail(THUMBNAIL_SIZE)
    if thumb.mode in ("RGBA", "P"):
        thumb = thumb.convert("RGB")

    thumb_dir = file_path.parent / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{file_path.stem}_thumb.jpg"
    thumb.save(thumb_path, format="JPEG", quality=85)
    return str(thumb_path.relative_to(photo_dir))


def _hydrate_legacy_photos_for_vin(
    vin: str, photo_dir: Path, session: Session, allowed_extensions: set[str]
) -> int:
    """Create VehiclePhoto entries for existing filesystem photos for a single VIN."""
    vehicle_dir = photo_dir / vin
    if not vehicle_dir.exists():
        return 0

    # Get existing photo records for this VIN
    result = session.execute(
        text("SELECT file_path FROM vehicle_photos WHERE vin = :vin"), {"vin": vin}
    )
    existing = {Path(row[0]).name for row in result.fetchall()}

    # Get vehicle's main_photo
    vehicle_result = session.execute(
        text("SELECT main_photo FROM vehicles WHERE vin = :vin"), {"vin": vin}
    )
    vehicle_row = vehicle_result.fetchone()
    main_photo = vehicle_row[0] if vehicle_row else None

    new_count = 0

    for file in vehicle_dir.iterdir():
        if not file.is_file() or file.parent.name == "thumbnails":
            continue
        if file.suffix.lower() not in allowed_extensions:
            continue
        if file.name in existing:
            continue

        relative_photo_path = str(file.relative_to(photo_dir))
        thumb_candidate = vehicle_dir / "thumbnails" / f"{file.stem}_thumb.jpg"
        if thumb_candidate.exists():
            thumbnail_relative = str(thumb_candidate.relative_to(photo_dir))
        else:
            thumbnail_relative = _generate_thumbnail_for_existing(file, photo_dir)

        is_main = main_photo == relative_photo_path

        # Insert new photo record
        session.execute(
            text("""
                INSERT INTO vehicle_photos (vin, file_path, thumbnail_path, is_main, caption, uploaded_at)
                VALUES (:vin, :file_path, :thumbnail_path, :is_main, NULL, CURRENT_TIMESTAMP)
            """),
            {
                "vin": vin,
                "file_path": relative_photo_path,
                "thumbnail_path": thumbnail_relative,
                "is_main": is_main,
            },
        )
        new_count += 1

    return new_count


def upgrade():
    """Hydrate VehiclePhoto entries for existing filesystem photos."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Get photo directory from environment or use default
    photo_dir = Path(os.getenv("PHOTOS_DIR", str(data_dir / "photos")))

    if not photo_dir.exists():
        print("ℹ No photos directory found, skipping photo hydration")
        return

    # Get allowed photo extensions from settings (default set)
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if vehicle_photos table exists
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_photos'"
            )
        )
        if not result.fetchone():
            print("ℹ vehicle_photos table does not exist, skipping photo hydration")
            return

        # Get all VINs from vehicles table
        result = conn.execute(text("SELECT vin FROM vehicles"))
        vins = [row[0] for row in result.fetchall()]

        if not vins:
            print("ℹ No vehicles found, skipping photo hydration")
            return

        total_photos = 0
        for vin in vins:
            try:
                session = Session(bind=conn)
                count = _hydrate_legacy_photos_for_vin(
                    vin, photo_dir, session, allowed_extensions
                )
                total_photos += count
                if count > 0:
                    print(f"✓ Hydrated {count} photo(s) for vehicle {vin}")
            except Exception as e:
                logger.error("Error hydrating photos for VIN %s: %s", vin, e)
                print(f"✗ Error hydrating photos for VIN {vin}: {e}")

        if total_photos > 0:
            print(
                f"✓ Total: Hydrated {total_photos} legacy photos across {len(vins)} vehicles"
            )
        else:
            print("ℹ No legacy photos found to hydrate")


def downgrade():
    """
    This migration is idempotent and doesn't modify existing data.
    Downgrade is a no-op.
    """
    print("ℹ Downgrade not needed (migration is idempotent)")


if __name__ == "__main__":
    upgrade()
