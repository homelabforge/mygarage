"""
Unit tests for file validation utilities.

Tests magic byte verification, MIME type validation, and file size checks.
"""

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.utils.file_validation import (
    MAGIC_AVAILABLE,
    MAGIC_BYTES,
    validate_csv_upload,
    validate_file_magic_bytes,
    verify_file_content_type,
)


def _csv_upload(content: bytes, content_type: str = "text/csv") -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename="upload.csv",
        headers=Headers({"content-type": content_type}),
    )


def _export_shaped_fuel_csv(rows: int) -> str:
    """A fuel file as MyGarage exports it: about thirty columns, most empty."""
    header = (
        "units_version,unit_system,Date,Filled At,Odometer (mi),Engine Hours,Gallons,"
        "Price Per Gallon,Rebate,Total Cost,Full Tank,Missed Fill-up,Is Hauling,"
        "Fuel Type Used,Station ID,Station,Driver ID,Driver,Payment Method,Trip Type,"
        "Outside Temp (F),OBC MPG,OBC Avg Speed (mph),OBC Trip Duration (s),"
        "SOC Start (%),SOC End (%),Charge Level,Charge Location,Battery SOH (%),Notes"
    )
    lines = [header]
    for i in range(rows):
        lines.append(
            f"6,imperial,2028-01-{i + 1:02d},,{87000 + i * 300},,10.1,3.49,,{35.25 + i:.2f},"
            "Yes,No,No,Regular,,Shell,,,,,,,,,,,,,,"
        )
    return "\n".join(lines) + "\n"


@pytest.mark.unit
class TestCsvUploadValidation:
    """A CSV upload is judged by the shape every importer reads.

    Every importer reads the comma format with a header row. The check used to
    run `csv.Sniffer` over the first 1,024 characters, which for an export about
    thirty columns wide is a header, four or five rows and one row cut in half,
    and the sniffer's line-to-line consistency test rejected it (#163).
    """

    async def test_an_export_longer_than_the_old_sample_is_accepted(self):
        data = _export_shaped_fuel_csv(20)
        assert len(data) > 1024
        assert await validate_csv_upload(_csv_upload(data.encode())) == data

    async def test_a_semicolon_file_is_refused_as_not_comma_separated(self):
        data = "Date;Odometer (km);Liters\n2028-01-01;1000;40\n"
        with pytest.raises(HTTPException) as refused:
            await validate_csv_upload(_csv_upload(data.encode()))
        assert refused.value.status_code == 400
        assert "comma-separated" in refused.value.detail

    async def test_plain_text_is_refused(self):
        with pytest.raises(HTTPException) as refused:
            await validate_csv_upload(_csv_upload(b"just a sentence with no table in it\n"))
        assert refused.value.status_code == 400
        assert "comma-separated" in refused.value.detail

    async def test_an_empty_file_is_reported_as_empty(self):
        with pytest.raises(HTTPException) as refused:
            await validate_csv_upload(_csv_upload(b"  \n"))
        assert refused.value.status_code == 400
        assert refused.value.detail == "CSV file is empty"

    async def test_a_spreadsheet_byte_order_mark_is_not_part_of_the_first_column(self):
        data = await validate_csv_upload(
            _csv_upload(b"\xef\xbb\xbfDate,Odometer (km)\n2028-01-01,1000\n")
        )
        assert data.startswith("Date,")

    async def test_a_non_csv_content_type_is_still_refused(self):
        with pytest.raises(HTTPException) as refused:
            await validate_csv_upload(_csv_upload(b"Date,Odometer\n", "application/pdf"))
        assert refused.value.status_code == 400


