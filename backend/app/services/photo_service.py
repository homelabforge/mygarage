"""Photo management business logic."""

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException

from app.config import settings
from app.utils.path_validation import validate_path_within_base

logger = logging.getLogger(__name__)

try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:  # pragma: no cover - optional dependency
    HEIF_SUPPORTED = False

IMAGE_FORMAT_MAP = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}

THUMBNAIL_SIZE = (512, 512)
PHOTO_DIR = settings.photos_dir


class PhotoService:
    """Service for managing vehicle photos."""

    @staticmethod
    def save_image_with_thumbnail(
        contents: bytes,
        destination_dir: Path,
        unique_id: str,
        original_extension: str,
    ) -> tuple[str, str]:
        """
        Persist the uploaded image and a thumbnail, returning relative paths.

        Args:
            contents: Image file bytes
            destination_dir: Directory to save the image
            unique_id: Unique identifier for the file
            original_extension: Original file extension

        Returns:
            Tuple of (relative_photo_path, relative_thumbnail_path)

        Raises:
            HTTPException: If image format is invalid or not supported
        """
        extension = original_extension.lower()
        if extension == ".heic":
            if not HEIF_SUPPORTED:
                raise HTTPException(
                    status_code=415,
                    detail="HEIC images are not supported on this server (pillow-heif missing)",
                )
            extension = ".jpg"

        try:
            image = Image.open(BytesIO(contents))
            image = ImageOps.exif_transpose(image)
        except UnidentifiedImageError:
            raise HTTPException(status_code=400, detail="Invalid image file")

        image_format = IMAGE_FORMAT_MAP.get(extension, image.format or "PNG")
        filename = f"{unique_id}{extension}"
        file_path = destination_dir / filename

        # Validate path is within allowed directory
        validated_path = validate_path_within_base(file_path, PHOTO_DIR, raise_error=True)

        image_to_save = image.copy()
        if image_format in ("JPEG", "WEBP") and image_to_save.mode in ("RGBA", "P"):
            image_to_save = image_to_save.convert("RGB")

        destination_dir.mkdir(parents=True, exist_ok=True)
        image_to_save.save(validated_path, format=image_format, quality=92)

        thumbnail_dir = destination_dir / "thumbnails"
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_filename = f"{unique_id}_thumb.jpg"
        thumbnail_path = thumbnail_dir / thumbnail_filename

        # Validate thumbnail path is within allowed directory
        validated_thumb_path = validate_path_within_base(thumbnail_path, PHOTO_DIR, raise_error=True)

        thumb = image.copy()
        thumb.thumbnail(THUMBNAIL_SIZE)
        if thumb.mode in ("RGBA", "P"):
            thumb = thumb.convert("RGB")
        thumb.save(validated_thumb_path, format="JPEG", quality=85)

        relative_photo_path = str(file_path.relative_to(PHOTO_DIR))
        relative_thumbnail_path = str(thumbnail_path.relative_to(PHOTO_DIR))
        return relative_photo_path, relative_thumbnail_path

    @staticmethod
    def generate_thumbnail_for_existing(file_path: Path) -> Optional[str]:
        """
        Create a thumbnail for an existing image file.

        Args:
            file_path: Path to the existing image file

        Returns:
            Relative path to the thumbnail, or None if generation failed
        """
        try:
            image = Image.open(file_path)
            image = ImageOps.exif_transpose(image)
        except UnidentifiedImageError:
            logger.warning("Failed to open image for thumbnail generation: %s", file_path)
            return None

        thumb = image.copy()
        thumb.thumbnail(THUMBNAIL_SIZE)
        if thumb.mode in ("RGBA", "P"):
            thumb = thumb.convert("RGB")

        thumb_dir = file_path.parent / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{file_path.stem}_thumb.jpg"
        thumb.save(thumb_path, format="JPEG", quality=85)
        return str(thumb_path.relative_to(PHOTO_DIR))

    @staticmethod
    def build_photo_payload(vin: str, photo, photo_dir: Path = PHOTO_DIR) -> dict:
        """
        Build consistent photo response dict.

        Args:
            vin: Vehicle VIN
            photo: VehiclePhoto model instance
            photo_dir: Base photo directory

        Returns:
            Dictionary with photo metadata
        """
        file_rel_path = photo.file_path
        filename = Path(file_rel_path).name
        file_path = photo_dir / file_rel_path
        size = file_path.stat().st_size if file_path.exists() else 0

        thumbnail_url = None
        thumbnail_path = None
        if photo.thumbnail_path:
            thumb_name = Path(photo.thumbnail_path).name
            thumbnail_url = f"/api/vehicles/{vin}/photos/thumbnails/{thumb_name}"
            thumbnail_path = photo.thumbnail_path

        return {
            "id": photo.id,
            "filename": filename,
            "path": f"/api/vehicles/{vin}/photos/{filename}",
            "thumbnail_url": thumbnail_url,
            "thumbnail_path": thumbnail_path,
            "file_path": photo.file_path,
            "size": size,
            "is_main": photo.is_main,
            "caption": photo.caption,
            "uploaded_at": photo.uploaded_at,
        }
