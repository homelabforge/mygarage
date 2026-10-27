"""The v9 JSON sections: financing, tax, tolls, warranties, spot rentals, the vehicle (task 5)."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import TaxRecord, Vehicle, Vendor, WarrantyRecord
from app.models.financing import FinancingRecord
from app.models.spot_rental import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.toll import TollTag, TollTransaction

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _reset_limits() -> None:
    """The import and export limiters are per route; this module posts more than they allow."""
    from app.routes.export import limiter as export_limiter
    from app.routes.import_data import limiter as import_limiter

    export_limiter.reset()
    import_limiter.reset()


async def _vehicle(db_session: AsyncSession, owner_id: Any, vin: str, **fields: Any) -> str:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=owner_id,
            nickname=vin,
            vehicle_type="RV",
            year=2024,
            make="Test",
            model="Sections",
            **fields,
        )
    )
    await db_session.commit()
    return vin


async def _post_json(client: AsyncClient, headers: dict, vin: str, payload: dict) -> dict:
    r = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=headers,
        files={"file": ("vehicle.json", json.dumps(payload).encode(), "application/json")},
        data={"skip_duplicates": "true"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _seed_every_section(db_session: AsyncSession, vin: str) -> None:
    """One row of each new section, a tagged and an untagged toll, a rental with two bills."""
    lender = (
        await db_session.execute(select(Vendor).where(Vendor.name == "B3 Lender"))
    ).scalar() or Vendor(name="B3 Lender")
    db_session.add(lender)
    await db_session.flush()
    tag = TollTag(
        vin=vin, toll_system="EZ TAG", tag_number="B3TAG001", status="inactive", notes="old"
    )
    rental = SpotRental(
        vin=vin,
        location_name="B3 RV Park",
        location_address="1 Lake Rd",
        check_in_date=date(2026, 4, 1),
        check_out_date=date(2026, 6, 30),
        nightly_rate=Decimal("40.00"),
        weekly_rate=Decimal("250.00"),
        monthly_rate=Decimal("800.00"),
        electric=Decimal("30.00"),
        water=Decimal("10.00"),
        waste=Decimal("5.00"),
        total_cost=Decimal("2400.00"),
        amenities="wifi",
        notes="lakeside",
    )
    db_session.add_all(
        [
            FinancingRecord(
                vin=vin,
                vendor_id=lender.id,
                date=date(2026, 1, 15),
                amount=Decimal("450.00"),
                category="loan_payment",
                notes="jan",
            ),
            TaxRecord(
                vin=vin,
                date=date(2026, 2, 1),
                tax_type="Registration",
                amount=Decimal("120.00"),
                renewal_date=date(2027, 2, 1),
                notes="plates",
            ),
            tag,
            WarrantyRecord(
                vin=vin,
                warranty_type="Powertrain",
                provider="B3 Motors",
                start_date=date(2024, 1, 1),
                end_date=date(2029, 1, 1),
                mileage_limit_km=Decimal("160934.40"),
                coverage_details="engine",
                policy_number="PT-1",
                notes="factory",
            ),
            rental,
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            TollTransaction(
                vin=vin,
                toll_tag_id=tag.id,
                date=date(2026, 3, 1),
                amount=Decimal("2.50"),
                location="Hardy Toll Road",
                notes="commute",
            ),
            TollTransaction(
                vin=vin, date=date(2026, 3, 2), amount=Decimal("1.25"), location="Beltway 8"
            ),
            SpotRentalBilling(
                spot_rental_id=rental.id,
                billing_date=date(2026, 4, 1),
                monthly_rate=Decimal("800.00"),
                electric=Decimal("30.00"),
                water=Decimal("10.00"),
                waste=Decimal("5.00"),
                total=Decimal("845.00"),
                notes="april",
            ),
            SpotRentalBilling(
                spot_rental_id=rental.id,
                billing_date=date(2026, 5, 1),
                monthly_rate=Decimal("800.00"),
                electric=Decimal("25.00"),
                total=Decimal("825.00"),
            ),
        ]
    )
    await db_session.commit()


async def _restored(sessionmaker: Any, vin: str) -> dict[str, list[tuple]]:
    """Every new section's rows for `vin`, as plain tuples, through a fresh session."""
    async with sessionmaker() as fresh:

        async def rows(stmt: Any) -> list[Any]:
            return list((await fresh.execute(stmt)).scalars().all())

        financing = await rows(
            select(FinancingRecord)
            .where(FinancingRecord.vin == vin)
            .options(selectinload(FinancingRecord.vendor))
        )
        taxes = await rows(select(TaxRecord).where(TaxRecord.vin == vin))
        tags = await rows(select(TollTag).where(TollTag.vin == vin).order_by(TollTag.id))
        tolls = await rows(
            select(TollTransaction)
            .where(TollTransaction.vin == vin)
            .options(selectinload(TollTransaction.toll_tag))
            .order_by(TollTransaction.date)
        )
        warranties = await rows(select(WarrantyRecord).where(WarrantyRecord.vin == vin))
        rentals = await rows(
            select(SpotRental)
            .where(SpotRental.vin == vin)
            .options(selectinload(SpotRental.billings))
        )
    return {
        "financing": [
            (f.date, f.amount, f.category, f.vendor.name if f.vendor else None, f.notes)
            for f in financing
        ],
        "tax": [(t.date, t.tax_type, t.amount, t.renewal_date, t.notes) for t in taxes],
        "tags": [(t.toll_system, t.tag_number, t.status, t.notes) for t in tags],
        "tolls": [
            (t.date, t.amount, t.location, t.toll_tag.tag_number if t.toll_tag else None, t.notes)
            for t in tolls
        ],
        "warranties": [
            (
                w.warranty_type,
                w.provider,
                w.start_date,
                w.end_date,
                w.mileage_limit_km,
                w.coverage_details,
                w.policy_number,
                w.notes,
            )
            for w in warranties
        ],
        "rentals": [
            (
                r.location_name,
                r.location_address,
                r.check_in_date,
                r.check_out_date,
                r.nightly_rate,
                r.weekly_rate,
                r.monthly_rate,
                r.electric,
                r.water,
                r.waste,
                r.total_cost,
                r.amenities,
                r.notes,
                sorted(
                    (b.billing_date, b.monthly_rate, b.electric, b.water, b.waste, b.total, b.notes)
                    for b in r.billings
                ),
            )
            for r in rentals
        ],
    }


