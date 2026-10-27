"""
Integration tests for window sticker routes.

Tests window sticker OCR and file management endpoints.
"""

import logging
import string
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import JSON, DateTime, Numeric, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import TypeDecorator

from app.models.vehicle import Vehicle
from app.routes import window_sticker as window_sticker_route
from app.services.settings_service import SettingsService
from tests.integration.routes._legacy_reads import read_ok


@pytest.mark.integration
@pytest.mark.asyncio
class TestWindowStickerRoutes:
    """Test window sticker API endpoints."""

    # -------------------------------------------------------------------------
    # GET /window-sticker endpoint tests
    # -------------------------------------------------------------------------

    async def test_get_window_sticker_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot get window sticker data."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/window-sticker")
        assert response.status_code == 401

    async def test_get_window_sticker_not_found(self, client: AsyncClient, auth_headers):
        """Test getting window sticker for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/window-sticker",
            headers=auth_headers,
        )
        # Returns 403 or 404 depending on auth flow
        assert response.status_code in [403, 404]

    async def test_get_window_sticker_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting window sticker when none has been uploaded."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        # No sticker uploaded yet
        assert data["window_sticker_file_path"] is None

    # -------------------------------------------------------------------------
    # POST /window-sticker/upload endpoint tests
    # -------------------------------------------------------------------------

    async def test_upload_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot upload window stickers."""
        files = {"file": ("test.pdf", b"fake pdf", "application/pdf")}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
            files=files,
        )
        assert response.status_code == 401

    async def test_upload_invalid_file_type(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test upload with invalid file type."""
        files = {"file": ("test.txt", b"not a pdf or image", "text/plain")}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
            headers=auth_headers,
            files=files,
        )

        assert response.status_code == 400
        assert "invalid file type" in response.json()["detail"].lower()

    async def test_upload_success(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test successful window sticker upload with mocked OCR."""
        # Create fake PDF content
        pdf_content = b"%PDF-1.4 fake pdf content"

        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.extract_data_from_file = AsyncMock(
                return_value={
                    "msrp_total": 35000,
                    "exterior_color": "Silver",
                    "window_sticker_parser_used": "generic",
                }
            )
            mock_ocr_class.return_value = mock_ocr

            files = {"file": ("window_sticker.pdf", pdf_content, "application/pdf")}
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
                headers=auth_headers,
                files=files,
            )

        assert response.status_code == 201
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert data["window_sticker_file_path"] is not None

    async def test_upload_image_file(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test upload with image file type."""
        # Create fake PNG content (minimal valid PNG header)
        png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.extract_data_from_file = AsyncMock(return_value={})
            mock_ocr_class.return_value = mock_ocr

            files = {"file": ("window_sticker.png", png_content, "image/png")}
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/window-sticker/upload",
                headers=auth_headers,
                files=files,
            )

        assert response.status_code == 201

    # -------------------------------------------------------------------------
    # POST /window-sticker/test endpoint tests
    # -------------------------------------------------------------------------

    async def test_test_extraction_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot test extraction."""
        files = {"file": ("test.pdf", b"fake pdf", "application/pdf")}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/test",
            files=files,
        )
        assert response.status_code == 401

    async def test_test_extraction_success(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test extraction endpoint returns extraction results."""
        pdf_content = b"%PDF-1.4 test content"

        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.test_extraction = AsyncMock(
                return_value={
                    "success": True,
                    "parser_name": "generic",
                    "manufacturer_detected": "Unknown",
                    "raw_text": "Sample OCR text",
                    "extracted_data": {"msrp_total": 30000},
                    "validation_warnings": [],
                    "error": None,
                }
            )
            mock_ocr_class.return_value = mock_ocr

            files = {"file": ("test.pdf", pdf_content, "application/pdf")}
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/window-sticker/test",
                headers=auth_headers,
                files=files,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["parser_name"] == "generic"

    # -------------------------------------------------------------------------
    # PATCH /window-sticker/data endpoint tests
    # -------------------------------------------------------------------------

    async def test_update_data_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot update data."""
        response = await client.patch(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/data",
            json={"msrp_total": 40000},
        )
        assert response.status_code == 401

    async def test_update_data_success(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating window sticker data."""
        response = await client.patch(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/data",
            headers=auth_headers,
            json={
                "msrp_total": 42000,
                "exterior_color": "Blue",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Updated values should be reflected (if the model supports them)
        assert data["vin"] == test_vehicle["vin"]

    # -------------------------------------------------------------------------
    # DELETE /window-sticker endpoint tests
    # -------------------------------------------------------------------------

    async def test_delete_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot delete window stickers."""
        response = await client.delete(f"/api/vehicles/{test_vehicle['vin']}/window-sticker")
        assert response.status_code == 401

    async def test_delete_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting when no window sticker exists."""
        # First, ensure no sticker exists by deleting any existing one
        # (Previous tests may have uploaded a sticker)
        await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker",
            headers=auth_headers,
        )

        # Now try to delete again - should return 404
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker",
            headers=auth_headers,
        )

        # Should return 404 since we just deleted it
        assert response.status_code == 404

    # -------------------------------------------------------------------------
    # GET /window-sticker/file endpoint tests
    # -------------------------------------------------------------------------

    async def test_download_file_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot download files."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/window-sticker/file")
        assert response.status_code == 401

    async def test_download_file_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test downloading when no file exists."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/window-sticker/file",
            headers=auth_headers,
        )

        assert response.status_code == 404

    # -------------------------------------------------------------------------
    # GET /parsers endpoint tests
    # -------------------------------------------------------------------------

    async def test_list_parsers_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot list parsers."""
        response = await client.get("/api/vehicles/window-sticker/parsers")
        assert response.status_code == 401

    async def test_list_parsers_success(self, client: AsyncClient, auth_headers):
        """Test listing available parsers."""
        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.list_available_parsers.return_value = [
                {
                    "manufacturer": "Generic",
                    "parser_class": "GenericWindowStickerParser",
                    "supported_makes": ["all"],
                }
            ]
            mock_ocr_class.return_value = mock_ocr

            response = await client.get(
                "/api/vehicles/window-sticker/parsers",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    # -------------------------------------------------------------------------
    # GET /ocr-status endpoint tests
    # -------------------------------------------------------------------------

    async def test_ocr_status_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot get OCR status."""
        response = await client.get("/api/vehicles/window-sticker/ocr-status")
        assert response.status_code == 401

    async def test_ocr_status_success(self, client: AsyncClient, auth_headers):
        """Test getting OCR engine status."""
        with patch("app.routes.window_sticker.WindowStickerOCRService") as mock_ocr_class:
            mock_ocr = MagicMock()
            mock_ocr.get_ocr_status.return_value = {
                "pymupdf_available": True,
                "tesseract_available": True,
                "paddleocr_enabled": False,
                "paddleocr_available": False,
            }
            mock_ocr_class.return_value = mock_ocr

            response = await client.get(
                "/api/vehicles/window-sticker/ocr-status",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "pymupdf_available" in data
        assert "tesseract_available" in data

    # -------------------------------------------------------------------------
    # Authorization tests
    # -------------------------------------------------------------------------

    async def test_window_sticker_forbidden_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Test that non-owner users cannot access another user's window sticker."""
        vin = test_vehicle["vin"]
        response = await client.get(
            f"/api/vehicles/{vin}/window-sticker",
            headers=non_admin_headers,
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# OCR text longer than its column
# ---------------------------------------------------------------------------

# Every text column the upload copies OCR output into.
OCR_TEXT_COLUMNS = [
    "assembly_location",
    "exterior_color",
    "interior_color",
    "sticker_engine_description",
    "sticker_transmission_description",
    "sticker_drivetrain",
    "wheel_specs",
    "tire_specs",
    "warranty_powertrain",
    "warranty_basic",
    "environmental_rating_ghg",
    "environmental_rating_smog",
    "window_sticker_parser_used",
    "window_sticker_extracted_vin",
]


NEW_BYTES = b"%PDF-1.4 sticker"


def _width(column: str) -> int:
    width = getattr(Vehicle.__table__.c[column].type, "length", None)
    assert isinstance(width, int), column
    return width


async def _upload_with_ocr(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    parsed: dict[str, Any] | Exception,
    *,
    replace: bool = False,
) -> Response:
    """Upload a sticker whose OCR returns `parsed`, or raises it when it's an
    exception. `replace` sends the field the drawer sends with "keep" off."""
    response, _ = await _upload_watching_ocr(client, headers, vin, parsed, replace=replace)
    return response


async def _upload_watching_ocr(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    parsed: dict[str, Any] | Exception,
    *,
    replace: bool = False,
) -> tuple[Response, MagicMock]:
    """`_upload_with_ocr`, also handing back the OCR mock to ask what it was called with."""
    with patch("app.routes.window_sticker.WindowStickerOCRService") as ocr_class:
        ocr = MagicMock()
        if isinstance(parsed, Exception):
            ocr.extract_data_from_file = AsyncMock(side_effect=parsed)
        else:
            # A copy: the route drops misread numbers from the dict it gets.
            ocr.extract_data_from_file = AsyncMock(return_value=dict(parsed))
        ocr_class.return_value = ocr
        response = await client.post(
            f"/api/vehicles/{vin}/window-sticker/upload",
            files={"file": ("sticker.pdf", NEW_BYTES, "application/pdf")},
            data={"replace": "true"} if replace else None,
            headers=headers,
        )
    return response, ocr


async def _stored(sessionmaker: async_sessionmaker[AsyncSession], vin: str, column: str) -> Any:
    """What the row holds, read through a session the route never touched."""
    async with sessionmaker() as session:
        stmt = select(Vehicle.__table__.c[column]).where(Vehicle.vin == vin)
        return (await session.execute(stmt)).scalar()


@pytest.mark.integration
@pytest.mark.parametrize("column", OCR_TEXT_COLUMNS)
async def test_ocr_text_longer_than_its_column_is_clipped(
    client, auth_headers, own_vehicle, test_sessionmaker, column
):
    """OCR now and then reads a whole paragraph into a short field. PostgreSQL
    refused it, a 500 with the file already on disk, and SQLite kept it whole."""
    vin = own_vehicle.vin
    width = _width(column)

    uploaded = await _upload_with_ocr(client, auth_headers, vin, {column: "x" * (width + 20)})

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, column) == "x" * width
    await read_ok(client, auth_headers, f"/api/vehicles/{vin}")


@pytest.mark.integration
async def test_a_100_character_colour_saves(client, auth_headers, own_vehicle, test_sessionmaker):
    """It fits the sticker's colour column, but the upload also fills the
    vehicle's own colour when that's empty, and that one holds 30."""
    vin = own_vehicle.vin
    assert own_vehicle.color is None
    # Not one repeated letter, so a cut from the wrong end shows.
    colour = (string.ascii_lowercase * 4)[:100]

    uploaded = await _upload_with_ocr(client, auth_headers, vin, {"exterior_color": colour})

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "exterior_color") == colour
    assert await _stored(test_sessionmaker, vin, "color") == colour[:30]
    body = await read_ok(client, auth_headers, f"/api/vehicles/{vin}")
    assert body["color"] == colour[:30]


@pytest.mark.integration
async def test_a_cut_is_logged_once_without_the_text(client, auth_headers, own_vehicle, caplog):
    """One field too long, one warning: its column and both lengths, never the
    OCR text, and nothing for the strings that fit.

    Guards the once: mutant "drop `len(value) <= length` from _fit_to_column's
    early return" logs a cut for every string, five warnings here, not one.
    """
    vin = own_vehicle.vin
    parsed = {
        "assembly_location": "OCRTEXT" * 20,
        "exterior_color": "Blue",
        "interior_color": "Black",
        "window_sticker_parser_used": "generic",
    }

    # Everything the route logs, so the text check covers every level.
    with caplog.at_level(logging.DEBUG, logger="app.routes.window_sticker"):
        uploaded = await _upload_with_ocr(client, auth_headers, vin, parsed)

    assert uploaded.status_code == 201, uploaded.text
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.name == "app.routes.window_sticker" and r.levelno == logging.WARNING
    ]
    assert warnings == ["Window sticker: cut parsed assembly_location from 140 to 100 characters"]
    assert "OCRTEXT" not in caplog.text


# ---------------------------------------------------------------------------
# A re-scan fills empty fields only, unless replacing (D1)
# ---------------------------------------------------------------------------

# What the scan reads in the D1 tests.
SCAN: dict[str, Any] = {
    "msrp_base": 30000,
    "exterior_color": "Red",
    "window_sticker_parser_used": "generic",
    "standard_equipment": {"Safety": ["ABS"]},
}
OLD_BYTES = b"%PDF-1.4 the sticker already on file"
ROUTE_LOGGER = "app.routes.window_sticker"


@contextmanager
def _route_log_captured(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """The route's records go to caplog only. log_cli prints everything live,
    so an expected traceback would otherwise spill into the run's output."""
    route_log = logging.getLogger(ROUTE_LOGGER)
    route_log.addHandler(caplog.handler)
    previous = route_log.propagate
    route_log.propagate = False
    try:
        yield
    finally:
        route_log.propagate = previous
        route_log.removeHandler(caplog.handler)


def _route_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == ROUTE_LOGGER and r.levelno == logging.ERROR]


# What DELETE cleared before the lists became module constants, copied off
# the route as it stood. The upload wrote the same set minus path and time.
TODAY_DELETE_CLEARS = (
    "window_sticker_file_path",
    "window_sticker_uploaded_at",
    "msrp_base",
    "msrp_options",
    "msrp_total",
    "destination_charge",
    "fuel_economy_city_l_per_100km",
    "fuel_economy_highway_l_per_100km",
    "fuel_economy_combined_l_per_100km",
    "standard_equipment",
    "optional_equipment",
    "assembly_location",
    "exterior_color",
    "interior_color",
    "sticker_engine_description",
    "sticker_transmission_description",
    "sticker_drivetrain",
    "wheel_specs",
    "tire_specs",
    "warranty_powertrain",
    "warranty_basic",
    "environmental_rating_ghg",
    "environmental_rating_smog",
    "window_sticker_options_detail",
    "window_sticker_packages",
    "window_sticker_parser_used",
    "window_sticker_confidence_score",
    "window_sticker_extracted_vin",
)


@pytest_asyncio.fixture
async def sticker_on_file(
    client: AsyncClient, own_vehicle: Vehicle, db_session: AsyncSession, tmp_path: Path
) -> AsyncGenerator[Path]:
    """A sticker already saved: a real file with known bytes, the row pointing
    at it, msrp_base 25000. Storage moves to tmp_path so the file checks only
    ever see this test's files. Needs `client` so its own storage swap goes
    first and is put back last."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(window_sticker_route, "STICKER_STORAGE_PATH", tmp_path)
        old = tmp_path / own_vehicle.vin / "window_sticker_old.pdf"
        old.parent.mkdir()
        old.write_bytes(OLD_BYTES)
        own_vehicle.window_sticker_file_path = str(old)
        own_vehicle.window_sticker_uploaded_at = datetime(2026, 1, 2, 3, 4, 5)
        own_vehicle.msrp_base = Decimal("25000")
        await db_session.commit()
        yield old


@pytest.mark.integration
async def test_a_rescan_fills_only_the_empty_fields(
    client, auth_headers, own_vehicle, db_session, test_sessionmaker
):
    """D1: a price typed by hand survives the scan; the empty fields fill."""
    vin = own_vehicle.vin
    own_vehicle.msrp_base = Decimal("25000")
    await db_session.commit()

    uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN)

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "msrp_base") == Decimal("25000")
    assert await _stored(test_sessionmaker, vin, "exterior_color") == "Red"
    assert await _stored(test_sessionmaker, vin, "standard_equipment") == {"Safety": ["ABS"]}
    assert await _stored(test_sessionmaker, vin, "window_sticker_parser_used") == "generic"


@pytest.mark.integration
async def test_a_blank_string_and_an_empty_object_count_as_empty(
    client, auth_headers, own_vehicle, db_session, test_sessionmaker
):
    """A field cleared to "" or {} reads as nothing to keep. Passes on main
    too (it overwrote everything); it pins the rule for the fill-empty code."""
    vin = own_vehicle.vin
    own_vehicle.exterior_color = ""
    own_vehicle.interior_color = "   "
    own_vehicle.standard_equipment = {}
    await db_session.commit()

    uploaded = await _upload_with_ocr(
        client, auth_headers, vin, {**SCAN, "interior_color": "Black"}
    )

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "exterior_color") == "Red"
    assert await _stored(test_sessionmaker, vin, "interior_color") == "Black"
    assert await _stored(test_sessionmaker, vin, "standard_equipment") == {"Safety": ["ABS"]}


@pytest.mark.integration
async def test_a_zero_is_a_value_and_is_kept(
    client, auth_headers, own_vehicle, db_session, test_sessionmaker
):
    vin = own_vehicle.vin
    own_vehicle.msrp_options = Decimal("0")
    await db_session.commit()

    uploaded = await _upload_with_ocr(client, auth_headers, vin, {"msrp_options": 500})

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "msrp_options") == Decimal("0")


@pytest.mark.integration
async def test_replace_clears_the_old_values_first(
    client, auth_headers, own_vehicle, sticker_on_file, db_session, test_sessionmaker
):
    vin = own_vehicle.vin
    own_vehicle.assembly_location = "Ohio"
    await db_session.commit()

    uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "msrp_base") == Decimal("30000")
    # The new sticker doesn't say, so the old sticker's value goes with it.
    assert await _stored(test_sessionmaker, vin, "assembly_location") is None


@pytest.mark.integration
async def test_every_upload_resets_the_scan_metadata(
    client, auth_headers, own_vehicle, sticker_on_file, db_session, test_sessionmaker
):
    """Parser, confidence and VIN read describe the file on record, so even a
    keep-mode upload swaps them for the new scan's, None where it has none."""
    vin = own_vehicle.vin
    own_vehicle.window_sticker_confidence_score = Decimal("90")
    await db_session.commit()

    uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN)

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "window_sticker_confidence_score") is None
    assert await _stored(test_sessionmaker, vin, "window_sticker_parser_used") == "generic"


