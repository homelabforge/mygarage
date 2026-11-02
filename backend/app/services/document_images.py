"""Turn an uploaded document into the few JPEG images a vision model reads (#211).

A PDF is rasterised page by page with PyMuPDF; an image (JPEG, PNG, WebP,
HEIC/HEIF through pillow-heif) is opened with Pillow, its EXIF orientation
applied, and re-encoded. Everything is bounded: at most ``max_pages`` pages,
the longest side at most ``max_side`` pixels, and the JPEG quality lowered
until the batch fits ``max_total_bytes``, so a 20 MB scan costs the endpoint
a couple of megabytes at most. Pure CPU, synchronous; callers run it in a
thread.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageOps

try:
    from pillow_heif.as_plugin import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - the dependency is pinned
    pass

logger = logging.getLogger(__name__)

JPEG = "image/jpeg"
#: Rasterisation scale for PDF pages: 72 dpi × 2 = 144 dpi, enough to read
#: the small print of a certificate without producing a poster.
_PDF_ZOOM = 2.0
#: The text layer a PDF needs before it counts as text (not a scan).
MIN_TEXT_CHARS = 100


def is_pdf(filename: str | None, content_type: str | None) -> bool:
    name = (filename or "").lower()
    return name.endswith(".pdf") or (content_type or "").lower() == "application/pdf"


def has_text_layer(pdf_bytes: bytes, *, min_chars: int = MIN_TEXT_CHARS) -> bool:
    """Whether the PDF carries a usable text layer (it is not a scan)."""
    try:
        import pymupdf

        total = 0
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                total += len(page.get_text().strip())
                if total >= min_chars:
                    return True
        return False
    except Exception as exc:  # noqa: BLE001 - an unreadable file is "no text"
        logger.info("PDF text layer check failed: %s", exc)
        return False


def _encode(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _prepare(image: Image.Image, max_side: int) -> Image.Image:
    """Oriented, RGB, no larger than ``max_side`` on its longest side."""
    oriented = ImageOps.exif_transpose(image) or image
    if oriented.mode not in ("RGB", "L"):
        oriented = oriented.convert("RGB")
    oriented.thumbnail((max_side, max_side))
    return oriented


def _pdf_pages(pdf_bytes: bytes, max_pages: int) -> list[Image.Image]:
    import pymupdf

    pages: list[Image.Image] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            pix = page.get_pixmap(matrix=pymupdf.Matrix(_PDF_ZOOM, _PDF_ZOOM))
            pages.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    return pages


def to_images(
    file_bytes: bytes,
    filename: str | None,
    content_type: str | None,
    *,
    max_pages: int = 2,
    max_side: int = 1600,
    quality: int = 85,
    max_total_bytes: int = 2_000_000,
) -> list[tuple[bytes, str]]:
    """The document as JPEG ``(bytes, mime)`` pairs, bounded as described above.

    Raises ValueError for a file neither PyMuPDF nor Pillow can open.
    """
    try:
        if is_pdf(filename, content_type):
            sources = _pdf_pages(file_bytes, max_pages)
        else:
            sources = [Image.open(io.BytesIO(file_bytes))]
    except Exception as exc:  # noqa: BLE001 - both libraries raise broadly
        raise ValueError("The file is not a readable PDF or image") from exc
    if not sources:
        raise ValueError("The document has no pages")

    prepared = [_prepare(image, max_side) for image in sources[:max_pages]]
    for q in range(quality, 39, -10):
        encoded = [_encode(image, q) for image in prepared]
        if sum(len(e) for e in encoded) <= max_total_bytes:
            return [(e, JPEG) for e in encoded]
    # Still too big at the lowest quality: halve the side and try once more.
    smaller = [_prepare(image, max_side // 2) for image in prepared]
    encoded = [_encode(image, 40) for image in smaller]
    return [(e, JPEG) for e in encoded]