_EXPECTED = {
    "financing": [(date(2026, 1, 15), Decimal("450.00"), "loan_payment", "B3 Lender", "jan")],
    "tax": [(date(2026, 2, 1), "Registration", Decimal("120.00"), date(2027, 2, 1), "plates")],
    "tags": [("EZ TAG", "B3TAG001", "inactive", "old")],
    "tolls": [
        (date(2026, 3, 1), Decimal("2.50"), "Hardy Toll Road", "B3TAG001", "commute"),
        (date(2026, 3, 2), Decimal("1.25"), "Beltway 8", None, None),
    ],
    "warranties": [
        (
            "Powertrain",
            "B3 Motors",
            date(2024, 1, 1),
            date(2029, 1, 1),
            Decimal("160934.40"),
            "engine",
            "PT-1",
            "factory",
        )
    ],
    "rentals": [
        (
            "B3 RV Park",
            "1 Lake Rd",
            date(2026, 4, 1),
            date(2026, 6, 30),
            Decimal("40.00"),
            Decimal("250.00"),
            Decimal("800.00"),
            Decimal("30.00"),
            Decimal("10.00"),
            Decimal("5.00"),
            Decimal("2400.00"),
            "wifi",
            "lakeside",
            [
                (
                    date(2026, 4, 1),
                    Decimal("800.00"),
                    Decimal("30.00"),
                    Decimal("10.00"),
                    Decimal("5.00"),
                    Decimal("845.00"),
                    "april",
                ),
                (
                    date(2026, 5, 1),
                    Decimal("800.00"),
                    Decimal("25.00"),
                    None,
                    None,
                    Decimal("825.00"),
                    None,
                ),
            ],
        )
    ],
}

