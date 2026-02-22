"""Tests for garage analytics PDF report generation."""

from decimal import Decimal

import fitz  # PyMuPDF

from app.utils.pdf_garage_report import generate_garage_analytics_pdf

PDF_MAGIC = b"%PDF"


def _extract_text(pdf_bytes: bytes, normalize: bool = False) -> str:
    """Extract all text from PDF bytes using PyMuPDF.

    Args:
        pdf_bytes: Raw PDF bytes.
        normalize: If True, collapse newlines to spaces for wrapped text matching.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()  # type: ignore[operator]
    doc.close()
    if normalize:
        text = " ".join(text.split())
    return text


def _make_garage_data(
    vehicle_count: int = 3,
    include_trends: bool = True,
    include_all_cost_fields: bool = True,
) -> dict:
    """Build minimal garage analytics data dict for testing."""
    total_costs: dict = {
        "total_garage_value": Decimal("120000.00"),
        "total_maintenance": Decimal("5000.00"),
        "total_upgrades": Decimal("2000.00"),
        "total_fuel": Decimal("8000.00"),
        "total_def": Decimal("300.00"),
        "total_insurance": Decimal("4000.00"),
        "total_taxes": Decimal("1500.00"),
    }
    if include_all_cost_fields:
        total_costs.update(
            {
                "total_inspection": Decimal("400.00"),
                "total_collision": Decimal("1200.00"),
                "total_detailing": Decimal("600.00"),
            }
        )
    else:
        total_costs.update(
            {
                "total_inspection": Decimal("0.00"),
                "total_collision": Decimal("0.00"),
                "total_detailing": Decimal("0.00"),
            }
        )

    cost_breakdown = [
        {"category": "Maintenance", "amount": Decimal("5000.00")},
        {"category": "Fuel", "amount": Decimal("8000.00")},
        {"category": "Insurance", "amount": Decimal("4000.00")},
        {"category": "Upgrades", "amount": Decimal("2000.00")},
        {"category": "Taxes", "amount": Decimal("1500.00")},
        {"category": "Collision", "amount": Decimal("1200.00")},
        {"category": "Detailing", "amount": Decimal("600.00")},
        {"category": "Inspection", "amount": Decimal("400.00")},
        {"category": "DEF", "amount": Decimal("300.00")},
    ]

    vehicles = [
        {
            "vin": "VIN001",
            "name": "2021 Honda Accord",
            "nickname": "Accord",
            "purchase_price": Decimal("30000.00"),
            "total_maintenance": Decimal("2000.00"),
            "total_upgrades": Decimal("500.00"),
            "total_inspection": Decimal("150.00"),
            "total_collision": Decimal("0.00"),
            "total_detailing": Decimal("200.00"),
            "total_fuel": Decimal("3000.00"),
            "total_def": Decimal("0.00"),
            "total_cost": Decimal("5850.00"),
        },
        {
            "vin": "VIN002",
            "name": "2023 Ram 3500",
            "nickname": "Ram",
            "purchase_price": Decimal("65000.00"),
            "total_maintenance": Decimal("2500.00"),
            "total_upgrades": Decimal("1200.00"),
            "total_inspection": Decimal("200.00"),
            "total_collision": Decimal("1200.00"),
            "total_detailing": Decimal("300.00"),
            "total_fuel": Decimal("4500.00"),
            "total_def": Decimal("300.00"),
            "total_cost": Decimal("10200.00"),
        },
        {
            "vin": "VIN003",
            "name": "2020 Mitsubishi Mirage",
            "nickname": "Mirage",
            "purchase_price": Decimal("25000.00"),
            "total_maintenance": Decimal("500.00"),
            "total_upgrades": Decimal("300.00"),
            "total_inspection": Decimal("50.00"),
            "total_collision": Decimal("0.00"),
            "total_detailing": Decimal("100.00"),
            "total_fuel": Decimal("500.00"),
            "total_def": Decimal("0.00"),
            "total_cost": Decimal("1450.00"),
        },
    ]

    monthly_trends = []
    if include_trends:
        monthly_trends = [
            {
                "month": "Jan 25",
                "service": Decimal("400.00"),
                "fuel": Decimal("300.00"),
                "def_cost": Decimal("25.00"),
                "total": Decimal("725.00"),
            },
            {
                "month": "Feb 25",
                "service": Decimal("350.00"),
                "fuel": Decimal("280.00"),
                "def_cost": Decimal("20.00"),
                "total": Decimal("650.00"),
            },
        ]

    return {
        "vehicle_count": vehicle_count,
        "total_costs": total_costs,
        "cost_breakdown_by_category": cost_breakdown,
        "cost_by_vehicle": vehicles[:vehicle_count],
        "monthly_trends": monthly_trends,
    }


class TestGenerateGarageAnalyticsPdf:
    """Tests for generate_garage_analytics_pdf."""

    def test_returns_valid_pdf(self) -> None:
        data = _make_garage_data()
        buf = generate_garage_analytics_pdf(data)
        content = buf.read()
        assert content[:4] == PDF_MAGIC
        assert len(content) > 5000

    def test_contains_vehicle_count(self) -> None:
        data = _make_garage_data(vehicle_count=3)
        buf = generate_garage_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "Total Vehicles" in text
        assert "3 vehicles" in text

    def test_contains_kpi_labels(self) -> None:
        data = _make_garage_data()
        buf = generate_garage_analytics_pdf(data)
        text = _extract_text(buf.read(), normalize=True)
        assert "GARAGE VALUE" in text
        assert "OPERATING COST" in text
        assert "TOTAL MAINTENANCE" in text
        assert "TOTAL FUEL" in text

    def test_contains_vehicle_names(self) -> None:
        data = _make_garage_data()
        buf = generate_garage_analytics_pdf(data)
        # Narrow columns may split words, so strip ALL whitespace for matching
        text = _extract_text(buf.read(), normalize=True).replace(" ", "")
        assert "Accord" in text
        assert "Ram" in text
        assert "Mirage" in text

    def test_contains_all_cost_category_headers(self) -> None:
        """Regression: all GarageVehicleCost fields must have column headers."""
        data = _make_garage_data(include_all_cost_fields=True)
        buf = generate_garage_analytics_pdf(data)
        # Strip ALL whitespace - narrow columns split words across lines
        text = _extract_text(buf.read(), normalize=True).replace(" ", "")
        assert "MAINT." in text
        assert "UPGRADES" in text
        assert "INSPECT." in text
        assert "COLLISION" in text
        assert "DETAIL." in text
        assert "FUEL" in text
        assert "DEF" in text
        assert "TOTAL" in text
        assert "PURCHASE" in text

    def test_contains_section_headings(self) -> None:
        data = _make_garage_data()
        buf = generate_garage_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "Cost Breakdown by Category" in text
        assert "Cost by Vehicle" in text
        assert "Monthly Spending Trends" in text

    def test_contains_branded_elements(self) -> None:
        data = _make_garage_data()
        buf = generate_garage_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "MyGarage" in text
        assert "homelabforge.io" in text

    def test_no_monthly_trends(self) -> None:
        data = _make_garage_data(include_trends=False)
        buf = generate_garage_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "Monthly Spending Trends" not in text

    def test_single_vehicle(self) -> None:
        data = _make_garage_data(vehicle_count=1)
        buf = generate_garage_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "1 vehicle" in text

    def test_regression_inspection_collision_detailing_values(self) -> None:
        """Ensure the data flow bug fix carries all cost fields through."""
        data = _make_garage_data(include_all_cost_fields=True)
        # Verify the input data has non-zero values for previously-dropped fields
        for v in data["cost_by_vehicle"]:
            if v["name"] == "2023 Ram 3500":
                assert v["total_inspection"] == Decimal("200.00")
                assert v["total_collision"] == Decimal("1200.00")
                assert v["total_detailing"] == Decimal("300.00")
                break

        buf = generate_garage_analytics_pdf(data)
        # Strip ALL whitespace — narrow columns split dollar values across lines
        text = _extract_text(buf.read(), normalize=True).replace(" ", "")
        # format_currency_compact drops cents for values >= $100
        assert "$200" in text  # inspection
        assert "$1,200" in text  # collision
        assert "$300" in text  # detailing
