"""Path validation utilities for preventing path traversal attacks."""

# pyright: reportArgumentType=false, reportReturnType=false

import re
import logging
from pathlib import Path
from typing import Optional
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks.

    Args:
        filename: Original filename to sanitize

    Returns:
        Sanitized filename safe for filesystem operations

    Raises:
        HTTPException: If filename is invalid or empty after sanitization
    """
    # Remove null bytes
    filename = filename.replace("\0", "")

    # Remove path separators (both Unix and Windows)
    filename = re.sub(r"[/\\]", "", filename)

    # Remove leading dots to prevent hidden files and relative paths
    filename = filename.lstrip(".")

    # Ensure filename is not empty after sanitization
    if not filename or len(filename.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: filename cannot be empty",
        )

    # Limit filename length (filesystem limits)
    if len(filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: filename too long (max 255 characters)",
        )

    return filename


def validate_path_within_base(
    file_path: Path, base_path: Path, raise_error: bool = True
) -> Optional[Path]:
    """Ensure file_path is within base_path to prevent path traversal.

    This function resolves both paths to their canonical forms and verifies
    that the file path is a child of the base path.

    Args:
        file_path: Path to validate
        base_path: Base directory that should contain file_path
        raise_error: If True, raise HTTPException on validation failure

    Returns:
        Resolved path if valid, None if invalid and raise_error=False

    Raises:
        HTTPException: If path is outside base and raise_error=True
    """
    try:
        # Resolve to absolute paths
        resolved_path = file_path.resolve()
        resolved_base = base_path.resolve()

        # Check if path is within base using relative_to
        # This will raise ValueError if resolved_path is not relative to resolved_base
        resolved_path.relative_to(resolved_base)

        return resolved_path

    except (ValueError, RuntimeError):
        logger.warning(
            "Path traversal attempt detected: %s outside %s", file_path, base_path
        )

        if raise_error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file path: path traversal not allowed",
            )
        return None


def validate_and_resolve_path(
    filename: str, base_dir: Path, allowed_extensions: Optional[set] = None
) -> Path:
    """Complete validation: sanitize filename, check extension, prevent traversal.

    This is a convenience function that combines sanitization, extension checking,
    and path traversal prevention.

    Args:
        filename: Original filename from user input
        base_dir: Base directory for file storage
        allowed_extensions: Set of allowed file extensions (e.g., {'.pdf', '.jpg'})

    Returns:
        Validated and resolved Path object

    Raises:
        HTTPException: If validation fails at any step
    """
    # Step 1: Sanitize the filename
    safe_filename = sanitize_filename(filename)

    # Step 2: Check file extension if restrictions apply
    if allowed_extensions:
        file_ext = Path(safe_filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file extension: {file_ext}. Allowed: {', '.join(allowed_extensions)}",
            )

    # Step 3: Build full path and validate it's within base directory
    full_path = base_dir / safe_filename
    validated_path = validate_path_within_base(full_path, base_dir, raise_error=True)

    return validated_path
