"""Unit tests for Matrix notification service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications.matrix import MatrixNotificationService


@pytest.mark.asyncio
async def test_matrix_send_success():
    service = MatrixNotificationService(
        homeserver="https://matrix.example.com",
        access_token="syt_token",
        room_id="!room:example.com",
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch.object(service.client, "put", new=AsyncMock(return_value=mock_response)) as put:
        ok = await service.send("Title", "Body", priority="default")
        assert ok is True
        assert put.await_count == 1

    await service.close()


@pytest.mark.asyncio
async def test_matrix_send_failure():
    import httpx

    service = MatrixNotificationService(
        homeserver="https://matrix.example.com",
        access_token="syt_token",
        room_id="!room:example.com",
    )
    with patch.object(
        service.client,
        "put",
        new=AsyncMock(side_effect=httpx.ConnectError("boom")),
    ):
        ok = await service.send("Title", "Body")
        assert ok is False
    await service.close()
