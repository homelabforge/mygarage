"""Tests for vehicle analytics PDF report generation."""

from decimal import Decimal

import fitz  # PyMuPDF

from app.utils.pdf_vehicle_report import generate_vehicle_analytics_pdf

PDF_MAGIC = b"%PDF"


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using PyMuPDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()  # type: ignore[operator]
    doc.close()
    return text


def _make_analytics_data(
    vehicle_name: str = "2021 Honda Accord",
    vin: str = "1HGCV1F31MA000001",
    total_cost: Decimal = Decimal("5000.00"),
    service_count: int = 10,
    fuel_count: int = 20,
    include_monthly: bool = True,
    include_service_breakdown: bool = True,
) -> dict:
    """Build minimal analytics data dict for testing."""
    monthly = []
    if include_monthly:
        monthly = [
            {
                "year": 2025,
                "month": 1,
                "month_name": "January",
                "total_service_cost": Decimal("300.00"),
                "total_fuel_cost": Decimal("150.00"),
                "total_def_cost": Decimal("0.00"),
                "total_cost": Decimal("450.00"),
                "service_count": 3,
                "fuel_count": 4,
            },
            {
                "year": 2025,
                "month": 2,
                "month_name": "February",
                "total_service_cost": Decimal("200.00"),
                "total_fuel_cost": Decimal("120.00"),
                "total_def_cost": Decimal("0.00"),
                "total_cost": Decimal("320.00"),
                "service_count": 2,
                "fuel_count": 3,
            },
        ]

    breakdown = []
    if include_service_breakdown:
        breakdown = [
            {
                "service_type": "Oil Change",
                "total_cost": Decimal("300.00"),
                "count": 4,
                "average_cost": Decimal("75.00"),
            },
            {
                "service_type": "Brake Service",
                "total_cost": Decimal("800.00"),
                "count": 2,
                "average_cost": Decimal("400.00"),
            },
        ]

    return {
        "vin": vin,
        "vehicle_name": vehicle_name,
        "vehicle_type": "Car",
        "days_owned": 365,
        "total_miles_driven": 12000,
        "average_miles_per_month": 1000,
        "cost_analysis": {
            "total_service_cost": Decimal("3000.00"),
            "total_fuel_cost": Decimal("2000.00"),
            "total_def_cost": Decimal("0.00"),
            "total_cost": total_cost,
            "average_monthly_cost": Decimal("416.67"),
            "service_count": service_count,
            "fuel_count": fuel_count,
            "def_count": 0,
            "months_tracked": 12,
            "cost_per_mile": Decimal("0.42"),
            "rolling_avg_3m": Decimal("400.00"),
            "rolling_avg_6m": Decimal("420.00"),
            "trend_direction": "decreasing",
            "monthly_breakdown": monthly,
            "service_type_breakdown": breakdown,
            "anomalies": [],
        },
        "cost_projection": {
            "monthly_average": Decimal("416.67"),
            "six_month_projection": Decimal("2500.00"),
            "twelve_month_projection": Decimal("5000.00"),
            "assumptions": "Projection assumes spending remains at recent averages.",
        },
        "fuel_economy": {
            "average_mpg": Decimal("30.5"),
            "best_mpg": Decimal("35.2"),
            "worst_mpg": Decimal("26.1"),
            "recent_mpg": Decimal("31.0"),
            "trend": "stable",
            "data_points": [],
        },
        "fuel_alerts": [],
        "service_history": [],
        "predictions": [],
    }


def _make_vendor_data() -> dict:
    """Build vendor analytics data dict for testing."""
    return {
        "vendors": [
            {
                "vendor_name": "AutoZone",
                "total_spent": Decimal("1200.00"),
                "service_count": 5,
                "average_cost": Decimal("240.00"),
                "service_types": ["Oil Change", "Brake Service"],
            },
            {
                "vendor_name": "Jiffy Lube",
                "total_spent": Decimal("600.00"),
                "service_count": 3,
                "average_cost": Decimal("200.00"),
                "service_types": ["Oil Change"],
            },
        ],
        "total_vendors": 2,
        "most_used_vendor": "AutoZone",
        "highest_spending_vendor": "AutoZone",
    }


