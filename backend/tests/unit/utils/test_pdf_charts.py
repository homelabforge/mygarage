"""Tests for PDF chart generation functions."""

from decimal import Decimal

from app.utils.pdf_charts import (
    render_donut_chart,
    render_garage_monthly_trends,
    render_monthly_spending_chart,
    render_projection_bars,
)

PNG_MAGIC = b"\x89PNG"


class TestRenderMonthlySpendingChart:
    """Tests for render_monthly_spending_chart."""

    def test_returns_valid_png(self) -> None:
        data = [
            {
                "month_name": "January",
                "year": 2025,
                "total_service_cost": Decimal("500.00"),
                "total_fuel_cost": Decimal("200.00"),
            },
            {
                "month_name": "February",
                "year": 2025,
                "total_service_cost": Decimal("300.00"),
                "total_fuel_cost": Decimal("180.00"),
            },
        ]
        buf = render_monthly_spending_chart(data)
        content = buf.read()
        assert content[:4] == PNG_MAGIC
        assert len(content) > 1000  # Real chart image should be substantial

    def test_empty_data_returns_png(self) -> None:
        buf = render_monthly_spending_chart([])
        content = buf.read()
        assert content[:4] == PNG_MAGIC

    def test_single_month(self) -> None:
        data = [
            {
                "month_name": "March",
                "year": 2025,
                "total_service_cost": Decimal("100.00"),
                "total_fuel_cost": Decimal("50.00"),
            },
        ]
        buf = render_monthly_spending_chart(data)
        assert buf.read()[:4] == PNG_MAGIC

    def test_handles_zero_costs(self) -> None:
        data = [
            {
                "month_name": "April",
                "year": 2025,
                "total_service_cost": Decimal("0.00"),
                "total_fuel_cost": Decimal("0.00"),
            },
        ]
        buf = render_monthly_spending_chart(data)
        assert buf.read()[:4] == PNG_MAGIC

    def test_handles_none_values(self) -> None:
        data = [
            {
                "month_name": "May",
                "year": 2025,
                "total_service_cost": None,
                "total_fuel_cost": None,
            },
        ]
        buf = render_monthly_spending_chart(data)
        assert buf.read()[:4] == PNG_MAGIC

    def test_year_labels_change(self) -> None:
        """Year suffix should appear on labels when year changes."""
        data = [
            {
                "month_name": "November",
                "year": 2024,
                "total_service_cost": Decimal("100"),
                "total_fuel_cost": Decimal("50"),
            },
            {
                "month_name": "December",
                "year": 2024,
                "total_service_cost": Decimal("100"),
                "total_fuel_cost": Decimal("50"),
            },
            {
                "month_name": "January",
                "year": 2025,
                "total_service_cost": Decimal("100"),
                "total_fuel_cost": Decimal("50"),
            },
        ]
        buf = render_monthly_spending_chart(data)
        content = buf.read()
        assert content[:4] == PNG_MAGIC
        assert len(content) > 1000


class TestRenderDonutChart:
    """Tests for render_donut_chart."""

    def test_returns_valid_png(self) -> None:
        categories = [
            ("Oil Change", 500.0),
            ("Brake Service", 300.0),
            ("Tire Rotation", 200.0),
        ]
        buf = render_donut_chart(categories, total=1000.0)
        content = buf.read()
        assert content[:4] == PNG_MAGIC
        assert len(content) > 1000

    def test_empty_categories(self) -> None:
        buf = render_donut_chart([], total=0.0)
        assert buf.read()[:4] == PNG_MAGIC

    def test_single_category(self) -> None:
        buf = render_donut_chart([("Service", 100.0)], total=100.0)
        assert buf.read()[:4] == PNG_MAGIC

    def test_zero_total(self) -> None:
        buf = render_donut_chart([("Service", 0.0)], total=0.0)
        assert buf.read()[:4] == PNG_MAGIC

    def test_many_categories(self) -> None:
        """Test with more categories than colors in the palette."""
        cats = [(f"Category {i}", float(100 - i * 10)) for i in range(10)]
        buf = render_donut_chart(cats, total=550.0)
        assert buf.read()[:4] == PNG_MAGIC


class TestRenderProjectionBars:
    """Tests for render_projection_bars."""

    def test_returns_valid_png(self) -> None:
        buf = render_projection_bars(
            current_amount=5000.0,
            six_month=3000.0,
            twelve_month=6000.0,
            months_tracked=12,
        )
        content = buf.read()
        assert content[:4] == PNG_MAGIC
        assert len(content) > 1000

    def test_zero_values(self) -> None:
        buf = render_projection_bars(
            current_amount=0.0,
            six_month=0.0,
            twelve_month=0.0,
            months_tracked=0,
        )
        assert buf.read()[:4] == PNG_MAGIC

    def test_large_values(self) -> None:
        buf = render_projection_bars(
            current_amount=50000.0,
            six_month=25000.0,
            twelve_month=50000.0,
            months_tracked=36,
        )
        assert buf.read()[:4] == PNG_MAGIC


class TestRenderGarageMonthlyTrends:
    """Tests for render_garage_monthly_trends."""

    def test_returns_valid_png(self) -> None:
        data = [
            {
                "month": "Jan 25",
                "service": Decimal("400"),
                "fuel": Decimal("200"),
                "def_cost": Decimal("30"),
            },
            {
                "month": "Feb 25",
                "service": Decimal("300"),
                "fuel": Decimal("180"),
                "def_cost": Decimal("25"),
            },
        ]
        buf = render_garage_monthly_trends(data)
        content = buf.read()
        assert content[:4] == PNG_MAGIC
        assert len(content) > 1000

    def test_empty_data(self) -> None:
        buf = render_garage_monthly_trends([])
        assert buf.read()[:4] == PNG_MAGIC

    def test_single_month(self) -> None:
        data = [
            {
                "month": "Mar 25",
                "service": Decimal("100"),
                "fuel": Decimal("50"),
                "def_cost": Decimal("0"),
            },
        ]
        buf = render_garage_monthly_trends(data)
        assert buf.read()[:4] == PNG_MAGIC

    def test_handles_missing_fields(self) -> None:
        """Fields default to 0 when missing."""
        data = [{"month": "Apr 25"}]
        buf = render_garage_monthly_trends(data)
        assert buf.read()[:4] == PNG_MAGIC
