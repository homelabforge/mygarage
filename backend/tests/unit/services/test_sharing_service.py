"""
Unit tests for vehicle sharing service.

Tests vehicle sharing with read/write permissions.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas.family import VehicleShareCreate, VehicleShareUpdate
from app.services.sharing_service import SharingService


@pytest_asyncio.fixture
async def owner_user(db_session) -> User:
    """Create or get a vehicle owner user."""
    result = await db_session.execute(select(User).where(User.username == "share_owner"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="share_owner",
            email="share_owner@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    """Create or get an admin user."""
    result = await db_session.execute(select(User).where(User.username == "share_admin"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="share_admin",
            email="share_admin@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def recipient_user(db_session) -> User:
    """Create or get a share recipient user."""
    result = await db_session.execute(select(User).where(User.username == "share_recipient"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="share_recipient",
            email="share_recipient@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=False,
            relationship="spouse",
            full_name="Share Recipient",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def other_user(db_session) -> User:
    """Create or get another user (not owner or recipient)."""
    result = await db_session.execute(select(User).where(User.username == "share_other"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="share_other",
            email="share_other@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def disabled_user(db_session) -> User:
    """Create or get a disabled user."""
    result = await db_session.execute(select(User).where(User.username == "share_disabled"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="share_disabled",
            email="share_disabled@example.com",
            hashed_password=test_password_hash,
            is_active=False,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def share_vehicle(db_session, owner_user) -> Vehicle:
    """Create or get a vehicle for sharing tests."""
    test_vin = "SHARING1234567890"
    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == test_vin))
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        vehicle = Vehicle(
            vin=test_vin,
            user_id=owner_user.id,
            nickname="Sharing Test Vehicle",
            vehicle_type="Car",
            year=2021,
            make="Honda",
            model="Civic",
        )
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)

    # Ensure vehicle belongs to owner for each test
    vehicle.user_id = owner_user.id
    await db_session.commit()

    # Clear any existing shares for clean test state
    from sqlalchemy import delete

    await db_session.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin == test_vin))
    await db_session.commit()

    return vehicle


@pytest.mark.unit
@pytest.mark.asyncio
class TestShareVehicle:
    """Test vehicle sharing functionality."""

    async def test_share_vehicle_read_permission(
        self, db_session, owner_user, recipient_user, share_vehicle
    ):
        """Test sharing vehicle with read permission."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )

        result = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=request,
            current_user=owner_user,
        )

        assert result.vehicle_vin == share_vehicle.vin
        assert result.user.id == recipient_user.id
        assert result.permission == "read"
        assert result.shared_by.id == owner_user.id

    async def test_share_vehicle_write_permission(
        self, db_session, owner_user, recipient_user, share_vehicle
    ):
        """Test sharing vehicle with write permission."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="write",
        )

        result = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=request,
            current_user=owner_user,
        )

        assert result.permission == "write"

    async def test_admin_can_share(self, db_session, admin_user, recipient_user, share_vehicle):
        """Test that admin can share any vehicle."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )

        result = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=request,
            current_user=admin_user,
        )

        assert result.shared_by.id == admin_user.id

    async def test_non_owner_cannot_share(
        self, db_session, other_user, recipient_user, share_vehicle
    ):
        """Test that non-owner non-admin cannot share vehicle."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )

        with pytest.raises(Exception) as exc_info:
            await service.share_vehicle(
                vin=share_vehicle.vin,
                share_request=request,
                current_user=other_user,
            )

        assert exc_info.value.status_code == 403

    async def test_cannot_share_with_self(self, db_session, owner_user, share_vehicle):
        """Test that owner cannot share with themselves."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=owner_user.id,
            permission="read",
        )

        with pytest.raises(Exception) as exc_info:
            await service.share_vehicle(
                vin=share_vehicle.vin,
                share_request=request,
                current_user=owner_user,
            )

        assert exc_info.value.status_code == 400
        assert "yourself" in exc_info.value.detail.lower()

    async def test_cannot_share_with_owner(self, db_session, admin_user, owner_user, share_vehicle):
        """Test that cannot share with the vehicle owner."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=owner_user.id,
            permission="read",
        )

        with pytest.raises(Exception) as exc_info:
            await service.share_vehicle(
                vin=share_vehicle.vin,
                share_request=request,
                current_user=admin_user,
            )

        assert exc_info.value.status_code == 400
        assert "owner" in exc_info.value.detail.lower()

    async def test_cannot_share_with_disabled_user(
        self, db_session, owner_user, disabled_user, share_vehicle
    ):
        """Test that cannot share with disabled user."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=disabled_user.id,
            permission="read",
        )

        with pytest.raises(Exception) as exc_info:
            await service.share_vehicle(
                vin=share_vehicle.vin,
                share_request=request,
                current_user=owner_user,
            )

        assert exc_info.value.status_code == 400
        assert "disabled" in exc_info.value.detail.lower()

    async def test_duplicate_share_rejected(
        self, db_session, owner_user, recipient_user, share_vehicle
    ):
        """Test that duplicate shares are rejected."""
        service = SharingService(db_session)

        request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )

        # Create first share
        await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=request,
            current_user=owner_user,
        )

        # Try to create duplicate
        with pytest.raises(Exception) as exc_info:
            await service.share_vehicle(
                vin=share_vehicle.vin,
                share_request=request,
                current_user=owner_user,
            )

        assert exc_info.value.status_code == 409