@pytest.mark.integration
@pytest.mark.parametrize(
    "scan",
    [RuntimeError("tesseract fell over"), {}],
    ids=["ocr-raised", "ocr-read-nothing"],
)
async def test_a_scan_that_read_nothing_keeps_the_values_and_says_so(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker, scan, caplog
):
    """Replace with nothing to replace the values with clears nothing. The new
    file is still the sticker on record, and the response says the scan was
    empty instead of swallowing it."""
    vin = own_vehicle.vin

    with _route_log_captured(caplog):
        uploaded = await _upload_with_ocr(client, auth_headers, vin, scan, replace=True)

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "msrp_base") == Decimal("25000")
    new_path = await _stored(test_sessionmaker, vin, "window_sticker_file_path")
    assert new_path == uploaded.json()["window_sticker_file_path"]
    assert new_path != str(sticker_on_file)
    assert Path(new_path).read_bytes() == NEW_BYTES
    assert not sticker_on_file.exists()
    assert uploaded.json().get("scan_read_nothing") is True
    expected = ["OCR extraction failed: tesseract fell over"] if isinstance(scan, Exception) else []
    assert [r.getMessage() for r in _route_errors(caplog)] == expected


@pytest.mark.integration
async def test_a_failed_write_keeps_the_sticker_on_file(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker, caplog
):
    vin = own_vehicle.vin
    columns = ("window_sticker_file_path", "window_sticker_uploaded_at", "msrp_base")
    before = {c: await _stored(test_sessionmaker, vin, c) for c in columns}
    assert before["window_sticker_file_path"] == str(sticker_on_file)
    assert before["msrp_base"] == Decimal("25000")

    with (
        _route_log_captured(caplog),
        patch("app.routes.window_sticker.open", side_effect=OSError, create=True),
    ):
        uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 500, uploaded.text
    assert sticker_on_file.exists()
    assert sticker_on_file.read_bytes() == OLD_BYTES
    assert {c: await _stored(test_sessionmaker, vin, c) for c in columns} == before
    (error,) = _route_errors(caplog)
    assert error.getMessage() == f"Failed to save window sticker for {vin}"
    assert error.exc_info is not None and error.exc_info[0] is OSError


