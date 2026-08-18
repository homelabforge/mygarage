"""Integration tests for opt-in LLM fuel receipt parse."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.fuel import FuelRecord
from app.models.settings import Setting


async def set_settings(db_session, settings_dict: dict[str, str]) -> None:
    for key, value in settings_dict.items():
        result = await db_session.execute(select(Setting).where(Setting.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db_session.add(Setting(key=key, value=value))
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestReceiptParse:
    async def test_disabled_returns_403(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "false"})
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
            data={"text": "Shell 12.4 gal $45.50"},
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()

    async def test_mocked_llm_returns_draft_keys(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(
            db_session,
            {
                "llm_receipt_parse_enabled": "true",
                "llm_base_url": "http://127.0.0.1:11434/v1",
                "llm_model": "llama3.2",
            },
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"date":"2026-08-01","liters":45.4,"cost":52.10,'
                                '"price_per_unit":1.147,"odometer_km":12345.0,'
                                '"station_name":"Shell","fuel_type_used":"Regular",'
                                '"kwh":null,"notes":null}'
                            )
                        }
                    }
                ]
            }
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                data={"text": "Shell station receipt"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "llm"
        draft = body["draft"]
        for key in (
            "date",
            "liters",
            "cost",
            "price_per_unit",
            "odometer_km",
            "station_name",
            "fuel_type_used",
            "notes",
            "kwh",
        ):
            assert key in draft
        assert draft["station_name"] == "Shell"
        assert draft["liters"] == 45.4

        count = await db_session.execute(
            select(func.count())
            .select_from(FuelRecord)
            .where(
                FuelRecord.vin == test_vehicle["vin"],
                FuelRecord.notes == "Shell station receipt",
            )
        )
        assert count.scalar_one() == 0

    async def test_oversized_file_returns_413(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        with patch("app.routes.fuel.MAX_RECEIPT_UPLOAD_BYTES", 16):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                files={"file": ("receipt.jpg", b"x" * 64, "image/jpeg")},
                headers=auth_headers,
            )
        assert response.status_code == 413
        assert (
            "too large" in response.json()["detail"].lower()
            or "exceeds" in response.json()["detail"].lower()
        )

    async def test_oversized_text_returns_413(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_receipt_parse_enabled": "true"})
        with patch("app.routes.fuel.MAX_RECEIPT_TEXT_CHARS", 8):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/fuel/parse-receipt",
                data={"text": "this is longer than eight"},
                headers=auth_headers,
            )
        assert response.status_code == 413
