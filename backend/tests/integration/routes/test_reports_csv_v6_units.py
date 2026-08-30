"""What the two report CSVs put on the wire, in the caller's units (v6).

Issue #152 phase 2b task 5. `routes/reports.py` was the last CSV surface still
writing canonical kilometres and litres to every reader regardless of their
preferences, and the only render in that file that did not resolve a
`RenderContext` at all.

The rulings this pins
---------------------
- T5-R1: units come from `render_context_for_request`, so these are the
  CALLER's units and never the vehicle owner's, and no `?units=` parameter
  exists. Every caller below is an admin reading a vehicle someone else owns,
  which is what makes "caller's units" a discriminating claim rather than a
  restatement of "the owner's units".
- T5-R1 again: `show_both` is ignored, because R10 says cells are numeric.
  `test_show_both_never_reaches_a_cell` is the guard; it is why these tests
  route through `unit_adapters`' conversion layer and not
  `unit_formatting`'s composition layer.
- T5-R2: no `units_version` / `unit_system` column on either report. The
  units live in the header tokens.
- T5-R3/R4: the emitted header row is refused on import, by the guard derived
  from the very constants the endpoints emit from.
- T5-R5: one base name per quantity, so the service-history report's
  `Mileage` becomes `Odometer (<token>)`.
- T5-R6: the fuel `Description` stops carrying `f"{record.liters}L"`.

Hand-computed expectations
--------------------------
Factors are `UnitConverter`'s rounded constants, not the exact SI values.
Every literal below was computed BY HAND and never routed back through the
code under test.

  MILES_TO_KM           1.60934
  US_GALLONS_TO_LITERS  3.78541
  UK_GALLONS_TO_LITERS  4.54609

  12345.00 km / 1.60934 = 7670.846433...  -> "7670.846"  (3 dp)
    800.00 km / 1.60934 =  497.098189...  ->  "497.098"
    900.00 km / 1.60934 =  559.235463...  ->  "559.235"
   40.000 L  / 3.78541  =   10.566887...  ->  "10.5669"  (4 dp)
   20.000 L  / 3.78541  =    5.283443...  ->   "5.2834"
   40.000 L  / 4.54609  =    8.798769...  ->   "8.7988"
   20.000 L  / 4.54609  =    4.399384...  ->   "4.3994"

Tests share one database with no per-test rollback, so every row created here
is torn down in `finally`, and every username, email and VIN is scoped to this
module.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET, UnitSet
from app.models.fuel import FuelRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vendor import Vendor
from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Pre-computed argon2id hash for "testpassword123", copied from
# tests/conftest.py: hashing here would need threads these containers do not
# always have.
_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

_OWNER = "t5rep_owner"
_METRIC_CALLER = "t5rep_metric"
_IMPERIAL_CALLER = "t5rep_imperial"
_UK_CALLER = "t5rep_uk"
_SHOW_BOTH_CALLER = "t5rep_showboth"
_USERNAMES = (_OWNER, _METRIC_CALLER, _IMPERIAL_CALLER, _UK_CALLER, _SHOW_BOTH_CALLER)

_VIN = "T5REPORTUNITS001"
_VENDOR = "T5 Report Garage"

# Imperial with UK gallons: the shape a UK instance seeds (migration 093).
UK_IMPERIAL = UnitSet.model_validate(
    IMPERIAL_PRESET.model_dump()
    | {"volume": "gal_uk", "consumption": "mpg_uk", "secondary_gallon": "uk"}
)

# --- seeded canonical values -----------------------------------------------
_SERVICE_ODOMETER_KM = Decimal("12345.00")
_SERVICE_COST = Decimal("49.99")
_FUEL_A_ODOMETER_KM = Decimal("800.00")
_FUEL_A_LITERS = Decimal("40.000")
_FUEL_A_COST = Decimal("55.00")
_FUEL_B_ODOMETER_KM = Decimal("900.00")
_FUEL_B_LITERS = Decimal("20.000")
_FUEL_B_COST = Decimal("30.00")

# --- hand-written expected header rows -------------------------------------
SERVICE_HISTORY_METRIC = [
    "Date",
    "Odometer (km)",
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
]
SERVICE_HISTORY_IMPERIAL = [
    "Date",
    "Odometer (mi)",
    "Category",
    "Description",
    "Cost",
    "Vendor",
    "Notes",
]
ALL_RECORDS_METRIC = [
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (km)",
    "Vendor",
    "Volume (L)",
]
ALL_RECORDS_IMPERIAL = [
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (mi)",
    "Vendor",
    "Volume (gal_us)",
]
ALL_RECORDS_UK = [
    "Date",
    "Type",
    "Category",
    "Description",
    "Cost",
    "Odometer (mi)",
    "Vendor",
    "Volume (gal_uk)",
]


# The exact 400 detail each emitted report is refused with, hand-written.
SERVICE_HISTORY_REFUSAL = (
    "This header row matches the service-history report export, which is a "
    "printable summary rather than a backup: it flattens each service visit "
    "into one row per line item and carries columns the importer does not "
    "consume, so importing it would create malformed records. Re-export the "
    "vehicle from Export > Service records instead."
)
ALL_RECORDS_REFUSAL = (
    "This header row matches the all-records report export, which is a "
    "printable summary rather than a backup: it interleaves fuel rows with "
    "service rows in one file, so importing it would create a service visit "
    "out of every fill-up. Re-export the vehicle from Export instead, one "
    "record type at a time."
)


def _headers_for(user: User) -> dict[str, str]:
    """Bearer headers for `user`, matching conftest's `auth_headers`."""
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


