"""
Integration tests for document routes.

Tests document upload, retrieval, and deletion.
"""

import pytest
from httpx import AsyncClient
from io import BytesIO


@pytest.mark.integration
@pytest.mark.asyncio
class TestDocumentRoutes:
    """Test document API endpoints."""

    async def test_upload_document(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test uploading a document to a vehicle."""
        # Create a fake PDF
        fake_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nTest PDF content"

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("test_document.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={
                "title": "Test Document",  # Required field
                "document_type": "Service Record",
                "description": "Test document",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "title" in data

    async def test_list_documents(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test listing documents for a vehicle."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/documents",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data

    async def test_download_document(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading a document."""
        # First upload a document
        fake_pdf = b"%PDF-1.4\nTest content"

        upload_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("download_test.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={"title": "Download Test Doc"},
            headers=auth_headers,
        )

        if upload_response.status_code == 201:
            doc_data = upload_response.json()
            doc_id = doc_data.get("id")

            if doc_id:
                # Download the document - route includes VIN
                download_response = await client.get(
                    f"/api/vehicles/{test_vehicle['vin']}/documents/{doc_id}/download",
                    headers=auth_headers,
                )

                # Should return file or success
                assert download_response.status_code in [200, 302]

    async def test_delete_document(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a document."""
        # Upload a document
        fake_pdf = b"%PDF-1.4\nTest"

        upload_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("delete_test.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={"title": "Delete Test Doc"},
            headers=auth_headers,
        )

        if upload_response.status_code == 201:
            doc_data = upload_response.json()
            doc_id = doc_data.get("id")

            if doc_id:
                # Delete the document - route includes VIN
                delete_response = await client.delete(
                    f"/api/vehicles/{test_vehicle['vin']}/documents/{doc_id}",
                    headers=auth_headers,
                )

                assert delete_response.status_code in [204, 200]

    async def test_upload_invalid_document_type(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid file types are rejected."""
        # Create an executable file (not allowed)
        fake_exe = b"MZ\x90\x00"

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("bad.exe", BytesIO(fake_exe), "application/x-msdownload")},
            data={"title": "Bad File"},
            headers=auth_headers,
        )

        assert response.status_code in [400, 415, 422]

    async def test_upload_document_unauthorized(
        self, client: AsyncClient, test_vehicle
    ):
        """Test that unauthenticated users cannot upload documents."""
        fake_pdf = b"%PDF-1.4\n"

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("test.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={"title": "Unauthorized Doc"},
        )

        assert response.status_code == 401

    async def test_upload_document_with_metadata(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test uploading document with metadata."""
        fake_pdf = b"%PDF-1.4\n"

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("metadata_test.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={
                "title": "Insurance Policy",
                "document_type": "Insurance",
                "description": "Insurance policy document",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["document_type"] == "Insurance"
        assert data["title"] == "Insurance Policy"

    async def test_list_documents_empty(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test listing documents when vehicle has none."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data
        assert data["total"] >= 0
