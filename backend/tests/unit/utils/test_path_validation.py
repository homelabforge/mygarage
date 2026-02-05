"""
Unit tests for path validation utilities.

Tests path traversal prevention, filename sanitization, and extension validation.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.utils.path_validation import (
    sanitize_filename,
    validate_and_resolve_path,
    validate_path_within_base,
)


@pytest.mark.unit
class TestSanitizeFilename:
    """Test filename sanitization."""

    def test_basic_filename(self):
        """Test sanitizing a basic valid filename."""
        result = sanitize_filename("document.pdf")
        assert result == "document.pdf"

    def test_removes_path_separators_unix(self):
        """Test removing Unix path separators."""
        result = sanitize_filename("path/to/file.pdf")
        assert result == "pathtofile.pdf"

    def test_removes_path_separators_windows(self):
        """Test removing Windows path separators."""
        result = sanitize_filename("path\\to\\file.pdf")
        assert result == "pathtofile.pdf"

    def test_removes_leading_dots(self):
        """Test removing leading dots (hidden files)."""
        result = sanitize_filename("..hidden")
        assert result == "hidden"

    def test_removes_multiple_leading_dots(self):
        """Test removing multiple leading dots (path traversal)."""
        result = sanitize_filename("....traversal")
        assert result == "traversal"

    def test_removes_null_bytes(self):
        """Test removing null bytes (injection attack)."""
        result = sanitize_filename("file\x00.pdf")
        assert result == "file.pdf"
        assert "\x00" not in result

    def test_preserves_internal_dots(self):
        """Test that dots in filename are preserved."""
        result = sanitize_filename("file.name.pdf")
        assert result == "file.name.pdf"

    def test_raises_on_empty_filename(self):
        """Test that empty filename raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            sanitize_filename("")
        assert exc_info.value.status_code == 400
        assert "cannot be empty" in exc_info.value.detail

    def test_raises_on_only_dots(self):
        """Test that filename with only dots raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            sanitize_filename("...")
        assert exc_info.value.status_code == 400
        assert "cannot be empty" in exc_info.value.detail

    def test_raises_on_only_path_separators(self):
        """Test that filename with only path separators raises HTTPException."""
        with pytest.raises(HTTPException) as exc_info:
            sanitize_filename("///")
        assert exc_info.value.status_code == 400

    def test_raises_on_filename_too_long(self):
        """Test that filename exceeding 255 chars raises HTTPException."""
        long_filename = "a" * 256 + ".pdf"
        with pytest.raises(HTTPException) as exc_info:
            sanitize_filename(long_filename)
        assert exc_info.value.status_code == 400
        assert "too long" in exc_info.value.detail

    def test_max_length_filename(self):
        """Test that filename at max length is allowed."""
        filename = "a" * 251 + ".pdf"  # 255 chars total
        result = sanitize_filename(filename)
        assert len(result) == 255

    def test_path_traversal_attempt(self):
        """Test that path traversal attempts are neutralized."""
        result = sanitize_filename("../../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result
        assert ".." not in result

    def test_preserves_spaces(self):
        """Test that spaces in filenames are preserved."""
        result = sanitize_filename("my document.pdf")
        assert result == "my document.pdf"

    def test_preserves_unicode(self):
        """Test that unicode characters are preserved."""
        result = sanitize_filename("документ.pdf")
        assert result == "документ.pdf"


@pytest.mark.unit
class TestValidatePathWithinBase:
    """Test path containment validation."""

    def test_valid_path_within_base(self, tmp_path):
        """Test that valid path within base is allowed."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()
        file_path = base_dir / "document.pdf"

        result = validate_path_within_base(file_path, base_dir)
        assert result is not None
        assert result == file_path.resolve()

    def test_nested_valid_path(self, tmp_path):
        """Test that nested path within base is allowed."""
        base_dir = tmp_path / "uploads"
        subdir = base_dir / "subdir"
        subdir.mkdir(parents=True)
        file_path = subdir / "document.pdf"

        result = validate_path_within_base(file_path, base_dir)
        assert result is not None

    def test_path_traversal_blocked(self, tmp_path):
        """Test that path traversal is blocked."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()
        # Try to escape base directory
        file_path = base_dir / ".." / "secret.txt"

        with pytest.raises(HTTPException) as exc_info:
            validate_path_within_base(file_path, base_dir)
        assert exc_info.value.status_code == 400
        assert "path traversal" in exc_info.value.detail

    def test_path_traversal_no_raise(self, tmp_path):
        """Test that path traversal returns None when raise_error=False."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()
        file_path = base_dir / ".." / "secret.txt"

        result = validate_path_within_base(file_path, base_dir, raise_error=False)
        assert result is None

    def test_absolute_path_outside_base(self, tmp_path):
        """Test that absolute path outside base is blocked."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()
        file_path = Path("/etc/passwd")

        with pytest.raises(HTTPException):
            validate_path_within_base(file_path, base_dir)

    def test_symlink_escape_blocked(self, tmp_path):
        """Test that symlink escaping is blocked."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Create a symlink pointing outside base
        external_dir = tmp_path / "external"
        external_dir.mkdir()

        symlink = base_dir / "link"
        try:
            symlink.symlink_to(external_dir)
            file_path = symlink / "secret.txt"

            with pytest.raises(HTTPException):
                validate_path_within_base(file_path, base_dir)
        except OSError:
            # Skip if symlinks not supported
            pytest.skip("Symlinks not supported on this system")