@pytest.mark.integration
async def test_a_failed_commit_keeps_the_sticker_on_file(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker, caplog
):
    vin = own_vehicle.vin
    vin_dir = sticker_on_file.parent
    on_disk_at_commit: list[list[str]] = []

    async def refuse(self: AsyncSession) -> None:
        on_disk_at_commit.append(sorted(p.name for p in vin_dir.iterdir()))
        raise SQLAlchemyError("disk I/O error")

    # This request only: the fixtures' own commits have to work afterwards.
    with _route_log_captured(caplog), pytest.MonkeyPatch.context() as mp:
        mp.setattr(AsyncSession, "commit", refuse)
        uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 500, uploaded.text
    # It was the route's commit that failed, with the new file beside the old.
    assert len(on_disk_at_commit) == 1, on_disk_at_commit
    assert len(on_disk_at_commit[0]) == 2, on_disk_at_commit
    assert sticker_on_file.read_bytes() == OLD_BYTES
    assert list(vin_dir.iterdir()) == [sticker_on_file]
    assert await _stored(test_sessionmaker, vin, "window_sticker_file_path") == str(sticker_on_file)
    assert await _stored(test_sessionmaker, vin, "msrp_base") == Decimal("25000")
    (error,) = _route_errors(caplog)
    assert error.getMessage() == f"Window sticker upload failed for {vin}"
    assert error.exc_info is not None and error.exc_info[0] is SQLAlchemyError


