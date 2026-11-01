"""Imports are held to the same number bounds as the API.

Every importer builds its ORM rows directly, so none of the Create schemas'
`ge`/`le` bounds ever ran on imported data: a negative cost, a negative
odometer or a `NaN` went straight into the database, where the API would
have refused each of them with a 422. A negative cost then drags the garage
analytics down with it.
"""

import json
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.service_visit import ServiceVisit
from app.models.tax import TaxRecord
from app.models.vehicle import Vehicle
from app.models.warranty import WarrantyRecord
from app.schemas._money import MONEY_MAX
from app.schemas.fuel import FuelRecordCreate

# Diesel, so the DEF imports are accepted.
pytestmark = pytest.mark.own_vehicle(
    vehicle_type="Truck", make="Ram", model="2500", fuel_type="diesel"
)


async def _count(db: AsyncSession, model: Any, vin: str, **where: Any) -> int:
    conditions = [model.vin == vin] + [getattr(model, k) == v for k, v in where.items()]
    result = await db.execute(select(func.count()).select_from(model).where(*conditions))
    return int(result.scalar() or 0)


async def _post_csv(
    client: AsyncClient, auth_headers: dict[str, str], vin: str, kind: str, csv: str
) -> dict[str, Any]:
    response = await client.post(
        f"/api/import/vehicles/{vin}/{kind}/csv",
        headers=auth_headers,
        files={"file": (f"{kind}.csv", BytesIO(csv.encode()), "text/csv")},
        data={"skip_duplicates": "false"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# (route, header, bad row, model, the bad row's identifying column and value)
CSV_OUT_OF_BOUNDS = [
    pytest.param(
        "fuel",
        "Date,Odometer (km),Liters,Price Per Liter,Total Cost",
        "2043-01-02,1000,40,1.50,-60.00",
        FuelRecord,
        {"date": date(2043, 1, 2)},
        id="fuel-negative-cost",
    ),
    pytest.param(
        "fuel",
        "Date,Odometer (km),Liters,Price Per Liter,Total Cost",
        "2043-01-03,NaN,40,1.50,60.00",
        FuelRecord,
        {"date": date(2043, 1, 3)},
        id="fuel-nan-odometer",
    ),
    pytest.param(
        "fuel",
        "Date,Odometer (km),Liters,Price Per Liter,Total Cost",
        "2043-01-04,1000,-40,1.50,60.00",
        FuelRecord,
        {"date": date(2043, 1, 4)},
        id="fuel-negative-volume",
    ),
    pytest.param(
        "fuel",
        "Date,Odometer (km),Liters,Total Cost,Rebate",
        "2043-01-05,1000,40,60.00,Infinity",
        FuelRecord,
        {"date": date(2043, 1, 5)},
        id="fuel-infinite-rebate",
    ),
    pytest.param(
        "service",
        "Date,Odometer (km),Description,Cost",
        "2043-01-06,1000,Oil change,-45.00",
        ServiceVisit,
        {"date": date(2043, 1, 6)},
        id="service-negative-cost",
    ),
    pytest.param(
        "service",
        "Date,Odometer (km),Description,Cost",
        "2043-01-14,1000,Oil change,Infinity",
        ServiceVisit,
        {"date": date(2043, 1, 14)},
        # A line item's cost has only ge=0, so Infinity passes every bound and
        # only the finite check stops it.
        id="service-infinite-cost",
    ),
    pytest.param(
        "service",
        "Date,Odometer (km),Engine Hours,Description,Cost",
        "2043-01-07,1000,-3,Oil change,45.00",
        ServiceVisit,
        {"date": date(2043, 1, 7)},
        id="service-negative-hours",
    ),
    pytest.param(
        "def",
        "Date,Odometer (km),Liters,Price Per Unit,Total Cost,Fill Level",
        "2043-01-08,1000,9.5,1.10,-10.45,0.60",
        DEFRecord,
        {"date": date(2043, 1, 8)},
        id="def-negative-cost",
    ),
    pytest.param(
        "def",
        "Date,Odometer (km),Liters,Price Per Unit,Total Cost,Fill Level",
        "2043-01-09,1000,9.5,1.10,10.45,1.5",
        DEFRecord,
        {"date": date(2043, 1, 9)},
        id="def-fill-level-over-full",
    ),
    pytest.param(
        "odometer",
        "Date,Reading (km),Notes",
        "2043-01-10,-500,bad",
        OdometerRecord,
        {"date": date(2043, 1, 10)},
        id="odometer-negative-reading",
    ),
    pytest.param(
        "hours",
        "Date,Engine Hours,Notes",
        "2043-01-11,-12,bad",
        HoursRecord,
        {"date": date(2043, 1, 11)},
        id="hours-negative-reading",
    ),
    pytest.param(
        "warranties",
        "Provider,Type,Start Date,End Date,Mileage Limit (km),Notes",
        "Bounds Warranty Co,Powertrain,2043-01-12,2046-01-12,-100000,bad",
        WarrantyRecord,
        {"provider": "Bounds Warranty Co"},
        id="warranty-negative-mileage-limit",
    ),
    pytest.param(
        "tax",
        "Date,Type,Amount,Renewal Date,Notes",
        "2043-01-13,Registration,-85.00,2044-01-13,bad",
        TaxRecord,
        {"date": date(2043, 1, 13)},
        id="tax-negative-amount",
    ),
]


@pytest.mark.integration
@pytest.mark.asyncio
class TestCsvImportHoldsApiBounds:
    @pytest.mark.parametrize(("kind", "header", "row", "model", "where"), CSV_OUT_OF_BOUNDS)
    async def test_a_value_the_api_refuses_fails_its_row(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
        kind: str,
        header: str,
        row: str,
        model: Any,
        where: dict[str, Any],
    ):
        vin = own_vehicle.vin
        data = await _post_csv(client, auth_headers, vin, kind, f"{header}\n{row}\n")

        assert data["success_count"] == 0, data
        assert data["error_count"] == 1, data
        # The reason reaches the user, not just the log.
        assert "must be" in data["errors"][0], data
        assert await _count(db_session, model, vin, **where) == 0

    async def test_a_negative_temperature_still_imports(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
    ):
        """The bounds are the API's, not a blanket sign check: -12 °C is a winter fill-up."""
        vin = own_vehicle.vin
        data = await _post_csv(
            client,
            auth_headers,
            vin,
            "fuel",
            "Date,Odometer (km),Liters,Price Per Liter,Total Cost,Outside Temp (C)\n"
            "2043-02-01,1000,40,1.50,60.00,-12\n",
        )

        assert data["success_count"] == 1, data
        assert await _count(db_session, FuelRecord, vin, date=date(2043, 2, 1)) == 1

    async def test_an_imperial_volume_still_imports(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
    ):
        """Gallons convert to litres with more than the schema's 3 decimal places.

        Only the bounds are enforced, not the precision rules, or every imperial
        file would fail.
        """
        vin = own_vehicle.vin
        data = await _post_csv(
            client,
            auth_headers,
            vin,
            "fuel",
            "Date,Odometer (mi),Volume (gal_us),Price Per Unit (gal_us),Total Cost\n"
            "2043-02-02,1000,10.5,3.459,36.32\n",
        )

        assert data["success_count"] == 1, data
        assert await _count(db_session, FuelRecord, vin, date=date(2043, 2, 2)) == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestJsonImportHoldsApiBounds:
    async def test_values_the_api_refuses_fail_their_records(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
    ):
        vin = own_vehicle.vin
        payload = {
            "export_version": "3",
            "units": "metric",
            "service_records": [
                {"date": "2043-03-01", "odometer_km": 1000, "service_type": "Oil", "cost": -45},
                {"date": "2043-03-07", "odometer_km": -1000, "service_type": "Oil", "cost": 45},
            ],
            "fuel_records": [
                {"date": "2043-03-02", "odometer_km": 1000, "liters": 40, "cost": -60},
                {"date": "2043-03-03", "odometer_km": 1000, "liters": 40, "rebate": -5},
            ],
            "def_records": [{"date": "2043-03-04", "odometer_km": 1000, "cost": -10}],
            "odometer_records": [{"date": "2043-03-05", "odometer_km": -500}],
        }
        response = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={
                "file": ("backup.json", BytesIO(json.dumps(payload).encode()), "application/json")
            },
            data={"skip_duplicates": "false"},
        )
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["service_records"]["error_count"] == 2, data
        assert data["fuel_records"]["error_count"] == 2, data
        assert data["def_records"]["error_count"] == 1, data
        assert data["odometer_records"]["error_count"] == 1, data
        assert len(data["errors"]) == 6, data
        assert all("must be" in error for error in data["errors"]), data
        assert await _count(db_session, ServiceVisit, vin, date=date(2043, 3, 1)) == 0
        assert await _count(db_session, ServiceVisit, vin, date=date(2043, 3, 7)) == 0
        assert await _count(db_session, FuelRecord, vin, date=date(2043, 3, 2)) == 0
        assert await _count(db_session, FuelRecord, vin, date=date(2043, 3, 3)) == 0
        assert await _count(db_session, DEFRecord, vin, date=date(2043, 3, 4)) == 0
        assert await _count(db_session, OdometerRecord, vin, date=date(2043, 3, 5)) == 0

    async def test_a_nan_literal_fails_its_record(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
    ):
        """json.loads accepts a bare NaN, so a backup can carry one."""
        vin = own_vehicle.vin
        body = (
            '{"export_version": "3", "units": "metric", "fuel_records": '
            '[{"date": "2043-03-06", "odometer_km": 1000, "liters": 40, "cost": NaN}]}'
        )
        response = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={"file": ("backup.json", BytesIO(body.encode()), "application/json")},
            data={"skip_duplicates": "false"},
        )
        assert response.status_code == 200, response.text

        assert response.json()["fuel_records"]["error_count"] == 1, response.json()
        assert await _count(db_session, FuelRecord, vin, date=date(2043, 3, 6)) == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestThirdPartyImportHoldsApiBounds:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("cost", Decimal("-60"), id="negative-cost"),
            pytest.param("liters", Decimal("-40"), id="negative-volume"),
            pytest.param("soc_end_pct", Decimal("140"), id="soc-over-100"),
            pytest.param("kwh", Decimal("NaN"), id="nan-energy"),
        ],
    )
    async def test_a_value_the_api_refuses_fails_its_row(
        self,
        own_vehicle: Vehicle,
        db_session: AsyncSession,
        field: str,
        value: Decimal,
    ):
        from app.routes import import_data

        vin = own_vehicle.vin
        parsed = [{"date": date(2043, 4, 1), "odometer_km": Decimal("1000"), field: value}]
        result = await import_data._persist_parsed_fuel(vin, parsed, False, db_session)

        assert result["success_count"] == 0, result
        assert result["error_count"] == 1, result
        assert "must be" in result["errors"][0], result
        assert await _count(db_session, FuelRecord, vin, date=date(2043, 4, 1)) == 0

    async def test_a_value_exactly_on_a_float_bound_imports(
        self,
        own_vehicle: Vehicle,
        db_session: AsyncSession,
    ):
        """le=9999.999 is a float; compared as one it sits a hair below 9999.999,
        which refused the value pydantic accepts."""
        from app.routes import import_data

        vin = own_vehicle.vin
        parsed = [
            {
                "date": date(2043, 4, 2),
                "odometer_km": Decimal("1000"),
                "liters": Decimal("9999.999"),
            }
        ]
        result = await import_data._persist_parsed_fuel(vin, parsed, False, db_session)

        assert result["success_count"] == 1, result