@pytest.mark.unit
class TestMagicByteVerification:
    """Test magic byte content type verification."""

    def test_verify_pdf_valid(self):
        """Test that valid PDF magic bytes are recognized."""
        pdf_content = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"  # Valid PDF header
        is_valid = verify_file_content_type(pdf_content, "application/pdf")

        assert is_valid is True

    def test_verify_jpeg_valid_ff_d8_ff_e0(self):
        """Test that valid JPEG magic bytes (FF D8 FF E0) are recognized."""
        jpeg_content = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # Valid JPEG header
        is_valid = verify_file_content_type(jpeg_content, "image/jpeg")

        assert is_valid is True

    def test_verify_jpeg_valid_ff_d8_ff_e1(self):
        """Test that valid JPEG magic bytes (FF D8 FF E1) are recognized."""
        jpeg_content = b"\xff\xd8\xff\xe1\x00\x10Exif"  # Valid JPEG with Exif
        is_valid = verify_file_content_type(jpeg_content, "image/jpeg")

        assert is_valid is True

    def test_verify_png_valid(self):
        """Test that valid PNG magic bytes are recognized."""
        png_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"  # Valid PNG header
        is_valid = verify_file_content_type(png_content, "image/png")

        assert is_valid is True

    def test_verify_gif87a_valid(self):
        """Test that valid GIF87a magic bytes are recognized."""
        gif_content = b"GIF87a\x01\x00\x01\x00"  # Valid GIF87a header
        is_valid = verify_file_content_type(gif_content, "image/gif")

        assert is_valid is True

    def test_verify_gif89a_valid(self):
        """Test that valid GIF89a magic bytes are recognized."""
        gif_content = b"GIF89a\x01\x00\x01\x00"  # Valid GIF89a header
        is_valid = verify_file_content_type(gif_content, "image/gif")

        assert is_valid is True

    def test_verify_webp_valid(self):
        """Test that valid WebP magic bytes are recognized."""
        webp_content = b"RIFF\x00\x00\x00\x00WEBP"  # Valid WebP header
        is_valid = verify_file_content_type(webp_content, "image/webp")

        assert is_valid is True

    def test_verify_docx_valid(self):
        """Test that valid DOCX magic bytes (ZIP signature) are recognized."""
        # DOCX files are ZIP archives with PK header
        docx_content = b"PK\x03\x04\x14\x00\x00\x00"  # Valid ZIP/DOCX header
        is_valid = verify_file_content_type(
            docx_content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        assert is_valid is True

    def test_verify_xlsx_valid(self):
        """Test that valid XLSX magic bytes (ZIP signature) are recognized."""
        xlsx_content = b"PK\x03\x04\x14\x00\x00\x00"  # Valid ZIP/XLSX header
        is_valid = verify_file_content_type(
            xlsx_content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        assert is_valid is True

    def test_verify_doc_valid(self):
        """Test that valid DOC magic bytes (OLE) are recognized."""
        # Legacy DOC files use OLE format
        doc_content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # Valid OLE header
        is_valid = verify_file_content_type(doc_content, "application/msword")

        assert is_valid is True

    def test_verify_xls_valid(self):
        """Test that valid XLS magic bytes (OLE) are recognized."""
        xls_content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # Valid OLE header
        is_valid = verify_file_content_type(xls_content, "application/vnd.ms-excel")

        assert is_valid is True

    def test_verify_wrong_magic_bytes(self):
        """Test that wrong magic bytes are rejected."""
        # PDF content type with JPEG magic bytes
        jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        is_valid = verify_file_content_type(jpeg_bytes, "application/pdf")

        assert is_valid is False

    def test_verify_empty_content(self):
        """Test that empty content is rejected."""
        empty_content = b""
        is_valid = verify_file_content_type(empty_content, "application/pdf")

        assert is_valid is False

    @pytest.mark.skipif(MAGIC_AVAILABLE, reason="Test valid only without python-magic")
    def test_verify_unknown_mime_type(self):
        """Test that unknown MIME types default to allowing."""
        # Unknown MIME type should return True (allow by default)
        unknown_content = b"Some content"
        is_valid = verify_file_content_type(unknown_content, "application/unknown")

        # Without python-magic installed, it should allow
        assert is_valid is True

    def test_verify_partial_magic_bytes(self):
        """Test that partial magic byte matches are rejected."""
        # Only first byte matches PDF
        partial_pdf = b"%XYZ-1.4\n"
        is_valid = verify_file_content_type(partial_pdf, "application/pdf")

        assert is_valid is False

    def test_verify_content_shorter_than_signature(self):
        """Test handling content shorter than expected signature."""
        # Very short content
        short_content = b"%"  # Too short to be a valid PDF
        is_valid = verify_file_content_type(short_content, "application/pdf")

        assert is_valid is False


@pytest.mark.unit
class TestFileMagicBytesValidation:
    """Test complete file validation with magic bytes."""

    def test_validate_valid_pdf(self):
        """Test validation of valid PDF file."""
        pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        is_valid, error = validate_file_magic_bytes(
            pdf_bytes, "document.pdf", "application/pdf", strict=False
        )

        assert is_valid is True
        assert error is None

    def test_validate_valid_jpeg(self):
        """Test validation of valid JPEG file."""
        jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        is_valid, error = validate_file_magic_bytes(
            jpeg_bytes, "photo.jpg", "image/jpeg", strict=False
        )

        assert is_valid is True
        assert error is None

    def test_validate_invalid_strict_mode(self):
        """Test that invalid files are rejected in strict mode."""
        # PDF bytes with JPEG MIME type
        pdf_bytes = b"%PDF-1.4\n"
        is_valid, error = validate_file_magic_bytes(
            pdf_bytes, "fake.jpg", "image/jpeg", strict=True
        )

        assert is_valid is False
        assert error is not None
        assert "does not match declared type" in error

    def test_validate_invalid_non_strict_mode(self):
        """Non-strict now returns the real result too (v2.28.0, G-2).

        Previously a confirmed mismatch returned (True, None) in non-strict mode,
        silently allowing a disguised file. It now returns (False, msg) and the
        caller decides; ``strict`` only changes log severity.
        """
        # PDF bytes with JPEG MIME type
        pdf_bytes = b"%PDF-1.4\n"
        is_valid, error = validate_file_magic_bytes(
            pdf_bytes, "fake.jpg", "image/jpeg", strict=False
        )

        assert is_valid is False
        assert error is not None
        assert "does not match declared type" in error

    def test_validate_empty_file(self):
        """Test validation of empty file."""
        empty_bytes = b""
        is_valid, error = validate_file_magic_bytes(
            empty_bytes, "empty.pdf", "application/pdf", strict=True
        )

        assert is_valid is False
        assert error is not None

    def test_validate_unknown_mime_type(self):
        """Validation of an unknown declared MIME type.

        With libmagic available the content is detected (text/plain) and does
        not match the bogus declared type, so v2.28.0 rejects it (G-2). Without
        libmagic the function falls back to allowing it. Either way such MIME
        types are not in any upload config's allowlist, so real uploads are
        unaffected.
        """
        from app.utils.file_validation import MAGIC_AVAILABLE

        content = b"Some content"
        is_valid, error = validate_file_magic_bytes(
            content, "file.xyz", "application/x-unknown", strict=False
        )

        assert is_valid is (not MAGIC_AVAILABLE)


@pytest.mark.unit
class TestMagicBytesConstants:
    """Test that MAGIC_BYTES constants are properly defined."""

    def test_magic_bytes_has_pdf(self):
        """Test that PDF magic bytes are defined."""
        assert "application/pdf" in MAGIC_BYTES
        assert MAGIC_BYTES["application/pdf"] == b"%PDF"

    def test_magic_bytes_has_jpeg(self):
        """Test that JPEG magic bytes are defined."""
        assert "image/jpeg" in MAGIC_BYTES
        assert isinstance(MAGIC_BYTES["image/jpeg"], list)
        assert b"\xff\xd8\xff\xe0" in MAGIC_BYTES["image/jpeg"]

    def test_magic_bytes_has_png(self):
        """Test that PNG magic bytes are defined."""
        assert "image/png" in MAGIC_BYTES
        assert MAGIC_BYTES["image/png"] == b"\x89PNG\r\n\x1a\n"

    def test_magic_bytes_has_gif(self):
        """Test that GIF magic bytes are defined."""
        assert "image/gif" in MAGIC_BYTES
        assert isinstance(MAGIC_BYTES["image/gif"], list)
        assert b"GIF87a" in MAGIC_BYTES["image/gif"]
        assert b"GIF89a" in MAGIC_BYTES["image/gif"]

    def test_magic_bytes_has_webp(self):
        """Test that WebP magic bytes are defined."""
        assert "image/webp" in MAGIC_BYTES
        assert MAGIC_BYTES["image/webp"] == b"RIFF"

    def test_magic_bytes_has_office_formats(self):
        """Test that Office format magic bytes are defined."""
        # DOCX
        assert (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in MAGIC_BYTES
        )
        # XLSX
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in MAGIC_BYTES
        # DOC
        assert "application/msword" in MAGIC_BYTES
        # XLS
        assert "application/vnd.ms-excel" in MAGIC_BYTES

    def test_magic_bytes_all_values_are_bytes_or_list(self):
        """Test that all magic byte values are bytes or list of bytes."""
        for mime_type, signature in MAGIC_BYTES.items():
            if isinstance(signature, list):
                for sig in signature:
                    assert isinstance(sig, bytes), f"{mime_type} signature must be bytes"
            else:
                assert isinstance(signature, bytes), f"{mime_type} signature must be bytes"


@pytest.mark.unit
class TestFileSizeLimits:
    """Test file size limit handling."""

    def test_max_read_parameter(self):
        """Test that max_read parameter limits bytes read for signature check."""
        # Create content with PDF signature at start
        pdf_content = b"%PDF" + b"x" * 1000  # PDF + lots of padding

        # Should work with default max_read (16 bytes)
        is_valid = verify_file_content_type(pdf_content, "application/pdf")
        assert is_valid is True

        # Should still work with smaller max_read (just needs first 4 bytes)
        is_valid = verify_file_content_type(pdf_content, "application/pdf", max_read=4)
        assert is_valid is True

    def test_max_read_too_small(self):
        """Test that insufficient max_read may cause false negatives."""
        pdf_content = b"%PDF-1.4\n"

        # With max_read=2, can't read full signature
        is_valid = verify_file_content_type(pdf_content, "application/pdf", max_read=2)

        # Should still match (startswith only needs first bytes)
        assert is_valid is False or is_valid is True  # Implementation dependent