@pytest.mark.integration
async def test_a_replace_moves_the_record_to_the_new_file(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker
):
    vin = own_vehicle.vin

    uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 201, uploaded.text
    new_path = Path(await _stored(test_sessionmaker, vin, "window_sticker_file_path"))
    assert new_path != sticker_on_file
    assert new_path.parent == sticker_on_file.parent
    assert new_path.read_bytes() == NEW_BYTES
    assert not sticker_on_file.exists()
    assert uploaded.json().get("scan_read_nothing") is False


@pytest.mark.integration
async def test_replace_with_no_sticker_on_file_keeps_typed_values(
    client, auth_headers, own_vehicle, test_sessionmaker
):
    """Fable F-6: with no sticker there's nothing to replace, so the values
    typed through the review PATCH survive. Main ignored the field and passed
    too; this goes red if the `old_path` guard is dropped."""
    vin = own_vehicle.vin
    typed = await client.patch(
        f"/api/vehicles/{vin}/window-sticker/data",
        json={"assembly_location": "Ohio"},
        headers=auth_headers,
    )
    assert typed.status_code == 200, typed.text

    uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "assembly_location") == "Ohio"
    assert await _stored(test_sessionmaker, vin, "exterior_color") == "Red"


@pytest.mark.integration
async def test_the_vehicle_colour_follows_the_kept_sticker_colour(
    client, auth_headers, own_vehicle, db_session, test_sessionmaker
):
    """Keep mode kept the typed exterior colour, so the vehicle's own colour
    fills from that, not from the scan's reading it just discarded."""
    vin = own_vehicle.vin
    assert own_vehicle.color is None
    own_vehicle.exterior_color = "Blue"
    await db_session.commit()

    uploaded = await _upload_with_ocr(client, auth_headers, vin, SCAN)

    assert uploaded.status_code == 201, uploaded.text
    assert await _stored(test_sessionmaker, vin, "exterior_color") == "Blue"
    assert await _stored(test_sessionmaker, vin, "color") == "Blue"


