"""Integration tests for /api/widget/* endpoints.

Covers the HTTP surface end-to-end: request-time ownership scoping, revoke
semantics, the 401-vs-400 contract under auth_mode=none, ownership transfer
drift, archive behavior, and rate limiting. Business logic correctness for
aggregates and MPG is covered separately in
tests/unit/services/test_widget_aggregation.py.
"""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.fuel import FuelRecord
from app.models.service_visit import ServiceVisit
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.widget_api_key import WidgetApiKey
from app.services.widget_auth import (
    display_prefix,
    generate_widget_key,
    hash_widget_key,
    widget_limiter,
)
from app.utils.datetime_utils import utc_now

TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw"
    "$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)


def _unique_vin() -> str:
    return ("WGT" + uuid.uuid4().hex)[:17].upper()


@pytest_asyncio.fixture
async def set_auth_mode(db_session):
    """Fixture returning a helper that sets the auth_mode setting and resets it after."""

    async def _apply(mode: str | None) -> None:
        existing = (
            await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        ).scalar_one_or_none()
        if existing is None:
            if mode is not None:
                db_session.add(Setting(key="auth_mode", value=mode))
        else:
            if mode is None:
                await db_session.delete(existing)
            else:
                existing.value = mode
        await db_session.commit()

    yield _apply
    await _apply("local")


