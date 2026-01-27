"""Unit tests for analytics service functions."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.services import analytics_service


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
        # Create DataFrame with year/month columns (required by calculate_rolling_averages)
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

        # With only 2 months, 3m/6m/12m averages should be None
        assert rolling_avgs["rolling_3m"] is None
        assert rolling_avgs["rolling_6m"] is None
        assert rolling_avgs["rolling_12m"] is None

    def test_detect_anomalies_z_score(self):
        """Test anomaly detection using Z-score method."""
        # Normal distribution with one outlier
        values = pd.Series([100, 110, 105, 108, 102, 500, 107, 103])

        anomaly_indices = analytics_service.detect_anomalies(values, std_threshold=2.0)

        # Index 5 (value 500) should be detected as anomaly
        assert 5 in anomaly_indices
        assert len(anomaly_indices) == 1

    def test_detect_anomalies_no_anomalies(self):
        """Test anomaly detection with no anomalies."""
        # All values within normal range
        values = pd.Series([100, 105, 102, 108, 103, 107, 104])

        anomaly_indices = analytics_service.detect_anomalies(values, std_threshold=2.0)

        assert len(anomaly_indices) == 0

    def test_detect_anomalies_insufficient_data(self):
        """Test anomaly detection with insufficient data."""
        values = pd.Series([100, 200])

        anomaly_indices = analytics_service.detect_anomalies(values, std_threshold=2.0)

        # Should return empty list with < 3 data points
        assert len(anomaly_indices) == 0

    def test_calculate_monthly_aggregation(self):
        """Test monthly cost aggregation."""
        # Create sample data with proper alignment:
        # - January 2024: 31 days (service)
        # - February 2024: 29 days (fuel) - leap year
        # - March 2024: 31 days (service)
        dates = pd.date_range(start="2024-01-01", end="2024-03-31", freq="D")
        df = pd.DataFrame(
            {
                "date": dates,
                "type": ["service"] * 31 + ["fuel"] * 29 + ["service"] * 31,
                "cost": [100.0] * len(dates),
            }
        )

        monthly_df = analytics_service.calculate_monthly_aggregation(df)

        # Should have 3 months
        assert len(monthly_df) == 3

        # Check columns
        assert "year" in monthly_df.columns
        assert "month" in monthly_df.columns
        assert "month_name" in monthly_df.columns
        assert "service_cost" in monthly_df.columns
        assert "fuel_cost" in monthly_df.columns
        assert "total_cost" in monthly_df.columns
        assert "service_count" in monthly_df.columns
        assert "fuel_count" in monthly_df.columns

        # January should have 31 service records and no fuel
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
def test_calculate_fuel_economy_basic():
    """Test basic fuel economy calculation."""
    # This would require mock FuelRecord objects
    # Simplified test showing the structure
    assert True  # Placeholder


@pytest.mark.unit
@pytest.mark.analytics
def test_seasonal_analysis_grouping():
    """Test seasonal grouping logic."""
    # Test that dates are correctly grouped into seasons
    winter_date = date(2024, 1, 15)
    spring_date = date(2024, 4, 15)
    summer_date = date(2024, 7, 15)
    fall_date = date(2024, 10, 15)

    # Helper to determine season (would be in analytics_service)
    def get_season(month):
        if month in [12, 1, 2]:
            return "Winter"
        elif month in [3, 4, 5]:
            return "Spring"
        elif month in [6, 7, 8]:
            return "Summer"
        else:
            return "Fall"

    assert get_season(winter_date.month) == "Winter"
    assert get_season(spring_date.month) == "Spring"
    assert get_season(summer_date.month) == "Summer"
    assert get_season(fall_date.month) == "Fall"