def _make_seasonal_data() -> dict:
    """Build seasonal analytics data dict for testing."""
    return {
        "seasons": [
            {
                "season": "Winter",
                "total_cost": Decimal("1500.00"),
                "service_count": 4,
                "average_cost": Decimal("375.00"),
                "variance_from_annual": Decimal("12.5"),
                "common_services": ["Oil Change"],
            },
            {
                "season": "Spring",
                "total_cost": Decimal("1200.00"),
                "service_count": 3,
                "average_cost": Decimal("400.00"),
                "variance_from_annual": Decimal("-5.0"),
                "common_services": ["Brake Service"],
            },
            {
                "season": "Summer",
                "total_cost": Decimal("800.00"),
                "service_count": 2,
                "average_cost": Decimal("400.00"),
                "variance_from_annual": Decimal("-20.0"),
                "common_services": ["Tire Rotation"],
            },
            {
                "season": "Fall",
                "total_cost": Decimal("1000.00"),
                "service_count": 3,
                "average_cost": Decimal("333.33"),
                "variance_from_annual": Decimal("-8.5"),
                "common_services": ["Oil Change"],
            },
        ],
        "highest_cost_season": "Winter",
        "lowest_cost_season": "Summer",
        "annual_average": Decimal("1125.00"),
    }


class TestGenerateVehicleAnalyticsPdf:
    """Tests for generate_vehicle_analytics_pdf."""

    def test_returns_valid_pdf(self) -> None:
        data = _make_analytics_data()
        buf = generate_vehicle_analytics_pdf(data)
        content = buf.read()
        assert content[:4] == PDF_MAGIC
        assert len(content) > 5000

    def test_contains_vehicle_name(self) -> None:
        data = _make_analytics_data(vehicle_name="2023 Ram 3500")
        buf = generate_vehicle_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "2023 Ram 3500" in text

    def test_contains_vin(self) -> None:
        data = _make_analytics_data(vin="3C63RRGL9NG000001")
        buf = generate_vehicle_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "3C63RRGL9NG000001" in text

    def test_contains_section_headings(self) -> None:
        data = _make_analytics_data()
        buf = generate_vehicle_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "Monthly Spending" in text
        assert "Service Breakdown" in text

    def test_contains_kpi_labels(self) -> None:
        data = _make_analytics_data()
        buf = generate_vehicle_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "TOTAL COST" in text
        assert "COST PER MILE" in text
        assert "AVG MONTHLY" in text
        assert "PROJECTED 12-MO" in text

    def test_with_vendor_data(self) -> None:
        data = _make_analytics_data()
        vendor = _make_vendor_data()
        buf = generate_vehicle_analytics_pdf(data, vendor_data=vendor)
        text = _extract_text(buf.read())
        assert "Vendor Analysis" in text
        assert "AutoZone" in text

    def test_with_seasonal_data(self) -> None:
        data = _make_analytics_data()
        seasonal = _make_seasonal_data()
        buf = generate_vehicle_analytics_pdf(data, seasonal_data=seasonal)
        text = _extract_text(buf.read())
        assert "Seasonal Spending" in text

    def test_with_all_data(self) -> None:
        data = _make_analytics_data()
        vendor = _make_vendor_data()
        seasonal = _make_seasonal_data()
        buf = generate_vehicle_analytics_pdf(data, vendor, seasonal)
        text = _extract_text(buf.read())
        assert "MyGarage" in text

    def test_no_vendor_no_seasonal(self) -> None:
        data = _make_analytics_data()
        buf = generate_vehicle_analytics_pdf(data, vendor_data=None, seasonal_data=None)
        content = buf.read()
        assert content[:4] == PDF_MAGIC

    def test_zero_costs(self) -> None:
        data = _make_analytics_data(
            total_cost=Decimal("0.00"),
            service_count=0,
            fuel_count=0,
            include_monthly=False,
            include_service_breakdown=False,
        )
        buf = generate_vehicle_analytics_pdf(data)
        content = buf.read()
        assert content[:4] == PDF_MAGIC

    def test_contains_branded_footer(self) -> None:
        data = _make_analytics_data()
        buf = generate_vehicle_analytics_pdf(data)
        text = _extract_text(buf.read())
        assert "homelabforge.io" in text
