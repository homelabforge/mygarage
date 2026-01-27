"""File upload validation utilities."""

# pyright: reportArgumentType=false, reportOptionalMemberAccess=false, reportMissingImports=false, reportPossiblyUnboundVariable=false

import csv
import logging

from fastapi import HTTPException, UploadFile

from app.config import settings

logger = logging.getLogger(__name__)

# Import python-magic for content-type verification
try:
    import magic

    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False
    logger.warning("python-magic not available, magic byte verification disabled")

# Magic byte signatures for common file types
MAGIC_BYTES = {
    "application/pdf": b"%PDF",
    "image/jpeg": [
        b"\xff\xd8\xff\xe0",
        b"\xff\xd8\xff\xe1",
        b"\xff\xd8\xff\xe2",
        b"\xff\xd8\xff\xdb",
    ],
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": b"RIFF",
    # Office formats use ZIP
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK\x03\x04",
    # Legacy Office formats
    "application/msword": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    "application/vnd.ms-excel": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
}


def verify_file_content_type(
    file_content: bytes, declared_mime: str, max_read: int = 16
) -> bool:
    """Verify file content matches declared MIME type using magic bytes.

    Args:
        file_content: File content bytes
        declared_mime: Declared MIME type from upload
        max_read: Number of bytes to read for signature check

    Returns:
        True if content matches declared type, False otherwise
    """
    if not file_content:
        return False

    # Get first few bytes for signature check
    header = file_content[:max_read]

    # Check against known signatures first (faster)
    if declared_mime in MAGIC_BYTES:
        signatures = MAGIC_BYTES[declared_mime]
        if not isinstance(signatures, list):
            signatures = [signatures]

        # Check if any signature matches
        for sig in signatures:
            if header.startswith(sig):
                return True

        # Signature didn't match
        logger.warning("Magic byte mismatch for %s", declared_mime)
        return False

    # Fallback: use python-magic if available
    if MAGIC_AVAILABLE:
        try:
            detected_mime = magic.from_buffer(file_content, mime=True)
            # Be lenient with text files (text/plain vs text/csv)
            if declared_mime in ["text/plain", "text/csv"] and detected_mime in [
                "text/plain",
                "text/csv",
            ]:
                return True
            return detected_mime == declared_mime
        except Exception as e:
            logger.debug("Magic detection failed for %s: %s", declared_mime, e)
            # If magic fails, allow (don't break uploads)
            return True

    # No verification available - allow
    return True


