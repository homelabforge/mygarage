"""Unit tests for analytics service functions."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services import analytics_service


def _make_fuel_record(**kwargs):
    """Create a mock FuelRecord-like object with sensible defaults."""
    defaults = {
        "id": 1,
        "vin": "1HGBH41JXMN109186",
        "date": date(2024, 1, 15),
        "mileage": 50000,
        "gallons": Decimal("12.5"),
        "propane_gallons": None,
        "tank_size_lb": None,
        "tank_quantity": None,
        "kwh": None,
        "cost": Decimal("45.00"),
        "price_per_unit": None,
        "fuel_type": "Gasoline",
        "is_full_tank": True,
        "missed_fillup": False,
        "is_hauling": False,
        "notes": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_service_record(**kwargs):
    """Create a mock ServiceRecord-like object with sensible defaults."""
    defaults = {
        "id": 1,
        "vin": "1HGBH41JXMN109186",
        "date": date(2024, 1, 15),
        "mileage": 50000,
        "service_type": "Oil Change",
        "cost": Decimal("75.00"),
        "notes": None,
        "vendor_name": "AutoShop",
        "vendor_location": None,
        "service_category": "Maintenance",
        "insurance_claim": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
@pytest.mark.analytics
class TestAnalyticsService:
    """Test analytics service utility functions."""

    def test_calculate_trend_direction_increasing(self):
        """Test trend calculation for increasing values."""
        series = pd.Series([100, 120, 140, 160, 180])
        trend = analytics_service.calculate_trend_direction(series)
        assert trend == "increasing"

    def test_calculate_trend_direction_decreasing(self):
        """Test trend calculation for decreasing values."""
        series = pd.Series([180, 160, 140, 120, 100])
        trend = analytics_service.calculate_trend_direction(series)
        assert trend == "decreasing"

    def test_calculate_trend_direction_stable(self):
        """Test trend calculation for stable values."""
        series = pd.Series([100, 102, 98, 101, 99])
        trend = analytics_service.calculate_trend_direction(series)
        assert trend == "stable"

    def test_calculate_trend_direction_empty_series(self):
        """Test trend calculation with empty series."""
        series = pd.Series([])
        trend = analytics_service.calculate_trend_direction(series)
        assert trend == "stable"

    def test_calculate_rolling_averages(self):
        """Test rolling average calculations."""
        df = pd.DataFrame(
            {
                "year": [2024] * 12 + [2025],
                "month": list(range(1, 13)) + [1],
                "total_cost": [
                    100,
                    200,
                    300,
                    400,
                    500,
                    600,
                    700,
                    800,
                    900,
                    1000,
                    1100,
                    1200,
                    1300,
                ],
            }
        )

        rolling_avgs = analytics_service.calculate_rolling_averages(df)

        assert "rolling_3m" in rolling_avgs
        assert "rolling_6m" in rolling_avgs
        assert "rolling_12m" in rolling_avgs

        # 3-month rolling average of last 3 values: (1100 + 1200 + 1300) / 3 = 1200
        assert rolling_avgs["rolling_3m"] == Decimal("1200.00")

        # 6-month rolling average
        expected_6m = sum([800, 900, 1000, 1100, 1200, 1300]) / 6
        assert rolling_avgs["rolling_6m"] == Decimal(str(round(expected_6m, 2)))

    def test_calculate_rolling_averages_insufficient_data(self):
        """Test rolling averages with insufficient data."""
        df = pd.DataFrame({"year": [2024, 2024], "month": [1, 2], "total_cost": [100, 200]})

        rolling_avgs = analytics_service.calculate_rolling_averages(df)

        assert rolling_avgs["rolling_3m"] is None
        assert rolling_avgs["rolling_6m"] is None
        assert rolling_avgs["rolling_12m"] is None

    def test_detect_anomalies_z_score(self):
        """Test anomaly detection using Z-score method."""
        values = pd.Series([100, 110, 105, 108, 102, 500, 107, 103])

        anomaly_indices = analytics_service.detect_anomalies(values, std_threshold=2.0)

        assert 5 in anomaly_indices
        assert len(anomaly_indices) == 1

    def test_detect_anomalies_no_anomalies(self):
        """Test anomaly detection with no anomalies."""
        values = pd.Series([100, 105, 102, 108, 103, 107, 104])

        anomaly_indices = analytics_service.detect_anomalies(values, std_threshold=2.0)

        assert len(anomaly_indices) == 0

    def test_detect_anomalies_insufficient_data(self):
        """Test anomaly detection with insufficient data."""
        values = pd.Series([100, 200])

        anomaly_indices = analytics_service.detect_anomalies(values, std_threshold=2.0)

        assert len(anomaly_indices) == 0

    def test_calculate_monthly_aggregation(self):
        """Test monthly cost aggregation."""
        dates = pd.date_range(start="2024-01-01", end="2024-03-31", freq="D")
        df = pd.DataFrame(
            {
                "date": dates,
                "type": ["service"] * 31 + ["fuel"] * 29 + ["service"] * 31,
                "cost": [100.0] * len(dates),
            }
        )

        monthly_df = analytics_service.calculate_monthly_aggregation(df)

        assert len(monthly_df) == 3

        assert "year" in monthly_df.columns
        assert "month" in monthly_df.columns
        assert "month_name" in monthly_df.columns
        assert "service_cost" in monthly_df.columns
        assert "fuel_cost" in monthly_df.columns
        assert "total_cost" in monthly_df.columns
        assert "service_count" in monthly_df.columns
        assert "fuel_count" in monthly_df.columns

        jan_row = monthly_df[monthly_df["month"] == 1].iloc[0]
        assert jan_row["service_count"] == 31
        assert jan_row["fuel_count"] == 0

    def test_records_to_dataframe_empty(self):
        """Test converting empty record lists to DataFrame."""
        df = analytics_service.records_to_dataframe([], [])

        assert df.empty
        assert "date" in df.columns
        assert "type" in df.columns
        assert "cost" in df.columns


@pytest.mark.unit
@pytest.mark.analytics
class TestRecordsToDataframe:
    """Test records_to_dataframe with actual data."""

    def test_service_records_only(self):
        """Test conversion with service records."""
        records = [
            _make_service_record(id=1, date=date(2024, 1, 15), cost=Decimal("100.00")),
            _make_service_record(id=2, date=date(2024, 2, 20), cost=Decimal("200.00")),
        ]

        df = analytics_service.records_to_dataframe(records, [])

        assert len(df) == 2
        assert all(df["type"] == "service")
        assert df["cost"].sum() == 300.0
        # Verify sorted by date
        assert df.iloc[0]["date"] <= df.iloc[1]["date"]

    def test_fuel_records_only(self):
        """Test conversion with fuel records."""
        records = [
            _make_fuel_record(
                id=1, date=date(2024, 3, 10), cost=Decimal("55.00"), gallons=Decimal("15.5")
            ),
            _make_fuel_record(
                id=2, date=date(2024, 1, 5), cost=Decimal("40.00"), gallons=Decimal("12.0")
            ),
        ]

        df = analytics_service.records_to_dataframe([], records)

        assert len(df) == 2
        assert all(df["type"] == "fuel")
        # Should be sorted by date (Jan before Mar)
        assert df.iloc[0]["date"] < df.iloc[1]["date"]

    def test_mixed_records(self):
        """Test conversion with both service and fuel records."""
        service = [_make_service_record(date=date(2024, 2, 1), cost=Decimal("150.00"))]
        fuel = [_make_fuel_record(date=date(2024, 1, 15), cost=Decimal("50.00"))]

        df = analytics_service.records_to_dataframe(service, fuel)

        assert len(df) == 2
        assert set(df["type"]) == {"service", "fuel"}
        # Fuel (Jan) should come first
        assert df.iloc[0]["type"] == "fuel"

    def test_skips_records_without_date_or_cost(self):
        """Test that records missing date or cost are filtered out."""
        records = [
            _make_service_record(id=1, date=date(2024, 1, 1), cost=Decimal("100.00")),
            _make_service_record(id=2, date=None, cost=Decimal("50.00")),
            _make_service_record(id=3, date=date(2024, 3, 1), cost=None),
        ]

        df = analytics_service.records_to_dataframe(records, [])

        assert len(df) == 1


@pytest.mark.unit
@pytest.mark.analytics
class TestCalculateFuelEconomy:
    """Test fuel economy calculation."""

    def test_basic_mpg_calculation(self):
        """Test MPG calculation with valid fill-up sequence."""
        records = [
            _make_fuel_record(
                date=date(2024, 1, 1), mileage=10000, gallons=Decimal("15.0"), cost=Decimal("50.00")
            ),
            _make_fuel_record(
                date=date(2024, 1, 15),
                mileage=10300,
                gallons=Decimal("12.0"),
                cost=Decimal("40.00"),
            ),
            _make_fuel_record(
                date=date(2024, 2, 1), mileage=10600, gallons=Decimal("12.5"), cost=Decimal("42.00")
            ),
        ]

        df, stats = analytics_service.calculate_fuel_economy_with_pandas(records)

        # First record is baseline (no diff), so 2 data points
        assert len(df) == 2
        assert "average_mpg" in stats
        assert "best_mpg" in stats
        assert "worst_mpg" in stats
        assert "recent_mpg" in stats
        assert "trend" in stats

        # MPG: 300/12=25, 300/12.5=24
        assert stats["average_mpg"] > Decimal("0")
        assert stats["best_mpg"] >= stats["worst_mpg"]

    def test_insufficient_records(self):
        """Test that fewer than 2 records returns empty."""
        records = [
            _make_fuel_record(date=date(2024, 1, 1), mileage=10000, gallons=Decimal("15.0")),
        ]

        df, stats = analytics_service.calculate_fuel_economy_with_pandas(records)

        assert df.empty
        assert stats == {}

    def test_empty_records(self):
        """Test with no records."""
        df, stats = analytics_service.calculate_fuel_economy_with_pandas([])

        assert df.empty
        assert stats == {}

    def test_filters_unrealistic_mpg(self):
        """Test that unrealistic MPG values (>100 or <5) are filtered."""
        records = [
            _make_fuel_record(
                date=date(2024, 1, 1), mileage=10000, gallons=Decimal("15.0"), cost=Decimal("50.00")
            ),
            # Tiny distance = unrealistically low MPG (2/15 = 0.13 MPG)
            _make_fuel_record(
                date=date(2024, 1, 15),
                mileage=10002,
                gallons=Decimal("15.0"),
                cost=Decimal("50.00"),
            ),
            # Normal trip
            _make_fuel_record(
                date=date(2024, 2, 1), mileage=10302, gallons=Decimal("12.0"), cost=Decimal("40.00")
            ),
        ]

        df, stats = analytics_service.calculate_fuel_economy_with_pandas(records)

        # Only the normal trip (300 mi / 12 gal = 25 MPG) should remain
        assert len(df) == 1
        assert stats["average_mpg"] == Decimal("25.0")

    def test_filters_negative_miles(self):
        """Test that negative mileage diffs are filtered (odometer correction)."""
        records = [
            _make_fuel_record(
                date=date(2024, 1, 1), mileage=10000, gallons=Decimal("12.0"), cost=Decimal("40.00")
            ),
            # Odometer went backwards
            _make_fuel_record(
                date=date(2024, 1, 15), mileage=9500, gallons=Decimal("12.0"), cost=Decimal("40.00")
            ),
            # Normal
            _make_fuel_record(
                date=date(2024, 2, 1), mileage=9800, gallons=Decimal("12.0"), cost=Decimal("40.00")
            ),
        ]

        df, stats = analytics_service.calculate_fuel_economy_with_pandas(records)

        # Only the 9500->9800 (300 mi) trip should be valid
        assert len(df) == 1

    def test_records_missing_mileage_or_gallons(self):
        """Test that records without mileage or gallons are excluded."""
        records = [
            _make_fuel_record(
                date=date(2024, 1, 1), mileage=10000, gallons=Decimal("12.0"), cost=Decimal("40.00")
            ),
            _make_fuel_record(
                date=date(2024, 1, 15), mileage=None, gallons=Decimal("12.0"), cost=Decimal("40.00")
            ),
            _make_fuel_record(
                date=date(2024, 2, 1), mileage=10600, gallons=None, cost=Decimal("40.00")
            ),
        ]

        # Only 1 valid record after filtering → less than 2 data points → empty
        df, stats = analytics_service.calculate_fuel_economy_with_pandas(records)

        assert df.empty
        assert stats == {}


@pytest.mark.unit
@pytest.mark.analytics
class TestCalculateSeasonalPatterns:
    """Test seasonal analysis grouping."""

    def test_all_four_seasons(self):
        """Test data spanning all four seasons."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2024-01-15",  # Winter
                        "2024-04-15",  # Spring
                        "2024-07-15",  # Summer
                        "2024-10-15",  # Fall
                    ]
                ),
                "cost": [100.0, 200.0, 300.0, 400.0],
                "type": ["service"] * 4,
            }
        )

        result = analytics_service.calculate_seasonal_patterns(df)

        assert len(result) == 4
        seasons = result["season"].tolist()
        assert "Winter" in seasons
        assert "Spring" in seasons
        assert "Summer" in seasons
        assert "Fall" in seasons

        winter = result[result["season"] == "Winter"].iloc[0]
        assert winter["total_cost"] == 100.0
        assert winter["count"] == 1

        summer = result[result["season"] == "Summer"].iloc[0]
        assert summer["total_cost"] == 300.0

    def test_empty_dataframe(self):
        """Test that empty data returns all seasons with zeros."""
        df = pd.DataFrame(columns=["date", "cost", "type"])

        result = analytics_service.calculate_seasonal_patterns(df)

        assert len(result) == 4
        assert all(result["total_cost"] == 0.0)
        assert all(result["count"] == 0)

    def test_partial_year_still_has_all_seasons(self):
        """Test that data covering only some months still returns all 4 seasons."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-06-01", "2024-07-01", "2024-08-01"]),
                "cost": [100.0, 200.0, 300.0],
                "type": ["service"] * 3,
            }
        )

        result = analytics_service.calculate_seasonal_patterns(df)

        assert len(result) == 4

        summer = result[result["season"] == "Summer"].iloc[0]
        assert summer["total_cost"] == 600.0
        assert summer["count"] == 3

        # Other seasons should be zero
        winter = result[result["season"] == "Winter"].iloc[0]
        assert winter["total_cost"] == 0.0
        assert winter["count"] == 0

    def test_december_is_winter(self):
        """Test that December is classified as Winter."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-12-25"]),
                "cost": [500.0],
                "type": ["service"],
            }
        )

        result = analytics_service.calculate_seasonal_patterns(df)

        winter = result[result["season"] == "Winter"].iloc[0]
        assert winter["total_cost"] == 500.0


