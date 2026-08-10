"""Unified file upload service for all upload endpoints."""

# pyright: reportOptionalMemberAccess=false

import asyncio
import logging
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.utils.file_validation import validate_file_magic_bytes
from app.utils.path_validation import sanitize_filename, validate_path_within_base

logger = logging.getLogger(__name__)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:
    _HEIF_AVAILABLE = False


class FileUploadConfig:
    """Configuration for file upload operations."""

    def __init__(
        self,
        base_dir: Path,
        allowed_extensions: set[str],
        allowed_mimes: set[str],
        max_size_bytes: int,
        generate_unique_name: bool = True,
        verify_magic_bytes: bool = True,
        strict_magic_bytes: bool = False,
        create_thumbnail: bool = False,
        thumbnail_size: tuple[Any, ...] = (300, 300),
    ):
        self.base_dir = base_dir
        self.allowed_extensions = allowed_extensions
        self.allowed_mimes = allowed_mimes
        self.max_size_bytes = max_size_bytes
        self.generate_unique_name = generate_unique_name
        self.verify_magic_bytes = verify_magic_bytes
        self.strict_magic_bytes = strict_magic_bytes
        self.create_thumbnail = create_thumbnail
        self.thumbnail_size = thumbnail_size


class UploadResult:
    """Result of file upload operation."""

    def __init__(
        self,
        filename: str,
        file_path: Path,
        file_size: int,
        content_type: str,
        thumbnail_path: Path | None = None,
    ):
        self.filename = filename
        self.file_path = file_path
        self.file_size = file_size
        self.content_type = content_type
        self.thumbnail_path = thumbnail_path


