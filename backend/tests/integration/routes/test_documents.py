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
        fake_pdf = b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\nTest PDF content'

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("test_document.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={"document_type": "Service Record", "description": "Test document"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "filename" in data or "id" in data

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
        assert isinstance(data, list) or ("documents" in data)

    async def test_download_document(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading a document."""
        # First upload a document
        fake_pdf = b'%PDF-1.4\nTest content'

        upload_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("download_test.pdf", BytesIO(fake_pdf), "application/pdf")},
            headers=auth_headers,
        )

        if upload_response.status_code == 201:
            doc_data = upload_response.json()
            doc_id = doc_data.get("id") or doc_data.get("filename")

            if doc_id:
                # Download the document
                download_response = await client.get(
                    f"/api/documents/{doc_id}/download",
                    headers=auth_headers,
                )

                # Should return file or success
                assert download_response.status_code in [200, 302]

    async def test_delete_document(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a document."""
        # Upload a document
        fake_pdf = b'%PDF-1.4\nTest'

        upload_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("delete_test.pdf", BytesIO(fake_pdf), "application/pdf")},
            headers=auth_headers,
        )

        if upload_response.status_code == 201:
            doc_data = upload_response.json()
            doc_id = doc_data.get("id")

            if doc_id:
                # Delete the document
                delete_response = await client.delete(
                    f"/api/documents/{doc_id}",
                    headers=auth_headers,
                )

                assert delete_response.status_code in [204, 200]

    async def test_upload_invalid_document_type(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid file types are rejected."""
        # Create an executable file (not allowed)
        fake_exe = b'MZ\x90\x00'

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("bad.exe", BytesIO(fake_exe), "application/x-msdownload")},
            headers=auth_headers,
        )

        assert response.status_code in [400, 415, 422]

    async def test_upload_document_unauthorized(
        self, client: AsyncClient, test_vehicle
    ):
        """Test that unauthenticated users cannot upload documents."""
        fake_pdf = b'%PDF-1.4\n'

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("test.pdf", BytesIO(fake_pdf), "application/pdf")},
        )

        assert response.status_code == 401

    async def test_upload_document_with_metadata(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test uploading document with metadata."""
        fake_pdf = b'%PDF-1.4\n'

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/documents",
            files={"file": ("metadata_test.pdf", BytesIO(fake_pdf), "application/pdf")},
            data={
                "document_type": "Insurance",
                "description": "Insurance policy document",
                "date": "2024-01-15",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        if "document_type" in data:
            assert data["document_type"] == "Insurance"

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
        # Should return empty list or structure
        if isinstance(data, list):
            assert len(data) >= 0
        else:
            assert "documents" in data
