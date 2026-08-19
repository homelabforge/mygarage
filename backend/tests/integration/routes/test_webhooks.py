"""Integration tests for inbound webhook fuel / odometer / Telegram ingest."""

from datetime import date
from io import BytesIO

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.fuel import FuelRecord
from app.models.settings import Setting
from app.models.vehicle import Vehicle

# The app's complete reminder vocabulary. routes/reminders.py filters on these
# and the UI renders exactly these three tabs, so any other value makes a
# reminder invisible and unrecoverable.
VALID_REMINDER_STATUSES = {"pending", "done", "dismissed"}


async def _set_setting(db_session, key: str, value: str) -> None:
    result = await db_session.execute(select(Setting).where(Setting.key == key))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = value
    else:
        db_session.add(Setting(key=key, value=value))
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _reset_webhook_settings(db_session):
    """Clear the global webhook settings this module writes.

    The suite shares one database with no per-test rollback, so leaving these
    set changes the behaviour of every test that runs afterwards. Cleared before
    as well as after, so a prior failure cannot leak into the next test either.
    """

    async def _clear():
        for key in ("webhook_ingest_token", "telegram_inbound_enabled", "telegram_chat_id"):
            result = await db_session.execute(select(Setting).where(Setting.key == key))
            setting = result.scalar_one_or_none()
            if setting is not None:
                setting.value = ""
        await db_session.commit()

    await _clear()
    yield
    await _clear()