@pytest.mark.integration
async def test_a_scan_that_read_nothing_leaves_the_vehicle_colour_alone(
    client, auth_headers, own_vehicle, db_session, test_sessionmaker
):
    """The notice says nothing else was changed, so a scan with no colour
    never copies the stored exterior colour into the vehicle's."""
    vin = own_vehicle.vin
    own_vehicle.exterior_color = "Blue"
    await db_session.commit()

    uploaded = await _upload_with_ocr(client, auth_headers, vin, {})

    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json().get("scan_read_nothing") is True
    assert await _stored(test_sessionmaker, vin, "color") is None


def test_an_old_path_unlink_cannot_take_is_a_warning(caplog: pytest.LogCaptureFixture):
    """After the commit the upload has worked; a stored path unlink refuses
    (a NUL raises ValueError, not OSError) must log, not turn it into a 500."""
    with _route_log_captured(caplog):
        window_sticker_route._unlink_quietly(Path("window_sticker\x00.pdf"))

    assert [(r.name, r.levelno) for r in caplog.records] == [(ROUTE_LOGGER, logging.WARNING)]


def _a_value_for(column: str) -> Any:
    """Something non-null that fits the column."""
    kind = Vehicle.__table__.c[column].type
    # A ScaledNumeric is a Numeric underneath.
    if isinstance(kind, TypeDecorator):
        kind = kind.impl_instance
    if isinstance(kind, Numeric):
        return Decimal("1")
    if isinstance(kind, JSON):
        return {"k": "v"}
    if isinstance(kind, DateTime):
        return datetime(2026, 1, 2, 3, 4, 5)
    return "7"


