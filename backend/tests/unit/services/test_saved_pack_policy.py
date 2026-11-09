"""Who may change a saved pack, and what a pack is allowed to contain.

Both are policy rather than plumbing, and both have a case that only shows up
away from the happy path: `auth_mode='none'` leaves no identity to compare
against, and a pack cannot carry a schedule the apply pipeline would reshape.
"""

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models.maintenance_rule import MaintenanceRule
from app.models.reminder_pack import ReminderPack
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas.reminder_pack import SaveReminderPackRequest, custom_pack_id, pack_slug
from app.services import reminder_pack_service
from app.services.reminder_pack_service import (
    PACKS_DIR,
    _vehicle_types,
    may_edit,
    unsavable_reason,
)

PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
    "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)
OWNER_VIN = "PACKPOLICY0000001"


async def _user(db_session, username: str, is_admin: bool = False) -> User:
    result = await db_session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            username=username,
            email=f"{username}@example.com",
            hashed_password=PASSWORD_HASH,
            is_active=True,
            is_admin=is_admin,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    user.is_admin = is_admin
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def pack_owner(db_session) -> User:
    return await _user(db_session, "pack_owner")


@pytest_asyncio.fixture
async def pack_stranger(db_session) -> User:
    return await _user(db_session, "pack_stranger")


@pytest_asyncio.fixture
async def pack_admin(db_session) -> User:
    return await _user(db_session, "pack_admin", is_admin=True)


@pytest_asyncio.fixture(autouse=True)
async def _clean(db_session):
    yield
    await db_session.execute(delete(ReminderPack))
    await db_session.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin == OWNER_VIN))
    await db_session.execute(delete(MaintenanceRule).where(MaintenanceRule.vin == OWNER_VIN))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == OWNER_VIN))
    await db_session.commit()


def _pack(creator_id: int | None) -> ReminderPack:
    return ReminderPack(
        pack_id="custom-x",
        name="X",
        description="",
        vehicle_types=[],
        created_by_user_id=creator_id,
    )


@pytest.mark.integration
class TestWhoMayChangeAPack:
    def test_with_auth_disabled_everyone_may(self):
        """`auth_mode='none'` is supported and `require_auth` returns None in it,
        so there is no identity to compare and a creator check would refuse
        everybody, locking the feature shut on the default configuration."""
        assert may_edit(_pack(None), None) is True
        assert may_edit(_pack(7), None) is True

    def test_the_creator_may(self, pack_owner):
        assert may_edit(_pack(pack_owner.id), pack_owner) is True

    def test_a_stranger_may_not(self, pack_owner, pack_stranger):
        assert may_edit(_pack(pack_owner.id), pack_stranger) is False

    def test_an_admin_may(self, pack_owner, pack_admin):
        assert may_edit(_pack(pack_owner.id), pack_admin) is True

    def test_a_null_creator_is_admin_only_once_auth_is_on(self, pack_stranger, pack_admin):
        """A pack from a deleted user, or saved while auth was off. Nobody can
        prove they made it, so nobody inherits it."""
        assert may_edit(_pack(None), pack_stranger) is False
        assert may_edit(_pack(None), pack_admin) is True


@pytest.mark.integration
class TestWhatAPackMayContain:
    def test_a_typeless_rule_is_refused(self):
        rule = MaintenanceRule(vin=OWNER_VIN, title="Check the winch", maintenance_type=None)
        assert unsavable_reason(rule, set()) == (
            "a reminder with no maintenance type cannot go in a pack"
        )

    def test_a_repeated_type_is_refused(self):
        rule = MaintenanceRule(vin=OWNER_VIN, title="Oil", maintenance_type="engine_oil_filter")
        reason = unsavable_reason(rule, {"engine_oil_filter"})
        assert reason is not None and "engine_oil_filter" in reason

    def test_an_ordinary_rule_is_fine(self):
        rule = MaintenanceRule(vin=OWNER_VIN, title="Oil", maintenance_type="engine_oil_filter")
        assert unsavable_reason(rule, set()) is None