@pytest.mark.unit
class TestValidateAndResolvePath:
    """Test combined validation function."""

    def test_valid_filename_and_path(self, tmp_path):
        """Test valid filename and path combination."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        result = validate_and_resolve_path("document.pdf", base_dir)
        assert result.name == "document.pdf"
        assert str(base_dir) in str(result)

    def test_sanitizes_filename(self, tmp_path):
        """Test that filename is sanitized."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Leading dots should be stripped
        result = validate_and_resolve_path("..hidden.pdf", base_dir)
        assert result.name == "hidden.pdf"

    def test_validates_allowed_extension(self, tmp_path):
        """Test extension validation with allowed extensions."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        allowed = {".pdf", ".jpg", ".png"}
        result = validate_and_resolve_path("image.jpg", base_dir, allowed_extensions=allowed)
        assert result.suffix == ".jpg"

    def test_rejects_disallowed_extension(self, tmp_path):
        """Test rejection of disallowed extension."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        allowed = {".pdf", ".jpg"}
        with pytest.raises(HTTPException) as exc_info:
            validate_and_resolve_path("script.exe", base_dir, allowed_extensions=allowed)
        assert exc_info.value.status_code == 400
        assert ".exe" in exc_info.value.detail

    def test_extension_case_insensitive(self, tmp_path):
        """Test that extension checking is case-insensitive."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        allowed = {".pdf", ".jpg"}
        result = validate_and_resolve_path("IMAGE.JPG", base_dir, allowed_extensions=allowed)
        assert result.suffix.lower() == ".jpg"

    def test_no_extension_restrictions(self, tmp_path):
        """Test with no extension restrictions."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Any extension should be allowed
        result = validate_and_resolve_path("script.sh", base_dir)
        assert result.name == "script.sh"

    def test_prevents_traversal_in_combined(self, tmp_path):
        """Test that traversal is blocked in combined validation."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Even though ../secret.txt becomes secrettxt after sanitization,
        # the path should still be within base
        result = validate_and_resolve_path("../secret.txt", base_dir)
        # After sanitization: "secret.txt" (../ removed as path separators and dots stripped)
        assert str(base_dir) in str(result)

    def test_empty_filename_rejected(self, tmp_path):
        """Test that empty filename is rejected."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        with pytest.raises(HTTPException) as exc_info:
            validate_and_resolve_path("", base_dir)
        assert exc_info.value.status_code == 400


@pytest.mark.unit
class TestSecurityScenarios:
    """Test specific security attack scenarios."""

    def test_null_byte_injection(self, tmp_path):
        """Test null byte injection attack."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Null byte could truncate string in some systems
        result = validate_and_resolve_path("valid.pdf\x00.exe", base_dir)
        assert "\x00" not in str(result)
        assert result.name == "valid.pdf.exe"

    def test_double_url_encoding(self, tmp_path):
        """Test handling of potentially double-encoded paths."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # %2e%2e = ..
        # This would only be an issue if decoded, which we don't do
        result = validate_and_resolve_path("%2e%2e%2fpasswd", base_dir)
        # Should be treated as literal string
        assert "%" in result.name

    def test_unicode_path_separator(self, tmp_path):
        """Test handling of unicode path separators."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # Unicode fullwidth solidus: ／
        # These should either be stripped or kept as literal chars
        result = validate_and_resolve_path("test／file.pdf", base_dir)
        assert result is not None

    def test_windows_device_names(self, tmp_path):
        """Test handling of Windows reserved names."""
        base_dir = tmp_path / "uploads"
        base_dir.mkdir()

        # CON, PRN, AUX, NUL are reserved on Windows
        # They should be sanitized but we just ensure no crash
        result = validate_and_resolve_path("CON.pdf", base_dir)
        assert result is not None
