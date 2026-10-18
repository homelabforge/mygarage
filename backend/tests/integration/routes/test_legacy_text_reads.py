"""A stored string outside today's input rules reads back.

The number and vocabulary suites' sibling, for text. A length or pattern rule,
or an email check, on a response refuses a stored value the same way a bound
does, and turns every read of the record into a 500. PostgreSQL holds a string
to its column's width at write time and SQLite doesn't, and SSO sign-in, the
importers and the sticker OCR write some of these columns without the input
schema. So each row is written straight through the ORM and read back through
its real routes.

A string past its column's width only fits on SQLite, so those cases skip on
PostgreSQL.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address_book import AddressBookEntry
from app.models.insurance import InsurancePolicy, InsurancePolicyField, InsurancePolicyVehicle
from app.models.reminder import Reminder
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.services.auth import create_access_token
from app.utils.household_time import household_today
from tests.integration.routes._legacy_reads import read_ok

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DAY = date(2020, 1, 1)
EMPTY_LABEL = [{"label": "", "value": "x"}]


def _skip_unless_sqlite(db: AsyncSession) -> None:
    if db.get_bind().dialect.name != "sqlite":
        pytest.skip("only SQLite stores a string past its column's width")


async def _policy_with_empty_labels(
    db: AsyncSession, vin: str, user_id: int, levels: tuple[str, ...]
) -> int:
    """A policy on the vehicle, with an empty-label field at each level asked
    for ("policy", "vehicle"). Returns its id."""
    today = household_today()
    policy = InsurancePolicy(
        provider="Legacy Mutual",
        policy_number="LEG-" + uuid.uuid4().hex[:8],
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=150),
        premium_amount=Decimal("600.00"),
        premium_frequency="Annual",
        created_by_user_id=user_id,
    )
    db.add(policy)
    await db.flush()
    policy_id = policy.id
    link = InsurancePolicyVehicle(policy_id=policy_id, vin=vin, policy_type="Full Coverage")
    db.add(link)
    await db.flush()
    for level in levels:
        db.add(
            InsurancePolicyField(
                policy_id=policy_id,
                policy_vehicle_id=link.id if level == "vehicle" else None,
                label="",
                value="x",
            )
        )
    await db.commit()
    return policy_id


async def _drop_policies(db: AsyncSession, ids: list[int]) -> None:
    # Not the vehicle's: a policy outlives its vehicles. Links and fields cascade.
    await db.rollback()
    await db.execute(delete(InsurancePolicy).where(InsurancePolicy.id.in_(ids)))
    await db.commit()


async def test_sso_account_with_a_short_name_and_a_local_email(client, db_session):
    """SSO auto-create keeps the identity provider's username and email as given."""
    taken = or_(User.username == "jo", User.email == "bob@corp.local")
    # A failed earlier run leaves its row behind, and both columns are unique.
    await db_session.execute(delete(User).where(taken))
    await db_session.commit()
    user = User(
        username="jo",
        email="bob@corp.local",
        hashed_password=None,
        auth_method="oidc",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id
    try:
        token = create_access_token(data={"sub": str(user_id), "username": "jo"})
        me = await read_ok(client, {"Authorization": f"Bearer {token}"}, "/api/auth/me")
        assert (me["username"], me["email"]) == ("jo", "bob@corp.local")
    finally:
        await db_session.rollback()
        await db_session.execute(delete(User).where(User.id == user_id))
        await db_session.commit()


async def test_address_book_email_at_a_local_domain(client, auth_headers, db_session):
    entry = AddressBookEntry(business_name="Corner Garage", email="shop@garage.local")
    db_session.add(entry)
    await db_session.commit()
    entry_id = entry.id
    try:
        body = await read_ok(client, auth_headers, f"/api/address-book/{entry_id}")
        assert body["email"] == "shop@garage.local"
    finally:
        await db_session.rollback()
        await db_session.execute(delete(AddressBookEntry).where(AddressBookEntry.id == entry_id))
        await db_session.commit()


async def test_policy_field_with_an_empty_label(
    client, auth_headers, db_session, own_vehicle, test_user
):
    vin = own_vehicle.vin
    policy_id = await _policy_with_empty_labels(
        db_session, vin, test_user["id"], ("policy", "vehicle")
    )
    try:
        one = await read_ok(client, auth_headers, f"/api/insurance/policies/{policy_id}")
        (by_vehicle,) = await read_ok(client, auth_headers, f"/api/vehicles/{vin}/insurance")
        for body in (one, by_vehicle):
            assert body["fields"] == EMPTY_LABEL
            assert body["vehicles"][0]["fields"] == EMPTY_LABEL
    finally:
        await _drop_policies(db_session, [policy_id])


async def test_long_colour(client, auth_headers, db_session, own_vehicle):
    _skip_unless_sqlite(db_session)
    vin = own_vehicle.vin
    own_vehicle.color = "x" * 100
    await db_session.commit()

    body = await read_ok(client, auth_headers, f"/api/vehicles/{vin}")
    assert body["color"] == "x" * 100
    listed = await read_ok(client, auth_headers, "/api/vehicles?limit=500")
    (mine,) = [v for v in listed["vehicles"] if v["vin"] == vin]
    assert mine["color"] == "x" * 100


async def test_long_line_item_description(client, auth_headers, db_session, own_vehicle):
    _skip_unless_sqlite(db_session)
    visit = ServiceVisit(vin=own_vehicle.vin, date=DAY)
    db_session.add(visit)
    await db_session.flush()
    db_session.add(ServiceLineItem(visit_id=visit.id, description="x" * 250))
    await db_session.commit()

    one = await read_ok(
        client, auth_headers, f"/api/vehicles/{own_vehicle.vin}/service-visits/{visit.id}"
    )
    assert one["line_items"][0]["description"] == "x" * 250


@pytest.mark.parametrize("level", ["policy", "vehicle"])
async def test_renewing_a_policy_with_an_empty_label_field(
    client, auth_headers, db_session, own_vehicle, test_user, level
):
    """Renewing copies each named field as stored, the way it copies the
    coverages. It used to run them through the input rules, so one empty label
    answered 500 and left the household with no next term."""
    policy_id = await _policy_with_empty_labels(
        db_session, own_vehicle.vin, test_user["id"], (level,)
    )
    renewed_id = None
    try:
        response = await client.post(
            f"/api/insurance/policies/{policy_id}/renew", json={}, headers=auth_headers
        )
        assert response.status_code == 201, response.text
        renewed = response.json()
        renewed_id = renewed["id"]
        assert renewed_id != policy_id
        carried = renewed["fields"] if level == "policy" else renewed["vehicles"][0]["fields"]
        assert carried == EMPTY_LABEL
    finally:
        await _drop_policies(db_session, [policy_id] + ([renewed_id] if renewed_id else []))


@pytest.mark.parametrize(
    ("mode", "title", "maintenance_type", "description"),
    [
        pytest.param("create_visit", "", None, "Completed reminder", id="create-empty"),
        pytest.param("create_visit", "x" * 250, None, "x" * 200, id="create-too-long"),
        pytest.param("link_visit", "", None, "Completed reminder", id="link-empty"),
        # Blank once stripped, so the type's own label stands in.
        pytest.param(
            "create_visit",
            "  ",
            "engine_oil_filter",
            "Engine oil and filter",
            id="create-blank-typed",
        ),
    ],
)
async def test_completing_a_reminder_whose_title_breaks_the_line_item_rules(
    client, auth_headers, db_session, own_vehicle, mode, title, maintenance_type, description
):
    """The import stores a reminder's title raw, and completing it writes that
    title onto a line item, whose rules it may break."""
    if len(title) > 200:
        _skip_unless_sqlite(db_session)
    vin = own_vehicle.vin
    today = household_today()
    reminder = Reminder(
        vin=vin,
        title=title,
        reminder_type="date",
        due_date=today,
        status="pending",
        maintenance_type=maintenance_type,
    )
    db_session.add(reminder)
    body: dict[str, object] = {"completed_date": today.isoformat()}
    if mode == "link_visit":
        visit = ServiceVisit(vin=vin, date=today)
        db_session.add(visit)
        await db_session.flush()
        body |= {"mode": "link_visit", "service_visit_id": visit.id}
    await db_session.commit()

    response = await client.post(
        f"/api/vehicles/{vin}/reminders/{reminder.id}/complete", json=body, headers=auth_headers
    )
    assert response.status_code == 200, response.text
    visit_id = response.json()["service_visit_id"]
    if mode == "link_visit":
        # Through the session, not the visit's GET: that read a stored "" as a
        # 500 of its own until the response dropped its min_length.
        stored = await db_session.execute(
            select(ServiceLineItem.description).where(ServiceLineItem.visit_id == visit_id)
        )
        assert stored.scalars().all() == [description]
    else:
        visit_read = await read_ok(
            client, auth_headers, f"/api/vehicles/{vin}/service-visits/{visit_id}"
        )
        assert [item["description"] for item in visit_read["line_items"]] == [description]


@pytest.mark.parametrize("mode", ["create_visit", "link_visit"])
async def test_completing_a_reminder_whose_stored_type_is_not_a_code(
    client, auth_headers, db_session, own_vehicle, mode
):
    """A hand edit or an old restore can leave free text in `maintenance_type`.

    Completing it fed that text to the strict line-item schema, whose
    `ValidationError` inside the handler was a 500 (EBR-5); the link mode wrote
    it onto the new line item instead. A stored non-code now falls back to the
    title's classification, as a reminder with no type does.
    """
    vin = own_vehicle.vin
    today = household_today()
    reminder = Reminder(
        vin=vin,
        title="Oil change",
        reminder_type="date",
        due_date=today,
        status="pending",
        maintenance_type="Oil Change",
    )
    db_session.add(reminder)
    body: dict[str, object] = {"completed_date": today.isoformat()}
    if mode == "link_visit":
        visit = ServiceVisit(vin=vin, date=today)
        db_session.add(visit)
        await db_session.flush()
        body |= {"mode": "link_visit", "service_visit_id": visit.id}
    await db_session.commit()

    response = await client.post(
        f"/api/vehicles/{vin}/reminders/{reminder.id}/complete", json=body, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    line_item_id = response.json()["line_item_id"]
    stored = await db_session.scalar(
        select(ServiceLineItem.maintenance_type).where(ServiceLineItem.id == line_item_id)
    )
    # Literal: what `classify("Oil change")` returns (test_maintenance_types.py).
    assert stored == "engine_oil_filter"