async def _make_preset_user(
    db: AsyncSession,
    username: str,
    preference: str,
    *,
    show_both_units: bool = False,
    **overrides: object,
) -> User:
    """An admin account on `preference`, with only the named overrides set.

    Everything not named stays NULL, which is what makes this a genuine
    "preset plus one override" row rather than a materialised custom one.
    """
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=True,
        unit_preference=preference,
        show_both_units=show_both_units,
        **overrides,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_materialised_user(db: AsyncSession, username: str, units: UnitSet) -> User:
    """A `custom` admin account with all eleven quantities written out."""
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=True,
        unit_preference="custom",
        show_both_units=False,
        unit_distance=units.distance,
        unit_speed=units.speed,
        unit_length=units.length,
        unit_volume=units.volume,
        unit_consumption=units.consumption,
        unit_pressure=units.pressure,
        unit_temperature=units.temperature,
        unit_mass=units.mass,
        unit_torque=units.torque,
        unit_tread=units.tread,
        secondary_gallon=units.secondary_gallon,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed(db: AsyncSession, owner: User) -> None:
    """One vehicle owned by `owner`: one service visit and two fuel records.

    Two fuel records rather than one, because the `Description` fallback and
    the recorded fuel grade are different branches (T5-R6) and a single row
    can only exercise one of them.
    """
    db.add(
        Vehicle(
            vin=_VIN,
            user_id=owner.id,
            nickname="T5 Report Units",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="T5Report",
        )
    )
    vendor = Vendor(name=_VENDOR)
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)

    visit = ServiceVisit(
        vin=_VIN,
        vendor_id=vendor.id,
        date=date(2026, 3, 1),
        odometer_km=_SERVICE_ODOMETER_KM,
        service_category="Maintenance",
        notes="Report note",
    )
    db.add(visit)
    await db.commit()
    await db.refresh(visit)
    db.add(ServiceLineItem(visit_id=visit.id, description="Oil change", cost=_SERVICE_COST))
    db.add(
        FuelRecord(
            vin=_VIN,
            date=date(2026, 3, 2),
            odometer_km=_FUEL_A_ODOMETER_KM,
            liters=_FUEL_A_LITERS,
            cost=_FUEL_A_COST,
            fuel_type_used="Premium",
        )
    )
    db.add(
        FuelRecord(
            vin=_VIN,
            date=date(2026, 3, 3),
            odometer_km=_FUEL_B_ODOMETER_KM,
            liters=_FUEL_B_LITERS,
            cost=_FUEL_B_COST,
            fuel_type_used=None,
        )
    )
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    """Remove every row this module creates, child-first.

    Ordered explicitly rather than relying on cascade, so teardown does not
    depend on the FK pragma being on for whichever dialect is running. The
    `Vendor` is a global row, not a per-vehicle one, so it needs removing too.
    """
    visit_ids = (
        (await db.execute(select(ServiceVisit.id).where(ServiceVisit.vin == _VIN))).scalars().all()
    )
    if visit_ids:
        await db.execute(delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids)))
    await db.execute(delete(ServiceVisit).where(ServiceVisit.vin == _VIN))
    await db.execute(delete(FuelRecord).where(FuelRecord.vin == _VIN))
    await db.execute(delete(Vehicle).where(Vehicle.vin == _VIN))
    await db.execute(delete(Vendor).where(Vendor.name == _VENDOR))
    await db.execute(delete(User).where(User.username.in_(_USERNAMES)))
    await db.commit()


