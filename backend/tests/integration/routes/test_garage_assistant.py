"""Integration tests for Ask My Garage assistant."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

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
class TestGarageAssistant:
    async def test_disabled_returns_403(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(db_session, {"llm_garage_assistant_enabled": "false"})
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/assistant/chat",
            json={"message": "What oil does this use?"},
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()

    async def test_mocked_llm_returns_answer_and_citations(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await set_settings(
            db_session,
            {
                "llm_garage_assistant_enabled": "true",
                "llm_base_url": "http://127.0.0.1:11434/v1",
                "llm_model": "llama3.2",
            },
        )

        # Seed oil viscosity so context packer includes it
        from app.models.vehicle import Vehicle

        vehicle = await db_session.get(Vehicle, test_vehicle["vin"])
        assert vehicle is not None
        vehicle.oil_viscosity = "5W-30"
        vehicle.lug_nut_torque_nm = 135
        await db_session.commit()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"answer":"This vehicle uses 5W-30. Lug torque is 135 Nm.",'
                                '"citations":[{"source":"vehicle_spec","label":"Oil viscosity",'
                                '"detail":"5W-30"},{"source":"vehicle_spec","label":"Lug nut torque",'
                                '"detail":"135 Nm"}],'
                                '"missing":[]}'
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
                f"/api/vehicles/{test_vehicle['vin']}/assistant/chat",
                json={"message": "What oil and lug torque?"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert "5W-30" in body["answer"]
        assert len(body["citations"]) >= 1
        assert body["citations"][0]["source"] == "vehicle_spec"

    async def test_llm_payload_carries_the_callers_units_only(
        self, client: AsyncClient, auth_headers, test_user, test_vehicle, db_session
    ):
        """#237, end to end: an imperial caller's specs reach the model in lb-ft and
        quarts, and the canonical Nm/liter figures it quoted back never leave."""
        from decimal import Decimal

        from app.models.user import User
        from app.models.vehicle import Vehicle

        await set_settings(
            db_session,
            {
                "llm_garage_assistant_enabled": "true",
                "llm_base_url": "http://127.0.0.1:11434/v1",
                "llm_model": "llama3.2",
            },
        )
        user = await db_session.get(User, test_user["id"])
        assert user is not None
        previous = (user.unit_preference, user.show_both_units)
        user.unit_preference = "imperial"
        user.show_both_units = False
        vehicle = await db_session.get(Vehicle, test_vehicle["vin"])
        assert vehicle is not None
        # The reporter's numbers: 100 lb-ft and 5 US qt, stored canonical.
        vehicle.lug_nut_torque_nm = Decimal("135.6")
        vehicle.oil_capacity_liters = Decimal("4.73")
        await db_session.commit()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={"choices": [{"message": {"content": '{"answer":"ok"}'}}]}
        )

        try:
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(return_value=mock_response)
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=None)
                mock_client.return_value = mock_instance

                response = await client.post(
                    f"/api/vehicles/{test_vehicle['vin']}/assistant/chat",
                    json={"message": "What is the lug nut torque?"},
                    headers=auth_headers,
                )
        finally:
            user.unit_preference, user.show_both_units = previous
            await db_session.commit()

        assert response.status_code == 200
        messages = mock_instance.post.call_args.kwargs["json"]["messages"]
        sent = next(m["content"] for m in messages if m["role"] == "user")
        assert "100.0 lb-ft" in sent
        assert "gal" in sent
        assert "135.6" not in sent
        assert "4.73" not in sent