_NEW_SECTIONS = (
    "financing_records",
    "tax_records",
    "toll_tags",
    "toll_transactions",
    "warranties",
    "spot_rentals",
)


async def test_a_backup_round_trip_restores_every_new_section(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(db_session, test_user["id"], "B3RTSECTIONSRC001")
    target = await _vehicle(db_session, test_user["id"], "B3RTSECTIONDST001")
    await _seed_every_section(db_session, source)

    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    data = await _post_json(client, auth_headers, target, exported.json())
    # main: KeyError, no bucket for any of the six
    assert [data[s]["success_count"] for s in _NEW_SECTIONS] == [1, 1, 1, 2, 1, 1], data
    assert data["errors"] == [] and data["warnings"] == [], data
    assert await _restored(test_sessionmaker, target) == _EXPECTED

    again = await _post_json(client, auth_headers, target, exported.json())
    assert [again[s]["skipped_count"] for s in _NEW_SECTIONS] == [1, 1, 1, 2, 1, 1], again
    assert await _restored(test_sessionmaker, target) == _EXPECTED


async def test_a_row_the_api_would_refuse_is_a_row_error_and_the_rest_imports(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONBAD001")
    payload = {
        "export_version": "9",
        "units": "metric",
        "financing_records": [
            {"date": "2026-01-01", "amount": 10.0, "category": "lease", "vendor_name": None}
        ],
        "tax_records": [{"date": "2026-01-02", "tax_type": "Parking", "amount": 5.0}],
        "toll_tags": [
            {"toll_system": "EZ TAG", "tag_number": "B3LOST01", "status": "lost"},
            {"toll_system": "ezpass", "tag_number": "B3EZP001", "status": "active"},
        ],
        "toll_transactions": [
            {"date": "2026-01-03", "amount": 1.0, "location": "Plaza A", "toll_tag_index": 0},
            {"date": "2026-01-04", "amount": 2.0, "location": "Plaza B", "toll_tag_index": 1},
        ],
        "warranties": [{"provider": "Nobody", "start_date": "2026-01-01"}],
        "spot_rentals": [
            {
                "location_name": "Early Park",
                "check_in_date": "2026-02-01",
                "billings": [{"billing_date": "2026-01-15", "total": 10.0}],
            }
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # main: KeyError, none of the six sections is read
    assert data["errors"] == [
        "Financing record 0: category must be one of lease_payment, loan_payment, upfront_fee",
        "Tax record 0: tax_type must be one of Registration, Inspection, Property Tax, Tolls",
        "Toll tag 0: status must be one of active, inactive",
        "Warranty 0: warranty_type is missing",
        "Spot rental 0: billing 0: billing date cannot be before check-in date",
    ], data
    assert data["warnings"] == [
        "Toll transaction 0: its toll tag was not imported, saved without one"
    ], data
    restored = await _restored(test_sessionmaker, vin)
    # The spelling people type becomes the listed name, as the API does it.
    assert restored["tags"] == [("E-ZPass", "B3EZP001", "active", None)]
    assert restored["tolls"] == [
        (date(2026, 1, 3), Decimal("1.00"), "Plaza A", None, None),
        (date(2026, 1, 4), Decimal("2.00"), "Plaza B", "B3EZP001", None),
    ]
    assert restored["financing"] == restored["tax"] == restored["warranties"] == []
    assert restored["rentals"] == []

    # A re-import adds none: the toll whose tag failed keys as untagged, as it was stored.
    again = await _post_json(client, auth_headers, vin, payload)
    assert again["toll_transactions"]["skipped_count"] == 2, again
    assert len((await _restored(test_sessionmaker, vin))["tolls"]) == 2


async def test_the_vehicle_section_is_written_in_full_and_read_only_on_import(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    source = await _vehicle(
        db_session,
        test_user["id"],
        "B3RTSECTIONVEH001",
        exterior_color="Ruby Red",
        interior_color="Black",
        oil_viscosity="0W-20",
        purchase_price=Decimal("0"),
    )
    target = await _vehicle(db_session, test_user["id"], "B3RTSECTIONVEH002")
    exported = await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    vehicle = exported.json()["vehicle"]
    # main: KeyError (G1b-09: only the legacy `color` was written)
    assert (vehicle["exterior_color"], vehicle["interior_color"], vehicle["oil_viscosity"]) == (
        "Ruby Red",
        "Black",
        "0W-20",
    )
    # main: null (a $0 purchase price read as no price)
    assert vehicle["purchase_price"] == 0
    assert "user_id" not in vehicle and "main_photo" not in vehicle

    await _post_json(client, auth_headers, target, exported.json())
    async with test_sessionmaker() as fresh:
        kept = (await fresh.execute(select(Vehicle).where(Vehicle.vin == target))).scalar_one()
    assert (kept.exterior_color, kept.oil_viscosity, kept.nickname) == (None, None, target)


# -- R1-H1: rows that share the old coarse keys --------------------------------


async def test_two_identical_same_day_tolls_both_restore_and_a_reimport_adds_none(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Through one plaza twice in a day: two charges, not one."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONTOLL02")
    toll = {"date": "2026-03-05", "amount": 2.5, "location": "Hardy Toll Road", "notes": None}
    payload = {
        "export_version": "9",
        "units": "metric",
        "toll_tags": [],
        "toll_transactions": [{**toll, "toll_tag_index": None}, {**toll, "toll_tag_index": None}],
    }
    first = await _post_json(client, auth_headers, vin, payload)
    # main: KeyError, the section isn't read
    assert first["toll_transactions"]["success_count"] == 2, first
    again = await _post_json(client, auth_headers, vin, payload)
    assert again["toll_transactions"]["skipped_count"] == 2, again
    assert len((await _restored(test_sessionmaker, vin))["tolls"]) == 2


async def test_rows_sharing_the_old_keys_restore_beside_a_stored_match(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Each pair shares R5's first-draft key; the target already holds the first of each."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONPAIR01")
    db_session.add_all(
        [
            FinancingRecord(
                vin=vin, date=date(2026, 5, 1), amount=Decimal("100.00"), category="loan_payment"
            ),
            TaxRecord(
                vin=vin, date=date(2026, 5, 2), tax_type="Registration", amount=Decimal("50.00")
            ),
            WarrantyRecord(
                vin=vin,
                warranty_type="Extended",
                provider="B3 Pair Co",
                start_date=date(2026, 1, 1),
                end_date=date(2027, 1, 1),
            ),
            SpotRental(
                vin=vin,
                location_name="B3 Pair Park",
                check_in_date=date(2026, 6, 1),
                check_out_date=date(2026, 6, 30),
                total_cost=Decimal("500.00"),
            ),
        ]
    )
    await db_session.commit()
    payload = {
        "export_version": "9",
        "units": "metric",
        "financing_records": [
            {
                "date": "2026-05-01",
                "amount": 100.0,
                "category": "loan_payment",
                "vendor_name": None,
            },
            {
                "date": "2026-05-01",
                "amount": 100.0,
                "category": "loan_payment",
                "vendor_name": "B3 Pair Bank",
            },
        ],
        "tax_records": [
            {
                "date": "2026-05-02",
                "tax_type": "Registration",
                "amount": 50.0,
                "renewal_date": None,
            },
            {
                "date": "2026-05-02",
                "tax_type": "Registration",
                "amount": 75.0,
                "renewal_date": None,
            },
        ],
        "warranties": [
            {
                "warranty_type": "Extended",
                "provider": "B3 Pair Co",
                "start_date": "2026-01-01",
                "end_date": "2027-01-01",
                "policy_number": None,
                "mileage_limit_km": None,
            },
            {
                "warranty_type": "Extended",
                "provider": "B3 Pair Co",
                "start_date": "2026-01-01",
                "end_date": "2028-01-01",
                "policy_number": "EXT-2",
                "mileage_limit_km": None,
            },
        ],
        "spot_rentals": [
            {
                "location_name": "B3 Pair Park",
                "check_in_date": "2026-06-01",
                "check_out_date": "2026-06-30",
                "total_cost": 500.0,
                "billings": [],
            },
            {
                "location_name": "B3 Pair Park",
                "check_in_date": "2026-06-01",
                "check_out_date": "2026-07-31",
                "total_cost": 900.0,
                "billings": [{"billing_date": "2026-07-01", "total": 400.0}],
            },
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # main: KeyError, none of the four sections is read
    sections = ("financing_records", "tax_records", "warranties", "spot_rentals")
    assert [(data[s]["success_count"], data[s]["skipped_count"]) for s in sections] == [
        (1, 1),
        (1, 1),
        (1, 1),
        (1, 1),
    ], data
    restored = await _restored(test_sessionmaker, vin)
    assert sorted(f[3] or "" for f in restored["financing"]) == ["", "B3 Pair Bank"]
    assert sorted(t[2] for t in restored["tax"]) == [Decimal("50.00"), Decimal("75.00")]
    assert sorted(w[6] or "" for w in restored["warranties"]) == ["", "EXT-2"]
    assert sorted((r[3], r[13]) for r in restored["rentals"]) == [
        (date(2026, 6, 30), []),
        (
            date(2026, 7, 31),
            [(date(2026, 7, 1), None, None, None, None, Decimal("400.00"), None)],
        ),
    ]


# -- Fable F-1: a number stored past its column's scale still matches ----------


async def test_a_reimport_matches_a_mileage_limit_stored_past_its_scale(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """36,000 mi is 57936.384 km in a NUMERIC(10,2); a legacy SQLite row keeps it, the
    export writes 57936.38, and a re-import into the same vehicle must skip it (T-20).

    The ORM rounds at bind since #245, so the figure goes in through raw SQL. On
    PostgreSQL the column rounds it, so there the test passes either way.
    """
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONSCALE1")
    warranty = WarrantyRecord(
        vin=vin,
        warranty_type="Powertrain",
        provider="B3 Scale Co",
        start_date=date(2026, 1, 1),
        mileage_limit_km=Decimal("57936.38"),
    )
    db_session.add(warranty)
    await db_session.flush()
    await db_session.execute(
        text("UPDATE warranty_records SET mileage_limit_km = 57936.384 WHERE id = :id"),
        {"id": warranty.id},
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text

    data = await _post_json(client, auth_headers, vin, exported.json())
    # main: KeyError, no warranties section
    assert (data["warranties"]["success_count"], data["warranties"]["skipped_count"]) == (
        0,
        1,
    ), data


# -- R5: what SQL can't compare still tells two rows apart ----------------------


async def test_a_stored_row_does_not_swallow_one_with_another_lender_tag_or_bills(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """Each file row matches a stored one in every SQL key part and differs only in
    what the matcher compares on the loaded row: the lender, the tag, the bills."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONSAME01")
    lender = Vendor(name="B3 Same Lender A")
    tag = TollTag(vin=vin, toll_system="EZ TAG", tag_number="B3SAMEA1")
    rental = SpotRental(
        vin=vin,
        location_name="B3 Same Park",
        check_in_date=date(2026, 6, 1),
        check_out_date=date(2026, 6, 30),
        total_cost=Decimal("500.00"),
    )
    db_session.add_all([lender, tag, rental])
    await db_session.flush()
    db_session.add_all(
        [
            FinancingRecord(
                vin=vin,
                vendor_id=lender.id,
                date=date(2026, 5, 1),
                amount=Decimal("100.00"),
                category="loan_payment",
            ),
            TollTransaction(
                vin=vin,
                toll_tag_id=tag.id,
                date=date(2026, 5, 3),
                amount=Decimal("2.50"),
                location="B3 Same Plaza",
            ),
            SpotRentalBilling(
                spot_rental_id=rental.id, billing_date=date(2026, 6, 15), total=Decimal("250.00")
            ),
        ]
    )
    await db_session.commit()
    toll = {"date": "2026-05-03", "amount": 2.5, "location": "B3 Same Plaza", "notes": None}
    payload = {
        "export_version": "9",
        "units": "metric",
        "financing_records": [
            {
                "date": "2026-05-01",
                "amount": 100.0,
                "category": "loan_payment",
                "vendor_name": "B3 Same Lender B",
            }
        ],
        "toll_tags": [{"toll_system": "EZ TAG", "tag_number": "B3SAMEB1", "status": "active"}],
        "toll_transactions": [{**toll, "toll_tag_index": 0}, {**toll, "toll_tag_index": None}],
        "spot_rentals": [
            {
                "location_name": "B3 Same Park",
                "check_in_date": "2026-06-01",
                "check_out_date": "2026-06-30",
                "total_cost": 500.0,
                "billings": [{"billing_date": "2026-06-20", "total": 250.0}],
            }
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # main: KeyError, none of the sections is read
    sections = ("financing_records", "toll_transactions", "spot_rentals")
    assert [(data[s]["success_count"], data[s]["skipped_count"]) for s in sections] == [
        (1, 0),
        (2, 0),
        (1, 0),
    ], data
    restored = await _restored(test_sessionmaker, vin)
    assert sorted(f[3] for f in restored["financing"]) == ["B3 Same Lender A", "B3 Same Lender B"]
    assert sorted(t[3] or "" for t in restored["tolls"]) == ["", "B3SAMEA1", "B3SAMEB1"]
    assert sorted(r[13][0][0] for r in restored["rentals"]) == [
        date(2026, 6, 15),
        date(2026, 6, 20),
    ]


# -- R2: a value the API would refuse is a row error on every backend ----------


_ROW_ERRORS = [
    (
        "financing_records",
        {"date": "2026-01-01", "category": "lease_payment"},
        "Financing record 0: amount is missing",
    ),
    (
        "tax_records",
        {"date": "2026-01-01", "amount": -1.0},
        "Tax record 0: amount must be at least 0, not -1.0",
    ),
    (
        "tax_records",
        {"date": "2026-01-01", "amount": 1.0, "notes": 5},
        "Tax record 0: notes must be text",
    ),
    (
        "toll_tags",
        {"toll_system": "x" * 51, "tag_number": "B3LONG01"},
        "Toll tag 0: toll_system must be at most 50 characters",
    ),
    ("toll_tags", {"toll_system": "EZ TAG"}, "Toll tag 0: tag_number is missing"),
    (
        "toll_transactions",
        {"date": "2026-01-01", "amount": 1.0, "location": "x" * 201},
        "Toll transaction 0: location must be at most 200 characters",
    ),
    (
        "toll_transactions",
        {"date": "2026-01-01", "amount": 1.0, "location": "A", "toll_tag_index": True},
        "Toll transaction 0: toll_tag_index must be the index of a toll tag in this file",
    ),
    (
        "warranties",
        {"warranty_type": "Lifetime", "start_date": "2026-01-01"},
        "Warranty 0: warranty_type must be one of Manufacturer, Powertrain, Extended, "
        "Bumper-to-Bumper, Emissions, Corrosion, Other",
    ),
    (
        "spot_rentals",
        {"check_in_date": "2026-01-01", "billings": {}},
        "Spot rental 0: billings must be a list",
    ),
    (
        "spot_rentals",
        {"check_in_date": "2026-01-01", "billings": ["bill"]},
        "Spot rental 0: billing 0: must be an object",
    ),
    (
        "spot_rentals",
        {
            "check_in_date": "2026-01-01",
            "check_out_date": "2026-01-31",
            "billings": [{"billing_date": "2026-02-01"}],
        },
        "Spot rental 0: billing 0: billing date cannot be after check-out date",
    ),
]


@pytest.mark.parametrize(
    ("case", "section", "row", "error"),
    [(case, *row_error) for case, row_error in enumerate(_ROW_ERRORS)],
    ids=[f"{row_error[0]}-{case}" for case, row_error in enumerate(_ROW_ERRORS)],
)
async def test_a_value_the_column_cannot_hold_is_a_row_error(
    case: int,
    section: str,
    row: dict,
    error: str,
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session,
):
    vin = await _vehicle(db_session, test_user["id"], f"B3RTSECTIONTYP{case:03d}")
    payload = {"export_version": "9", "units": "metric", "toll_tags": [], section: [row]}
    data = await _post_json(client, auth_headers, vin, payload)
    # main: KeyError, the section isn't read
    assert (data[section]["error_count"], data["errors"]) == (1, [error]), data


# -- Fix round 1 -----------------------------------------------------------------


async def test_a_tag_stored_under_a_typed_spelling_matches_its_own_backup(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The tag update path stored "ezpass" as typed before it normalized; no migration
    renamed it. The export writes it as stored and the import reads it as "E-ZPass", so
    both sides are compared under the listed name."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONEZP001")
    tag = TollTag(vin=vin, toll_system="ezpass", tag_number="B3RAWEZ1", status="active")
    db_session.add(tag)
    await db_session.flush()
    db_session.add(
        TollTransaction(
            vin=vin,
            toll_tag_id=tag.id,
            date=date(2026, 3, 9),
            amount=Decimal("3.00"),
            location="I-95",
        )
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    assert exported.json()["toll_tags"][0]["toll_system"] == "ezpass"

    data = await _post_json(client, auth_headers, vin, exported.json())
    # caaaac47: (1, 0) and (1, 0), a second tag and its toll written again
    assert [
        (data[s]["success_count"], data[s]["skipped_count"])
        for s in ("toll_tags", "toll_transactions")
    ] == [(0, 1), (0, 1)], data
    restored = await _restored(test_sessionmaker, vin)
    assert restored["tags"] == [("ezpass", "B3RAWEZ1", "active", None)]
    assert len(restored["tolls"]) == 1


async def test_a_warranty_past_its_column_but_not_the_api_restores(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """WarrantyRecordCreate bounds neither provider nor policy number, and SQLite keeps
    a value past the String column, so a backup must restore what the API stored (R2)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONWLONG1")
    payload = {
        "export_version": "9",
        "units": "metric",
        "warranties": [
            {
                "warranty_type": "Other",
                "start_date": "2026-01-01",
                "provider": "p" * 101,
                "policy_number": "n" * 51,
            }
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # caaaac47: a row error, "provider must be at most 100 characters"
    assert (data["warranties"]["success_count"], data["errors"]) == (1, []), data
    restored = await _restored(test_sessionmaker, vin)
    assert [(w[1], w[6]) for w in restored["warranties"]] == [("p" * 101, "n" * 51)]


async def test_a_financing_lender_past_100_characters_restores_on_its_vendor(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """The CSV and v8 imports make vendors with no length cap and SQLite keeps the whole
    name. The lender is looked up by exact name, so it has to come back whole."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONLLONG1")
    long_name = "B3 Long Lender " + "v" * 86
    assert len(long_name) == 101
    lender = (
        await db_session.execute(select(Vendor).where(Vendor.name == long_name))
    ).scalar() or Vendor(name=long_name)
    db_session.add(lender)
    await db_session.commit()
    payload = {
        "export_version": "9",
        "units": "metric",
        "financing_records": [
            {
                "date": "2026-01-01",
                "amount": 1.0,
                "category": "lease_payment",
                "vendor_name": long_name,
            }
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # 30150423: a row error, "vendor_name must be at most 100 characters"
    assert (data["financing_records"]["success_count"], data["errors"]) == (1, []), data
    async with test_sessionmaker() as fresh:
        (record,) = (
            await fresh.execute(select(FinancingRecord).where(FinancingRecord.vin == vin))
        ).scalars()
        assert record.vendor_id == lender.id
    restored = await _restored(test_sessionmaker, vin)
    assert [f[3] for f in restored["financing"]] == [long_name]


async def test_a_rental_with_no_billings_key_writes_no_bills_and_keys_without_them(
    client: AsyncClient, auth_headers, test_user, db_session: AsyncSession, test_sessionmaker
):
    """T-16: an absent `billings` key is no bills to write and no bills to compare; a
    present one that isn't a list is still a row error (test_a_value_the_column_...)."""
    vin = await _vehicle(db_session, test_user["id"], "B3RTSECTIONNOBIL1")
    rental = SpotRental(vin=vin, location_name="B3 Billed Park", check_in_date=date(2026, 7, 1))
    db_session.add(rental)
    await db_session.flush()
    db_session.add(
        SpotRentalBilling(
            spot_rental_id=rental.id, billing_date=date(2026, 7, 5), total=Decimal("90.00")
        )
    )
    await db_session.commit()
    payload = {
        "export_version": "9",
        "units": "metric",
        "spot_rentals": [
            {"location_name": "B3 Billed Park", "check_in_date": "2026-07-01"},
            {"location_name": "B3 Bare Park", "check_in_date": "2026-08-01"},
        ],
    }
    data = await _post_json(client, auth_headers, vin, payload)
    # caaaac47: two row errors, "billings must be a list"
    rentals = data["spot_rentals"]
    assert (rentals["success_count"], rentals["skipped_count"], data["errors"]) == (1, 1, []), data
    restored = await _restored(test_sessionmaker, vin)
    assert sorted((r[0], len(r[13])) for r in restored["rentals"]) == [
        ("B3 Bare Park", 0),
        ("B3 Billed Park", 1),
    ]


@pytest.mark.parametrize(
    ("suffix", "moved_from", "moved_to"),
    [
        ("1", "monthly_rate", "electric"),
        ("2", "electric", "water"),
        ("3", "water", "waste"),
        ("4", "waste", "monthly_rate"),
    ],
)
async def test_a_bill_with_the_same_total_and_another_breakdown_imports(
    client: AsyncClient,
    auth_headers,
    test_user,
    db_session: AsyncSession,
    test_sessionmaker,
    suffix: str,
    moved_from: str,
    moved_to: str,
):
    """Same stay, same bill total, $5 moved between two lines: another rental (R1-H2)."""
    vin = await _vehicle(db_session, test_user["id"], f"B3RTSECTIONBREAK{suffix}")
    rental = SpotRental(
        vin=vin,
        location_name="B3 Breakdown Park",
        check_in_date=date(2026, 7, 1),
        check_out_date=date(2026, 7, 31),
        total_cost=Decimal("480.00"),
    )
    db_session.add(rental)
    await db_session.flush()
    db_session.add(
        SpotRentalBilling(
            spot_rental_id=rental.id,
            billing_date=date(2026, 7, 31),
            monthly_rate=Decimal("400.00"),
            electric=Decimal("50.00"),
            water=Decimal("20.00"),
            waste=Decimal("10.00"),
            total=Decimal("480.00"),
        )
    )
    await db_session.commit()
    exported = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    own_export = exported.json()
    (stored_rental,) = own_export["spot_rentals"]
    (bill,) = stored_rental["billings"]
    other_bill = {
        **bill,
        moved_from: float(Decimal(str(bill[moved_from])) - 5),
        moved_to: float(Decimal(str(bill[moved_to])) + 5),
    }
    other = {
        "export_version": own_export["export_version"],
        "units": own_export["units"],
        "spot_rentals": [{**stored_rental, "billings": [other_bill]}],
    }

    data = await _post_json(client, auth_headers, vin, other)
    # main: (0, 1), the bill compared by date and total alone
    rentals = data["spot_rentals"]
    assert (rentals["success_count"], rentals["skipped_count"]) == (1, 0), data
    again = await _post_json(client, auth_headers, vin, own_export)
    rentals = again["spot_rentals"]
    assert (rentals["success_count"], rentals["skipped_count"]) == (0, 1), again
    restored = await _restored(test_sessionmaker, vin)
    assert len(restored["rentals"]) == 2