def _rows(body: str) -> list[list[str]]:
    """Every row of a report CSV, header included, as plain lists."""
    return list(csv.reader(io.StringIO(body)))


async def _get(client: AsyncClient, headers: dict[str, str], report: str) -> str:
    """One report's body, asserting it was actually produced."""
    response = await client.get(f"/api/vehicles/{_VIN}/reports/{report}", headers=headers)
    assert response.status_code == 200, response.text
    return response.content.decode("utf-8")


class TestServiceHistoryCsv:
    """`Mileage` becomes `Odometer (<token>)`, and the value follows."""

    async def test_metric_caller(self, client: AsyncClient, db_session: AsyncSession) -> None:
        try:
            owner = await _make_preset_user(db_session, _OWNER, "imperial")
            caller = await _make_preset_user(db_session, _METRIC_CALLER, "metric")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "service-history-csv"))
            assert rows[0] == SERVICE_HISTORY_METRIC
            assert rows[1] == [
                "2026-03-01",
                "12345.00",
                "Maintenance",
                "Oil change",
                "49.99",
                _VENDOR,
                "Report note",
            ]
        finally:
            await _cleanup(db_session)

    async def test_imperial_caller(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """The owner is metric and the caller imperial, so a route reading the
        OWNER's units instead of the caller's fails here."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_preset_user(db_session, _IMPERIAL_CALLER, "imperial")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "service-history-csv"))
            assert rows[0] == SERVICE_HISTORY_IMPERIAL
            assert rows[1] == [
                "2026-03-01",
                "7670.846",
                "Maintenance",
                "Oil change",
                "49.99",
                _VENDOR,
                "Report note",
            ]
        finally:
            await _cleanup(db_session)

    async def test_no_marker_or_version_column(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """T5-R2: a report is not importable, so the two machine columns the
        backup exports carry would be cost with no function."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(owner), "service-history-csv"))
            assert "units_version" not in rows[0]
            assert "unit_system" not in rows[0]
        finally:
            await _cleanup(db_session)


class TestAllRecordsCsv:
    """The new `Volume (<token>)` column, and what each row type puts in it."""

    async def test_metric_caller(self, client: AsyncClient, db_session: AsyncSession) -> None:
        try:
            owner = await _make_preset_user(db_session, _OWNER, "imperial")
            caller = await _make_preset_user(db_session, _METRIC_CALLER, "metric")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "all-records-csv"))
            assert rows[0] == ALL_RECORDS_METRIC
            assert rows[1] == [
                "2026-03-01",
                "Service",
                "Maintenance",
                "Oil change",
                "49.99",
                "12345.00",
                _VENDOR,
                "",
            ]
            assert rows[2] == [
                "2026-03-02",
                "Fuel",
                "Fuel",
                "Premium",
                "55.00",
                "800.00",
                "",
                "40.000",
            ]
            assert rows[3] == [
                "2026-03-03",
                "Fuel",
                "Fuel",
                "Fuel",
                "30.00",
                "900.00",
                "",
                "20.000",
            ]
        finally:
            await _cleanup(db_session)

    async def test_imperial_caller(self, client: AsyncClient, db_session: AsyncSession) -> None:
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_preset_user(db_session, _IMPERIAL_CALLER, "imperial")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "all-records-csv"))
            assert rows[0] == ALL_RECORDS_IMPERIAL
            assert rows[1][5] == "7670.846"
            assert rows[1][7] == ""
            assert rows[2][5] == "497.098"
            assert rows[2][7] == "10.5669"
            assert rows[3][5] == "559.235"
            assert rows[3][7] == "5.2834"
        finally:
            await _cleanup(db_session)

    async def test_uk_gallon_caller(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """The distance and the volume resolve independently: a UK account is
        miles AND imperial gallons, and a route that keyed the volume off the
        distance preference (or off `IMPERIAL_PRESET`) emits US gallons here.
        """
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_materialised_user(db_session, _UK_CALLER, UK_IMPERIAL)
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "all-records-csv"))
            assert rows[0] == ALL_RECORDS_UK
            assert rows[2][7] == "8.7988"
            assert rows[3][7] == "4.3994"
        finally:
            await _cleanup(db_session)

    async def test_a_mixed_unit_account_spells_each_column_separately(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Kilometres with US gallons. Neither preset produces this pair, so a
        route that picked one marker and derived both columns from it cannot
        pass: the header must be `Odometer (km)` AND `Volume (gal_us)`.
        """
        try:
            owner = await _make_preset_user(db_session, _OWNER, "imperial")
            caller = await _make_preset_user(
                db_session, _METRIC_CALLER, "metric", unit_volume="gal_us"
            )
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "all-records-csv"))
            assert rows[0][5] == "Odometer (km)"
            assert rows[0][7] == "Volume (gal_us)"
            assert rows[2][5] == "800.00"
            assert rows[2][7] == "10.5669"
        finally:
            await _cleanup(db_session)

    async def test_the_volume_column_is_appended_after_vendor(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Under metric the seven pre-v6 columns keep their exact spellings
        and positions, so a spreadsheet reading columns 0..6 is unaffected."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(owner), "all-records-csv"))
            assert rows[0][:7] == [
                "Date",
                "Type",
                "Category",
                "Description",
                "Cost",
                "Odometer (km)",
                "Vendor",
            ]
            assert rows[0][7] == "Volume (L)"
        finally:
            await _cleanup(db_session)

    async def test_a_service_row_leaves_the_volume_cell_empty(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A service visit has no fuel volume: the quantity is ABSENT, not
        zero. `0` would claim the visit consumed nothing and would drag an
        average over the column down."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(owner), "all-records-csv"))
            assert rows[1][1] == "Service"
            assert rows[1][7] == ""
        finally:
            await _cleanup(db_session)


class TestTheFuelDescription:
    """T5-R6: `f"{record.liters}L"` was a canonical litre value with a
    hardcoded `L`, which is simply wrong for an imperial reader."""

    async def test_the_description_never_carries_a_quantity(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_preset_user(db_session, _IMPERIAL_CALLER, "imperial")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "all-records-csv"))
            assert rows[2][3] == "Premium"
            assert rows[3][3] == "Fuel"
            for row in rows[1:]:
                assert "40.000L" not in row[3]
                assert "L" not in row[3].removeprefix("Premium")
        finally:
            await _cleanup(db_session)

    async def test_the_quantity_moved_to_its_own_numeric_cell(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The volume is still readable, just as a number a spreadsheet can
        sum rather than as text inside a free-text column."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(owner), "all-records-csv"))
            assert rows[2][7] == "40.000"
            assert Decimal(rows[2][7]) == Decimal("40.000")
        finally:
            await _cleanup(db_session)


class TestAZeroIsARealValue:
    """`0` is a value, not a missing one, in both the odometer and the cost.

    Behaviour change, deliberate and user-visible. Every numeric cell on both
    reports used to be written with a FALSY guard (`visit.odometer_km or ""`,
    `f"{item.cost:.2f}" if item.cost else ""`), which cannot tell a genuine
    `Decimal("0.00")` from a missing value and erased both into a blank cell.

    The odometer half changed first, as a side effect of routing the cell
    through `csv_emission.cell_for`, which blanks only `None`. That left the
    cost cell beside it still falsy, which was worse than either consistent
    answer: one row, two rules. The cost cells are now `is not None` too.

    The two cases this makes distinguishable in a file:

    - the first service on a brand-new vehicle, logged at 0 km, versus a
      service whose odometer nobody recorded;
    - a warranty repair that genuinely cost $0.00, versus a service whose
      cost nobody recorded.

    Not covered anywhere else: every seeded fixture in this file uses non-zero
    odometers and costs, so all the other assertions pass either way.
    """

    async def test_a_zero_odometer_and_a_zero_cost_both_emit_numbers(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Both cells, both endpoints: both odometer sites, and two of the
        three cost sites (the service-history line item and the all-records
        service row)."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            visit = ServiceVisit(
                vin=_VIN,
                date=date(2026, 2, 1),
                odometer_km=Decimal("0.00"),
                service_category="Maintenance",
                notes="Delivery inspection",
            )
            db_session.add(visit)
            await db_session.commit()
            await db_session.refresh(visit)
            db_session.add(
                ServiceLineItem(visit_id=visit.id, description="PDI", cost=Decimal("0.00"))
            )
            await db_session.commit()

            rows = _rows(await _get(client, _headers_for(owner), "service-history-csv"))
            zero_row = next(row for row in rows[1:] if row[0] == "2026-02-01")
            assert zero_row[1] == "0.00"
            assert zero_row[4] == "0.00"

            rows = _rows(await _get(client, _headers_for(owner), "all-records-csv"))
            zero_row = next(row for row in rows[1:] if row[0] == "2026-02-01")
            assert zero_row[5] == "0.00"
            assert zero_row[4] == "0.00"
        finally:
            await _cleanup(db_session)

    async def test_a_zero_cost_fuel_row_emits_a_number(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The third cost site: all-records writes fuel rows through their
        own row list, so the service-row fix does not reach it.

        A free fill-up is real (a loyalty reward, a fleet card, a warranty
        top-up), and blanking it makes the row look like one whose cost was
        never entered.
        """
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            db_session.add(
                FuelRecord(
                    vin=_VIN,
                    date=date(2026, 2, 4),
                    odometer_km=Decimal("1000.00"),
                    liters=Decimal("10.000"),
                    cost=Decimal("0.00"),
                    fuel_type_used="Regular",
                )
            )
            await db_session.commit()

            rows = _rows(await _get(client, _headers_for(owner), "all-records-csv"))
            free_row = next(row for row in rows[1:] if row[0] == "2026-02-04")
            assert free_row[1] == "Fuel"
            assert free_row[4] == "0.00"
            assert free_row[7] == "10.000"
        finally:
            await _cleanup(db_session)

    async def test_a_zero_odometer_converts_rather_than_blanking(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """0 km is 0 mi, but through the converter, at the imperial column's
        three decimals rather than the metric column's two."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_preset_user(db_session, _IMPERIAL_CALLER, "imperial")
            await _seed(db_session, owner)
            visit = ServiceVisit(
                vin=_VIN,
                date=date(2026, 2, 2),
                odometer_km=Decimal("0.00"),
                service_category="Maintenance",
            )
            db_session.add(visit)
            await db_session.commit()
            await db_session.refresh(visit)
            db_session.add(
                ServiceLineItem(visit_id=visit.id, description="PDI", cost=Decimal("1.00"))
            )
            await db_session.commit()

            rows = _rows(await _get(client, _headers_for(caller), "service-history-csv"))
            zero_row = next(row for row in rows[1:] if row[0] == "2026-02-02")
            assert zero_row[1] == "0.000"
        finally:
            await _cleanup(db_session)

    async def test_a_missing_odometer_and_a_missing_cost_are_still_blank(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The half of the old behaviour that was right, and the half of the
        new behaviour that would be wrong if `is not None` were dropped for a
        plain truthiness-free `f"{...}"`: NULL stays empty."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            await _seed(db_session, owner)
            visit = ServiceVisit(
                vin=_VIN,
                date=date(2026, 2, 3),
                odometer_km=None,
                service_category="Maintenance",
            )
            db_session.add(visit)
            await db_session.commit()
            await db_session.refresh(visit)
            db_session.add(ServiceLineItem(visit_id=visit.id, description="PDI", cost=None))
            await db_session.commit()

            rows = _rows(await _get(client, _headers_for(owner), "service-history-csv"))
            blank_row = next(row for row in rows[1:] if row[0] == "2026-02-03")
            assert blank_row[1] == ""
            assert blank_row[4] == ""

            rows = _rows(await _get(client, _headers_for(owner), "all-records-csv"))
            blank_row = next(row for row in rows[1:] if row[0] == "2026-02-03")
            assert blank_row[5] == ""
            assert blank_row[4] == ""
        finally:
            await _cleanup(db_session)


class TestCellsAreNumericOnly:
    """R10: no `adapter.format()` output reaches a cell, on either report."""

    async def test_show_both_never_reaches_a_cell(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An account that opted into showing the counterpart still gets bare
        numbers: `show_both` is a composition-layer concept and these cells
        come from the conversion layer (T5-R1)."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_preset_user(
                db_session, _SHOW_BOTH_CALLER, "imperial", show_both_units=True
            )
            await _seed(db_session, owner)
            service = _rows(await _get(client, _headers_for(caller), "service-history-csv"))
            all_records = _rows(await _get(client, _headers_for(caller), "all-records-csv"))
            # The conversion DID happen, so "no counterpart in the cell" is
            # not just "nothing was converted".
            assert service[1][1] == "7670.846"
            assert all_records[2][7] == "10.5669"
            for report, rows in (("service", service), ("all", all_records)):
                for row in rows[1:]:
                    for cell in row:
                        assert "(" not in cell, (report, row)
        finally:
            await _cleanup(db_session)

    async def test_no_grouping_separator_or_unit_label(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`adapter.format()` renders 12345 km as `7,671 mi`: a thousands
        separator, a label, and the adapter's zero-decimal presentation
        precision. All three are wrong in a numeric cell."""
        try:
            owner = await _make_preset_user(db_session, _OWNER, "metric")
            caller = await _make_preset_user(db_session, _IMPERIAL_CALLER, "imperial")
            await _seed(db_session, owner)
            rows = _rows(await _get(client, _headers_for(caller), "service-history-csv"))
            odometer = rows[1][1]
            assert odometer == "7670.846"
            assert "," not in odometer
            assert "mi" not in odometer
        finally:
            await _cleanup(db_session)


class TestTheEmittedReportIsRefusedOnImport:
    """T5-R3/R4 end to end: what the endpoint writes, the importer refuses.

    The link is structural, not a coincidence: `REJECTED_HEADER_TUPLES` is
    derived from the same header templates these endpoints emit from. This
    test is what proves the derivation covers the rows actually produced,
    rather than rows a unit test asked for.
    """

    @pytest.mark.parametrize(
        ("preference", "report", "expected_detail"),
        [
            ("metric", "service-history-csv", SERVICE_HISTORY_REFUSAL),
            ("imperial", "service-history-csv", SERVICE_HISTORY_REFUSAL),
            ("metric", "all-records-csv", ALL_RECORDS_REFUSAL),
            ("imperial", "all-records-csv", ALL_RECORDS_REFUSAL),
        ],
    )
    async def test_a_freshly_exported_report_cannot_be_imported(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        preference: str,
        report: str,
        expected_detail: str,
    ) -> None:
        try:
            owner = await _make_preset_user(db_session, _OWNER, preference)
            await _seed(db_session, owner)
            headers = _headers_for(owner)
            body = await _get(client, headers, report)
            response = await client.post(
                f"/api/import/vehicles/{_VIN}/service/csv",
                headers=headers,
                files={"file": ("report.csv", io.BytesIO(body.encode()), "text/csv")},
                data={"skip_duplicates": "false"},
            )
            assert response.status_code == 400, response.text
            # Whole message, not a substring: the pre-v6 refusal reads
            # "unversioned service-history report export ...", which CONTAINS
            # the v6 wording, so a substring assertion here passed before this
            # task changed anything.
            assert response.json()["detail"] == expected_detail
        finally:
            await _cleanup(db_session)
