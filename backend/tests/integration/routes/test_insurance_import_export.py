"""Household insurance through the import and export routes.

The export is per VEHICLE (its columns never changed), so the interesting
property is that importing two vehicles' files rebuilds ONE household policy,
and that an import can never rewrite money already recorded on a policy.
"""

import csv
import io
import json
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.vehicle import Vehicle
from app.schemas._money import MONEY_MAX

RAM = "INSIMPEXP00000001"
MIRAGE = "INSIMPEXP00000002"
HEADER = (
    "Provider,Policy Number,Type,Start Date,End Date,Premium,Premium Frequency,"
    "Deductible,Coverage Limits,Notes"
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture(autouse=True)
async def garage(db_session: AsyncSession, test_user):
    await db_session.execute(delete(InsurancePolicy))
    for vin, nickname in ((RAM, "Ram"), (MIRAGE, "Mirage")):
        existing = (
            await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
        ).scalar_one_or_none()
        if existing is None:
            db_session.add(
                Vehicle(vin=vin, user_id=test_user["id"], nickname=nickname, vehicle_type="Car")
            )
    await db_session.commit()
    yield
    await db_session.execute(delete(InsurancePolicy))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([RAM, MIRAGE])))
    await db_session.commit()


async def _import_csv(client: AsyncClient, headers, vin: str, *rows: str) -> dict:
    body = "\n".join([HEADER, *rows]) + "\n"
    response = await client.post(
        f"/api/import/vehicles/{vin}/insurance/csv",
        files={"file": ("insurance.csv", body, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _policies(db: AsyncSession) -> list[InsurancePolicy]:
    result = await db.execute(
        select(InsurancePolicy)
        .order_by(InsurancePolicy.id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars().unique().all())


def _shares(policy: InsurancePolicy) -> dict[str, Decimal | None]:
    return {link.vin: link.premium_share for link in policy.vehicle_links}


ROW = "Progressive,P-100,{type},2026-01-01,2026-07-01,{premium},Semi-Annual,{deductible},,{notes}"


async def test_two_vehicles_files_rebuild_one_household_policy(client, db_session, auth_headers):
    first = await _import_csv(
        client,
        auth_headers,
        RAM,
        ROW.format(type="Full Coverage", premium="320.00", deductible="500.00", notes="truck"),
    )
    second = await _import_csv(
        client,
        auth_headers,
        MIRAGE,
        ROW.format(type="Liability", premium="280.00", deductible="", notes=""),
    )
    assert (first["success_count"], second["success_count"]) == (1, 1), (first, second)

    policies = await _policies(db_session)
    assert len(policies) == 1, "the same policy on two vehicles is ONE policy"
    assert policies[0].premium_amount == Decimal("600.00")
    assert _shares(policies[0]) == {RAM: Decimal("320.00"), MIRAGE: Decimal("280.00")}
    ram_link = next(link for link in policies[0].vehicle_links if link.vin == RAM)
    assert (ram_link.policy_type, ram_link.deductible, ram_link.notes) == (
        "Full Coverage",
        Decimal("500.00"),
        "truck",
    )


async def test_the_export_round_trips_each_vehicles_own_numbers(client, db_session, auth_headers):
    await _import_csv(
        client,
        auth_headers,
        RAM,
        ROW.format(type="Full Coverage", premium="320.00", deductible="500.00", notes=""),
    )
    await _import_csv(
        client,
        auth_headers,
        MIRAGE,
        ROW.format(type="Liability", premium="280.00", deductible="", notes=""),
    )

    exported = await client.get(
        f"/api/export/vehicles/{MIRAGE}/insurance/csv", headers=auth_headers
    )
    assert exported.status_code == 200
    await db_session.execute(delete(InsurancePolicy))
    await db_session.commit()

    response = await client.post(
        f"/api/import/vehicles/{MIRAGE}/insurance/csv",
        files={"file": ("insurance.csv", exported.text, "text/csv")},
        headers=auth_headers,
    )
    assert response.json()["error_count"] == 0, response.json()

    (policy,) = await _policies(db_session)
    assert _shares(policy) == {MIRAGE: Decimal("280.00")}
    assert policy.vehicle_links[0].policy_type == "Liability"


async def test_importing_again_is_a_duplicate_not_a_second_link(client, db_session, auth_headers):
    row = ROW.format(type="Full Coverage", premium="320.00", deductible="", notes="")
    await _import_csv(client, auth_headers, RAM, row)
    again = await _import_csv(client, auth_headers, RAM, row)

    assert again["skipped_count"] == 1
    (policy,) = await _policies(db_session)
    assert policy.premium_amount == Decimal("320.00")


async def test_an_import_never_rewrites_money_already_on_a_policy(
    client, db_session, auth_headers, test_user
):
    # A policy priced 600 whose one vehicle takes the computed (unset) share.
    existing = InsurancePolicy(
        provider="Progressive",
        policy_number="P-100",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
        premium_amount=Decimal("600.00"),
        premium_frequency="Semi-Annual",
        created_by_user_id=test_user["id"],
    )
    existing.vehicle_links.append(InsurancePolicyVehicle(vin=RAM, policy_type="Full Coverage"))
    db_session.add(existing)
    await db_session.commit()

    await _import_csv(
        client,
        auth_headers,
        MIRAGE,
        ROW.format(type="Liability", premium="280.00", deductible="", notes=""),
    )

    (policy,) = await _policies(db_session)
    # The Ram's effective share was 600 and must still be: (880 - 280) / 1.
    assert policy.premium_amount == Decimal("880.00")
    assert _shares(policy) == {RAM: None, MIRAGE: Decimal("280.00")}


async def test_a_blank_premium_stays_unknown_and_never_dilutes_a_priced_policy(
    client, db_session, auth_headers, test_user
):
    existing = InsurancePolicy(
        provider="Progressive",
        policy_number="P-100",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
        premium_amount=Decimal("600.00"),
        premium_frequency="Semi-Annual",
        created_by_user_id=test_user["id"],
    )
    existing.vehicle_links.append(InsurancePolicyVehicle(vin=RAM, policy_type="Full Coverage"))
    db_session.add(existing)
    await db_session.commit()

    await _import_csv(
        client,
        auth_headers,
        MIRAGE,
        ROW.format(type="Liability", premium="", deductible="", notes=""),
    )

    policies = await _policies(db_session)
    assert len(policies) == 2, "an unset share on the priced policy would halve the Ram's"
    priced, unknown = policies
    assert (priced.premium_amount, _shares(priced)) == (Decimal("600.00"), {RAM: None})
    assert unknown.premium_amount is None, "unknown must not become 0.00"
    assert _shares(unknown) == {MIRAGE: None}


async def test_the_json_backup_carries_insurance_with_named_fields_at_both_levels(
    client, db_session, auth_headers
):
    created = await client.post(
        "/api/insurance/policies",
        json={
            "provider": "Progressive",
            "policy_number": "P-JSON",
            "start_date": "2026-01-01",
            "end_date": "2026-07-01",
            "premium_amount": "600.00",
            "premium_frequency": "Semi-Annual",
            "fields": [{"label": "Agent Phone", "value": "555-0100"}],
            "vehicles": [
                {
                    "vin": RAM,
                    "policy_type": "Full Coverage",
                    "deductible": "500.00",
                    "fields": [{"label": "Collision Deductible", "value": "$500"}],
                },
                {"vin": MIRAGE, "policy_type": "Liability"},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    exported = await client.get(f"/api/export/vehicles/{RAM}/json", headers=auth_headers)
    backup = exported.json()
    assert backup["export_version"] == "9"
    (entry,) = backup["insurance_policies"]
    assert entry["premium_share"] == 300.0, "the vehicle's EFFECTIVE share, not the policy total"

    await db_session.execute(delete(InsurancePolicy))
    await db_session.commit()
    restored = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["insurance_policies"]["success"] == 1, restored.json()

    (policy,) = await _policies(db_session)
    assert [(f.label, f.value) for f in policy.fields] == [("Agent Phone", "555-0100")]
    (link,) = policy.vehicle_links
    assert (link.vin, link.premium_share, link.deductible) == (
        RAM,
        Decimal("300.00"),
        Decimal("500.00"),
    )
    assert [(f.label, f.value) for f in link.fields] == [("Collision Deductible", "$500")]


async def test_an_import_never_joins_another_owners_policy(
    client, db_session, auth_headers, non_admin_user
):
    # CB-R1-H4: the migration keeps owners apart; the importer did not. The
    # importing user here is an ADMIN, who can see and write every policy.
    other = "INSIMPEXP00000003"
    db_session.add(
        Vehicle(vin=other, user_id=non_admin_user["id"], nickname="Theirs", vehicle_type="Car")
    )
    theirs = InsurancePolicy(
        provider="Progressive",
        policy_number="P-100",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
        premium_amount=Decimal("500.00"),
        premium_frequency="Semi-Annual",
        created_by_user_id=non_admin_user["id"],
    )
    theirs.vehicle_links.append(InsurancePolicyVehicle(vin=other, policy_type="Liability"))
    db_session.add(theirs)
    await db_session.commit()
    try:
        await _import_csv(
            client,
            auth_headers,
            RAM,
            ROW.format(type="Full Coverage", premium="320.00", deductible="", notes=""),
        )

        policies = await _policies(db_session)
        assert len(policies) == 2, "a look-alike policy of another owner is not this one"
        assert {tuple(sorted(_shares(p))) for p in policies} == {(other,), (RAM,)}
        untouched = next(p for p in policies if other in _shares(p))
        assert untouched.premium_amount == Decimal("500.00")
    finally:
        await db_session.execute(delete(InsurancePolicy))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == other))
        await db_session.commit()


async def test_the_json_backup_keeps_the_date_a_vehicle_left_the_policy(
    client, db_session, auth_headers
):
    # CB-R1-H5: a restore put a vehicle that LEFT the policy back on it for
    # the whole term.
    policy = InsurancePolicy(
        provider="Progressive",
        policy_number="P-LEFT",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 1),
    )
    policy.vehicle_links.append(
        InsurancePolicyVehicle(vin=RAM, policy_type="Liability", effective_to=date(2026, 3, 1))
    )
    db_session.add(policy)
    await db_session.commit()

    backup = (await client.get(f"/api/export/vehicles/{RAM}/json", headers=auth_headers)).json()
    assert backup["insurance_policies"][0]["effective_to"] == "2026-03-01"

    await db_session.execute(delete(InsurancePolicy))
    await db_session.commit()
    await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )

    (restored,) = await _policies(db_session)
    assert restored.vehicle_links[0].effective_to == date(2026, 3, 1)


async def test_the_importers_refuse_a_fraction_of_a_cent(client, db_session, auth_headers):
    # CB-R1-H3: the API schema's whole-cents rule does not reach an importer,
    # which builds ORM rows directly. Two 0.005 rows summed to a 0.01 premium
    # and were then STORED as two 0.01 shares.
    result = await _import_csv(
        client,
        auth_headers,
        RAM,
        ROW.format(type="Full Coverage", premium="0.005", deductible="", notes=""),
        ROW.format(type="Full Coverage", premium="10.00", deductible="0.001", notes="").replace(
            "P-100", "P-101"
        ),
    )
    assert result["success_count"] == 0 and result["error_count"] == 2, result
    assert "whole number of cents" in " ".join(result["errors"])
    assert await _policies(db_session) == []

    backup = {
        "export_version": "7",
        "units": "metric",
        "vehicle": {"vin": RAM},
        "insurance_policies": [
            {
                "provider": "Progressive",
                "policy_number": "P-JSONCENT",
                "start_date": "2026-01-01",
                "end_date": "2026-07-01",
                "policy_type": "Liability",
                "premium_share": 0.005,
            }
        ],
    }
    restored = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["insurance_policies"]["errors"] == 1, restored.json()
    assert await _policies(db_session) == []


async def test_the_json_backup_carries_the_standard_coverages(
    client: AsyncClient, db_session: AsyncSession, auth_headers
):
    """A restore has to reproduce the coverage rows, not just their totals."""
    created = await client.post(
        "/api/insurance/policies",
        json={
            "provider": "Progressive",
            "policy_number": "P-COV",
            "start_date": "2026-01-01",
            "end_date": "2026-07-01",
            "premium_amount": "600.00",
            "premium_frequency": "Semi-Annual",
            "vehicles": [
                {
                    "vin": RAM,
                    "policy_type": "Full Coverage",
                    "coverages": [
                        {
                            "coverage_key": "bodily_injury",
                            "limit_primary": "100000.00",
                            "limit_secondary": "300000.00",
                            "premium": "55.00",
                        },
                        {"coverage_key": "roadside_assistance"},
                    ],
                }
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    backup = (await client.get(f"/api/export/vehicles/{RAM}/json", headers=auth_headers)).json()
    (entry,) = backup["insurance_policies"]
    assert [c["coverage_key"] for c in entry["coverages"]] == [
        "bodily_injury",
        "roadside_assistance",
    ]

    await db_session.execute(delete(InsurancePolicy))
    await db_session.commit()
    restored = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert restored.status_code == 200, restored.text

    policies = await _policies(db_session)
    (link,) = policies[0].vehicle_links
    rows = {c.coverage_key: c for c in link.coverages}
    assert set(rows) == {"bodily_injury", "roadside_assistance"}
    assert rows["bodily_injury"].limit_secondary == Decimal("300000.00")
    assert rows["bodily_injury"].premium == Decimal("55.00")
    assert rows["roadside_assistance"].premium is None


async def test_a_version_7_backup_converts_its_coverage_text(
    client: AsyncClient, db_session: AsyncSession, auth_headers
):
    """The release before this one wrote one text box. Restoring that file has
    to land the same rows an in-place upgrade (migration 108) would have."""
    backup = {
        "export_version": "7",
        "units": "metric",
        "vehicle": {"vin": RAM},
        "insurance_policies": [
            {
                "provider": "Progressive",
                "policy_number": "P-LEGACY",
                "start_date": "2026-01-01",
                "end_date": "2026-07-01",
                "policy_type": "Full Coverage",
                "premium_share": 600.0,
                "coverage_limits": (
                    "Bodily Injury Liability $100,000 each person/$300,000 each accident\n"
                    "Roadside Assistance\n"
                    "Roof Protection Plus $5,000\n"
                    "Disappearing Deductibles"
                ),
            }
        ],
    }
    restored = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert restored.status_code == 200, restored.text

    policies = await _policies(db_session)
    (link,) = policies[0].vehicle_links
    rows = {c.coverage_key: c for c in link.coverages}
    assert set(rows) == {"bodily_injury", "roadside_assistance"}
    assert rows["bodily_injury"].limit_primary == Decimal("100000.00")
    # Parity with migration 108, which is what the docstring promises: a
    # priced leftover becomes a named field, an unpriced one stays prose.
    assert [(f.label, f.value) for f in link.fields] == [("Roof Protection Plus", "$5,000")]
    assert link.notes == "Disappearing Deductibles"


async def test_the_csv_column_round_trips_the_coverages(
    client: AsyncClient, db_session: AsyncSession, auth_headers
):
    """The flat export keeps its Coverage Limits column, now written from the
    rows and read back through the same parser: no amount may move."""
    limits = "Bodily Injury Liability $100,000 each person/$300,000 each accident"
    row = (
        "Progressive,P-CSV,Full Coverage,2026-01-01,2026-07-01,600.00,Semi-Annual,"
        f'500.00,"{limits}",imported'
    )
    await _import_csv(client, auth_headers, RAM, row)

    exported = await client.get(f"/api/export/vehicles/{RAM}/insurance/csv", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    # The "$" file above goes back out bare, like the Premium and Deductible
    # cells beside it, and the bare file is what re-imports below.
    (exported_row,) = list(csv.DictReader(io.StringIO(exported.text)))
    assert exported_row["Coverage Limits"] == (
        "Bodily Injury Liability 100000.00 each person/300000.00 each accident"
    )

    await db_session.execute(delete(InsurancePolicy))
    await db_session.commit()
    response = await client.post(
        f"/api/import/vehicles/{RAM}/insurance/csv",
        files={"file": ("insurance.csv", exported.text, "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text

    policies = await _policies(db_session)
    (link,) = policies[0].vehicle_links
    (coverage,) = link.coverages
    assert coverage.coverage_key == "bodily_injury"
    assert (coverage.limit_primary, coverage.limit_secondary) == (
        Decimal("100000.00"),
        Decimal("300000.00"),
    )


async def test_an_import_refuses_a_coverage_amount_it_cannot_store(
    client: AsyncClient, db_session: AsyncSession, auth_headers
):
    """Importers build rows directly, so the API's slot rule is re-applied."""
    backup = {
        "export_version": "8",
        "units": "metric",
        "vehicle": {"vin": RAM},
        "insurance_policies": [
            {
                "provider": "Progressive",
                "policy_number": "P-BADSLOT",
                "start_date": "2026-01-01",
                "end_date": "2026-07-01",
                "policy_type": "Liability",
                "coverages": [{"coverage_key": "collision", "limit_primary": 100.0}],
            }
        ],
    }
    response = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["insurance_policies"]["errors"] == 1, response.json()
    assert await _policies(db_session) == []


async def test_an_import_refuses_a_fractional_count(
    client: AsyncClient, db_session: AsyncSession, auth_headers
):
    """A count slot is a number of days, not money.

    30.5 satisfies the whole-cents rule that guards the money slots, so it used
    to be stored, and the flat exports write a count with no decimals: the next
    export of this policy said 30 without anyone touching it.
    """
    backup = {
        "export_version": "8",
        "units": "metric",
        "vehicle": {"vin": RAM},
        "insurance_policies": [
            {
                "provider": "Progressive",
                "policy_number": "P-HALFDAY",
                "start_date": "2026-01-01",
                "end_date": "2026-07-01",
                "policy_type": "Liability",
                "coverages": [
                    {
                        "coverage_key": "rental_reimbursement",
                        "limit_primary": 50.0,
                        "limit_secondary": 30.5,
                    }
                ],
            }
        ],
    }
    response = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["insurance_policies"]["errors"] == 1, response.json()
    assert await _policies(db_session) == []


# ---------------------------------------------------------------------------
# Amounts past the column (Plan B, B4)
# ---------------------------------------------------------------------------

TOO_MUCH = str(MONEY_MAX + Decimal("0.01"))
BIG_LIMITS = "Bodily Injury Liability $100,000,000,000 each person/$300,000 each accident"


async def _fresh_policies(sessionmaker) -> list[tuple[Decimal | None, set[str]]]:
    """(premium, vins) per policy, read through a session the import never touched."""
    async with sessionmaker() as session:
        policies = (
            (await session.execute(select(InsurancePolicy).order_by(InsurancePolicy.id)))
            .scalars()
            .unique()
            .all()
        )
        return [(p.premium_amount, {link.vin for link in p.vehicle_links}) for p in policies]


async def test_an_import_past_the_column_says_why(client, auth_headers, test_sessionmaker):
    """The reason reaches the row error in BOTH insurance importers. The CSV
    loop only caught its own row error ahead of a generic one (Codex R1-F5),
    and the JSON loop turned every reason into "could not be imported" (Fable
    F-B7)."""
    result = await _import_csv(
        client,
        auth_headers,
        RAM,
        ROW.format(type="Liability", premium=TOO_MUCH, deductible="", notes=""),
        ROW.format(type="Liability", premium="10.00", deductible=TOO_MUCH, notes="").replace(
            "P-100", "P-101"
        ),
        f'Progressive,P-102,Liability,2026-01-01,2026-07-01,10.00,Semi-Annual,,"{BIG_LIMITS}",',
    )
    assert result["success_count"] == 0 and result["error_count"] == 3, result
    premium, deductible, limit = result["errors"]
    assert f"premium_share must be at most {MONEY_MAX}" in premium, premium
    assert f"deductible must be at most {MONEY_MAX}" in deductible, deductible
    assert f"limit_primary must be at most {MONEY_MAX}" in limit, limit
    assert await _fresh_policies(test_sessionmaker) == []

    entry = {
        "provider": "Progressive",
        "start_date": "2026-01-01",
        "end_date": "2026-07-01",
        "policy_type": "Liability",
    }
    backup = {
        "export_version": "8",
        "units": "metric",
        "vehicle": {"vin": RAM},
        "insurance_policies": [
            {**entry, "policy_number": "P-J1", "premium_share": float(TOO_MUCH)},
            {
                **entry,
                "policy_number": "P-J2",
                "coverages": [{"coverage_key": "bodily_injury", "limit_primary": 1e11}],
            },
            # A reason of the importer's own, which the JSON loop lost too.
            {**entry, "policy_number": "P-J3", "premium_share": 0.005},
        ],
    }
    restored = await client.post(
        f"/api/import/vehicles/{RAM}/json",
        files={
            "file": ("backup.json", io.BytesIO(json.dumps(backup).encode()), "application/json")
        },
        headers=auth_headers,
    )
    assert restored.status_code == 200, restored.text
    data = restored.json()
    assert data["insurance_policies"]["errors"] == 3, data
    over, coverage, cents = data["errors"]
    assert f"premium_share must be at most {MONEY_MAX}" in over, over
    assert f"limit_primary must be at most {MONEY_MAX}" in coverage, coverage
    assert "whole number of cents" in cents, cents
    assert await _fresh_policies(test_sessionmaker) == []


async def test_premiums_that_sum_past_the_column_fail_the_row_that_tips_it(
    client, auth_headers, test_sessionmaker
):
    """Each vehicle's premium fits; together on one household policy they don't."""
    first = await _import_csv(
        client,
        auth_headers,
        RAM,
        ROW.format(type="Liability", premium=str(MONEY_MAX), deductible="", notes=""),
    )
    assert first["success_count"] == 1, first

    second = await _import_csv(
        client,
        auth_headers,
        MIRAGE,
        ROW.format(type="Liability", premium="0.01", deductible="", notes=""),
    )
    assert second["success_count"] == 0 and second["error_count"] == 1, second
    assert "policy premium would exceed the largest amount" in second["errors"][0], second

    assert await _fresh_policies(test_sessionmaker) == [(MONEY_MAX, {RAM})]
