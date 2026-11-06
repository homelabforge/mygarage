"""The provider routes (#219 takeover): which decoders exist, Automatic vs a chosen one, the key test."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.autoref import (
    AutoRefAuthError,
    AutoRefQuotaError,
    AutoRefUnavailableError,
    AutoRefUsage,
)
from app.utils.settings_crypto import encrypt
from tests.integration._secret_helpers import Keep, seed_rows, unreadable_ciphertext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KEY = "autoref-test-key-0001"
EU_VIN = "VF1RFB00X56123456"
NA_VIN = "1HGCM82633A004352"
NHTSA_EU = {"vin": EU_VIN, "make": "RENAULT", "manufacturer": "RENAULT S.A."}
AUTOREF_EU: dict[str, Any] = {
    "vin": EU_VIN,
    "year": None,
    "make": "Renault",
    "model": "Clio",
    "notes": [],
}


async def _autoref_on(
    db: AsyncSession, keep: Keep, key: str | None = KEY, enabled: str = "true"
) -> None:
    rows = {"autoref_enabled": enabled}
    rows["autoref_api_key"] = encrypt("autoref_api_key", key) if key else ""
    await seed_rows(db, keep, rows)


def _nhtsa_mock(cls: MagicMock, answer: dict[str, Any]) -> AsyncMock:
    cls.return_value.decode_vin = AsyncMock(return_value=dict(answer))
    return cls.return_value.decode_vin


def _autoref_mock(cls: MagicMock, answer: Any = None, error: Exception | None = None) -> AsyncMock:
    if error is not None:
        cls.return_value.decode = AsyncMock(side_effect=error)
    else:
        cls.return_value.decode = AsyncMock(return_value=answer)
    return cls.return_value.decode


class TestProviders:
    async def test_without_a_key_only_nhtsa(
        self, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows, key=None)
        response = await client.get("/api/vin/providers?country=FR", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"available": ["nhtsa"], "preferred": "nhtsa"}

    async def test_a_key_while_switched_off_is_not_available(
        self, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows, enabled="false")
        response = await client.get("/api/vin/providers?country=FR", headers=auth_headers)
        assert response.json()["available"] == ["nhtsa"]

    @pytest.mark.parametrize(
        ("country", "preferred"), [("FR", "autoref"), ("de", "autoref"), ("US", "nhtsa")]
    )
    async def test_country_orders_them(
        self, client: AsyncClient, auth_headers, db_session, keep_rows, country, preferred
    ):
        await _autoref_on(db_session, keep_rows)
        response = await client.get(f"/api/vin/providers?country={country}", headers=auth_headers)
        assert response.json() == {"available": ["nhtsa", "autoref"], "preferred": preferred}

    async def test_the_users_country_is_used_without_one(
        self, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        await client.put("/api/auth/me", json={"country": "FR"}, headers=auth_headers)
        try:
            response = await client.get("/api/vin/providers", headers=auth_headers)
            assert response.json()["preferred"] == "autoref"
        finally:
            await client.put("/api/auth/me", json={"country": None}, headers=auth_headers)

    async def test_an_unknown_country_is_422(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/vin/providers?country=XX", headers=auth_headers)
        assert response.status_code == 422

    async def test_an_unreadable_key_is_not_available(
        self, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await seed_rows(
            db_session,
            keep_rows,
            {
                "autoref_enabled": "true",
                "autoref_api_key": unreadable_ciphertext("autoref_api_key"),
            },
        )
        response = await client.get("/api/vin/providers?country=FR", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["available"] == ["nhtsa"]

    async def test_a_cleared_key_takes_effect_on_the_next_request(
        self, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        first = await client.get("/api/vin/providers?country=FR", headers=auth_headers)
        assert first.json()["available"] == ["nhtsa", "autoref"]
        await seed_rows(db_session, keep_rows, {"autoref_api_key": ""})
        second = await client.get("/api/vin/providers?country=FR", headers=auth_headers)
        assert second.json()["available"] == ["nhtsa"]


@patch("app.routes.vin.AutoRefService")
@patch("app.routes.vin.NHTSAService")
class TestDecode:
    async def test_automatic_in_europe_asks_autoref(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        nhtsa = _nhtsa_mock(nhtsa_cls, NHTSA_EU)
        autoref = _autoref_mock(autoref_cls, dict(AUTOREF_EU))
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "country": "FR"}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decoded_by"] == "autoref"
        assert body["model"] == "Clio"
        autoref.assert_awaited_once()
        nhtsa.assert_not_awaited()
        autoref_cls.assert_called_once_with(KEY)

    async def test_automatic_falls_back_on_an_error(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        _nhtsa_mock(nhtsa_cls, NHTSA_EU)
        _autoref_mock(autoref_cls, error=AutoRefUnavailableError(502))
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "country": "FR"}, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["decoded_by"] == "nhtsa"
        assert "autoref_unavailable" in response.json()["notes"]

    async def test_automatic_sends_a_north_american_vin_to_nhtsa_only(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        _nhtsa_mock(
            nhtsa_cls, {"vin": NA_VIN, "make": "HONDA", "model": "Accord", "error_code": "0"}
        )
        autoref = _autoref_mock(autoref_cls, dict(AUTOREF_EU))
        response = await client.post(
            "/api/vin/decode", json={"vin": NA_VIN, "country": "FR"}, headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["make"] == "Honda"
        autoref.assert_not_awaited()

    async def test_automatic_without_a_key_is_nhtsa(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows, key=None)
        _nhtsa_mock(nhtsa_cls, NHTSA_EU)
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "country": "FR"}, headers=auth_headers
        )
        assert response.json()["decoded_by"] == "nhtsa"
        autoref_cls.assert_not_called()

    async def test_explicit_nhtsa_in_europe_skips_autoref(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        _nhtsa_mock(nhtsa_cls, NHTSA_EU)
        autoref = _autoref_mock(autoref_cls, dict(AUTOREF_EU))
        response = await client.post(
            "/api/vin/decode",
            json={"vin": EU_VIN, "country": "FR", "provider": "nhtsa"},
            headers=auth_headers,
        )
        assert response.json()["decoded_by"] == "nhtsa"
        autoref.assert_not_awaited()

    async def test_explicit_autoref_without_a_key_is_409(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows, key=None)
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "provider": "autoref"}, headers=auth_headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "AutoRef is not configured"

    async def test_explicit_autoref_with_no_match_is_404(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows)
        nhtsa = _nhtsa_mock(nhtsa_cls, NHTSA_EU)
        _autoref_mock(autoref_cls, None)
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "provider": "autoref"}, headers=auth_headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "AutoRef has no record for this VIN"
        nhtsa.assert_not_awaited()

    @pytest.mark.parametrize(
        ("error", "status", "detail"),
        [
            (AutoRefAuthError(403), 502, "AutoRef rejected the API key"),
            (AutoRefQuotaError(), 429, "AutoRef quota used up"),
            (AutoRefUnavailableError(500), 502, "AutoRef error"),
            (AutoRefUnavailableError(timed_out=True), 504, "AutoRef request timed out"),
            (AutoRefUnavailableError(), 503, "Cannot connect to AutoRef"),
        ],
    )
    async def test_explicit_autoref_errors_map_to_statuses(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows,
        error, status, detail,
    ):  # fmt: skip
        await _autoref_on(db_session, keep_rows)
        _autoref_mock(autoref_cls, error=error)
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "provider": "autoref"}, headers=auth_headers
        )
        assert response.status_code == status
        assert response.json()["detail"] == detail

    async def test_an_unknown_country_is_422(
        self, nhtsa_cls, autoref_cls, client: AsyncClient, auth_headers
    ):
        response = await client.post(
            "/api/vin/decode", json={"vin": EU_VIN, "country": "XX"}, headers=auth_headers
        )
        assert response.status_code == 422


@patch("app.routes.vin.AutoRefService")
class TestKeyTest:
    URL = "/api/vin/autoref/test"

    async def test_non_admins_are_refused(
        self, autoref_cls, client: AsyncClient, non_admin_headers
    ):
        response = await client.post(self.URL, json={"api_key": "x"}, headers=non_admin_headers)
        assert response.status_code in (401, 403)
        autoref_cls.assert_not_called()

    async def test_a_typed_key_is_tested(self, autoref_cls, client: AsyncClient, auth_headers):
        autoref_cls.return_value.usage = AsyncMock(
            return_value=AutoRefUsage(plan="Test", limit=50, used=2, remaining=48, reset_date=None)
        )
        response = await client.post(self.URL, json={"api_key": "typed-key"}, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "valid": True,
            "message": "AutoRef API key is valid",
            "plan": "Test",
            "remaining": 48,
            "limit": 50,
        }
        autoref_cls.assert_called_once_with("typed-key")

    @pytest.mark.parametrize("sent", [None, "********"])
    async def test_no_key_or_the_mask_tests_the_stored_one(
        self, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows, sent
    ):
        await _autoref_on(db_session, keep_rows)
        autoref_cls.return_value.usage = AsyncMock(
            return_value=AutoRefUsage(plan="Test", limit=50, used=0, remaining=50, reset_date=None)
        )
        response = await client.post(self.URL, json={"api_key": sent}, headers=auth_headers)
        assert response.json()["valid"] is True
        autoref_cls.assert_called_once_with(KEY)

    async def test_nothing_stored_is_not_valid(
        self, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await _autoref_on(db_session, keep_rows, key=None)
        response = await client.post(self.URL, json={"api_key": None}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["valid"] is False
        autoref_cls.assert_not_called()

    async def test_an_unreadable_stored_key_asks_to_re_enter(
        self, autoref_cls, client: AsyncClient, auth_headers, db_session, keep_rows
    ):
        await seed_rows(
            db_session,
            keep_rows,
            {
                "autoref_enabled": "true",
                "autoref_api_key": unreadable_ciphertext("autoref_api_key"),
            },
        )
        response = await client.post(self.URL, json={"api_key": None}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["valid"] is False
        assert "re-enter" in response.json()["message"]
        autoref_cls.assert_not_called()

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (AutoRefAuthError(403), "AutoRef rejected the API key"),
            (AutoRefUnavailableError(503), "AutoRef is not reachable"),
            (AutoRefUnavailableError(timed_out=True), "AutoRef is not reachable"),
        ],
    )
    async def test_failures_are_a_200_with_valid_false(
        self, autoref_cls, client: AsyncClient, auth_headers, caplog, error, message
    ):
        caplog.set_level(logging.DEBUG)
        autoref_cls.return_value.usage = AsyncMock(side_effect=error)
        response = await client.post(
            self.URL, json={"api_key": "typed-key-9"}, headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False
        assert response.json()["message"] == message
        assert all("typed-key-9" not in r.getMessage() for r in caplog.records)
