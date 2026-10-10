"""
Integration tests for LiveLink ingestion routes.

Tests the WiCAN device telemetry ingestion endpoint.
Note: The /ingest endpoint uses token-based auth (not JWT), so these tests
verify the token validation flow.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.schemas.livelink_ingest import WiCANStatus
from app.services.livelink_service import LiveLinkService

BLANKABLE_STATUS_FIELDS = ["fw_version", "hw_version", "git_version", "sta_ip"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkIngest:
    """Test LiveLink ingestion endpoint."""

    # -------------------------------------------------------------------------
    # Disabled LiveLink tests
    # -------------------------------------------------------------------------

    async def test_ingest_returns_disabled_when_livelink_off(self, client: AsyncClient):
        """Test ingestion returns disabled status when LiveLink is disabled."""
        payload = {
            "autopid_data": {"ENGINE_RPM": 1500},
            "config": {},
            "status": {
                "device_id": "test_device_123",
                "hw_version": "1.0",
                "fw_version": "1.0.0",
            },
        }

        # Mock to pass auth but have LiveLink disabled
        with (
            patch(
                "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
            ) as mock_validate,
            patch("app.routes.livelink.LiveLinkService") as mock_service_class,
        ):
            mock_validate.return_value = True
            mock_service = MagicMock()
            mock_service.is_enabled = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "disabled"

    # -------------------------------------------------------------------------
    # Payload validation tests
    # -------------------------------------------------------------------------

    async def test_ingest_empty_payload_fails_validation(self, client: AsyncClient):
        """Test that empty payload fails validation."""
        response = await client.post(
            "/api/v1/livelink/ingest",
            json={},
            headers={"Authorization": "Bearer token"},
        )
        # Should fail Pydantic validation - autopid_data is required
        assert response.status_code == 422

    async def test_ingest_invalid_autopid_data_type(self, client: AsyncClient):
        """Test that invalid autopid_data type fails validation."""
        payload = {
            "autopid_data": "not_a_dict",  # Should be dict
            "config": {},
        }

        response = await client.post(
            "/api/v1/livelink/ingest",
            json=payload,
            headers={"Authorization": "Bearer token"},
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("ecu_status", [None, 1])
    async def test_ingest_refuses_an_ecu_status_that_isnt_text(
        self, client: AsyncClient, ecu_status: object
    ):
        """A guard: the ecu_status normaliser runs before the Literal and only
        touches text, so a null or a number is still a 422 and never a 500.

        Mutant: call `.strip()` on whatever arrives (an AttributeError escapes
        pydantic and 500s the ingest).
        """
        payload = {
            "autopid_data": {},
            "config": {},
            "status": {"device_id": "test12345678", "ecu_status": ecu_status},
        }

        response = await client.post(
            "/api/v1/livelink/ingest",
            json=payload,
            headers={"Authorization": "Bearer token"},
        )

        assert response.status_code == 422

    async def test_ingest_valid_minimal_payload(self, client: AsyncClient):
        """Test that minimal valid payload is accepted."""
        payload = {
            "autopid_data": {},  # Empty but valid dict
            "config": {},
            "status": {
                "device_id": "test12345678",
                "hw_version": "1.0",
                "fw_version": "1.0.0",
            },
        }

        # Mock auth and service
        with (
            patch(
                "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
            ) as mock_validate,
            patch("app.routes.livelink.LiveLinkService") as mock_service_class,
        ):
            mock_validate.return_value = True
            mock_service = MagicMock()
            mock_service.is_enabled = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 202

    async def test_ingest_with_telemetry_data(self, client: AsyncClient):
        """Test payload with telemetry data."""
        payload = {
            "autopid_data": {
                "ENGINE_RPM": 2500,
                "VEHICLE_SPEED": 65,
                "COOLANT_TEMP": 92,
            },
            "config": {
                "ENGINE_RPM": {"unit": "rpm", "class": "engine"},
                "VEHICLE_SPEED": {"unit": "km/h", "class": "speed"},
                "COOLANT_TEMP": {"unit": "C", "class": "temperature"},
            },
            "status": {
                "device_id": "test12345678",
                "hw_version": "2.0",
                "fw_version": "2.5.0",
                "sta_ip": "192.168.1.100",
                "rssi": -55,
                "battery_voltage": 12.8,
                "ecu_status": "online",
            },
        }

        with (
            patch(
                "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
            ) as mock_validate,
            patch("app.routes.livelink.LiveLinkService") as mock_service_class,
        ):
            mock_validate.return_value = True
            mock_service = MagicMock()
            mock_service.is_enabled = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 202


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.usefixtures("livelink_enabled")
@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("field", BLANKABLE_STATUS_FIELDS)
async def test_a_blank_status_field_creates_a_device_with_none(
    client: AsyncClient, db_session: AsyncSession, field: str, blank: str
) -> None:
    """A WiCAN that sends a blank version or IP didn't say, so the new device
    stores None. A stored '' firmware version sorted below every release."""
    device_id = "h4blankstatus"
    payload = {
        "autopid_data": {},
        "config": {},
        "status": {"device_id": device_id, field: blank},
    }
    try:
        with patch(
            "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
        ) as validate:
            validate.return_value = True
            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer t"},
            )

        assert response.status_code == 202
        assert "processing_error" not in response.json()
        db_session.expire_all()
        device = (
            await db_session.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one()
        assert getattr(device, field) is None
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        await db_session.commit()


@pytest.mark.parametrize("field", BLANKABLE_STATUS_FIELDS)
def test_the_blank_normaliser_leaves_anything_that_isnt_blank_text_alone(field: str) -> None:
    """A guard: like the ecu_status normaliser, the blank one only touches
    text. A real value is kept, a null stays None and a number is still a 422.

    Mutant: `return v.strip() or None` for whatever arrives (None and the
    number raise AttributeError, which pydantic doesn't turn into a 422).
    """
    assert getattr(WiCANStatus(device_id="aabbccddeeff", **{field: "4.45"}), field) == "4.45"
    assert getattr(WiCANStatus(device_id="aabbccddeeff", **{field: None}), field) is None
    with pytest.raises(ValidationError):
        WiCANStatus(device_id="aabbccddeeff", **{field: 4.45})


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.usefixtures("livelink_enabled")
async def test_a_tz_aware_ingest_timestamp_is_stored_as_utc(
    client: AsyncClient, db_session: AsyncSession, test_user: dict[str, object]
) -> None:
    """A device timestamp with an offset is stored as its UTC wall clock.

    SQLite used to drop the offset (12:00+02:00 stored as 12:00) and asyncpg
    refused the aware value, rolling the whole batch back with processing_error.
    """
    suffix = uuid.uuid4().hex[:10]
    vin = f"TZINGEST{suffix.upper()}"[:17]
    device_id = f"tzing{suffix}"
    # Telemetry-only payloads find their device by token. A per-device token
    # keeps that lookup off whatever other enabled devices the shared DB holds.
    token = f"tz-ingest-{suffix}"
    db_session.add(
        Vehicle(vin=vin, user_id=test_user["id"], nickname="TZ ingest", vehicle_type="Car")
    )
    await db_session.flush()
    db_session.add(
        LiveLinkDevice(
            device_id=device_id,
            vin=vin,
            enabled=True,
            device_token_hash=LiveLinkService.hash_token(token),
        )
    )
    # The ingest auto-registers the param in a table every test shares, so
    # only drop it afterwards if this test is the one that created it.
    param_created = (
        await db_session.execute(
            select(LiveLinkParameter.id).where(LiveLinkParameter.param_key == "ENGINE_RPM")
        )
    ).scalar_one_or_none() is None
    await db_session.commit()
    try:
        with patch("app.routes.livelink.validate_livelink_token", new_callable=AsyncMock):
            response = await client.post(
                "/api/v1/livelink/ingest",
                json={
                    "autopid_data": {"ENGINE_RPM": 800},
                    "timestamp": "2026-10-10T12:00:00+02:00",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 202
        assert response.json()["device_id"] == device_id
        assert "processing_error" not in response.json()
        db_session.expire_all()
        stored = (
            await db_session.execute(
                select(VehicleTelemetry.timestamp).where(
                    VehicleTelemetry.device_id == device_id,
                    VehicleTelemetry.param_key == "ENGINE_RPM",
                )
            )
        ).scalar_one()
        assert stored == datetime(2026, 10, 10, 10, 0)
    finally:
        await db_session.rollback()
        await db_session.execute(delete(VehicleTelemetry).where(VehicleTelemetry.vin == vin))
        await db_session.execute(
            delete(VehicleTelemetryLatest).where(VehicleTelemetryLatest.vin == vin)
        )
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        if param_created:
            await db_session.execute(
                delete(LiveLinkParameter).where(LiveLinkParameter.param_key == "ENGINE_RPM")
            )
        await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkTokenValidation:
    """Test LiveLink token validation logic."""

    async def test_validate_token_no_header(self):
        """Test validation fails without Authorization header."""
        from fastapi import HTTPException

        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(mock_db, None, "device_123")

        assert exc_info.value.status_code == 401
        assert "Missing Authorization header" in exc_info.value.detail

    async def test_validate_token_invalid_format(self):
        """Test validation fails with invalid header format."""
        from fastapi import HTTPException

        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(mock_db, "InvalidFormat", "device_123")

        assert exc_info.value.status_code == 401
        assert "Invalid Authorization header format" in exc_info.value.detail

    async def test_validate_token_invalid_token(self):
        """Test validation fails with invalid token."""
        from fastapi import HTTPException

        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.validate_device_token = AsyncMock(return_value=False)
            mock_service.validate_global_token = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            with pytest.raises(HTTPException) as exc_info:
                await validate_livelink_token(mock_db, "Bearer invalid_token", "device_123")

        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    async def test_validate_token_valid_device_token(self):
        """Test validation passes with valid device token."""
        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.validate_device_token = AsyncMock(return_value=True)
            mock_service_class.return_value = mock_service

            result = await validate_livelink_token(
                mock_db, "Bearer valid_device_token", "device_123"
            )

        assert result is True

    async def test_validate_token_valid_global_token(self):
        """Test validation passes with valid global token (when device token invalid)."""
        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.validate_device_token = AsyncMock(return_value=False)
            mock_service.validate_global_token = AsyncMock(return_value=True)
            mock_service_class.return_value = mock_service

            result = await validate_livelink_token(
                mock_db, "Bearer valid_global_token", "device_123"
            )

        assert result is True


@pytest.mark.parametrize(
    ("sent", "stored"),
    [("online", "online"), (" ON ", "online"), ("0", "offline"), ("melted", "unknown")],
)
def test_the_ecu_status_normaliser_feeds_the_literal(sent: str, stored: str):
    """A guard: the normaliser maps every word a device sends onto the
    vocabulary before the Literal sees it, so no WiCAN status is a 422.

    Mutant: make it an after-validator again (the Literal refuses " ON ").
    """
    assert WiCANStatus(device_id="aabbccddeeff", ecu_status=sent).ecu_status == stored