@pytest.mark.unit
@pytest.mark.analytics
class TestCalculateVendorAnalysis:
    """Test vendor analysis calculations."""

    def test_multiple_vendors(self):
        """Test vendor breakdown with multiple vendors."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]),
                "cost": [100.0, 200.0, 150.0, 300.0],
                "type": ["service", "service", "service", "service"],
                "vendor": ["Shop A", "Shop B", "Shop A", "Shop B"],
                "service_type": ["Oil Change", "Brake Pad", "Tire Rotation", "Alignment"],
            }
        )

        result = analytics_service.calculate_vendor_analysis(df)

        assert len(result) == 2
        # Sorted by total_spent descending
        assert result.iloc[0]["vendor"] == "Shop B"  # 200 + 300 = 500
        assert result.iloc[0]["total_spent"] == 500.0
        assert result.iloc[0]["service_count"] == 2

        assert result.iloc[1]["vendor"] == "Shop A"  # 100 + 150 = 250
        assert result.iloc[1]["total_spent"] == 250.0

    def test_excludes_fuel_records(self):
        """Test that fuel records are excluded from vendor analysis."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
                "cost": [100.0, 50.0],
                "type": ["service", "fuel"],
                "vendor": ["Shop A", "Fuel Station"],
                "service_type": ["Oil Change", "Fuel"],
            }
        )

        result = analytics_service.calculate_vendor_analysis(df)

        assert len(result) == 1
        assert result.iloc[0]["vendor"] == "Shop A"

    def test_empty_dataframe(self):
        """Test empty data returns empty result."""
        df = pd.DataFrame(columns=["date", "cost", "type", "vendor", "service_type"])

        result = analytics_service.calculate_vendor_analysis(df)

        assert result.empty

    def test_single_vendor(self):
        """Test with a single vendor."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-06-01"]),
                "cost": [100.0, 200.0],
                "type": ["service", "service"],
                "vendor": ["Only Shop", "Only Shop"],
                "service_type": ["Oil Change", "Brake Pad"],
            }
        )

        result = analytics_service.calculate_vendor_analysis(df)

        assert len(result) == 1
        assert result.iloc[0]["total_spent"] == 300.0
        assert result.iloc[0]["service_count"] == 2
        assert "service_types" in result.columns


@pytest.mark.unit
@pytest.mark.analytics
class TestCompareTimePeriods:
    """Test time period comparison."""

    def test_basic_comparison(self):
        """Test comparing two time periods with known costs."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2024-01-15",
                        "2024-02-15",
                        "2024-07-15",
                        "2024-08-15",
                    ]
                ),
                "cost": [100.0, 200.0, 300.0, 400.0],
                "type": ["service", "service", "service", "service"],
            }
        )

        result = analytics_service.compare_time_periods(
            df,
            period1_start=date(2024, 1, 1),
            period1_end=date(2024, 3, 31),
            period2_start=date(2024, 7, 1),
            period2_end=date(2024, 9, 30),
        )

        assert result["period1_cost"] == Decimal("300.00")  # 100 + 200
        assert result["period2_cost"] == Decimal("700.00")  # 300 + 400
        assert result["period1_count"] == 2
        assert result["period2_count"] == 2
        # Change: (700-300)/300 * 100 = 133.33%
        assert result["cost_change_pct"] > Decimal("0")

    def test_empty_dataframe(self):
        """Test comparison with empty data."""
        df = pd.DataFrame(columns=["date", "cost", "type"])

        result = analytics_service.compare_time_periods(
            df,
            period1_start=date(2024, 1, 1),
            period1_end=date(2024, 6, 30),
            period2_start=date(2024, 7, 1),
            period2_end=date(2024, 12, 31),
        )

        assert result["period1_cost"] == Decimal("0.00")
        assert result["period2_cost"] == Decimal("0.00")
        assert result["period1_count"] == 0
        assert result["period2_count"] == 0

    def test_no_data_in_period2(self):
        """Test when period 2 has no records."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-15"]),
                "cost": [100.0],
                "type": ["service"],
            }
        )

        result = analytics_service.compare_time_periods(
            df,
            period1_start=date(2024, 1, 1),
            period1_end=date(2024, 6, 30),
            period2_start=date(2024, 7, 1),
            period2_end=date(2024, 12, 31),
        )

        assert result["period1_cost"] == Decimal("100.00")
        assert result["period2_cost"] == Decimal("0.00")
        # -100% change
        assert result["cost_change_pct"] == Decimal("-100.0")

    def test_service_count_breakdown(self):
        """Test that service counts are broken out separately."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-15", "2024-01-20", "2024-07-15"]),
                "cost": [100.0, 50.0, 200.0],
                "type": ["service", "fuel", "service"],
            }
        )

        result = analytics_service.compare_time_periods(
            df,
            period1_start=date(2024, 1, 1),
            period1_end=date(2024, 6, 30),
            period2_start=date(2024, 7, 1),
            period2_end=date(2024, 12, 31),
        )

        assert result["period1_service_count"] == 1  # 1 service, 1 fuel
        assert result["period2_service_count"] == 1


