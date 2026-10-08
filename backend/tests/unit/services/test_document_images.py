"""`document_images`: the bounded JPEGs a vision model receives (#211).

Pages beyond the limit are dropped, EXIF orientation is applied (a phone
photo of a carte grise is usually stored sideways), the longest side and the
total byte size are bounded, and a file nothing can open is a ValueError
rather than a traceback.
"""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from app.services.document_images import JPEG, has_text_layer, is_pdf, to_images


def _pdf(pages: int, text: str | None = None) -> bytes:
    """A PDF of ``pages`` pages; ``text`` is repeated on each as six lines (a
    single long line would run off the page and be dropped from the layer)."""
    doc = pymupdf.open()
    for index in range(pages):
        page = doc.new_page(width=595, height=842)
        if text:
            lines = "\n".join(f"{text} page {index + 1} line {n}" for n in range(6))
            page.insert_text((72, 72), lines, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _jpeg(size: tuple[int, int], *, orientation: int | None = None, noise: bool = False) -> bytes:
    if noise:
        import random

        rng = random.Random(1)
        image = Image.frombytes(
            "RGB", size, bytes(rng.getrandbits(8) for _ in range(size[0] * size[1] * 3))
        )
    else:
        image = Image.new("RGB", size, (200, 220, 240))
    buffer = io.BytesIO()
    if orientation is not None:
        exif = image.getexif()
        exif[0x0112] = orientation
        image.save(buffer, format="JPEG", exif=exif.tobytes())
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


class TestIsPdf:
    def test_by_extension_or_content_type(self):
        assert is_pdf("carte-grise.PDF", None)
        assert is_pdf("scan", "application/pdf")
        assert is_pdf(None, "Application/PDF")
        assert not is_pdf("photo.jpg", "image/jpeg")
        assert not is_pdf(None, None)


class TestHasTextLayer:
    def test_text_pdf_counts_as_text(self):
        assert has_text_layer(_pdf(1, "CERTIFICAT D'IMMATRICULATION"))

    def test_blank_pdf_is_a_scan(self):
        assert not has_text_layer(_pdf(2))

    def test_short_text_below_the_threshold_is_a_scan(self):
        assert not has_text_layer(_pdf(1, "A"), min_chars=100)

    def test_garbage_is_not_text(self):
        assert not has_text_layer(b"not a pdf at all")


class TestToImages:
    def test_three_page_pdf_becomes_two_jpegs(self):
        images = to_images(_pdf(3, "x"), "doc.pdf", "application/pdf")
        assert len(images) == 2
        for data, mime in images:
            assert mime == JPEG
            decoded = _decode(data)
            assert decoded.format == "JPEG"
            assert max(decoded.size) <= 1600

    def test_max_pages_is_honoured(self):
        assert len(to_images(_pdf(3, "x"), "doc.pdf", None, max_pages=1)) == 1
        assert len(to_images(_pdf(3, "x"), "doc.pdf", None, max_pages=5)) == 3

    def test_exif_orientation_is_applied(self):
        # Orientation 6 = rotate 90° clockwise: a 400×200 landscape file that
        # a phone meant as portrait comes out 200×400.
        images = to_images(_jpeg((400, 200), orientation=6), "photo.jpg", "image/jpeg")
        assert len(images) == 1
        assert _decode(images[0][0]).size == (200, 400)

    def test_longest_side_is_bounded(self):
        images = to_images(_jpeg((3000, 1500)), "photo.jpg", "image/jpeg", max_side=800)
        width, height = _decode(images[0][0]).size
        assert (width, height) == (800, 400)

    def test_png_with_alpha_is_converted(self):
        image = Image.new("RGBA", (300, 300), (10, 20, 30, 128))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        images = to_images(buffer.getvalue(), "scan.png", "image/png")
        assert _decode(images[0][0]).mode == "RGB"

    def test_total_size_bound_lowers_quality_then_halves_the_side(self):
        noisy = _jpeg((1200, 1200), noise=True)
        roomy = to_images(noisy, "p.jpg", "image/jpeg", max_total_bytes=50_000_000)
        tight = to_images(noisy, "p.jpg", "image/jpeg", max_total_bytes=1)
        assert len(roomy) == len(tight) == 1
        assert len(tight[0][0]) < len(roomy[0][0])
        # No quality fits one byte, so the fallback halves the side bound
        # (1600 → 800) and the 1200-pixel source is reduced to it.
        assert max(_decode(tight[0][0]).size) == 800
        assert max(_decode(roomy[0][0]).size) == 1200

    def test_unreadable_file_is_a_value_error(self):
        with pytest.raises(ValueError):
            to_images(b"\x00\x01\x02 nothing", "x.jpg", "image/jpeg")
        with pytest.raises(ValueError):
            to_images(b"%PDF-1.7 truncated", "x.pdf", "application/pdf")

    def test_heic_is_read_when_the_codec_is_available(self):
        pillow_heif = pytest.importorskip("pillow_heif")
        image = Image.new("RGB", (320, 240), (90, 160, 30))
        buffer = io.BytesIO()
        try:
            image.save(buffer, format="HEIF")
        except Exception as exc:  # noqa: BLE001 - no encoder in this build
            pytest.skip(f"no HEIF encoder: {exc} ({pillow_heif.__version__})")
        images = to_images(buffer.getvalue(), "IMG_0001.HEIC", "image/heic")
        assert _decode(images[0][0]).size == (320, 240)