@pytest.mark.integration
async def test_delete_still_clears_every_sticker_column(
    client, auth_headers, own_vehicle, sticker_on_file, db_session, test_sessionmaker
):
    """The delete's list now comes from the upload's constants; none of
    today's 28 may drop out of it."""
    vin = own_vehicle.vin
    for column in TODAY_DELETE_CLEARS[1:]:  # the fixture set the path
        setattr(own_vehicle, column, _a_value_for(column))
    await db_session.commit()
    for column in TODAY_DELETE_CLEARS:
        assert await _stored(test_sessionmaker, vin, column) is not None, column

    deleted = await client.delete(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)

    assert deleted.status_code == 204, deleted.text
    for column in TODAY_DELETE_CLEARS:
        assert await _stored(test_sessionmaker, vin, column) is None, column


@pytest.mark.integration
async def test_delete_keeps_the_file_when_the_commit_fails(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker, caplog
):
    """The row still points at the file, so the file has to stay too."""
    vin = own_vehicle.vin
    commits: list[str] = []

    async def refuse(self: AsyncSession) -> None:
        commits.append("refused")
        raise SQLAlchemyError("disk I/O error")

    # This request only: the fixtures' own commits have to work afterwards.
    with _route_log_captured(caplog), pytest.MonkeyPatch.context() as mp:
        mp.setattr(AsyncSession, "commit", refuse)
        deleted = await client.delete(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)

    assert deleted.status_code == 500, deleted.text
    assert commits == ["refused"]
    assert sticker_on_file.read_bytes() == OLD_BYTES
    assert await _stored(test_sessionmaker, vin, "window_sticker_file_path") == str(sticker_on_file)
    assert await _stored(test_sessionmaker, vin, "msrp_base") == Decimal("25000")
    (error,) = _route_errors(caplog)
    assert error.getMessage() == f"Window sticker delete failed for {vin}"
    assert error.exc_info is not None and error.exc_info[0] is SQLAlchemyError


@pytest.mark.integration
async def test_delete_removes_the_file_after_the_commit(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker
):
    vin = own_vehicle.vin
    real_commit = AsyncSession.commit
    file_there_at_commit: list[bool] = []

    async def look_then_commit(self: AsyncSession) -> None:
        file_there_at_commit.append(sticker_on_file.exists())
        await real_commit(self)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(AsyncSession, "commit", look_then_commit)
        deleted = await client.delete(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)

    assert deleted.status_code == 204, deleted.text
    assert file_there_at_commit == [True]
    assert not sticker_on_file.exists()
    assert await _stored(test_sessionmaker, vin, "window_sticker_file_path") is None
    assert await _stored(test_sessionmaker, vin, "msrp_base") is None


@pytest.mark.integration
async def test_delete_survives_an_unlink_failure(
    client, auth_headers, own_vehicle, sticker_on_file, test_sessionmaker, caplog
):
    """The delete has worked once it commits; a file it can't remove is an orphan."""
    vin = own_vehicle.vin
    real_unlink = Path.unlink

    def refuse(self: Path, missing_ok: bool = False) -> None:
        if self == sticker_on_file:
            raise OSError("permission denied")
        real_unlink(self, missing_ok=missing_ok)

    with _route_log_captured(caplog), pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "unlink", refuse)
        deleted = await client.delete(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)

    assert deleted.status_code == 204, deleted.text
    assert await _stored(test_sessionmaker, vin, "window_sticker_file_path") is None
    assert await _stored(test_sessionmaker, vin, "msrp_base") is None
    assert sticker_on_file.exists()
    assert [(r.levelno, r.getMessage()) for r in caplog.records if r.name == ROUTE_LOGGER] == [
        (
            logging.WARNING,
            f"Failed to delete window sticker file {sticker_on_file}: permission denied",
        )
    ]