@pytest.mark.unit
@pytest.mark.analytics
class TestCalculatePropaneCosts:
    """Test propane cost calculation for fifth wheels."""

    def test_basic_propane_tracking(self):
        """Test propane cost aggregation with valid records."""
        records = [
            _make_fuel_record(
                id=1,
                date=date(2024, 1, 15),
                gallons=None,
                propane_gallons=Decimal("7.5"),
                tank_size_lb=Decimal("30"),
                tank_quantity=2,
                cost=Decimal("22.50"),
                price_per_unit=Decimal("3.00"),
            ),
            _make_fuel_record(
                id=2,
                date=date(2024, 2, 15),
                gallons=None,
                propane_gallons=Decimal("8.0"),
                tank_size_lb=Decimal("30"),
                tank_quantity=2,
                cost=Decimal("24.00"),
                price_per_unit=Decimal("3.00"),
            ),
        ]

        result = analytics_service.calculate_propane_costs(records)

        assert result["total_spent"] == Decimal("46.50")
        assert result["total_gallons"] == Decimal("15.50")  # 7.5 + 8.0
        assert result["record_count"] == 2
        assert result["avg_price_per_gallon"] is not None
        assert len(result["monthly_trend"]) == 2
        assert "30" in result["tank_breakdown"]

    def test_no_propane_records(self):
        """Test with no propane records (only gasoline)."""
        records = [
            _make_fuel_record(gallons=Decimal("12.0"), propane_gallons=None),
        ]

        result = analytics_service.calculate_propane_costs(records)

        assert result["total_spent"] == Decimal("0.00")
        assert result["record_count"] == 0
        assert result["monthly_trend"] == []

    def test_empty_records(self):
        """Test with empty list."""
        result = analytics_service.calculate_propane_costs([])

        assert result["total_spent"] == Decimal("0.00")
        assert result["total_gallons"] == Decimal("0.00")
        assert result["record_count"] == 0

    def test_tank_breakdown_multiple_sizes(self):
        """Test tank breakdown with different tank sizes."""
        records = [
            _make_fuel_record(
                id=1,
                date=date(2024, 1, 10),
                gallons=None,
                propane_gallons=Decimal("7.0"),
                tank_size_lb=Decimal("30"),
                cost=Decimal("21.00"),
                price_per_unit=Decimal("3.00"),
            ),
            _make_fuel_record(
                id=2,
                date=date(2024, 2, 10),
                gallons=None,
                propane_gallons=Decimal("10.0"),
                tank_size_lb=Decimal("40"),
                cost=Decimal("30.00"),
                price_per_unit=Decimal("3.00"),
            ),
        ]

        result = analytics_service.calculate_propane_costs(records)

        assert "30" in result["tank_breakdown"]
        assert "40" in result["tank_breakdown"]
        assert result["tank_breakdown"]["30"]["total_gallons"] == 7.0
        assert result["tank_breakdown"]["40"]["total_gallons"] == 10.0

    def test_refill_frequency(self):
        """Test refill frequency calculation with multiple fills of same tank."""
        records = [
            _make_fuel_record(
                id=1,
                date=date(2024, 1, 1),
                gallons=None,
                propane_gallons=Decimal("7.0"),
                tank_size_lb=Decimal("30"),
                cost=Decimal("21.00"),
                price_per_unit=Decimal("3.00"),
            ),
            _make_fuel_record(
                id=2,
                date=date(2024, 1, 15),
                gallons=None,
                propane_gallons=Decimal("7.0"),
                tank_size_lb=Decimal("30"),
                cost=Decimal("21.00"),
                price_per_unit=Decimal("3.00"),
            ),
            _make_fuel_record(
                id=3,
                date=date(2024, 2, 14),
                gallons=None,
                propane_gallons=Decimal("7.0"),
                tank_size_lb=Decimal("30"),
                cost=Decimal("21.00"),
                price_per_unit=Decimal("3.00"),
            ),
        ]

        result = analytics_service.calculate_propane_costs(records)

        assert "30" in result["refill_frequency"]
        freq = result["refill_frequency"]["30"]
        assert freq["avg_days_between"] > 0
        assert freq["min_days"] == 14  # Jan 1 → Jan 15
        assert freq["max_days"] == 30  # Jan 15 → Feb 14


