"""
Integration tests for attachment routes.

Tests file attachment upload, download, view, list, and delete operations
for service visits.
"""

from collections.abc import AsyncGenerator
from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment


@pytest.fixture
async def service_record(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
) -> AsyncGenerator[dict]:
    """Create a service visit for attachment tests, and clear it and its attachments after."""
    payload = {
        "vin": test_vehicle["vin"],
        "date": "2024-06-15",
        "odometer_km": 80467.0,
        "vendor_name": "Test Auto Shop",
        "total_cost": 150.00,
        "line_items": [
            {
                "description": "Oil Change",
                "cost": 75.00,
            },
            {
                "description": "Filter Replacement",
                "cost": 25.00,
            },
        ],
    }
    response = await client.post(
        f"/api/vehicles/{test_vehicle['vin']}/service-visits",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201
    visit = response.json()
    yield visit

    # Attachments have no FK to the visit, so deleting the visit leaves them behind,
    # and a later visit that reuses the id would list them.
    await db_session.rollback()
    rows = (
        await db_session.scalars(
            select(Attachment)
            .where(Attachment.record_type == "service_visit")
            .where(Attachment.record_id == visit["id"])
        )
    ).all()
    for row in rows:
        Path(row.file_path).unlink(missing_ok=True)
    await db_session.execute(delete(Attachment).where(Attachment.id.in_([r.id for r in rows])))
    await db_session.commit()
    gone = await client.delete(
        f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text


def create_test_file(filename: str, content: bytes = b"test content") -> tuple:
    """Create a test file for upload testing."""
    if filename.endswith(".pdf"):
        # PDF header for basic validation
        content = b"%PDF-1.4\n%test pdf content"
        content_type = "application/pdf"
    elif filename.endswith(".png"):
        # PNG header
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        content_type = "image/png"
    elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
        # JPEG header
        content = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        content_type = "image/jpeg"
    else:
        content_type = "application/octet-stream"

    return (filename, BytesIO(content), content_type)


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceVisitAttachments:
    """Test service visit attachment endpoints."""

    async def test_list_visit_attachments_empty(
        self, client: AsyncClient, auth_headers, service_record
    ):
        """Test listing attachments for a service visit with no attachments."""
        response = await client.get(
            f"/api/service-visits/{service_record['id']}/attachments",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "attachments" in data
        assert "total" in data
        assert data["total"] == 0

    async def test_upload_visit_attachment(self, client: AsyncClient, auth_headers, service_record):
        """Test uploading an attachment to a service visit."""
        file_data = create_test_file("work-order.pdf")

        response = await client.post(
            f"/api/service-visits/{service_record['id']}/attachments",
            headers=auth_headers,
            files={"file": file_data},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["record_type"] == "service_visit"
        assert data["record_id"] == service_record["id"]
        assert data["file_type"] == "application/pdf"
        # The bytes landed, under the test's tmp data dir.
        download = await client.get(data["download_url"], headers=auth_headers)
        assert download.status_code == 200
        assert download.content == file_data[1].getvalue()

    async def test_list_visit_attachments_after_upload(
        self, client: AsyncClient, auth_headers, service_record
    ):
        """Test listing service visit attachments after uploading."""
        # Upload an attachment
        file_data = create_test_file("invoice.pdf")
        upload_response = await client.post(
            f"/api/service-visits/{service_record['id']}/attachments",
            headers=auth_headers,
            files={"file": file_data},
        )
        assert upload_response.status_code == 201

        # List attachments
        response = await client.get(
            f"/api/service-visits/{service_record['id']}/attachments",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["attachments"]) == 1
        # Verify it's the correct type
        assert data["attachments"][0]["record_type"] == "service_visit"

    async def test_upload_to_nonexistent_visit(self, client: AsyncClient, auth_headers):
        """Test uploading attachment to non-existent service visit."""
        file_data = create_test_file("test.pdf")

        response = await client.post(
            "/api/service-visits/99999/attachments",
            headers=auth_headers,
            files={"file": file_data},
        )

        assert response.status_code == 404

    async def test_list_visit_attachments_nonexistent(self, client: AsyncClient, auth_headers):
        """Test listing attachments for non-existent service visit."""
        response = await client.get(
            "/api/service-visits/99999/attachments",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_visit_attachment_unauthorized(self, client: AsyncClient, service_record):
        """Test that unauthenticated users cannot access service visit attachments."""
        response = await client.get(f"/api/service-visits/{service_record['id']}/attachments")
        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestAttachmentResponses:
    """Test attachment response structure and URLs."""

    async def test_attachment_response_structure(
        self, client: AsyncClient, auth_headers, service_record
    ):
        """Test that attachment response has all required fields."""
        file_data = create_test_file("structure-test.pdf")

        response = await client.post(
            f"/api/service-visits/{service_record['id']}/attachments",
            headers=auth_headers,
            files={"file": file_data},
        )

        assert response.status_code == 201
        data = response.json()

        # Verify required fields
        assert "id" in data
        assert "record_type" in data
        assert "record_id" in data
        assert "file_name" in data
        assert "file_type" in data
        assert "file_size" in data
        assert "uploaded_at" in data
        assert "download_url" in data
        assert "view_url" in data

        # Verify URL format
        assert data["download_url"] == f"/api/attachments/{data['id']}/download"
        assert data["view_url"] == f"/api/attachments/{data['id']}/view"

    async def test_attachment_list_response_structure(
        self, client: AsyncClient, auth_headers, service_record
    ):
        """Test that attachment list response has correct structure."""
        # Upload a few attachments
        for i in range(2):
            file_data = create_test_file(f"list-test-{i}.pdf")
            uploaded = await client.post(
                f"/api/service-visits/{service_record['id']}/attachments",
                headers=auth_headers,
                files={"file": file_data},
            )
            assert uploaded.status_code == 201, uploaded.text

        # List attachments
        response = await client.get(
            f"/api/service-visits/{service_record['id']}/attachments",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "attachments" in data
        assert "total" in data
        assert isinstance(data["attachments"], list)
        assert isinstance(data["total"], int)
        assert data["total"] == 2
        assert len(data["attachments"]) == 2

        # Verify each attachment has required fields
        for attachment in data["attachments"]:
            assert "id" in attachment
            assert "file_name" in attachment
            assert "download_url" in attachment
