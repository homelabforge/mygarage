"""Unified file upload service for all upload endpoints."""

# pyright: reportArgumentType=false, reportOptionalMemberAccess=false, reportCallIssue=false

import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from fastapi import UploadFile, HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError
from io import BytesIO

from app.config import settings
from app.utils.path_validation import sanitize_filename, validate_path_within_base
from app.utils.file_validation import validate_file_magic_bytes

logger = logging.getLogger(__name__)


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
        create_thumbnail: bool = False,
        thumbnail_size: tuple[Any, ...] = (300, 300),
    ):
        self.base_dir = base_dir
        self.allowed_extensions = allowed_extensions
        self.allowed_mimes = allowed_mimes
        self.max_size_bytes = max_size_bytes
        self.generate_unique_name = generate_unique_name
        self.verify_magic_bytes = verify_magic_bytes
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
        thumbnail_path: Optional[Path] = None,
    ):
        self.filename = filename
        self.file_path = file_path
        self.file_size = file_size
        self.content_type = content_type
        self.thumbnail_path = thumbnail_path


class FileUploadService:
    """Centralized service for handling file uploads."""

    @staticmethod
    def generate_unique_filename(
        original_filename: str, include_timestamp: bool = True
    ) -> str:
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty"
            )

        # Verify magic bytes if configured
        if config.verify_magic_bytes:
            is_valid, error_msg = validate_file_magic_bytes(
                contents,
                file.filename,
                file.content_type,
                strict=False,  # Warn but allow
            )
            if not is_valid:
                logger.warning("Magic byte validation warning: %s", error_msg)

        return contents

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
        file: UploadFile, config: FileUploadConfig, subdirectory: Optional[str] = None
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

            # Determine destination directory
            destination_dir = config.base_dir
            if subdirectory:
                destination_dir = destination_dir / subdirectory

            destination_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename
            if config.generate_unique_name:
                filename = FileUploadService.generate_unique_filename(file.filename)
            else:
                filename = sanitize_filename(file.filename)

            # Build file path
            file_path = destination_dir / filename

            # Validate path is within base directory
            validated_path = validate_path_within_base(
                file_path, config.base_dir, raise_error=True
            )

            # Save file
            with open(validated_path, "wb") as f:
                f.write(contents)

            logger.info("Saved file: %s", validated_path)

            # Create thumbnail if configured and it's an image
            thumbnail_path = None
            if config.create_thumbnail and file.content_type.startswith("image/"):
                thumbnail_dir = destination_dir / "thumbnails"
                thumbnail_filename = f"{Path(filename).stem}_thumb.jpg"
                thumbnail_path = thumbnail_dir / thumbnail_filename

                FileUploadService.create_thumbnail(
                    contents, thumbnail_path, config.thumbnail_size
                )

                # Validate thumbnail path
                validate_path_within_base(
                    thumbnail_path, config.base_dir, raise_error=True
                )

                logger.info("Created thumbnail: %s", thumbnail_path)

            return UploadResult(
                filename=filename,
                file_path=validated_path,
                file_size=len(contents),
                content_type=file.content_type,
                thumbnail_path=thumbnail_path,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("File upload failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Upload failed: {str(e)}",
            )


# Predefined configurations for common upload types

PHOTO_UPLOAD_CONFIG = FileUploadConfig(
    base_dir=settings.photos_dir,
    allowed_extensions=settings.allowed_photo_extensions,
    allowed_mimes={"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"},
    max_size_bytes=settings.max_upload_size_bytes,
    generate_unique_name=True,
    verify_magic_bytes=True,
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
    create_thumbnail=False,
)