def test_the_field_lists_cover_what_upload_and_delete_wrote():
    """The upload fills from the same two lists, so a field missing here
    would silently stop being read off the sticker."""
    from app.routes.window_sticker import STICKER_DATA_FIELDS, STICKER_SCAN_FIELDS

    fields = (*STICKER_DATA_FIELDS, *STICKER_SCAN_FIELDS)
    assert len(fields) == len(set(fields)) == 26
    assert set(fields) == set(TODAY_DELETE_CLEARS[2:])


# ---------------------------------------------------------------------------
# The Settings > Files switches: window_sticker_enabled, window_sticker_ocr_enabled
# ---------------------------------------------------------------------------

STICKERS_OFF = "Window sticker uploads are switched off in Settings > Files"
OCR_OFF = "Window sticker OCR is switched off in Settings > Files"

Switches = Callable[..., Awaitable[None]]


@pytest_asyncio.fixture
async def sticker_switches(db_session: AsyncSession, keep_rows) -> Switches:
    """Set both switches for one test; `keep_rows` puts the rows back after."""
    await keep_rows("window_sticker_enabled", "window_sticker_ocr_enabled")

    async def switch(*, stickers: str = "true", ocr: str = "true") -> None:
        await SettingsService.set(db_session, "window_sticker_enabled", stickers)
        await SettingsService.set(db_session, "window_sticker_ocr_enabled", ocr)
        await db_session.commit()

    return switch


async def _test_watching_ocr(
    client: AsyncClient, headers: dict[str, str], vin: str
) -> tuple[Response, MagicMock]:
    """POST the dry-run test endpoint with a mocked OCR that would succeed."""
    with patch("app.routes.window_sticker.WindowStickerOCRService") as ocr_class:
        ocr = MagicMock()
        ocr.test_extraction = AsyncMock(
            return_value={
                "success": True,
                "parser_name": "generic",
                "manufacturer_detected": "Unknown",
                "raw_text": "Sample OCR text",
                "extracted_data": {"msrp_total": 30000},
                "validation_warnings": [],
                "error": None,
            }
        )
        ocr_class.return_value = ocr
        response = await client.post(
            f"/api/vehicles/{vin}/window-sticker/test",
            files={"file": ("sticker.pdf", NEW_BYTES, "application/pdf")},
            headers=headers,
        )
    return response, ocr


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


@pytest.mark.integration
async def test_stickers_off_refuses_the_upload_and_changes_nothing(
    client,
    auth_headers,
    own_vehicle,
    sticker_on_file,
    sticker_switches,
    test_sessionmaker,
    tmp_path,
):
    """A 409 that says where to switch it back on; no file lands in storage, the
    sticker on file stays, and no column moves. Red on main, which stored it."""
    vin = own_vehicle.vin
    await sticker_switches(stickers="false")
    columns = (*TODAY_DELETE_CLEARS, "color")
    before = {c: await _stored(test_sessionmaker, vin, c) for c in columns}

    uploaded, ocr = await _upload_watching_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 409, uploaded.text
    assert uploaded.json()["detail"] == STICKERS_OFF
    ocr.extract_data_from_file.assert_not_awaited()
    assert _files_under(tmp_path) == [sticker_on_file]
    assert sticker_on_file.read_bytes() == OLD_BYTES
    assert {c: await _stored(test_sessionmaker, vin, c) for c in columns} == before


@pytest.mark.integration
async def test_stickers_off_refuses_the_test_scan(
    client, auth_headers, own_vehicle, sticker_on_file, sticker_switches, tmp_path
):
    """The dry run scans an uploaded file too, so it is gated with the upload.
    Red on main, which ran it."""
    await sticker_switches(stickers="false")

    response, ocr = await _test_watching_ocr(client, auth_headers, own_vehicle.vin)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == STICKERS_OFF
    ocr.test_extraction.assert_not_awaited()
    assert _files_under(tmp_path) == [sticker_on_file]


