"""Pins what every report endpoint hands its renderer, through the client.

The CSV bodies match goldens byte for byte. The PDFs are pinned one step
earlier: a spy records what reaches the `PDFReportGenerator` constructor and
its `generate_*` call, so a moved query that drops or adds a row shows up
without parsing a PDF. Every expected value below was written by hand from
the seed.

The seed has one row per branch: a visit with no line items (with notes and
without), line items costing None and 0, no vendor, visits on both date bounds
and outside them, a visit the year before, fuel rows, Collision and Upgrades,
and a trailer for the cost summary's non-motorized path.

Tests share one database with no per-test rollback, so every row is torn down
in `finally` and every name, VIN and vendor is scoped to this module.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from datetime import date, datetime, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import IMPERIAL_PRESET
from app.models.fuel import FuelRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vendor import Vendor
from app.routes import reports as reports_route
from app.services.auth import create_access_token
from app.utils.pdf_generator import PDFReportGenerator
from app.utils.render_context import RenderContext

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

GOLDENS = Path(__file__).parent / "report_goldens"

# Same argon2id hash as tests/conftest.py, so nothing hashes at runtime.
_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

_OWNER = "rptsvc_owner"
_VIN = "RPTSVC00000000001"
# A trailer has no VIN, so it gets a generated "Q" key and shows its serial.
_TRAILER_KEY = "QRPTSVC0000000002"
_TRAILER_SERIAL = "TRL-7"
_VENDOR_A = "RptSvc Garage A"
_VENDOR_B = "RptSvc Body Shop B"

# The filenames carry today's date, so the clock is frozen.
_FROZEN = datetime(2026, 10, 4, 12, 0)
_STAMP = "20261004"

# The owner is imperial with no overrides, and the vehicle follows the account.
_CONTEXT = RenderContext(units=IMPERIAL_PRESET, show_both=False)

_VEHICLE_INFO = {
    "vin": _VIN,
    "identifier_label": "VIN",
    "identifier": _VIN,
    "year": 2019,
    "make": "Pin",
    "model": "Car",
}


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        return _FROZEN.replace(tzinfo=tz) if tz is not None else _FROZEN


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reports_route, "datetime", _FrozenDatetime)


_SPIED = (
    "__init__",
    "generate_service_history_pdf",
    "generate_sale_history_pdf",
    "generate_cost_summary_pdf",
    "generate_tax_deduction_pdf",
)


def _recording(
    name: str, original: Callable[..., Any], calls: list[tuple[str, dict[str, Any]]]
) -> Callable[..., Any]:
    signature = inspect.signature(original)

    def wrapper(self: PDFReportGenerator, *args: Any, **kwargs: Any) -> Any:
        # Bound by name, so positional vs keyword at the call site doesn't matter.
        arguments = dict(signature.bind(self, *args, **kwargs).arguments)
        arguments.pop("self")
        calls.append((name, arguments))
        return original(self, *args, **kwargs)

    return wrapper


@pytest.fixture
def pdf_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    """Every constructor and generate_* call, in order, still rendering for real."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for name in _SPIED:
        original = getattr(PDFReportGenerator, name)
        monkeypatch.setattr(PDFReportGenerator, name, _recording(name, original, calls))
    yield calls