@pytest.mark.integration
class TestAWronglyShapedVehicleTypesColumn:
    """`vehicle_types` is a JSON column, so a hand-edited row can hand the
    service any JSON value, not just a list of strings. Anything that is not a
    list of types means "offer this pack for every type", because a pack list
    that 500s is worse than a pack that is offered too widely.

    Valid JSON of the wrong shape is the only case left to defend: bytes that are
    not JSON at all now raise while the row loads, which is the trade recorded in
    `_vehicle_types`.
    """

    def test_a_json_object_means_every_type(self):
        row = _pack(None)
        row.vehicle_types = {"Truck": True}  # type: ignore[assignment]
        assert _vehicle_types(row) == []

    def test_a_bare_string_means_every_type(self):
        # Not a list of one type: `"Truck"` would otherwise iterate as letters.
        row = _pack(None)
        row.vehicle_types = "Truck"  # type: ignore[assignment]
        assert _vehicle_types(row) == []

    def test_non_string_entries_are_dropped_and_the_rest_kept(self):
        row = _pack(None)
        row.vehicle_types = ["Truck", 7, None, "Boat"]  # type: ignore[list-item]
        assert _vehicle_types(row) == ["Truck", "Boat"]


@pytest.mark.integration
class TestTheCustomNamespace:
    def test_no_shipped_pack_could_collide_with_a_saved_one(self):
        """The `custom-` prefix is what makes a collision impossible rather than
        something to check at runtime. That only holds while no shipped file
        claims the prefix, so this asserts the invariant the design rests on."""
        stems = [path.stem for path in PACKS_DIR.glob("*.json")]
        assert stems, "no built-in packs found; the glob or the directory moved"
        assert [stem for stem in stems if stem.startswith("custom-")] == []

    def test_a_long_name_still_fits_the_column_that_records_it(self):
        """`vehicle_maintenance_rules.source_pack_id` is VARCHAR(64), and a
        truncated id there would break the link from a rule back to its pack."""
        assert len(custom_pack_id("Very " * 40 + "Long Name")) <= 64

    def test_a_name_with_no_letters_has_no_slug(self):
        assert pack_slug("???") == ""
        assert custom_pack_id("???") == ""

    def test_the_slug_is_url_shaped(self):
        assert custom_pack_id("Truck & Trailer Standard") == "custom-truck-trailer-standard"


@pytest.mark.integration
@pytest.mark.asyncio
class TestPublishingNeedsWriteAccess:
    async def test_a_read_share_cannot_publish_the_owners_schedule(
        self, db_session, pack_owner, pack_stranger
    ):
        """Being allowed to LOOK at someone else's shared vehicle is not consent
        to publish its schedule to every user of the instance, which is what
        saving a pack does."""
        db_session.add(
            Vehicle(vin=OWNER_VIN, user_id=pack_owner.id, nickname="Theirs", vehicle_type="Truck")
        )
        await db_session.commit()
        rule = MaintenanceRule(
            vin=OWNER_VIN,
            maintenance_type="engine_oil_filter",
            title="Oil",
            interval_months=6,
            source="manual",
        )
        db_session.add(rule)
        db_session.add(
            VehicleShare(
                vehicle_vin=OWNER_VIN,
                user_id=pack_stranger.id,
                permission="read",
                shared_by=pack_owner.id,
            )
        )
        await db_session.commit()
        await db_session.refresh(rule)

        request = SaveReminderPackRequest(vin=OWNER_VIN, name="Theirs", rule_ids=[rule.id])
        with pytest.raises(HTTPException) as refused:
            await reminder_pack_service.save_pack_from_vehicle(db_session, request, pack_stranger)
        assert refused.value.status_code == 403

    async def test_deleting_the_creator_leaves_the_pack_behind(self, db_session, pack_owner):
        """ON DELETE SET NULL, not CASCADE: a departing user must not take the
        household's standard with them."""
        row = ReminderPack(
            pack_id="custom-keepme",
            name="Keep Me",
            description="",
            vehicle_types=[],
            created_by_user_id=pack_owner.id,
        )
        db_session.add(row)
        await db_session.commit()

        await db_session.delete(pack_owner)
        await db_session.commit()

        result = await db_session.execute(
            select(ReminderPack)
            .where(ReminderPack.pack_id == "custom-keepme")
            # The identity map would hand back the pre-delete row and the
            # assertion would read stale state rather than the database.
            .execution_options(populate_existing=True)
        )
        survivor = result.scalars().unique().one()
        assert survivor.created_by_user_id is None