@pytest.mark.integration
@pytest.mark.asyncio
class TestWebhookIngest:
    """Token-authenticated webhook endpoints."""

    async def test_fuel_requires_configured_token(self, client: AsyncClient, test_vehicle):
        response = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": test_vehicle["vin"],
                "odometer_km": "45000",
                "liters": "40",
                "cost": "60",
            },
            headers={"X-Webhook-Token": "anything"},
        )
        assert response.status_code == 503

    async def test_fuel_rejects_bad_token(self, client: AsyncClient, test_vehicle, db_session):
        await _set_setting(db_session, "webhook_ingest_token", "correct-token")
        response = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": test_vehicle["vin"],
                "odometer_km": "45000",
                "liters": "40",
            },
            headers={"X-Webhook-Token": "wrong-token"},
        )
        assert response.status_code == 401

    async def test_create_fuel_and_charge_via_webhook(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        vin = test_vehicle["vin"]

        ice = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": vin,
                "date": "2026-04-01",
                "odometer_km": "45000",
                "liters": "40.5",
                "price_per_unit": "1.55",
                "cost": "62.78",
                "notes": "webhook fill",
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert ice.status_code == 200
        assert ice.json()["vin"] == vin

        ev = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": vin,
                "date": "2026-04-02",
                "odometer_km": "45200",
                "kwh": "42.5",
                "price_per_unit": "0.20",
                "cost": "8.50",
                "soc_start_pct": "18",
                "soc_end_pct": "80",
                "charge_level": "L2",
                "charge_location": "home",
                "battery_soh_pct": "94",
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert ev.status_code == 200

        result = await db_session.execute(
            select(FuelRecord).where(
                FuelRecord.vin == vin,
                FuelRecord.date == date(2026, 4, 2),
            )
        )
        record = result.scalar_one()
        assert float(record.kwh) == pytest.approx(42.5)
        assert float(record.soc_start_pct) == pytest.approx(18)
        assert record.charge_level == "L2"
        assert record.charge_location == "home"
        assert record.price_basis == "per_kwh"
        assert record.fuel_type_used == "electric"

    async def test_odometer_webhook(self, client: AsyncClient, test_vehicle, db_session):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        response = await client.post(
            "/api/v1/webhooks/odometer",
            json={
                "vin": test_vehicle["vin"],
                "odometer_km": "46000",
                "notes": "via webhook",
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        assert float(response.json()["odometer_km"]) == pytest.approx(46000)

    async def test_complete_reminder_webhook(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        vin = test_vehicle["vin"]
        created = await client.post(
            f"/api/vehicles/{vin}/reminders",
            headers=auth_headers,
            json={
                "title": "Oil change",
                "reminder_type": "mileage",
                "due_mileage_km": 50000,
            },
        )
        assert created.status_code == 201
        reminder_id = created.json()["id"]

        response = await client.post(
            "/api/v1/webhooks/reminders/complete",
            json={"vin": vin, "reminder_id": reminder_id},
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        assert response.json()["status"] in VALID_REMINDER_STATUSES
        assert response.json()["status"] == "done"

    async def test_webhook_fuel_syncs_odometer(self, client: AsyncClient, test_vehicle, db_session):
        """A webhook fill-up must reach the odometer log like a UI fill-up does.

        Without it the Odometer tab and every mileage-based reminder never see
        the reading, so "due in X km" stays stale forever.
        """
        from app.models.odometer import OdometerRecord

        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        vin = test_vehicle["vin"]
        # An explicit unused date: sync_odometer_from_record matches on
        # (vin, date) and refuses to overwrite a manual record, so colliding
        # with another test's date would fail this for the wrong reason.
        response = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": vin,
                "date": "2026-09-14",
                "odometer_km": "77321",
                "liters": "40",
                "cost": "60",
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        fuel_id = response.json()["id"]

        # The model's columns are `source` and `fuel_record_id`; source_type and
        # source_id are parameter names on sync_odometer_from_record, not columns.
        result = await db_session.execute(
            select(OdometerRecord).where(
                OdometerRecord.vin == vin,
                OdometerRecord.source == "fuel",
                OdometerRecord.fuel_record_id == fuel_id,
            )
        )
        assert result.scalar_one_or_none() is not None, "webhook fill-up did not sync odometer"

    async def test_fuel_sync_survives_two_odometer_rows_on_one_date(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        """Two readings on one date are legitimate; syncing must not 500.

        idx_odometer_vin_date is not unique, so a manual entry plus a device
        reading (or two webhook posts) can share a date. sync_odometer_from_record
        used scalar_one_or_none(), which raised MultipleResultsFound and surfaced
        as a 500 on any fuel record for that date.
        """
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        vin = test_vehicle["vin"]
        headers = {"X-Webhook-Token": "secret-webhook"}

        for km in ("61000", "61050"):
            resp = await client.post(
                "/api/v1/webhooks/odometer",
                json={"vin": vin, "date": "2026-10-02", "odometer_km": km},
                headers=headers,
            )
            assert resp.status_code == 200

        response = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": vin,
                "date": "2026-10-02",
                "odometer_km": "61100",
                "liters": "35",
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

    async def test_telegram_reply_uses_send_message_method(self, client: AsyncClient, db_session):
        """Telegram only acts on a body containing a 'method' key."""
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        await _set_setting(db_session, "telegram_inbound_enabled", "true")
        response = await client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": 1, "message": {"text": "help", "chat": {"id": 42}}},
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "sendMessage"
        assert body["chat_id"] == 42
        assert "MyGarage" in body["text"]

    async def test_telegram_bad_syntax_returns_200(self, client: AsyncClient, db_session):
        """A 4xx makes Telegram redeliver the same update with backoff forever."""
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        await _set_setting(db_session, "telegram_inbound_enabled", "true")
        response = await client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": 2, "message": {"text": "fuel wat", "chat": {"id": 42}}},
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "sendMessage"
        assert "Could not log that" in body["text"]

    async def test_telegram_out_of_range_value_returns_200(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        """Pydantic ValidationError is not HTTPException; it must also be caught."""
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        await _set_setting(db_session, "telegram_inbound_enabled", "true")
        vin = test_vehicle["vin"]
        before = await db_session.scalar(
            select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
        )
        response = await client.post(
            "/api/v1/webhooks/telegram",
            json={
                "update_id": 3,
                "message": {"text": f"fuel {vin} 999999999999 40", "chat": {"id": 42}},
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "sendMessage"
        assert "Could not log that" in body["text"]

        after = await db_session.scalar(
            select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
        )
        assert after == before, "a rejected command must not create a fuel record"

    async def test_query_param_token_is_rejected(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        """?token= leaks the shared secret into granian, Traefik and CF logs."""
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        response = await client.post(
            "/api/v1/webhooks/odometer?token=secret-webhook",
            json={"vin": test_vehicle["vin"], "odometer_km": "45000"},
        )
        assert response.status_code == 401

    async def test_header_token_still_works(self, client: AsyncClient, test_vehicle, db_session):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        response = await client.post(
            "/api/v1/webhooks/odometer",
            json={"vin": test_vehicle["vin"], "odometer_km": "45123"},
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200

    async def test_webhook_is_rate_limited(self, client: AsyncClient, test_vehicle, db_session):
        """A shared secret with no lockout must not be guessable at full rate.

        The token check runs in the endpoint body rather than as a dependency
        precisely so slowapi's wrapper sees the request first.
        """
        from app.routes.webhooks import limiter

        limiter.reset()
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        saw_429 = False
        for _ in range(70):
            response = await client.post(
                "/api/v1/webhooks/odometer",
                json={"vin": test_vehicle["vin"], "odometer_km": "45000"},
                headers={"X-Webhook-Token": "wrong-token"},
            )
            if response.status_code == 429:
                saw_429 = True
                break
        limiter.reset()
        assert saw_429, "webhook routes accepted 70 token guesses without rate limiting"

    async def test_telegram_disabled_by_default(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        response = await client.post(
            "/api/v1/webhooks/telegram",
            json={
                "update_id": 1,
                "message": {
                    "text": f"fuel {test_vehicle['vin']} 10000 40",
                    "chat": {"id": 123},
                },
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 403

    async def test_telegram_fuel_command_by_nickname(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        await _set_setting(db_session, "telegram_inbound_enabled", "true")
        await _set_setting(db_session, "telegram_chat_id", "999")

        vehicle = await db_session.get(Vehicle, test_vehicle["vin"])
        vehicle.nickname = "Model3Demo"
        await db_session.commit()

        response = await client.post(
            "/api/v1/webhooks/telegram",
            json={
                "update_id": 2,
                "message": {
                    "text": "fuel Model3Demo 10000mi 12gal 3.50 42.00",
                    "chat": {"id": 999},
                },
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "sendMessage"
        assert "Logged fill-up" in body["text"]
        assert test_vehicle["vin"] in body["text"]

        result = await db_session.execute(
            select(FuelRecord).where(
                FuelRecord.vin == test_vehicle["vin"],
                FuelRecord.notes == "via telegram",
            )
        )
        record = result.scalar_one()
        assert record.liters is not None
        assert float(record.liters) == pytest.approx(45.425, abs=0.01)

    async def test_telegram_help(self, client: AsyncClient, db_session):
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")
        await _set_setting(db_session, "telegram_inbound_enabled", "true")
        await _set_setting(db_session, "telegram_chat_id", "")
        response = await client.post(
            "/api/v1/webhooks/telegram",
            json={"update_id": 3, "message": {"text": "/help", "chat": {"id": 1}}},
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["method"] == "sendMessage"
        assert "fuel <vin|nickname>" in body["text"]

    async def test_ambiguous_nickname_returns_409(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        """Multiple vehicles with same nickname should return 409 Conflict."""
        await _set_setting(db_session, "webhook_ingest_token", "secret-webhook")

        vehicle1 = await db_session.get(Vehicle, test_vehicle["vin"])
        vehicle1.nickname = "SharedName"
        db_session.add(Vehicle(vin="5YJ3E1EAXKF000002", nickname="SharedName", vehicle_type="Car"))
        await db_session.commit()

        response = await client.post(
            "/api/v1/webhooks/fuel",
            json={
                "vin": "SharedName",
                "odometer_km": "10000",
                "liters": "40",
            },
            headers={"X-Webhook-Token": "secret-webhook"},
        )
        assert response.status_code == 409
        assert "Ambiguous nickname" in response.json()["detail"]
        assert "use VIN instead" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestEvFuelAndThirdPartyImport:
    """EV charge-session create + Fuelio/Tesla CSV import endpoints."""

    @pytest.fixture(autouse=True)
    def _reset_import_rate_limit(self):
        from app.routes.import_data import limiter as import_limiter

        storage = import_limiter._storage
        storage.storage.clear()
        storage.expirations.clear()
        if hasattr(storage, "events"):
            storage.events.clear()

    async def test_create_ev_charge_session(self, client: AsyncClient, auth_headers, test_vehicle):
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel",
            headers=auth_headers,
            json={
                "vin": test_vehicle["vin"],
                "date": "2026-05-01",
                "odometer_km": 25000,
                "kwh": 42.5,
                "price_basis": "per_kwh",
                "price_per_unit": 0.2,
                "cost": 8.5,
                "soc_start_pct": 18,
                "soc_end_pct": 80,
                "charge_level": "L2",
                "charge_location": "home",
                "battery_soh_pct": 94,
                "fuel_type_used": "electric",
                "is_full_tank": False,
                "notes": "Overnight home charge",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert float(data["kwh"]) == pytest.approx(42.5)
        assert float(data["soc_start_pct"]) == pytest.approx(18)
        assert float(data["soc_end_pct"]) == pytest.approx(80)
        assert data["charge_level"] == "L2"
        assert data["charge_location"] == "home"
        assert float(data["battery_soh_pct"]) == pytest.approx(94)

    async def test_import_fuelio_csv(self, client: AsyncClient, auth_headers, test_vehicle):
        csv_content = (
            "Date,Odometer,Fuel Type,Volume(l),Price,Total cost,Full tank,Notes\n"
            "2026-01-15,12345.0,Gasoline,40.5,1.499,60.71,1,Shell\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/fuel/fuelio",
            headers=auth_headers,
            files={"file": ("fuelio.csv", BytesIO(csv_content.encode()), "text/csv")},
            data={"skip_duplicates": "true"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["success_count"] == 1
        assert response.json()["error_count"] == 0

    async def test_import_tesla_csv(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        csv_content = (
            "Charge End Date,Energy Added (kWh),Odometer,Cost,Starting SOC,Ending SOC,"
            "Charge Type,Location\n"
            "2026-03-01,42.5,15000,8.50,20,80,L2,Home\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/fuel/tesla",
            headers=auth_headers,
            files={"file": ("tesla.csv", BytesIO(csv_content.encode()), "text/csv")},
            data={"skip_duplicates": "true"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["success_count"] == 1

        result = await db_session.execute(
            select(FuelRecord).where(
                FuelRecord.vin == test_vehicle["vin"],
                FuelRecord.date == date(2026, 3, 1),
            )
        )
        record = result.scalar_one()
        assert float(record.kwh) == pytest.approx(42.5)
        assert float(record.soc_start_pct) == pytest.approx(20)
        assert record.charge_level == "L2"
        assert record.charge_location == "home"

    async def test_import_external_auto_detect(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        csv_content = (
            "Date,Odometer (km),Quantity (liters),Price/liter,Total cost,Full tank,Notes\n"
            "15/01/2026,20000,35.2,1.55,54.56,yes,BP\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/fuel/external",
            headers=auth_headers,
            files={"file": ("drivvo.csv", BytesIO(csv_content.encode()), "text/csv")},
            data={"skip_duplicates": "true"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["success_count"] == 1


@pytest.mark.integration
class TestWebhookCsrfExemption:
    """Webhook routes are token-authenticated and carry no browser session.

    CSRF middleware is disabled under MYGARAGE_TEST_MODE, so no request-level
    test can observe this. On a deployment with auth_mode local or oidc, a
    non-exempt POST is rejected before the handler runs, so every inbound
    webhook would 403.
    """

    def test_webhook_routes_match_an_exempt_prefix(self):
        from app.middleware import CSRFProtectionMiddleware
        from app.routes.webhooks import router

        for route in router.routes:
            assert any(route.path.startswith(p) for p in CSRFProtectionMiddleware.EXEMPT_PATHS), (
                f"{route.path} is not covered by any CSRF exempt prefix"
            )
