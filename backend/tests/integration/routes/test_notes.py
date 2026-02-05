"""
Integration tests for note routes.

Tests note CRUD operations.
"""

from datetime import datetime

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestNoteRoutes:
    """Test note API endpoints."""

    async def test_list_notes(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing notes for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "notes" in data
        assert "total" in data
        assert isinstance(data["notes"], list)

    async def test_get_note_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific note."""
        # First create a note
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-01-15",
                "title": "Test Note",
                "content": "This is a test note content.",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the note
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/notes/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["title"] == "Test Note"
        assert data["content"] == "This is a test note content."

    async def test_create_note(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new note."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "title": "Maintenance Reminder",
            "content": "Need to check tire pressure next week.",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == payload["title"]
        assert data["content"] == payload["content"]
        assert "id" in data
        assert "created_at" in data

    async def test_update_note(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a note."""
        # Create a note
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-02-01",
                "title": "Original Title",
                "content": "Original content.",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the note
        update_data = {
            "title": "Updated Title",
            "content": "Updated content with more details.",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/notes/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["content"] == "Updated content with more details."

    async def test_delete_note(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a note."""
        # Create a note
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-03-01",
                "content": "Note to be deleted.",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the note
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/notes/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/notes/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_note_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access notes."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/notes")

        assert response.status_code == 401

    async def test_create_note_validation(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that invalid notes are rejected."""
        # Content is required and must have min length 1
        invalid_payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-01-15",
            "title": "Test",
            "content": "",  # Empty content should fail
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_note_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test notes with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/notes",
            headers=auth_headers,
        )

        # get_vehicle_or_403 returns 403 if vehicle not found
        assert response.status_code in [403, 404]

    async def test_note_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get note with non-existent note ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/notes/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_note_without_title(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a note without a title (title is optional)."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "content": "Note without a title - just content.",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] is None
        assert data["content"] == "Note without a title - just content."

    async def test_note_ordering(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that notes are ordered by date descending."""
        # Create notes out of order
        dates = ["2022-01-01", "2024-01-01", "2023-01-01"]

        for date in dates:
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/notes",
                json={
                    "vin": test_vehicle["vin"],
                    "date": date,
                    "content": f"Note dated {date}",
                },
                headers=auth_headers,
            )

        # Get list
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        notes = data["notes"]

        # Should be ordered by date descending
        if len(notes) >= 2:
            for i in range(len(notes) - 1):
                assert notes[i]["date"] >= notes[i + 1]["date"]

    async def test_update_note_partial(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test partial update of note."""
        # Create a note
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-04-01",
                "title": "Initial Title",
                "content": "Initial content that should remain.",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update only title
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/notes/{record['id']}",
            json={"title": "New Title Only"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Original content unchanged
        assert data["content"] == "Initial content that should remain."
        # Title updated
        assert data["title"] == "New Title Only"

    async def test_note_with_long_content(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a note with long content."""
        long_content = "This is a detailed note. " * 100  # ~2500 characters
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "title": "Long Note",
            "content": long_content,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["content"] == long_content

    async def test_note_title_max_length(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that title respects max length constraint."""
        # Title max length is 100 characters
        long_title = "A" * 101  # 101 characters
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "title": long_title,
            "content": "Content for long title test.",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/notes",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error