def validate_file_magic_bytes(
    file_bytes: bytes, filename: str, declared_mime: str, strict: bool = False
) -> tuple[bool, str | None]:
    """Complete file validation with magic byte check.

    Args:
        file_bytes: File content
        filename: Original filename
        declared_mime: Declared MIME type
        strict: If True, fail on verification failure. If False, just warn.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Verify magic bytes
    is_valid = verify_file_content_type(file_bytes, declared_mime)

    if not is_valid:
        error_msg = f"File content does not match declared type {declared_mime}"
        if strict:
            logger.error("Magic byte validation failed for %s: %s", filename, error_msg)
            return False, error_msg
        else:
            logger.warning(
                "Magic byte validation warning for %s: %s", filename, error_msg
            )
            # In non-strict mode, just warn but allow
            return True, None

    return True, None


async def validate_csv_upload(file: UploadFile, max_size: int = None) -> str:
    """Validate CSV file upload.

    Args:
        file: The uploaded file
        max_size: Maximum file size in bytes (defaults to settings.max_csv_size_bytes)

    Returns:
        The decoded CSV content as string

    Raises:
        HTTPException: If validation fails
    """
    if max_size is None:
        max_size = settings.max_csv_size_bytes

    # Validate MIME type
    if file.content_type not in ["text/csv", "application/vnd.ms-excel", "text/plain"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Expected CSV file.",
        )

    # Read file with size limit
    contents = await file.read()

    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size / (1024 * 1024):.1f}MB",
        )

    # Decode content
    try:
        csv_data = contents.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail="Invalid file encoding. Expected UTF-8."
        )

    # Validate it's actually CSV format
    try:
        # Try to detect CSV format
        csv.Sniffer().sniff(csv_data[:1024] if len(csv_data) > 1024 else csv_data)
    except csv.Error as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV format: {str(e)}")

    # Check if file is empty
    if not csv_data.strip():
        raise HTTPException(status_code=400, detail="CSV file is empty")

    return csv_data


async def validate_image_upload(
    file: UploadFile, max_size: int = None, verify_magic: bool = True
) -> bytes:
    """Validate image file upload.

    Args:
        file: The uploaded file
        max_size: Maximum file size in bytes (defaults to settings.max_upload_size_bytes)
        verify_magic: If True, verify magic bytes match declared type

    Returns:
        The file contents as bytes

    Raises:
        HTTPException: If validation fails
    """
    if max_size is None:
        max_size = settings.max_upload_size_bytes

    # Validate MIME type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: {', '.join(allowed_types)}",
        )

    # Read file with size limit
    contents = await file.read()

    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size / (1024 * 1024):.1f}MB",
        )

    # Check if file is empty
    if not contents:
        raise HTTPException(status_code=400, detail="File is empty")

    # Verify magic bytes (HEIC is excluded as it has complex signature)
    if verify_magic and file.content_type != "image/heic":
        is_valid, error_msg = validate_file_magic_bytes(
            contents,
            file.filename,
            file.content_type,
            strict=False,  # Non-strict: warn but allow
        )
        if not is_valid:
            logger.warning("Image upload magic byte validation failed: %s", error_msg)

    return contents


async def validate_document_upload(
    file: UploadFile, max_size: int = None, verify_magic: bool = True
) -> bytes:
    """Validate document file upload.

    Args:
        file: The uploaded file
        max_size: Maximum file size in bytes (defaults to settings.max_document_size_bytes)
        verify_magic: If True, verify magic bytes match declared type

    Returns:
        The file contents as bytes

    Raises:
        HTTPException: If validation fails
    """
    if max_size is None:
        max_size = settings.max_document_size_bytes

    # Validate MIME type
    allowed_types = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/csv",
        "image/jpeg",
        "image/png",
    ]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed types: PDF, DOC, DOCX, XLS, XLSX, TXT, CSV, JPG, PNG",
        )

    # Read file with size limit
    contents = await file.read()

    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size / (1024 * 1024):.1f}MB",
        )

    # Check if file is empty
    if not contents:
        raise HTTPException(status_code=400, detail="File is empty")

    # Verify magic bytes
    if verify_magic:
        is_valid, error_msg = validate_file_magic_bytes(
            contents,
            file.filename,
            file.content_type,
            strict=False,  # Non-strict: warn but allow
        )
        if not is_valid:
            logger.warning(
                "Document upload magic byte validation failed: %s", error_msg
            )

    return contents


async def validate_attachment_upload(
    file: UploadFile, max_size: int = None, verify_magic: bool = True
) -> bytes:
    """Validate attachment file upload.

    Args:
        file: The uploaded file
        max_size: Maximum file size in bytes (defaults to settings.max_upload_size_bytes)
        verify_magic: If True, verify magic bytes match declared type

    Returns:
        The file contents as bytes

    Raises:
        HTTPException: If validation fails
    """
    if max_size is None:
        max_size = settings.max_upload_size_bytes

    # Validate MIME type
    if file.content_type not in settings.allowed_attachment_mime_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: {', '.join(settings.allowed_attachment_mime_types)}",
        )

    # Read file with size limit
    contents = await file.read()

    if len(contents) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_size / (1024 * 1024):.1f}MB",
        )

    # Check if file is empty
    if not contents:
        raise HTTPException(status_code=400, detail="File is empty")

    # Verify magic bytes
    if verify_magic:
        is_valid, error_msg = validate_file_magic_bytes(
            contents,
            file.filename,
            file.content_type,
            strict=False,  # Non-strict: warn but allow
        )
        if not is_valid:
            logger.warning(
                "Attachment upload magic byte validation failed: %s", error_msg
            )

    return contents