@pytest.mark.integration
async def test_stickers_off_still_shows_edits_and_deletes_the_sticker_on_file(
    client, auth_headers, own_vehicle, sticker_on_file, sticker_switches, test_sessionmaker
):
    """Regression guard (main passes: it gated nothing). The switch stops new
    stickers only (Fable F-12): the one on file can still be read, downloaded,
    corrected in the review and deleted, and the parser list and OCR status
    still answer."""
    vin = own_vehicle.vin
    await sticker_switches(stickers="false")

    shown = await client.get(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)
    assert shown.status_code == 200, shown.text
    assert shown.json()["window_sticker_file_path"] == str(sticker_on_file)

    downloaded = await client.get(f"/api/vehicles/{vin}/window-sticker/file", headers=auth_headers)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == OLD_BYTES

    edited = await client.patch(
        f"/api/vehicles/{vin}/window-sticker/data",
        json={"assembly_location": "Ohio"},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert await _stored(test_sessionmaker, vin, "assembly_location") == "Ohio"

    with patch("app.routes.window_sticker.WindowStickerOCRService") as ocr_class:
        ocr_class.return_value.list_available_parsers.return_value = []
        ocr_class.return_value.get_ocr_status.return_value = {
            "pymupdf_available": True,
            "tesseract_available": True,
            "paddleocr_enabled": False,
            "paddleocr_available": False,
        }
        parsers = await client.get("/api/vehicles/window-sticker/parsers", headers=auth_headers)
        status = await client.get("/api/vehicles/window-sticker/ocr-status", headers=auth_headers)
    assert parsers.status_code == 200, parsers.text
    assert status.status_code == 200, status.text

    deleted = await client.delete(f"/api/vehicles/{vin}/window-sticker", headers=auth_headers)
    assert deleted.status_code == 204, deleted.text
    assert not sticker_on_file.exists()
    assert await _stored(test_sessionmaker, vin, "window_sticker_file_path") is None


@pytest.mark.integration
@pytest.mark.parametrize("endpoint", ["upload", "test"])
async def test_a_non_owner_still_gets_403_with_stickers_off(
    client, non_admin_headers, own_vehicle, sticker_switches, endpoint
):
    """The switch isn't disclosed for a vehicle the caller can't reach.

    Regression guard (main answered 403 too); mutant: read the switch before
    the access check.
    """
    await sticker_switches(stickers="false", ocr="false")
    vin = own_vehicle.vin

    if endpoint == "upload":
        response = await _upload_with_ocr(client, non_admin_headers, vin, SCAN)
    else:
        response, _ = await _test_watching_ocr(client, non_admin_headers, vin)

    assert response.status_code == 403, response.text


@pytest.mark.integration
async def test_ocr_off_stores_the_file_without_a_scan(
    client, auth_headers, own_vehicle, sticker_on_file, sticker_switches, test_sessionmaker
):
    """The file becomes the sticker on record, OCR never runs, and the response
    says so in `ocr_skipped`, not `scan_read_nothing` (no scan ran). The scan
    metadata describes the file on record, which had no scan, so it empties.
    Red on main, which scanned and had no `ocr_skipped`."""
    vin = own_vehicle.vin
    await sticker_switches(ocr="false")

    uploaded, ocr = await _upload_watching_ocr(client, auth_headers, vin, SCAN)

    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body.get("ocr_skipped") is True
    assert body["scan_read_nothing"] is False
    ocr.extract_data_from_file.assert_not_awaited()
    new_path = Path(await _stored(test_sessionmaker, vin, "window_sticker_file_path"))
    assert str(new_path) == body["window_sticker_file_path"]
    assert new_path != sticker_on_file
    assert new_path.read_bytes() == NEW_BYTES
    assert not sticker_on_file.exists()
    for column in window_sticker_route.STICKER_SCAN_FIELDS:
        assert await _stored(test_sessionmaker, vin, column) is None, column
    # Nothing was read, so nothing filled: the empty fields stay empty.
    assert await _stored(test_sessionmaker, vin, "msrp_base") == Decimal("25000")
    assert await _stored(test_sessionmaker, vin, "exterior_color") is None


@pytest.mark.integration
async def test_ocr_off_replace_keeps_the_sticker_fields(
    client,
    auth_headers,
    own_vehicle,
    sticker_on_file,
    sticker_switches,
    db_session,
    test_sessionmaker,
):
    """Replace clears only for a sticker that was actually scanned; with OCR off
    there is nothing to put back. Red on main: its scan (SCAN, different values)
    cleared the old sticker's fields and wrote its own over them."""
    vin = own_vehicle.vin
    own_vehicle.assembly_location = "Ohio"
    own_vehicle.exterior_color = "Blue"
    await db_session.commit()
    await sticker_switches(ocr="false")

    uploaded, ocr = await _upload_watching_ocr(client, auth_headers, vin, SCAN, replace=True)

    assert uploaded.status_code == 201, uploaded.text
    kept = {
        "msrp_base": Decimal("25000"),
        "assembly_location": "Ohio",
        "exterior_color": "Blue",
        "standard_equipment": None,
    }
    assert {c: await _stored(test_sessionmaker, vin, c) for c in kept} == kept
    ocr.extract_data_from_file.assert_not_awaited()


@pytest.mark.integration
async def test_ocr_off_refuses_the_test_scan(
    client, auth_headers, own_vehicle, sticker_on_file, sticker_switches, tmp_path
):
    """The test endpoint is nothing but a scan. Red on main, which ran it."""
    await sticker_switches(ocr="false")

    response, ocr = await _test_watching_ocr(client, auth_headers, own_vehicle.vin)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == OCR_OFF
    ocr.test_extraction.assert_not_awaited()
    assert _files_under(tmp_path) == [sticker_on_file]
