"""Integration tests for the Quick Entry feature.

Covers:
- PUT /auth/me: preference updates (show_both, mobile_quick_entry)
- PUT /auth/me: rejects is_active and is_admin self-escalation
- GET /quick-entry/vehicles: an admin gets every non-archived vehicle; anyone
  else gets owned and write-shared ones
- Service visit write: 403 for read-only shared vehicle
- Odometer write: 403 for read-only shared vehicle

Unit preferences are no longer settable here (D9b). That route now lives in
tests/integration/routes/test_unit_preferences.py, which also pins the fact
that the old payload is rejected.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare


@pytest.mark.integration
@pytest.mark.asyncio
class TestUpdateCurrentUserPreferences:
    """Test PUT /auth/me preference updates."""

    async def test_update_accent_color(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that the per-account UI accent can be updated and persists."""
        response = await client.put(
            "/api/auth/me",
            json={"accent_color": "violet"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["accent_color"] == "violet"

        # Verify persisted
        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.accent_color == "violet"

        # Restore
        await client.put(
            "/api/auth/me",
            json={"accent_color": "blue"},
            headers=auth_headers,
        )

    async def test_update_accent_color_rejects_unsupported(self, client: AsyncClient, auth_headers):
        """An accent outside the six-key allowlist is rejected (422)."""
        response = await client.put(
            "/api/auth/me",
            json={"accent_color": "chartreuse"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_accent_color_unset_by_default(self, client: AsyncClient, auth_headers):
        """A freshly-created user has NO explicit accent (NULL) from GET /auth/me.

        NULL means "never picked" so the client's localStorage seed / default
        applies and useAccentSync must not override it; an explicit pick stores
        a non-null key that syncs across devices.
        """
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["accent_color"] is None

    async def test_update_theme(self, client: AsyncClient, auth_headers, test_user, db_session):
        """Test that the per-account light/dark theme can be updated and persists."""
        response = await client.put(
            "/api/auth/me",
            json={"theme": "light"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["theme"] == "light"

        # Verify persisted
        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.theme == "light"

    async def test_update_theme_rejects_unsupported(self, client: AsyncClient, auth_headers):
        """A theme outside the light/dark allowlist is rejected (422)."""
        response = await client.put(
            "/api/auth/me",
            json={"theme": "solarized"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_theme_unset_by_default(self, client: AsyncClient, auth_headers):
        """A freshly-created user has NO explicit theme (NULL) from GET /auth/me.

        NULL means "never picked" so the client's localStorage seed / default
        applies and useThemeSync must not override it; an explicit pick stores a
        non-null value that syncs across devices.
        """
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["theme"] is None

    async def test_update_dashboard_sort(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """The order the dashboard opens in is saved to the account."""
        response = await client.put(
            "/api/auth/me",
            json={"dashboard_sort": "maintenance"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["dashboard_sort"] == "maintenance"

        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.dashboard_sort == "maintenance"

    async def test_update_dashboard_sort_rejects_unsupported(
        self, client: AsyncClient, auth_headers
    ):
        """An order the dashboard menu does not offer is rejected (422)."""
        response = await client.put(
            "/api/auth/me",
            json={"dashboard_sort": "mileage"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_dashboard_sort_is_name_by_default(self, client: AsyncClient, auth_headers):
        """A user who never picked one opens on Name, as the dashboard always has."""
        response = await client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["dashboard_sort"] == "name"

    async def test_update_show_both_units(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that show_both_units can be updated."""
        response = await client.put(
            "/api/auth/me",
            json={"show_both_units": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["show_both_units"] is True

        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.show_both_units is True

        # Restore
        await client.put(
            "/api/auth/me",
            json={"show_both_units": False},
            headers=auth_headers,
        )

    async def test_update_mobile_quick_entry_enabled(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Test that mobile_quick_entry_enabled can be toggled."""
        response = await client.put(
            "/api/auth/me",
            json={"mobile_quick_entry_enabled": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["mobile_quick_entry_enabled"] is False

        user = await db_session.get(User, test_user["id"])
        await db_session.refresh(user)
        assert user.mobile_quick_entry_enabled is False

        # Restore
        await client.put(
            "/api/auth/me",
            json={"mobile_quick_entry_enabled": True},
            headers=auth_headers,
        )

    async def test_cannot_self_escalate_is_admin(self, client: AsyncClient, auth_headers):
        """Test that users cannot send is_admin via self-update (rejected by schema)."""
        response = await client.put(
            "/api/auth/me",
            json={"is_admin": True},
            headers=auth_headers,
        )
        # UserSelfUpdate has extra="forbid" — privileged fields get 422
        assert response.status_code == 422

    async def test_cannot_self_escalate_is_active(self, client: AsyncClient, auth_headers):
        """Test that users cannot send is_active via self-update (rejected by schema)."""
        response = await client.put(
            "/api/auth/me",
            json={"is_active": False},
            headers=auth_headers,
        )
        # UserSelfUpdate has extra="forbid" — privileged fields get 422
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
class TestQuickEntryVehicles:
    """Test GET /quick-entry/vehicles.

    `test_user` (behind `auth_headers`) is an ADMIN, and an admin sees every
    vehicle. So the owner/share rules are tested as `non_admin_user`; under the
    admin headers they would pass whether or not the rule held.
    """

    async def _add_user(self, db_session: AsyncSession, username: str) -> int:
        """Add a plain non-admin user and return its id."""
        user = User(
            username=username,
            email=f"{username}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.flush()
        return user.id

    async def _add_vehicle(
        self,
        db_session: AsyncSession,
        vin: str,
        user_id: int | None,
        *,
        archived: bool = False,
    ) -> None:
        """Add a bare vehicle. `user_id=None` is a vehicle created under auth_mode=none."""
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=user_id,
                nickname=f"QE {vin[-4:]}",
                vehicle_type="Car",
                year=2020,
                make="Test",
                model="Car",
                archived_at=datetime.now(UTC) if archived else None,
            )
        )
        await db_session.flush()

    async def _cleanup(
        self,
        db_session: AsyncSession,
        vins: list[str],
        user_ids: list[int] | None = None,
    ) -> None:
        """Delete the shares, vehicles and users a test added, by key."""
        await db_session.rollback()
        await db_session.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin.in_(vins)))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_(vins)))
        if user_ids:
            await db_session.execute(delete(User).where(User.id.in_(user_ids)))
        await db_session.commit()

    async def _vins(self, client: AsyncClient, headers: dict[str, str] | None) -> list[str]:
        """GET the Quick Entry list and return its VINs."""
        response = await client.get("/api/quick-entry/vehicles", headers=headers)
        assert response.status_code == 200
        return [v["vin"] for v in response.json()["vehicles"]]

    async def test_carries_what_decides_the_actions(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Quick Entry offers DEF only where the API accepts it (a diesel
        in either fuel slot), so it needs both slots, beside the type and the
        usage dimension that decide the rest."""
        response = await client.get("/api/quick-entry/vehicles", headers=auth_headers)

        assert response.status_code == 200
        row = next(v for v in response.json()["vehicles"] if v["vin"] == test_vehicle["vin"])
        assert (row["vehicle_type"], row["fuel_type"], row["fuel_type_secondary"]) == (
            "Car",
            "diesel",
            None,
        )

    async def test_auth_disabled_returns_all_vehicles(
        self, client: AsyncClient, test_vehicle, db_session
    ):
        """auth_mode='none' → require_auth returns None → all non-archived
        vehicles, without dereferencing current_user (regression: the endpoint
        used to 500 with AttributeError on current_user.id). That includes an
        unowned vehicle, which is what auth_mode='none' creates.

        Regression control: passes on 3.11.2 too.
        """
        from app.main import app
        from app.services.auth import require_auth

        vins = ["QEAUTHNONE0000001", "QEAUTHNONE0000002"]
        await self._add_vehicle(db_session, vins[0], None)
        await self._add_vehicle(db_session, vins[1], None, archived=True)
        await db_session.commit()

        app.dependency_overrides[require_auth] = lambda: None
        try:
            listed = await self._vins(client, None)  # no auth headers
        finally:
            app.dependency_overrides.pop(require_auth, None)
            await self._cleanup(db_session, vins)

        assert test_vehicle["vin"] in listed
        assert vins[0] in listed
        assert vins[1] not in listed

    async def test_admin_sees_unowned_vehicle(self, client: AsyncClient, auth_headers, db_session):
        """#308: a vehicle created under auth_mode=none has no owner. The admin
        can open it everywhere else, so Quick Entry must list it too."""
        vin = "QEADMINUNOWNED001"
        await self._add_vehicle(db_session, vin, None)
        await db_session.commit()
        try:
            listed = await self._vins(client, auth_headers)
        finally:
            await self._cleanup(db_session, [vin])

        assert vin in listed

    async def test_admin_sees_other_users_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        """An admin can write to every vehicle, so Quick Entry lists another
        user's unshared vehicle beside the admin's own."""
        vin = "QEADMINOTHER00001"
        other_id = await self._add_user(db_session, "qe_admin_other")
        await self._add_vehicle(db_session, vin, other_id)
        await db_session.commit()
        try:
            listed = await self._vins(client, auth_headers)
        finally:
            await self._cleanup(db_session, [vin], [other_id])

        assert vin in listed
        assert test_vehicle["vin"] in listed

    async def test_admin_excludes_archived_vehicles(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Seeing everything still stops at archived, owned by the admin or not."""
        live, archived_unowned, archived_own = (
            "QEADMINLIVE000001",
            "QEADMINARCHIVED01",
            "QEADMINARCHIVED02",
        )
        await self._add_vehicle(db_session, live, None)
        await self._add_vehicle(db_session, archived_unowned, None, archived=True)
        await self._add_vehicle(db_session, archived_own, test_user["id"], archived=True)
        await db_session.commit()
        try:
            listed = await self._vins(client, auth_headers)
        finally:
            await self._cleanup(db_session, [live, archived_unowned, archived_own])

        assert live in listed
        assert archived_unowned not in listed
        assert archived_own not in listed

    async def test_non_admin_sees_owned_vehicles(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session
    ):
        """Regression control: a non-admin's own vehicle is listed."""
        vin = "QENONADMINOWN0001"
        await self._add_vehicle(db_session, vin, non_admin_user["id"])
        await db_session.commit()
        try:
            listed = await self._vins(client, non_admin_headers)
        finally:
            await self._cleanup(db_session, [vin])

        assert vin in listed

    async def test_non_admin_excludes_archived_vehicles(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session
    ):
        """Regression control: a non-admin's archived vehicle is not listed."""
        vin = "QENONADMINARCH001"
        await self._add_vehicle(db_session, vin, non_admin_user["id"], archived=True)
        await db_session.commit()
        try:
            listed = await self._vins(client, non_admin_headers)
        finally:
            await self._cleanup(db_session, [vin])

        assert vin not in listed

    async def test_non_admin_sees_write_shared_vehicles(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session
    ):
        """Regression control: a vehicle write-shared to a non-admin is listed."""
        vin = "SHAREDWRITEVIN001"
        owner_id = await self._add_user(db_session, "otheruser_qe")
        await self._add_vehicle(db_session, vin, owner_id)
        db_session.add(
            VehicleShare(
                vehicle_vin=vin,
                user_id=non_admin_user["id"],
                permission="write",
                shared_by=owner_id,
            )
        )
        await db_session.commit()
        try:
            listed = await self._vins(client, non_admin_headers)
        finally:
            await self._cleanup(db_session, [vin], [owner_id])

        assert vin in listed

    async def test_non_admin_excludes_read_only_shared_vehicles(
        self, client: AsyncClient, non_admin_headers, non_admin_user, db_session
    ):
        """Regression control: Quick Entry only writes, so a read share is not listed."""
        vin = "SHAREDREADVIN0001"
        owner_id = await self._add_user(db_session, "otheruser_ro")
        await self._add_vehicle(db_session, vin, owner_id)
        db_session.add(
            VehicleShare(
                vehicle_vin=vin,
                user_id=non_admin_user["id"],
                permission="read",
                shared_by=owner_id,
            )
        )
        await db_session.commit()
        try:
            listed = await self._vins(client, non_admin_headers)
        finally:
            await self._cleanup(db_session, [vin], [owner_id])

        assert vin not in listed

    async def test_non_admin_excludes_unowned_and_unshared_vehicles(
        self, client: AsyncClient, non_admin_headers, test_vehicle, db_session
    ):
        """Regression control: the admin rule must not leak to everyone. A
        non-admin sees neither an unowned vehicle nor someone else's unshared one
        (here the admin's)."""
        vin = "QENONADMINUNOWN01"
        await self._add_vehicle(db_session, vin, None)
        await db_session.commit()
        try:
            listed = await self._vins(client, non_admin_headers)
        finally:
            await self._cleanup(db_session, [vin])

        assert vin not in listed
        assert test_vehicle["vin"] not in listed


@pytest.mark.integration
@pytest.mark.asyncio
class TestWriteAuthEnforcement:
    """Test that write operations enforce ownership/share permission.

    Uses a dedicated non-admin user as the requester so that get_vehicle_or_403
    actually enforces permissions (admin users bypass permission checks by design).
    """

    async def _setup_read_only_share(self, db_session):
        """Create a vehicle owner, a non-admin requester, and a read-only share.

        Returns primary-key VALUES rather than the live ORM objects --
        (vehicle_vin, share_id, owner_id, requester_id, nonadmin_headers) --
        because every caller's enforcement call is expected to 403, which
        rolls the shared test session back (conftest mirrors production
        `get_db`) and expires the whole identity map. Touching an expired
        object's attribute afterward (in `_cleanup`) would need a synchronous
        lazy-refresh and raise MissingGreenlet under an async session; plain
        values captured here, before any request, do not.
        """
        from app.services.auth import create_access_token

        vehicle_owner = User(
            username="writeauth_owner",
            email="writeauth_owner@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(vehicle_owner)
        await db_session.flush()

        vehicle = Vehicle(
            vin="READONLYSHARE0001",
            user_id=vehicle_owner.id,
            nickname="Read-Only Shared",
            vehicle_type="Car",
            year=2022,
            make="Ford",
            model="F-150",
        )
        db_session.add(vehicle)
        await db_session.flush()

        nonadmin_requester = User(
            username="writeauth_requester",
            email="writeauth_requester@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(nonadmin_requester)
        await db_session.flush()

        share = VehicleShare(
            vehicle_vin="READONLYSHARE0001",
            user_id=nonadmin_requester.id,
            permission="read",
            shared_by=vehicle_owner.id,
        )
        db_session.add(share)
        await db_session.commit()

        token = create_access_token(
            data={"sub": str(nonadmin_requester.id), "username": nonadmin_requester.username}
        )
        nonadmin_headers = {"Authorization": f"Bearer {token}"}

        return vehicle.vin, share.id, vehicle_owner.id, nonadmin_requester.id, nonadmin_headers

    async def _cleanup(self, db_session, share_id: int, vehicle_vin: str, *user_ids: int):
        """Remove test data created by _setup_read_only_share.

        Takes primary-key VALUES rather than the live ORM objects. The
        enforcement call under test is expected to 403, and since v3.4.0 the
        test `get_db` override mirrors production and rolls the shared
        session back on any raised HTTPException -- which expires every
        object in the identity map. Touching `share.id` etc. here afterward
        would need a synchronous lazy-refresh and raise MissingGreenlet under
        an async session; plain values captured before the call do not.
        """
        result = await db_session.execute(select(VehicleShare).where(VehicleShare.id == share_id))
        s = result.scalar_one_or_none()
        if s:
            await db_session.delete(s)

        result = await db_session.execute(select(Vehicle).where(Vehicle.vin == vehicle_vin))
        v = result.scalar_one_or_none()
        if v:
            await db_session.delete(v)

        for user_id in user_ids:
            result = await db_session.execute(select(User).where(User.id == user_id))
            u = result.scalar_one_or_none()
            if u:
                await db_session.delete(u)
        await db_session.commit()

    async def test_odometer_create_forbidden_for_read_share(self, client: AsyncClient, db_session):
        """Test that creating an odometer record on a read-only shared vehicle returns 403."""
        vin, share_id, owner_id, requester_id, nonadmin_headers = await self._setup_read_only_share(
            db_session
        )
        try:
            response = await client.post(
                f"/api/vehicles/{vin}/odometer",
                json={"vin": vin, "date": "2024-01-01", "odometer_km": 16093.40},
                headers=nonadmin_headers,
            )
            assert response.status_code == 403
        finally:
            await self._cleanup(db_session, share_id, vin, owner_id, requester_id)

    async def test_odometer_update_forbidden_for_read_share(self, client: AsyncClient, db_session):
        """Test that updating an odometer record on a read-only shared vehicle returns 403."""
        vin, share_id, owner_id, requester_id, nonadmin_headers = await self._setup_read_only_share(
            db_session
        )
        try:
            response = await client.put(
                f"/api/vehicles/{vin}/odometer/9999",
                json={"date": "2024-01-01", "odometer_km": 16095.01},
                headers=nonadmin_headers,
            )
            assert response.status_code == 403
        finally:
            await self._cleanup(db_session, share_id, vin, owner_id, requester_id)

    async def test_odometer_delete_forbidden_for_read_share(self, client: AsyncClient, db_session):
        """Test that deleting an odometer record on a read-only shared vehicle returns 403."""
        vin, share_id, owner_id, requester_id, nonadmin_headers = await self._setup_read_only_share(
            db_session
        )
        try:
            response = await client.delete(
                f"/api/vehicles/{vin}/odometer/9999",
                headers=nonadmin_headers,
            )
            assert response.status_code == 403
        finally:
            await self._cleanup(db_session, share_id, vin, owner_id, requester_id)