def _make_line_item(**kwargs):
    """Create a mock ServiceLineItem-like object with sensible defaults."""
    defaults = {
        "id": 1,
        "visit_id": 1,
        "description": "Oil Change",
        "cost": Decimal("50.00"),
        "notes": None,
        "is_inspection": False,
        "inspection_result": None,
        "inspection_severity": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_service_visit(**kwargs):
    """Create a mock ServiceVisit-like object with computed calculated_total_cost."""
    defaults = {
        "id": 1,
        "vin": "1HGBH41JXMN109186",
        "date": date(2024, 1, 15),
        "mileage": 50000,
        "total_cost": None,
        "tax_amount": None,
        "shop_supplies": None,
        "misc_fees": None,
        "notes": None,
        "service_category": "Maintenance",
        "line_items": [],
        "vendor": SimpleNamespace(name="AutoShop"),
    }
    defaults.update(kwargs)
    visit = SimpleNamespace(**defaults)

    # Compute calculated_total_cost property as the real model does
    subtotal = sum((li.cost for li in visit.line_items if li.cost), Decimal(0))
    total = subtotal
    if visit.tax_amount:
        total += visit.tax_amount
    if visit.shop_supplies:
        total += visit.shop_supplies
    if visit.misc_fees:
        total += visit.misc_fees
    visit.calculated_total_cost = total

    return visit


def _make_def_record(**kwargs):
    """Create a mock DEFRecord-like object."""
    defaults = {
        "id": 1,
        "vin": "1HGBH41JXMN109186",
        "date": date(2024, 1, 15),
        "mileage": 50000,
        "gallons": Decimal("2.5"),
        "cost": Decimal("18.75"),
        "price_per_unit": Decimal("7.50"),
        "fill_level": 0.85,
        "source": None,
        "brand": None,
        "notes": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
@pytest.mark.analytics
class TestVisitsToDataframe:
    """Test visits_to_dataframe with ServiceVisit objects."""

    def test_one_row_per_visit(self):
        """Verify that a visit with 3 line items produces 1 DataFrame row."""
        items = [
            _make_line_item(id=1, description="Oil Change", cost=Decimal("30.00")),
            _make_line_item(id=2, description="Air Filter", cost=Decimal("15.00")),
            _make_line_item(id=3, description="Cabin Filter", cost=Decimal("20.00")),
        ]
        visit = _make_service_visit(id=1, line_items=items)

        df = analytics_service.visits_to_dataframe([visit], [])

        assert len(df) == 1
        assert df.iloc[0]["cost"] == 65.0  # 30 + 15 + 20
        assert df.iloc[0]["type"] == "service"

    def test_visit_cost_includes_tax_fees(self):
        """Verify tax, shop_supplies, and misc_fees are included in row cost."""
        items = [_make_line_item(cost=Decimal("100.00"))]
        visit = _make_service_visit(
            line_items=items,
            tax_amount=Decimal("8.00"),
            shop_supplies=Decimal("3.50"),
            misc_fees=Decimal("2.00"),
        )

        df = analytics_service.visits_to_dataframe([visit], [])

        assert len(df) == 1
        # 100 + 8 + 3.50 + 2 = 113.50
        assert df.iloc[0]["cost"] == 113.5

    def test_def_records_included(self):
        """Verify DEF records produce type='def' rows."""
        def_records = [
            _make_def_record(id=1, date=date(2024, 1, 10), cost=Decimal("18.75")),
            _make_def_record(id=2, date=date(2024, 2, 10), cost=Decimal("20.00")),
        ]

        df = analytics_service.visits_to_dataframe([], [], def_records=def_records)

        assert len(df) == 2
        assert all(df["type"] == "def")
        assert df["cost"].sum() == 38.75

    def test_mixed_visits_fuel_def(self):
        """Test DataFrame with visits, fuel, and DEF together."""
        items = [_make_line_item(cost=Decimal("50.00"))]
        visit = _make_service_visit(date=date(2024, 1, 15), line_items=items)

        fuel = [_make_fuel_record(date=date(2024, 1, 20), cost=Decimal("45.00"))]
        def_recs = [_make_def_record(date=date(2024, 1, 25), cost=Decimal("18.75"))]

        df = analytics_service.visits_to_dataframe([visit], fuel, def_records=def_recs)

        assert len(df) == 3
        assert set(df["type"]) == {"service", "fuel", "def"}
        # Verify sorted by date
        dates = df["date"].tolist()
        assert dates == sorted(dates)

    def test_empty_visits(self):
        """Test with no data at all."""
        df = analytics_service.visits_to_dataframe([], [])

        assert df.empty
        assert "date" in df.columns
        assert "type" in df.columns
        assert "cost" in df.columns

    def test_visit_without_line_items_skipped_if_zero_cost(self):
        """Visits with no line items and no fees should be skipped."""
        visit = _make_service_visit(line_items=[])

        df = analytics_service.visits_to_dataframe([visit], [])

        assert df.empty

    def test_visit_vendor_name(self):
        """Verify vendor name is correctly mapped."""
        items = [_make_line_item(cost=Decimal("50.00"))]
        visit = _make_service_visit(
            line_items=items,
            vendor=SimpleNamespace(name="Pep Boys"),
        )

        df = analytics_service.visits_to_dataframe([visit], [])

        assert df.iloc[0]["vendor"] == "Pep Boys"

    def test_visit_no_vendor(self):
        """Verify missing vendor defaults to 'Unknown'."""
        items = [_make_line_item(cost=Decimal("50.00"))]
        visit = _make_service_visit(line_items=items, vendor=None)

        df = analytics_service.visits_to_dataframe([visit], [])

        assert df.iloc[0]["vendor"] == "Unknown"