async def _seed(db: AsyncSession) -> dict[str, str]:
    """The owner, both vehicles, and one row per branch. Returns auth headers."""
    owner = User(
        username=_OWNER,
        email=f"{_OWNER}@example.com",
        hashed_password=_PASSWORD_HASH,
        is_active=True,
        is_admin=False,
        unit_preference="imperial",
        show_both_units=False,
        language="en",
        date_format="mdy",
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    db.add(
        Vehicle(
            vin=_VIN,
            user_id=owner.id,
            nickname="Pin Car",
            vehicle_type="Car",
            year=2019,
            make="Pin",
            model="Car",
            license_plate="PIN-1",
        )
    )
    db.add(
        Vehicle(
            vin=_TRAILER_KEY,
            identifier_type="serial",
            identifier=_TRAILER_SERIAL,
            user_id=owner.id,
            nickname="Pin Trailer",
            vehicle_type="Trailer",
            year=2021,
            make="Haul",
            model="Box",
        )
    )
    vendor_a = Vendor(name=_VENDOR_A)
    vendor_b = Vendor(name=_VENDOR_B)
    db.add_all([vendor_a, vendor_b])
    await db.commit()
    await db.refresh(vendor_a)
    await db.refresh(vendor_b)

    async def visit(items: list[tuple[str, Decimal | None]], **fields: Any) -> None:
        row = ServiceVisit(**fields)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        for description, cost in items:
            db.add(ServiceLineItem(visit_id=row.id, description=description, cost=cost))
        await db.commit()

    # The year before: a Collision and an Upgrades visit, so each per-category
    # total has something its year filter must leave out.
    await visit(
        [("Door ding", Decimal("250.00"))],
        vin=_VIN,
        vendor_id=vendor_b.id,
        date=date(2024, 3, 10),
        odometer_km=Decimal("5000.00"),
        service_category="Collision",
        total_cost=Decimal("250.00"),
    )
    await visit(
        [("Tow hitch", Decimal("400.00"))],
        vin=_VIN,
        vendor_id=vendor_a.id,
        date=date(2024, 9, 9),
        odometer_km=Decimal("7000.00"),
        service_category="Upgrades",
        total_cost=Decimal("400.00"),
    )
    # Also the year before: out of the cost summary, tax year and the date window.
    await visit(
        [("Old oil", Decimal("40.00"))],
        vin=_VIN,
        vendor_id=vendor_a.id,
        date=date(2024, 12, 15),
        odometer_km=Decimal("9000.00"),
        service_category="Maintenance",
        total_cost=Decimal("40.00"),
    )
    # On the lower bound, with a 0 and a None line item.
    await visit(
        [
            ("Oil change", Decimal("49.99")),
            ("Free inspection", Decimal("0.00")),
            ("Wiper check", None),
        ],
        vin=_VIN,
        vendor_id=vendor_a.id,
        date=date(2025, 2, 1),
        odometer_km=Decimal("10000.00"),
        service_category="Maintenance",
        notes="Paid cash at Garage A",
        total_cost=Decimal("49.99"),
    )
    # Fee only, no vendor, no odometer: the notes fallback.
    await visit(
        [],
        vin=_VIN,
        date=date(2025, 5, 10),
        service_category="Maintenance",
        notes="Disposal fee, $15 cash",
        misc_fees=Decimal("15.00"),
        total_cost=Decimal("15.00"),
    )
    # No category, no vendor, a real zero odometer.
    await visit(
        [("Car wash", Decimal("12.00"))],
        vin=_VIN,
        date=date(2025, 7, 4),
        odometer_km=Decimal("0.00"),
        total_cost=Decimal("12.00"),
    )
    await visit(
        [("Bumper", Decimal("500.00"))],
        vin=_VIN,
        vendor_id=vendor_b.id,
        date=date(2025, 8, 20),
        odometer_km=Decimal("15000.00"),
        service_category="Collision",
        total_cost=Decimal("500.00"),
    )
    # On the upper bound. The description is a formula, so the CSV escapes it.
    await visit(
        [("=1+1", Decimal("300.00"))],
        vin=_VIN,
        vendor_id=vendor_a.id,
        date=date(2025, 11, 30),
        odometer_km=Decimal("18000.00"),
        service_category="Upgrades",
        total_cost=Decimal("300.00"),
    )
    # Past the upper bound: no items, no notes, no category, no total.
    await visit([], vin=_VIN, date=date(2025, 12, 20))
    # The trailer's one visit.
    await visit(
        [("Bearing repack", Decimal("80.00"))],
        vin=_TRAILER_KEY,
        date=date(2025, 4, 1),
        service_category="Maintenance",
        total_cost=Decimal("80.00"),
    )

    db.add_all(
        [
            FuelRecord(
                vin=_VIN,
                date=date(2024, 6, 1),
                odometer_km=Decimal("8000.00"),
                liters=Decimal("20.000"),
                cost=Decimal("30.00"),
                fuel_type_used="Regular",
            ),
            FuelRecord(
                vin=_VIN,
                date=date(2025, 3, 3),
                odometer_km=Decimal("11000.00"),
                liters=Decimal("40.000"),
                cost=Decimal("55.00"),
                fuel_type_used="Premium",
            ),
            FuelRecord(
                vin=_VIN,
                date=date(2025, 9, 9),
                odometer_km=Decimal("16000.00"),
                liters=Decimal("10.000"),
                cost=None,
                fuel_type_used=None,
            ),
            # Fuel on a trailer is nonsense, which is the point: the summary must skip it.
            FuelRecord(
                vin=_TRAILER_KEY,
                date=date(2025, 4, 2),
                liters=Decimal("5.000"),
                cost=Decimal("20.00"),
            ),
        ]
    )
    await db.commit()

    token = create_access_token(data={"sub": str(owner.id), "username": owner.username})
    return {"Authorization": f"Bearer {token}"}


async def _cleanup(db: AsyncSession) -> None:
    """Child-first, so teardown doesn't lean on the FK pragma."""
    vins = (_VIN, _TRAILER_KEY)
    visit_ids = (
        (await db.execute(select(ServiceVisit.id).where(ServiceVisit.vin.in_(vins))))
        .scalars()
        .all()
    )
    if visit_ids:
        await db.execute(delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids)))
    await db.execute(delete(ServiceVisit).where(ServiceVisit.vin.in_(vins)))
    await db.execute(delete(FuelRecord).where(FuelRecord.vin.in_(vins)))
    await db.execute(delete(Vehicle).where(Vehicle.vin.in_(vins)))
    await db.execute(delete(Vendor).where(Vendor.name.in_((_VENDOR_A, _VENDOR_B))))
    await db.execute(delete(User).where(User.username == _OWNER))
    await db.commit()