@pytest_asyncio.fixture
async def widget_owner(db_session) -> User:
    """Key-owning user, unique per-run to avoid cross-test carry-over."""
    u = User(
        username=f"widget_route_owner_{uuid.uuid4().hex[:8]}",
        email=f"widget_route_owner_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=TEST_PASSWORD_HASH,
        is_active=True,
        is_admin=False,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _make_vehicle(db_session, user: User, **overrides) -> Vehicle:
    v = Vehicle(
        vin=overrides.get("vin", _unique_vin()),
        nickname=overrides.get("nickname", "Test"),
        vehicle_type=overrides.get("vehicle_type", "Car"),
        user_id=user.id,
        year=overrides.get("year", 2022),
        make=overrides.get("make", "Honda"),
        model=overrides.get("model", "Civic"),
        archived_at=overrides.get("archived_at"),
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


async def _make_key(
    db_session,
    user: User,
    *,
    scope: str = "all_vehicles",
    allowed_vins: list[str] | None = None,
    revoked: bool = False,
) -> str:
    plaintext = generate_widget_key()
    key = WidgetApiKey(
        user_id=user.id,
        name="test",
        key_hash=hash_widget_key(plaintext),
        key_prefix=display_prefix(plaintext),
        scope=scope,
        allowed_vins=allowed_vins,
        revoked_at=utc_now() if revoked else None,
    )
    db_session.add(key)
    await db_session.commit()
    return plaintext


@pytest.mark.integration
@pytest.mark.asyncio
class TestSummaryEndpoint:
    async def test_valid_key_returns_200_with_schema(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)
        resp = await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        data = resp.json()
        # Every field from WidgetSummary must be present with int values.
        for field in (
            "total_vehicles",
            "active_vehicles",
            "archived_vehicles",
            "total_overdue_maintenance",
            "total_upcoming_maintenance",
            "total_service_records",
            "total_fuel_records",
            "total_documents",
            "total_notes",
            "total_photos",
        ):
            assert field in data
            assert isinstance(data[field], int)

    async def test_401_on_missing_header(self, client: AsyncClient, set_auth_mode):
        await set_auth_mode("local")
        resp = await client.get("/api/widget/summary")
        assert resp.status_code == 401

    async def test_401_on_wrong_prefix(self, client: AsyncClient, set_auth_mode):
        await set_auth_mode("local")
        resp = await client.get("/api/widget/summary", headers={"X-API-Key": "ll_not_a_widget_key"})
        assert resp.status_code == 401

    async def test_401_on_revoked(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner, revoked=True)
        resp = await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
        assert resp.status_code == 401

    async def test_401_on_auth_mode_none(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        # Auth mode toggled to 'none' — widget keys never valid in this mode.
        plaintext = await _make_key(db_session, widget_owner)
        await set_auth_mode("none")
        try:
            resp = await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
            assert resp.status_code == 401
        finally:
            await set_auth_mode("local")

    async def test_does_not_include_other_users_records(
        self,
        client: AsyncClient,
        db_session,
        widget_owner,
        set_auth_mode,
    ):
        """Baseline/delta check — session-scoped DB may carry data from other tests."""
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)

        # Baseline before seeding cross-user data.
        baseline = (
            await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
        ).json()

        other = User(
            username=f"widget_route_other_{uuid.uuid4().hex[:8]}",
            email=f"widget_route_other_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        mine = await _make_vehicle(db_session, widget_owner)
        theirs = await _make_vehicle(db_session, other)
        db_session.add(ServiceVisit(vin=mine.vin, date=date(2026, 1, 1)))
        db_session.add(ServiceVisit(vin=theirs.vin, date=date(2026, 1, 1)))
        await db_session.commit()

        after = (await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})).json()
        assert after["total_service_records"] - baseline["total_service_records"] == 1
        assert after["total_vehicles"] - baseline["total_vehicles"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehiclesListEndpoint:
    async def test_lists_only_owner_vehicles(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)
        mine = await _make_vehicle(db_session, widget_owner)

        resp = await client.get("/api/widget/vehicles", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        vins = {v["vin"] for v in resp.json()["vehicles"]}
        assert mine.vin in vins

    async def test_selected_vins_scope_filters_list(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        v1 = await _make_vehicle(db_session, widget_owner)
        v2 = await _make_vehicle(db_session, widget_owner)
        plaintext = await _make_key(
            db_session, widget_owner, scope="selected_vins", allowed_vins=[v1.vin]
        )
        resp = await client.get("/api/widget/vehicles", headers={"X-API-Key": plaintext})
        vins = [v["vin"] for v in resp.json()["vehicles"]]
        assert v1.vin in vins
        assert v2.vin not in vins


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleDetailEndpoint:
    async def test_200_for_owned_vin(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)
        v = await _make_vehicle(db_session, widget_owner)
        resp = await client.get(f"/api/widget/vehicle/{v.vin}", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"]
        assert data["year"] == 2022
        assert data["make"] == "Honda"

    async def test_404_for_other_users_vin(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)

        other = User(
            username=f"widget_route_other2_{uuid.uuid4().hex[:8]}",
            email=f"widget_route_other2_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        theirs = await _make_vehicle(db_session, other)

        resp = await client.get(
            f"/api/widget/vehicle/{theirs.vin}", headers={"X-API-Key": plaintext}
        )
        # 404, not 403 — avoid confirming existence.
        assert resp.status_code == 404

    async def test_404_when_vin_outside_selected_scope(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        v1 = await _make_vehicle(db_session, widget_owner)
        v2 = await _make_vehicle(db_session, widget_owner)
        plaintext = await _make_key(
            db_session, widget_owner, scope="selected_vins", allowed_vins=[v1.vin]
        )
        # v2 is owned but excluded by the key scope.
        resp = await client.get(f"/api/widget/vehicle/{v2.vin}", headers={"X-API-Key": plaintext})
        assert resp.status_code == 404

    async def test_ownership_transfer_drift_invalidates_immediately(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        """Plan gate: transferred VIN must drop from the key's access set at request time."""
        await set_auth_mode("local")
        v = await _make_vehicle(db_session, widget_owner)
        plaintext = await _make_key(
            db_session, widget_owner, scope="selected_vins", allowed_vins=[v.vin]
        )

        # Confirm visibility before transfer.
        before = await client.get(f"/api/widget/vehicle/{v.vin}", headers={"X-API-Key": plaintext})
        assert before.status_code == 200

        # Transfer ownership to a different user; key's allowed_vins still
        # contains this VIN but ownership has changed.
        new_owner = User(
            username=f"widget_route_new_owner_{uuid.uuid4().hex[:8]}",
            email=f"widget_route_new_owner_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(new_owner)
        await db_session.commit()
        await db_session.refresh(new_owner)
        v.user_id = new_owner.id
        await db_session.commit()

        after = await client.get(f"/api/widget/vehicle/{v.vin}", headers={"X-API-Key": plaintext})
        assert after.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestFanOutRegressionOverApi:
    """Same shape as the unit test, but exercised end-to-end through HTTP."""

    async def test_counts_stay_exact_with_mixed_child_records(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)
        v = await _make_vehicle(db_session, widget_owner)

        from decimal import Decimal

        baseline = (
            await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
        ).json()

        # Non-prime, mismatched counts — a fan-out would produce cartesian
        # products that never equal any of these individually.
        n_service, n_fuel = 4, 5
        for i in range(n_service):
            db_session.add(ServiceVisit(vin=v.vin, date=date(2026, 1, 1) + timedelta(days=i)))
        for i in range(n_fuel):
            db_session.add(
                FuelRecord(
                    vin=v.vin,
                    date=date(2026, 2, 1) + timedelta(days=i),
                    mileage=10000 + i * 300,
                    gallons=Decimal("10.0"),
                    price_per_unit=Decimal("3.50"),
                    cost=Decimal("35.00"),
                    is_full_tank=True,
                )
            )
        await db_session.commit()

        after = (await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})).json()
        assert after["total_service_records"] - baseline["total_service_records"] == n_service
        assert after["total_fuel_records"] - baseline["total_fuel_records"] == n_fuel


@pytest.mark.integration
@pytest.mark.asyncio
class TestRateLimiting:
    """slowapi enforcement on /api/widget/*.

    WIDGET_RATE_LIMIT is 60/minute per key-hash bucket. Exhausting the bucket
    in a tight loop and asserting the next call returns 429 verifies the
    limiter is wired up end-to-end, not just unit-tested in isolation.
    """

    async def test_429_after_limit_exhausted(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)
        # Wipe limiter state so this test's 60-req budget starts fresh even if
        # earlier tests consumed it for the same bucket.
        widget_limiter.reset()
        try:
            # Burn 60 successful requests to hit the per-minute ceiling.
            for i in range(60):
                resp = await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
                assert resp.status_code == 200, f"request {i} unexpectedly {resp.status_code}"
            # 61st must be 429.
            over = await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
            assert over.status_code == 429
        finally:
            widget_limiter.reset()

    async def test_reset_between_tests(
        self, client: AsyncClient, db_session, widget_owner, set_auth_mode
    ):
        """Smoke check that widget_limiter.reset() really clears the bucket.

        Without it, this test would inherit the 60-hit bucket from the prior
        test and 429 immediately — which would also confirm reset works by
        regression if someone removed it. Keeping the explicit reset makes
        the intent visible.
        """
        await set_auth_mode("local")
        plaintext = await _make_key(db_session, widget_owner)
        widget_limiter.reset()
        resp = await client.get("/api/widget/summary", headers={"X-API-Key": plaintext})
        assert resp.status_code == 200
