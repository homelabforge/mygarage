"""Analytics service with pandas-based data processing."""

from app.services.analytics_service.aggregation import (
    calculate_monthly_aggregation,
    calculate_rolling_averages,
)
from app.services.analytics_service.costs import calculate_spot_rental_costs
from app.services.analytics_service.dataframes import visits_to_dataframe
from app.services.analytics_service.fuel import (
    calculate_fuel_economy_with_pandas,
    calculate_propane_costs,
)
from app.services.analytics_service.patterns import (
    calculate_seasonal_patterns,
    calculate_vendor_analysis,
    detect_anomalies,
)
from app.services.analytics_service.trends import (
    calculate_trend_direction,
    compare_time_periods,
)

__all__ = [
    "calculate_fuel_economy_with_pandas",
    "calculate_monthly_aggregation",
    "calculate_propane_costs",
    "calculate_rolling_averages",
    "calculate_seasonal_patterns",
    "calculate_spot_rental_costs",
    "calculate_trend_direction",
    "calculate_vendor_analysis",
    "compare_time_periods",
    "detect_anomalies",
    "visits_to_dataframe",
]