@pytest.fixture
async def seeded(db_session: AsyncSession) -> Any:
    await _cleanup(db_session)
    try:
        yield await _seed(db_session)
    finally:
        await _cleanup(db_session)


async def _get(client: AsyncClient, headers: dict[str, str], path: str, **params: Any) -> Response:
    response = await client.get(
        f"/api/vehicles/{path}", headers=headers, params={k: v for k, v in params.items() if v}
    )
    assert response.status_code == 200, response.text
    return response


def _disposition(response: Response) -> str:
    return response.headers["content-disposition"]


def _history_row(
    when: date,
    odometer: str | None,
    category: str | None,
    service_type: str,
    cost: str | None,
    vendor: str | None,
) -> dict[str, Any]:
    return {
        "date": when,
        "odometer_km": Decimal(odometer) if odometer is not None else None,
        "service_category": category,
        "service_type": service_type,
        "cost": Decimal(cost) if cost is not None else None,
        "vendor_name": vendor,
    }


# Newest first, as the route orders them. The window is [2025-02-01, 2025-11-30].
_PAST_WINDOW = [_history_row(date(2025, 12, 20), None, None, "Service", "0", None)]
_IN_WINDOW = [
    _history_row(date(2025, 11, 30), "18000", "Upgrades", "=1+1", "300.00", _VENDOR_A),
    _history_row(date(2025, 8, 20), "15000", "Collision", "Bumper", "500.00", _VENDOR_B),
    _history_row(date(2025, 7, 4), "0", None, "Car wash", "12.00", None),
    _history_row(date(2025, 5, 10), None, "Maintenance", "Disposal fee, $15 cash", "15.00", None),
    _history_row(date(2025, 2, 1), "10000", "Maintenance", "Oil change", "49.99", _VENDOR_A),
    _history_row(date(2025, 2, 1), "10000", "Maintenance", "Free inspection", "0.00", _VENDOR_A),
    _history_row(date(2025, 2, 1), "10000", "Maintenance", "Wiper check", None, _VENDOR_A),
]
_BEFORE_WINDOW = [
    _history_row(date(2024, 12, 15), "9000", "Maintenance", "Old oil", "40.00", _VENDOR_A),
    _history_row(date(2024, 9, 9), "7000", "Upgrades", "Tow hitch", "400.00", _VENDOR_A),
    _history_row(date(2024, 3, 10), "5000", "Collision", "Door ding", "250.00", _VENDOR_B),
]