async def _post_json(
    client: AsyncClient, auth_headers: dict[str, str], vin: str, body: str, *, skip: bool
) -> dict[str, Any]:
    response = await client.post(
        f"/api/import/vehicles/{vin}/json",
        headers=auth_headers,
        files={"file": ("backup.json", BytesIO(body.encode()), "application/json")},
        data={"skip_duplicates": "true" if skip else "false"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
class TestJsonImportBoundsOrderAndReminders:
    async def test_an_out_of_bounds_service_record_is_an_error_even_when_it_duplicates(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
    ):
        """Bounds run before the duplicate check, as in every other section."""
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/service-visits",
            json={
                "date": "2043-05-01",
                "odometer_km": 3000,
                "line_items": [{"description": "Oil"}],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        body = json.dumps(
            {
                "export_version": "3",
                "units": "metric",
                "service_records": [
                    {"date": "2043-05-01", "odometer_km": 3000, "service_type": "Oil", "cost": -5}
                ],
            }
        )

        data = await _post_json(client, auth_headers, vin, body, skip=True)

        assert data["service_records"]["error_count"] == 1, data
        assert data["service_records"]["skipped_count"] == 0, data

    @pytest.mark.parametrize("miles", ["Infinity", "NaN", "1e12"])
    async def test_a_reminder_interval_the_api_refuses_fails(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        miles: str,
    ):
        vin = own_vehicle.vin
        body = (
            '{"export_version": "3", "units": "metric", "reminders": [{"description": '
            f'"Bounds reminder {miles}", "is_recurring": true, "recurrence_miles": {miles}}}]}}'
        )

        data = await _post_json(client, auth_headers, vin, body, skip=False)

        assert data["reminders"]["success_count"] == 0, data
        assert data["reminders"]["error_count"] == 1, data
        # The specific reason, in plain digits (not 1E+12).
        assert "must be" in data["errors"][0] and "E+" not in data["errors"][0], data


def test_a_misspelt_field_fails_even_on_an_empty_cell():
    """A typo'd name must fail every row, not only the rows that fill the column."""
    from app.routes.import_data import _within_api_bounds

    with pytest.raises(KeyError):
        _within_api_bounds(FuelRecordCreate, not_a_field=None)


# An amount one cent past the money column (Plan B, B4). The service and tax
# importers take their bounds from the Create schemas through
# `_within_api_bounds`, so the policy maximum reaches them with no code of
# their own: this pins that it does, with the reason and not a 500.
PAST_MAX = MONEY_MAX + Decimal("0.01")


@pytest.mark.integration
@pytest.mark.asyncio
class TestAnImportPastTheMoneyColumn:
    @pytest.mark.parametrize(
        ("kind", "header", "row", "model", "where", "reason"),
        [
            pytest.param(
                "service",
                "Date,Odometer (km),Description,Cost",
                f"2043-06-01,1000,Engine,{PAST_MAX}",
                ServiceVisit,
                {"date": date(2043, 6, 1)},
                f"cost must be at most {MONEY_MAX}, not {PAST_MAX}",
                id="service-cost",
            ),
            pytest.param(
                "tax",
                "Date,Type,Amount,Renewal Date,Notes",
                f"2043-06-02,Registration,{PAST_MAX},2044-06-02,big",
                TaxRecord,
                {"date": date(2043, 6, 2)},
                f"amount must be at most {MONEY_MAX}, not {PAST_MAX}",
                id="tax-amount",
            ),
        ],
    )
    async def test_a_csv_row_fails_with_the_reason(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
        kind: str,
        header: str,
        row: str,
        model: Any,
        where: dict[str, Any],
        reason: str,
    ):
        vin = own_vehicle.vin
        data = await _post_csv(client, auth_headers, vin, kind, f"{header}\n{row}\n")

        assert (data["success_count"], data["error_count"]) == (0, 1), data
        assert reason in data["errors"][0], data
        assert await _count(db_session, model, vin, **where) == 0

    async def test_a_json_service_record_fails_with_the_reason(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        own_vehicle: Vehicle,
        db_session: AsyncSession,
    ):
        vin = own_vehicle.vin
        body = json.dumps(
            {
                "export_version": "3",
                "units": "metric",
                "service_records": [
                    {
                        "date": "2043-06-03",
                        "odometer_km": 1000,
                        "service_type": "Engine",
                        "cost": str(PAST_MAX),
                    }
                ],
            }
        )

        data = await _post_json(client, auth_headers, vin, body, skip=False)

        assert data["service_records"]["error_count"] == 1, data
        assert f"cost must be at most {MONEY_MAX}, not {PAST_MAX}" in data["errors"][0], data
        assert await _count(db_session, ServiceVisit, vin, date=date(2043, 6, 3)) == 0
