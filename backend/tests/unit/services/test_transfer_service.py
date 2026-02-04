"""
Unit tests for vehicle transfer service.

Tests vehicle ownership transfers between users.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.models.vehicle_transfer import VehicleTransfer
from app.schemas.family import VehicleTransferRequest
from app.services.transfer_service import TransferService


@pytest_asyncio.fixture
async def admin_user(db_session) -> User:
    """Create or get an admin user for transfer tests."""
    result = await db_session.execute(select(User).where(User.username == "transfer_admin"))
    user = result.scalar_one_or_none()

    if not user:
        # Pre-computed hash for "testpassword123"
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="transfer_admin",
            email="transfer_admin@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def regular_user(db_session) -> User:
    """Create or get a regular (non-admin) user."""
    result = await db_session.execute(select(User).where(User.username == "transfer_regular"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="transfer_regular",
            email="transfer_regular@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def recipient_user(db_session) -> User:
    """Create or get a recipient user for transfers."""
    result = await db_session.execute(select(User).where(User.username == "transfer_recipient"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="transfer_recipient",
            email="transfer_recipient@example.com",
            hashed_password=test_password_hash,
            is_active=True,
            is_admin=False,
            relationship="child",
            full_name="Transfer Recipient",
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def disabled_user(db_session) -> User:
    """Create or get a disabled user."""
    result = await db_session.execute(select(User).where(User.username == "transfer_disabled"))
    user = result.scalar_one_or_none()

    if not user:
        test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
        user = User(
            username="transfer_disabled",
            email="transfer_disabled@example.com",
            hashed_password=test_password_hash,
            is_active=False,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def transfer_vehicle(db_session, admin_user) -> Vehicle:
    """Create or get a vehicle for transfer tests."""
    test_vin = "TRANSFER123456789"
    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == test_vin))
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        vehicle = Vehicle(
            vin=test_vin,
            user_id=admin_user.id,
            nickname="Transfer Test Vehicle",
            vehicle_type="Car",
            year=2020,
            make="Toyota",
            model="Camry",
        )
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)

    # Ensure vehicle belongs to admin for each test
    vehicle.user_id = admin_user.id
    await db_session.commit()

    return vehicle


@pytest.mark.unit
@pytest.mark.asyncio
class TestTransferVehicle:
    """Test vehicle transfer functionality."""

    async def test_transfer_vehicle_success(
        self, db_session, admin_user, recipient_user, transfer_vehicle
    ):
        """Test successful vehicle transfer by admin."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=recipient_user.id,
            transfer_notes="Test transfer",
            data_included={"service_records": True, "fuel_logs": True},
        )

        result = await service.transfer_vehicle(
            vin=transfer_vehicle.vin,
            transfer_request=request,
            current_user=admin_user,
        )

        assert result.vehicle_vin == transfer_vehicle.vin
        assert result.to_user.id == recipient_user.id
        assert result.transfer_notes == "Test transfer"

        # Verify vehicle ownership changed
        await db_session.refresh(transfer_vehicle)
        assert transfer_vehicle.user_id == recipient_user.id

    async def test_transfer_vehicle_non_admin_rejected(
        self, db_session, regular_user, recipient_user, transfer_vehicle
    ):
        """Test that non-admin users cannot transfer vehicles."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=recipient_user.id,
        )

        with pytest.raises(Exception) as exc_info:
            await service.transfer_vehicle(
                vin=transfer_vehicle.vin,
                transfer_request=request,
                current_user=regular_user,
            )

        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail.lower()

    async def test_transfer_to_same_owner_rejected(self, db_session, admin_user, transfer_vehicle):
        """Test that transfer to current owner is rejected."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=admin_user.id,
        )

        with pytest.raises(Exception) as exc_info:
            await service.transfer_vehicle(
                vin=transfer_vehicle.vin,
                transfer_request=request,
                current_user=admin_user,
            )

        assert exc_info.value.status_code == 400
        assert "already the owner" in exc_info.value.detail.lower()

    async def test_transfer_to_disabled_user_rejected(
        self, db_session, admin_user, disabled_user, transfer_vehicle
    ):
        """Test that transfer to disabled user is rejected."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=disabled_user.id,
        )

        with pytest.raises(Exception) as exc_info:
            await service.transfer_vehicle(
                vin=transfer_vehicle.vin,
                transfer_request=request,
                current_user=admin_user,
            )

        assert exc_info.value.status_code == 400
        assert "disabled" in exc_info.value.detail.lower()

    async def test_transfer_to_nonexistent_user_rejected(
        self, db_session, admin_user, transfer_vehicle
    ):
        """Test that transfer to non-existent user is rejected."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=99999,
        )

        with pytest.raises(Exception) as exc_info:
            await service.transfer_vehicle(
                vin=transfer_vehicle.vin,
                transfer_request=request,
                current_user=admin_user,
            )

        assert exc_info.value.status_code == 404
        assert "recipient" in exc_info.value.detail.lower()

    async def test_transfer_nonexistent_vehicle_rejected(
        self, db_session, admin_user, recipient_user
    ):
        """Test that transfer of non-existent vehicle is rejected."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=recipient_user.id,
        )

        with pytest.raises(Exception) as exc_info:
            await service.transfer_vehicle(
                vin="NONEXISTENT1234567",
                transfer_request=request,
                current_user=admin_user,
            )

        assert exc_info.value.status_code == 404
        assert "vehicle" in exc_info.value.detail.lower()

    async def test_transfer_clears_recipient_share(
        self, db_session, admin_user, recipient_user, transfer_vehicle
    ):
        """Test that transferring to a user removes their share."""
        service = TransferService(db_session)

        # Create a share for the recipient
        share = VehicleShare(
            vehicle_vin=transfer_vehicle.vin,
            user_id=recipient_user.id,
            permission="read",
            shared_by=admin_user.id,
        )
        db_session.add(share)
        await db_session.commit()

        # Transfer to recipient
        request = VehicleTransferRequest(to_user_id=recipient_user.id)

        await service.transfer_vehicle(
            vin=transfer_vehicle.vin,
            transfer_request=request,
            current_user=admin_user,
        )

        # Verify share was removed
        result = await db_session.execute(
            select(VehicleShare).where(
                VehicleShare.vehicle_vin == transfer_vehicle.vin,
                VehicleShare.user_id == recipient_user.id,
            )
        )
        assert result.scalar_one_or_none() is None

    async def test_transfer_creates_audit_record(
        self, db_session, admin_user, recipient_user, transfer_vehicle
    ):
        """Test that transfer creates an audit record."""
        service = TransferService(db_session)

        request = VehicleTransferRequest(
            to_user_id=recipient_user.id,
            transfer_notes="Audit test",
        )

        await service.transfer_vehicle(
            vin=transfer_vehicle.vin,
            transfer_request=request,
            current_user=admin_user,
        )

        # Verify audit record exists
        result = await db_session.execute(
            select(VehicleTransfer).where(VehicleTransfer.vehicle_vin == transfer_vehicle.vin)
        )
        transfers = result.scalars().all()

        assert len(transfers) >= 1
        latest = transfers[-1]
        assert latest.from_user_id == admin_user.id
        assert latest.to_user_id == recipient_user.id
        assert latest.transferred_by == admin_user.id
        assert latest.transfer_notes == "Audit test"


@pytest.mark.unit
@pytest.mark.asyncio
class TestTransferHistory:
    """Test transfer history retrieval."""

    async def test_get_transfer_history(
        self, db_session, admin_user, recipient_user, transfer_vehicle
    ):
        """Test getting transfer history for a vehicle."""
        service = TransferService(db_session)

        # Perform a transfer first
        request = VehicleTransferRequest(to_user_id=recipient_user.id)
        await service.transfer_vehicle(
            vin=transfer_vehicle.vin,
            transfer_request=request,
            current_user=admin_user,
        )

        # Get history
        transfers, total = await service.get_transfer_history(transfer_vehicle.vin)

        assert total >= 1
        assert len(transfers) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestEligibleRecipients:
    """Test eligible recipients retrieval."""

    async def test_get_eligible_recipients(
        self, db_session, admin_user, recipient_user, transfer_vehicle
    ):
        """Test getting eligible recipients for transfer."""
        service = TransferService(db_session)

        recipients = await service.get_eligible_recipients(
            vin=transfer_vehicle.vin,
            current_user=admin_user,
        )

        # Should include active users except current owner
        assert isinstance(recipients, list)

    async def test_get_eligible_recipients_non_admin_rejected(
        self, db_session, regular_user, transfer_vehicle
    ):
        """Test that non-admin cannot get eligible recipients."""
        service = TransferService(db_session)

        with pytest.raises(Exception) as exc_info:
            await service.get_eligible_recipients(
                vin=transfer_vehicle.vin,
                current_user=regular_user,
            )

        assert exc_info.value.status_code == 403