class TestServiceHistoryPdf:
    async def test_inside_the_window(
        self, client: AsyncClient, seeded: dict[str, str], pdf_calls: list, frozen_clock: None
    ) -> None:
        response = await _get(
            client,
            seeded,
            f"{_VIN}/reports/service-history-pdf",
            start_date="2025-02-01",
            end_date="2025-11-30",
            currency_code="EUR",
            locale="de-DE",
            date_format="dmy",
        )
        assert _disposition(response) == (
            f"attachment; filename=service_history_{_VIN}_{_STAMP}.pdf"
        )
        assert pdf_calls == [
            (
                "__init__",
                {
                    "render_context": _CONTEXT,
                    "currency_code": "EUR",
                    "locale": "de-DE",
                    "date_order": "dmy",
                },
            ),
            (
                "generate_service_history_pdf",
                {
                    "vehicle_info": _VEHICLE_INFO | {"license_plate": "PIN-1"},
                    "service_records": _IN_WINDOW,
                    "start_date": date(2025, 2, 1),
                    "end_date": date(2025, 11, 30),
                },
            ),
        ]

    async def test_no_window(
        self, client: AsyncClient, seeded: dict[str, str], pdf_calls: list, frozen_clock: None
    ) -> None:
        await _get(client, seeded, f"{_VIN}/reports/service-history-pdf")
        assert pdf_calls == [
            (
                "__init__",
                {
                    "render_context": _CONTEXT,
                    "currency_code": "USD",
                    "locale": "en-US",
                    "date_order": "mdy",
                },
            ),
            (
                "generate_service_history_pdf",
                {
                    "vehicle_info": _VEHICLE_INFO | {"license_plate": "PIN-1"},
                    "service_records": _PAST_WINDOW + _IN_WINDOW + _BEFORE_WINDOW,
                    "start_date": None,
                    "end_date": None,
                },
            ),
        ]


class TestSaleHistoryPdf:
    async def test_never_notes_and_no_costs(
        self, client: AsyncClient, seeded: dict[str, str], pdf_calls: list, frozen_clock: None
    ) -> None:
        response = await _get(client, seeded, f"{_VIN}/reports/sale-history-pdf", date_format="dmy")
        # The short tail of the VIN, not the whole thing.
        assert _disposition(response) == (
            f"attachment; filename=sale_history_{_VIN[-6:]}_{_STAMP}.pdf"
        )

        def row(when: date, odometer: str | None, service_type: str) -> dict[str, Any]:
            return {
                "date": when,
                "odometer_km": Decimal(odometer) if odometer is not None else None,
                "service_type": service_type,
            }

        assert pdf_calls == [
            ("__init__", {"render_context": _CONTEXT, "date_order": "dmy"}),
            (
                "generate_sale_history_pdf",
                {
                    "vehicle_info": _VEHICLE_INFO,
                    "service_records": [
                        row(date(2025, 12, 20), None, "Service"),
                        row(date(2025, 11, 30), "18000", "=1+1"),
                        row(date(2025, 8, 20), "15000", "Bumper"),
                        row(date(2025, 7, 4), "0", "Car wash"),
                        # The category, never the notes.
                        row(date(2025, 5, 10), None, "Maintenance"),
                        row(date(2025, 2, 1), "10000", "Oil change"),
                        row(date(2025, 2, 1), "10000", "Free inspection"),
                        row(date(2025, 2, 1), "10000", "Wiper check"),
                        row(date(2024, 12, 15), "9000", "Old oil"),
                        row(date(2024, 9, 9), "7000", "Tow hitch"),
                        row(date(2024, 3, 10), "5000", "Door ding"),
                    ],
                },
            ),
        ]


class TestCostSummaryPdf:
    async def test_motorized_year(
        self, client: AsyncClient, seeded: dict[str, str], pdf_calls: list, frozen_clock: None
    ) -> None:
        response = await _get(
            client,
            seeded,
            f"{_VIN}/reports/cost-summary-pdf",
            year=2025,
            # Lowercase isn't ISO shape, so it falls back to USD; the locale still passes.
            currency_code="gbp",
            locale="en-GB",
        )
        assert _disposition(response) == f"attachment; filename=cost_summary_{_VIN}_2025.pdf"
        assert pdf_calls == [
            (
                "__init__",
                {
                    "render_context": _CONTEXT,
                    "currency_code": "USD",
                    "locale": "en-GB",
                    "date_order": "mdy",
                },
            ),
            (
                "generate_cost_summary_pdf",
                {
                    "vehicle_info": _VEHICLE_INFO | {"vehicle_type": "Car"},
                    "cost_data": {
                        # Six 2025 visits; the three 2024 ones and the 2024 fill stay out.
                        "service_count": 6,
                        "service_total": Decimal("876.99"),
                        # The None-cost fill counts but adds nothing.
                        "fuel_count": 2,
                        "fuel_total": Decimal("55.00"),
                        "collision_count": 1,
                        "collision_total": Decimal("500.00"),
                        "upgrade_count": 1,
                        "upgrade_total": Decimal("300.00"),
                    },
                    "year": 2025,
                },
            ),
        ]

    async def test_trailer_skips_fuel(
        self, client: AsyncClient, seeded: dict[str, str], pdf_calls: list, frozen_clock: None
    ) -> None:
        response = await _get(client, seeded, f"{_TRAILER_KEY}/reports/cost-summary-pdf", year=2025)
        # The serial goes in the filename, never the generated key.
        assert _disposition(response) == (
            f"attachment; filename=cost_summary_{_TRAILER_SERIAL}_2025.pdf"
        )
        assert pdf_calls[1] == (
            "generate_cost_summary_pdf",
            {
                "vehicle_info": {
                    "vin": _TRAILER_KEY,
                    "identifier_label": "Serial",
                    "identifier": _TRAILER_SERIAL,
                    "year": 2021,
                    "make": "Haul",
                    "model": "Box",
                    "vehicle_type": "Trailer",
                },
                "cost_data": {
                    "service_count": 1,
                    "service_total": Decimal("80.00"),
                    "fuel_count": 0,
                    "fuel_total": 0,
                    "collision_count": 0,
                    "collision_total": 0,
                    "upgrade_count": 0,
                    "upgrade_total": 0,
                },
                "year": 2025,
            },
        )