@pytest.mark.unit
@pytest.mark.asyncio
class TestUpdateShare:
    """Test share update functionality."""

    async def test_update_share_permission(
        self, db_session, owner_user, recipient_user, share_vehicle
    ):
        """Test updating share permission."""
        service = SharingService(db_session)

        # Create share
        create_request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )
        share = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=create_request,
            current_user=owner_user,
        )

        # Update permission
        update_request = VehicleShareUpdate(permission="write")
        result = await service.update_share(
            share_id=share.id,
            update_request=update_request,
            current_user=owner_user,
        )

        assert result.permission == "write"

    async def test_admin_can_update_share(
        self, db_session, owner_user, admin_user, recipient_user, share_vehicle
    ):
        """Test that admin can update any share."""
        service = SharingService(db_session)

        # Create share as owner
        create_request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )
        share = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=create_request,
            current_user=owner_user,
        )

        # Update as admin
        update_request = VehicleShareUpdate(permission="write")
        result = await service.update_share(
            share_id=share.id,
            update_request=update_request,
            current_user=admin_user,
        )

        assert result.permission == "write"


@pytest.mark.unit
@pytest.mark.asyncio
class TestRevokeShare:
    """Test share revocation functionality."""

    async def test_revoke_share(self, db_session, owner_user, recipient_user, share_vehicle):
        """Test revoking a share."""
        service = SharingService(db_session)

        # Create share
        create_request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )
        share = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=create_request,
            current_user=owner_user,
        )

        # Revoke share
        await service.revoke_share(
            share_id=share.id,
            current_user=owner_user,
        )

        # Verify share is gone
        result = await db_session.execute(select(VehicleShare).where(VehicleShare.id == share.id))
        assert result.scalar_one_or_none() is None

    async def test_non_owner_cannot_revoke(
        self, db_session, owner_user, other_user, recipient_user, share_vehicle
    ):
        """Test that non-owner cannot revoke share."""
        service = SharingService(db_session)

        # Create share
        create_request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )
        share = await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=create_request,
            current_user=owner_user,
        )

        # Try to revoke as non-owner
        with pytest.raises(Exception) as exc_info:
            await service.revoke_share(
                share_id=share.id,
                current_user=other_user,
            )

        assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetVehicleShares:
    """Test getting vehicle shares."""

    async def test_get_shares_as_owner(self, db_session, owner_user, recipient_user, share_vehicle):
        """Test getting shares as owner."""
        service = SharingService(db_session)

        # Create share
        create_request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )
        await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=create_request,
            current_user=owner_user,
        )

        # Get shares
        shares, total = await service.get_vehicle_shares(
            vin=share_vehicle.vin,
            current_user=owner_user,
        )

        assert total >= 1
        assert len(shares) >= 1

    async def test_non_owner_cannot_view_shares(self, db_session, other_user, share_vehicle):
        """Test that non-owner cannot view shares."""
        service = SharingService(db_session)

        with pytest.raises(Exception) as exc_info:
            await service.get_vehicle_shares(
                vin=share_vehicle.vin,
                current_user=other_user,
            )

        assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
class TestCheckSharePermission:
    """Test checking share permissions."""

    async def test_check_read_permission(
        self, db_session, owner_user, recipient_user, share_vehicle
    ):
        """Test checking read permission."""
        service = SharingService(db_session)

        # Create read share
        create_request = VehicleShareCreate(
            user_id=recipient_user.id,
            permission="read",
        )
        await service.share_vehicle(
            vin=share_vehicle.vin,
            share_request=create_request,
            current_user=owner_user,
        )

        # Check permission
        permission = await service.check_share_permission(
            vin=share_vehicle.vin,
            user_id=recipient_user.id,
        )

        assert permission == "read"

    async def test_check_no_permission(self, db_session, other_user, share_vehicle):
        """Test checking permission when no share exists."""
        service = SharingService(db_session)

        permission = await service.check_share_permission(
            vin=share_vehicle.vin,
            user_id=other_user.id,
        )

        assert permission is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetShareableUsers:
    """Test getting shareable users."""

    async def test_get_shareable_users(self, db_session, owner_user):
        """Test getting list of shareable users."""
        service = SharingService(db_session)

        users = await service.get_shareable_users(current_user=owner_user)

        # Should return list of active users except current user
        assert isinstance(users, list)
        # Current user should not be in list
        for user in users:
            assert user.id != owner_user.id