class FileUploadService:
    """Centralized service for handling file uploads."""

    @staticmethod
    def generate_unique_filename(original_filename: str, include_timestamp: bool = True) -> str:
        """Generate a unique filename with optional timestamp.

        Args:
            original_filename: Original filename from upload
            include_timestamp: If True, include timestamp in filename

        Returns:
            Unique filename with UUID
        """
        # Sanitize the original filename
        safe_name = sanitize_filename(original_filename)

        # Extract extension
        extension = Path(safe_name).suffix[:10]  # Limit extension length

        # Generate unique ID
        unique_id = uuid.uuid4().hex[:12]

        # Build filename
        if include_timestamp:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"{timestamp}_{unique_id}{extension}"
        else:
            return f"{unique_id}{extension}"

    @staticmethod
    async def validate_upload(file: UploadFile, config: FileUploadConfig) -> bytes:
        """Validate uploaded file.

        Args:
            file: Uploaded file
            config: Upload configuration

        Returns:
            File contents as bytes

        Raises:
            HTTPException: If validation fails
        """
        # Validate file extension
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in config.allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file extension. Allowed: {', '.join(config.allowed_extensions)}",
            )

        # Validate MIME type
        if file.content_type not in config.allowed_mimes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed: {', '.join(config.allowed_mimes)}",
            )

        # Check file size BEFORE reading into memory
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Seek back to beginning

        if file_size > config.max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size exceeds maximum of {config.max_size_bytes / (1024 * 1024):.1f}MB",
            )

        # Read file contents
        contents = await file.read()

        if not contents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

        # Verify magic bytes if configured. A confirmed content/declared-type
        # mismatch is now REJECTED (was: logged and allowed) so a file disguised
        # with an allowed extension+MIME but mismatched content can't be stored.
        if config.verify_magic_bytes:
            is_valid, error_msg = validate_file_magic_bytes(
                contents,
                file.filename,
                file.content_type,
                strict=config.strict_magic_bytes,
            )
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg or "File content does not match its declared type",
                )

        return contents

    @staticmethod
    def _write_file(path: Path, contents: bytes) -> None:
        """Write file contents to disk (sync helper for thread pool)."""
        with open(path, "wb") as f:
            f.write(contents)

    @staticmethod
    def _verify_image_decodable(contents: bytes) -> None:
        """Fully decode an image to confirm it is a real, parseable image.

        Run BEFORE the disk write (G-4) so a corrupt or disguised image is
        rejected with a 400 and nothing is persisted. HEIC is skipped because
        Pillow cannot decode it without the optional pillow-heif plugin.

        Uses ``load()`` (full pixel decode), not ``verify()``: it rejects
        disguised/undecodable files while accepting whatever the downstream
        thumbnailer can actually open (``verify()`` also trips on CRC nits that
        ``load()`` and the thumbnailer tolerate).
        """
        try:
            with Image.open(BytesIO(contents)) as img:
                img.load()
        except (UnidentifiedImageError, OSError, ValueError) as e:
            logger.warning("Rejected undecodable image upload: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image file"
            )

    @staticmethod
    def _convert_heic_to_jpeg_bytes(contents: bytes) -> tuple[bytes, str]:
        """Convert HEIC/HEIF bytes to JPEG. Returns (jpeg_bytes, stem)."""
        with Image.open(BytesIO(contents)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = BytesIO()
            img.save(out, format="JPEG", quality=90)
            return out.getvalue(), f"photo_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def create_thumbnail(
        image_bytes: bytes, thumbnail_path: Path, size: tuple[Any, ...] = (300, 300)
    ) -> None:
        """Create thumbnail from image bytes.

        Args:
            image_bytes: Original image bytes
            thumbnail_path: Path to save thumbnail
            size: Thumbnail size (width, height)
        """
        try:
            # Open and orient image
            image = Image.open(BytesIO(image_bytes))
            image = ImageOps.exif_transpose(image)

            # Create thumbnail
            thumb = image.copy()
            thumb.thumbnail(size)

            # Convert RGBA to RGB for JPEG
            if thumb.mode in ("RGBA", "P"):
                thumb = thumb.convert("RGB")

            # Ensure directory exists
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

            # Save thumbnail
            thumb.save(thumbnail_path, format="JPEG", quality=85)

        except UnidentifiedImageError as e:
            logger.error("Failed to create thumbnail: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image file"
            )

    @staticmethod
    async def upload_file(
        file: UploadFile, config: FileUploadConfig, subdirectory: str | None = None
    ) -> UploadResult:
        """Complete file upload with validation, saving, and optional thumbnail.

        Args:
            file: Uploaded file
            config: Upload configuration
            subdirectory: Optional subdirectory within base_dir

        Returns:
            UploadResult with file details

        Raises:
            HTTPException: If upload fails
        """
        try:
            # Validate the upload
            contents = await FileUploadService.validate_upload(file, config)

            # For photo uploads (which get thumbnailed via Pillow), decode the
            # image BEFORE writing so a disguised/corrupt image is rejected with
            # nothing persisted (G-4). HEIC is converted to JPEG when pillow-heif
            # is available so browsers always receive a portable format.
            is_heic = (
                (file.content_type or "").lower() in {"image/heic", "image/heif"}
                or Path(file.filename or "").suffix.lower() in {".heic", ".heif"}
            )
            if is_heic and config.create_thumbnail:
                if not _HEIF_AVAILABLE:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="HEIC uploads require pillow-heif on the server",
                    )
                contents, filename_stem = await asyncio.to_thread(
                    FileUploadService._convert_heic_to_jpeg_bytes, contents
                )
                # Force JPEG destination name below
                file_filename_override = f"{filename_stem}.jpg"
                file_content_type_override = "image/jpeg"
            else:
                file_filename_override = None
                file_content_type_override = None
                if (
                    config.create_thumbnail
                    and file.content_type
                    and file.content_type.startswith("image/")
                    and not is_heic
                ):
                    FileUploadService._verify_image_decodable(contents)

            # Determine destination directory
            destination_dir = config.base_dir
            if subdirectory:
                destination_dir = destination_dir / subdirectory

            destination_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename
            if file_filename_override:
                if config.generate_unique_name:
                    filename = FileUploadService.generate_unique_filename(file_filename_override)
                else:
                    filename = sanitize_filename(file_filename_override)
            elif config.generate_unique_name:
                filename = FileUploadService.generate_unique_filename(file.filename)
            else:
                filename = sanitize_filename(file.filename)

            # Build file path
            file_path = destination_dir / filename

            # Validate path is within base directory
            validated_path = validate_path_within_base(file_path, config.base_dir, raise_error=True)

            # Save file (offload blocking I/O to thread pool)
            await asyncio.to_thread(FileUploadService._write_file, validated_path, contents)

            logger.info("Saved file: %s", validated_path)

            content_type = file_content_type_override or file.content_type

            # Create thumbnail if configured and it's an image
            thumbnail_path = None
            if config.create_thumbnail and content_type and content_type.startswith("image/"):
                thumbnail_dir = destination_dir / "thumbnails"
                thumbnail_filename = f"{Path(filename).stem}_thumb.jpg"
                thumbnail_path = thumbnail_dir / thumbnail_filename

                await asyncio.to_thread(
                    FileUploadService.create_thumbnail,
                    contents,
                    thumbnail_path,
                    config.thumbnail_size,
                )

                # Validate thumbnail path
                validate_path_within_base(thumbnail_path, config.base_dir, raise_error=True)

                logger.info("Created thumbnail: %s", thumbnail_path)

            return UploadResult(
                filename=filename,
                file_path=validated_path,
                file_size=len(contents),
                content_type=content_type,
                thumbnail_path=thumbnail_path,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("File upload failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Upload failed",
            )


# Predefined configurations for common upload types

PHOTO_UPLOAD_CONFIG = FileUploadConfig(
    base_dir=settings.photos_dir,
    allowed_extensions=settings.allowed_photo_extensions,
    allowed_mimes={"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic", "image/heif"},
    max_size_bytes=settings.max_upload_size_bytes,
    generate_unique_name=True,
    verify_magic_bytes=True,
    strict_magic_bytes=True,
    create_thumbnail=True,
    thumbnail_size=(512, 512),
)

ATTACHMENT_UPLOAD_CONFIG = FileUploadConfig(
    base_dir=settings.attachments_dir,
    allowed_extensions=settings.allowed_attachment_extensions,
    allowed_mimes=settings.allowed_attachment_mime_types,
    max_size_bytes=settings.max_upload_size_bytes,
    generate_unique_name=True,
    verify_magic_bytes=True,
    strict_magic_bytes=True,
    create_thumbnail=False,
)

DOCUMENT_UPLOAD_CONFIG = FileUploadConfig(
    base_dir=settings.documents_dir,
    allowed_extensions=settings.allowed_document_extensions,
    allowed_mimes={
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/csv",
        "image/jpeg",
        "image/png",
    },
    max_size_bytes=settings.max_document_size_bytes,
    generate_unique_name=True,
    verify_magic_bytes=True,
    strict_magic_bytes=True,
    create_thumbnail=False,
)