class TestTaxDeductionPdf:
    async def test_zero_and_none_costs_drop(
        self, client: AsyncClient, seeded: dict[str, str], pdf_calls: list, frozen_clock: None
    ) -> None:
        response = await _get(
            client, seeded, f"{_VIN}/reports/tax-deduction-pdf", year=2025, date_format="dmy"
        )
        assert _disposition(response) == f"attachment; filename=tax_deduction_{_VIN}_2025.pdf"

        def row(when: date, category: str, description: str, cost: str) -> dict[str, Any]:
            return {
                "date": when,
                "category": category,
                "description": description,
                "cost": Decimal(cost),
            }

        assert pdf_calls == [
            (
                "__init__",
                {
                    "render_context": _CONTEXT,
                    "currency_code": "USD",
                    "locale": "en-US",
                    "date_order": "dmy",
                },
            ),
            (
                "generate_tax_deduction_pdf",
                {
                    "vehicle_info": _VEHICLE_INFO,
                    # Oldest first. Free inspection (0) and Wiper check (None) are gone.
                    "deductible_records": [
                        row(date(2025, 2, 1), "Maintenance", "Oil change", "49.99"),
                        row(date(2025, 7, 4), "Service", "Car wash", "12.00"),
                        row(date(2025, 8, 20), "Collision", "Bumper", "500.00"),
                        row(date(2025, 11, 30), "Upgrades", "=1+1", "300.00"),
                    ],
                    "year": 2025,
                },
            ),
        ]


def _assert_golden(name: str, body: bytes) -> None:
    """Byte-for-byte against a committed golden. A missing one is written and fails."""
    path = GOLDENS / name
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        pytest.fail(f"wrote missing golden {name}; check it by eye and rerun")
    assert body == path.read_bytes()


class TestCsvGoldens:
    @pytest.mark.parametrize(
        ("golden", "params"),
        [
            ("service_history_window.csv", {"start_date": "2025-02-01", "end_date": "2025-11-30"}),
            ("service_history_all.csv", {}),
        ],
    )
    async def test_service_history(
        self,
        client: AsyncClient,
        seeded: dict[str, str],
        frozen_clock: None,
        golden: str,
        params: dict[str, str],
    ) -> None:
        response = await _get(client, seeded, f"{_VIN}/reports/service-history-csv", **params)
        assert _disposition(response) == (
            f"attachment; filename=service_history_{_VIN}_{_STAMP}.csv"
        )
        _assert_golden(golden, response.content)

    @pytest.mark.parametrize(
        ("golden", "params"),
        [("all_records_2025.csv", {"year": 2025}), ("all_records_all.csv", {})],
    )
    async def test_all_records(
        self,
        client: AsyncClient,
        seeded: dict[str, str],
        frozen_clock: None,
        golden: str,
        params: dict[str, Any],
    ) -> None:
        response = await _get(client, seeded, f"{_VIN}/reports/all-records-csv", **params)
        assert _disposition(response) == (f"attachment; filename=all_records_{_VIN}_{_STAMP}.csv")
        _assert_golden(golden, response.content)
